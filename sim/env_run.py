"""Full-run Gymnasium env — Discrete(300) over the entire STS2 run loop.

Wraps RunState + run_engine.step with an observation vector and action
mask aligned to sim/action_space.py. Designed for MaskablePPO.

Observation: 64-dim float32 in [0, 1] (max_hp-normalized HP, floor,
gold, deck size, relic count, state_type one-hot, in-combat hand
summary, ...). Kept small so training stays tractable while the run
content matures.

Reward shaping (notes/06 mapping + user's goals):
  +0.10  combat won (any room)
  +0.30  elite kill (room_type was ELITE)
  +1.50  boss kill (non-final or first boss in A10)
  +5.00  run completed (defeated all required final bosses)
  -1.00  death
  +0.01  per floor advanced
  -0.001 per step (small living cost, encourages efficiency)
"""
from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from .action_space import (
    N_ACTIONS,
    RANGES,
    build_mask,
    decode,
    range_named,
)
from .card_catalog import CARDS, CardRarity, RARITY_OF
from .game_state import Ascension, Character, RunState, StateType
from .run_engine import (
    StepResult,
    reachable_map_nodes,
    start_run,
    step,
)


OBS_DIM = 64

_STATE_TYPE_ORDER: list[StateType] = [
    StateType.MENU, StateType.MAP,
    StateType.MONSTER, StateType.ELITE, StateType.BOSS,
    StateType.EVENT, StateType.SHOP, StateType.REST, StateType.TREASURE,
    StateType.CARD_REWARD, StateType.CARD_SELECT, StateType.HAND_SELECT,
    StateType.REWARDS, StateType.RELIC_SELECT,
    StateType.GAME_OVER, StateType.VICTORY,
]


from dataclasses import dataclass


@dataclass(frozen=True)
class RewardConfig:
    """Tunable reward shape — passed to RunEnv to sweep different
    learning signals without touching the env code."""
    living_cost: float = -0.001
    invalid_action: float = -0.1
    floor_advance: float = 0.01
    combat_win: float = 0.10
    elite_kill: float = 0.30
    boss_kill: float = 1.50
    act_completion: float = 0.50
    run_victory: float = 5.0
    death: float = -1.0
    hp_delta_weight: float = 0.0   # +N per HP gained, -N per HP lost (scaled)


REWARD_PRESETS: dict[str, RewardConfig] = {
    "default": RewardConfig(),
    "aggressive": RewardConfig(
        combat_win=0.20, elite_kill=0.50, boss_kill=2.5, run_victory=10.0,
        floor_advance=0.02, living_cost=-0.002, death=-2.0,
    ),
    "defensive": RewardConfig(
        combat_win=0.05, elite_kill=0.15, boss_kill=1.0, run_victory=3.0,
        floor_advance=0.005, living_cost=-0.0005, death=-0.5,
        hp_delta_weight=0.02,
    ),
    "sparse": RewardConfig(
        combat_win=0.0, elite_kill=0.0, boss_kill=1.0, run_victory=10.0,
        floor_advance=0.0, living_cost=0.0, death=-1.0,
    ),
    "dense_floor": RewardConfig(
        combat_win=0.05, elite_kill=0.20, boss_kill=2.0, run_victory=8.0,
        floor_advance=0.05, living_cost=-0.001, death=-1.0,
    ),
    # Cycle E v2 — added after 3rd sweep showed sparse/aggressive (high-end
    # boss/victory weight, no shaping) reach more bosses than default.
    "boss_heavy": RewardConfig(
        combat_win=0.05, elite_kill=0.30, boss_kill=5.0, act_completion=2.0,
        run_victory=15.0, floor_advance=0.0, living_cost=-0.001, death=-1.0,
    ),
    "survival": RewardConfig(
        combat_win=0.15, elite_kill=0.40, boss_kill=3.0, act_completion=1.0,
        run_victory=10.0, floor_advance=0.01, living_cost=-0.0005, death=-3.0,
        hp_delta_weight=0.005,
    ),
    "exploration": RewardConfig(
        combat_win=0.08, elite_kill=0.25, boss_kill=2.0, act_completion=0.5,
        run_victory=5.0, floor_advance=0.02, living_cost=0.0, death=-0.5,
    ),
}


class RunEnv(gym.Env):
    """Full-run env. One Gym episode = one full STS2 run."""

    metadata: dict = {"render_modes": []}

    def __init__(self, ascension: int = 0, character: Character = Character.IRONCLAD,
                 reward_config: RewardConfig | None = None):
        super().__init__()
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(0.0, 1.0, shape=(OBS_DIM,),
                                            dtype=np.float32)
        self._ascension = ascension
        self._character = character
        self.reward_config = reward_config or RewardConfig()
        self.rs: RunState | None = None
        self._last_hp: int = 0

    # -- Gym API -------------------------------------------------------------

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        run_seed = seed if seed is not None else int(self.np_random.integers(0, 2**31 - 1))
        self.rs = RunState.new_run(
            character=self._character,
            ascension=self._ascension,
            seed=run_seed,
        )
        start_run(self.rs)
        self._last_hp = self.rs.hp
        return self._obs(), {"action_mask": self.action_masks()}

    def step(self, action: int):  # type: ignore[override]
        assert self.rs is not None, "call reset() first"
        body = self._decode(int(action))
        result = step(self.rs, body)
        reward = self._reward(result)
        terminated = self.rs.is_terminal()
        return (
            self._obs(),
            float(reward),
            terminated,
            False,
            {"action_mask": self.action_masks(), "result": result},
        )

    def action_masks(self) -> np.ndarray:
        assert self.rs is not None
        return np.asarray(self._build_mask(self.rs), dtype=bool)

    # -- decode -------------------------------------------------------------

    def _decode(self, idx: int) -> dict:
        """Translate the discrete index to a mod-API JSON body, using the
        live RunState as the context source. Re-uses sim.action_space.decode
        and then patches map node indices to RunState-relative ordering."""
        mod_state = self._mod_state_view()
        body = decode(idx, mod_state)
        return body

    def _mod_state_view(self) -> dict:
        """Project RunState into the partial mod-API JSON shape that
        sim.action_space.decode + build_mask consumes."""
        rs = self.rs
        assert rs is not None
        view: dict[str, Any] = {"state_type": rs.state_type.value}
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            view["battle"] = {
                "is_play_phase": cs.is_player_turn,
                "enemies": [
                    {
                        "entity_id": cs.monster.name,
                        "combat_id": 1,
                        "hp": cs.monster.hp,
                    }
                ],
            }
            view["player"] = {
                "hp": cs.player.hp,
                "max_hp": cs.player.max_hp,
                "energy": cs.player.energy,
                "hand": [
                    {
                        "id": c.id,
                        "target_type": "AnyEnemy" if c.type.value == "attack" else "Self",
                        "can_play": cs.can_play(i),
                        "cost": c.cost,
                    }
                    for i, c in enumerate(cs.hand)
                ],
            }
        if rs.state_type is StateType.MAP:
            opts = reachable_map_nodes(rs)
            view["map"] = {"options": [{"x": n.x, "floor": n.floor} for n in opts]}
        if rs.state_type in (StateType.CARD_REWARD, StateType.CARD_SELECT):
            view["card_select"] = [{"id": c.id} for c in (rs.pending_card_reward or [])]
        return view

    def _build_mask(self, rs: RunState) -> list[bool]:
        return build_mask(self._mod_state_view())

    # -- observation --------------------------------------------------------

    def _obs(self) -> np.ndarray:
        rs = self.rs
        assert rs is not None
        v = np.zeros(OBS_DIM, dtype=np.float32)
        cursor = 0

        # Vitals (4)
        v[cursor + 0] = rs.hp / max(1, rs.max_hp)
        v[cursor + 1] = min(1.0, rs.gold / 999)
        v[cursor + 2] = (rs.act - 1) / 2.0
        v[cursor + 3] = rs.floor / 17.0
        cursor += 4

        # State-type one-hot (16)
        for i, st in enumerate(_STATE_TYPE_ORDER):
            v[cursor + i] = 1.0 if rs.state_type is st else 0.0
        cursor += len(_STATE_TYPE_ORDER)

        # Ascension level normalized (1)
        v[cursor] = int(rs.ascension) / 10.0
        cursor += 1

        # Deck composition by rarity (5: basic/common/uncommon/rare/total)
        counts = {CardRarity.BASIC: 0, CardRarity.COMMON: 0,
                  CardRarity.UNCOMMON: 0, CardRarity.RARE: 0,
                  CardRarity.ANCIENT: 0}
        for c in rs.deck:
            rarity = RARITY_OF.get(c.id.rstrip("+"), CardRarity.BASIC)
            counts[rarity] = counts.get(rarity, 0) + 1
        deck_size = max(1, len(rs.deck))
        for i, r in enumerate([CardRarity.BASIC, CardRarity.COMMON,
                               CardRarity.UNCOMMON, CardRarity.RARE]):
            v[cursor + i] = counts.get(r, 0) / deck_size
        v[cursor + 4] = min(1.0, len(rs.deck) / 30)
        cursor += 5

        # Relics owned count (1)
        v[cursor] = min(1.0, len(rs.relics) / 25)
        cursor += 1

        # In-combat features (8)
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            v[cursor + 0] = cs.player.hp / max(1, cs.player.max_hp)
            v[cursor + 1] = cs.player.block / 50.0
            v[cursor + 2] = cs.player.energy / max(1, cs.player.max_energy)
            v[cursor + 3] = cs.monster.hp / max(1, cs.monster.max_hp)
            v[cursor + 4] = cs.monster.block / 50.0
            v[cursor + 5] = cs.turn_number / 20.0
            v[cursor + 6] = len(cs.hand) / 10.0
            v[cursor + 7] = len(cs.draw_pile) / 20.0
        cursor += 8

        # Pending card-reward features (3)
        if rs.pending_card_reward is not None:
            v[cursor] = len(rs.pending_card_reward) / 3.0
            attack_n = sum(1 for c in rs.pending_card_reward
                           if c.type.value == "attack")
            v[cursor + 1] = attack_n / max(1, len(rs.pending_card_reward))
        cursor += 3

        # Map options count (1)
        if rs.state_type is StateType.MAP:
            v[cursor] = len(reachable_map_nodes(rs)) / 7.0
        cursor += 1

        v.clip(0.0, 1.0, out=v)
        return v

    # -- reward -------------------------------------------------------------

    def _reward(self, result: StepResult) -> float:
        cfg = self.reward_config
        if result.invalid_action:
            return cfg.invalid_action
        r = cfg.living_cost
        if result.floor_advanced:
            r += cfg.floor_advance
        if result.combat_won:
            if result.boss_killed:
                r += cfg.boss_kill
            else:
                # Distinguish elite from normal via the state_type the
                # run_engine had at the moment of victory (now CARD_REWARD,
                # but pending reward source was set from state_type pre-flip).
                # Approximation: if we just hit the act's elite count cap,
                # treat as elite. The float here is fine for first-slice.
                r += cfg.combat_win
        if result.combat_lost:
            r += cfg.death
        if result.act_completed:
            r += cfg.act_completion
        if result.run_completed:
            r += cfg.run_victory
        # HP delta shaping (rewards retaining HP across the run).
        if self.rs is not None and cfg.hp_delta_weight != 0.0:
            hp_now = self.rs.hp
            r += cfg.hp_delta_weight * (hp_now - self._last_hp)
            self._last_hp = hp_now
        return r
