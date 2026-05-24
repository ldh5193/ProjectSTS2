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


OBS_DIM = 128


# Power ids the policy gets a stack-amount feature for. Order is part of
# the obs contract — re-shuffling breaks any trained policy.
_PLAYER_POWER_IDS = ("strength", "vulnerable", "weak", "dexterity", "frail")
_MONSTER_POWER_IDS = ("strength", "vulnerable", "weak")
# Substring heuristic: if any of these tokens appears in str(monster.next_move).upper()
# we treat the upcoming move as an attack. Better than "no intent signal at all"
# until a per-monster intent.damage() lands.
_ATTACK_MOVE_TOKENS = ("ATTACK", "STRIKE", "SLAM", "SLICE", "BUTT",
                       "CHOMP", "STAB", "BITE", "RAGE", "CLAW",
                       "TACKLE", "GORE", "REND", "MAUL", "DISMEMBER",
                       "HEAVY_SLASH", "PROD")


def _power_amount(creature, power_id: str) -> int:
    """Sum of all matching power stacks on a creature (most ids appear at
    most once; sum keeps the helper robust if duplicates ever land)."""
    return sum(p.amount for p in creature.powers if p.id == power_id)

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
    # Cycle E v3 — seeded by the 7th sweep where survival (HP shaping) jumped
    # from 7.5% → 17.5% win after Thorns/Plating started actually defending.
    # These chase the "HP-aware" lane harder.
    "survival_v2": RewardConfig(
        combat_win=0.10, elite_kill=0.40, boss_kill=4.0, act_completion=1.5,
        run_victory=12.0, floor_advance=0.01, living_cost=-0.0005, death=-3.0,
        hp_delta_weight=0.01,  # 2× the survival baseline (0.005)
    ),
    "tank": RewardConfig(
        combat_win=0.20, elite_kill=0.50, boss_kill=3.0, act_completion=1.0,
        run_victory=10.0, floor_advance=0.005, living_cost=-0.001, death=-2.0,
        hp_delta_weight=0.02,
    ),
    # Cycle E v4 — after 11 sweeps, tank emerged as new final best. Push
    # the "stiff terminal + heavy HP" lane further.
    "tank_plus": RewardConfig(
        combat_win=0.20, elite_kill=0.60, boss_kill=5.0, act_completion=2.0,
        run_victory=15.0, floor_advance=0.005, living_cost=-0.001, death=-2.5,
        hp_delta_weight=0.025,
    ),
    "balanced": RewardConfig(
        combat_win=0.12, elite_kill=0.35, boss_kill=2.5, act_completion=1.2,
        run_victory=8.0, floor_advance=0.015, living_cost=-0.0008, death=-1.5,
        hp_delta_weight=0.01,
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
        # Per-step memoization. `_state_gen` is bumped any time we mutate
        # RunState (reset or step). Each cache stores `(gen, value)` so
        # repeated calls within the same "frame" reuse the work. This
        # cannot change the policy's experience because the cached values
        # are bitwise-identical to a fresh recompute on the same state.
        self._state_gen: int = 0
        self._view_cache: tuple[int, dict] | None = None
        self._map_cache: tuple[int, list] | None = None
        self._mask_cache: tuple[int, np.ndarray] | None = None

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
        self._invalidate_caches()
        return self._obs(), {"action_mask": self.action_masks()}

    def step(self, action: int):  # type: ignore[override]
        assert self.rs is not None, "call reset() first"
        body = self._decode(int(action))
        result = step(self.rs, body)
        self._invalidate_caches()
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
        cached = self._mask_cache
        if cached is not None and cached[0] == self._state_gen:
            return cached[1]
        m = np.asarray(self._build_mask(self.rs), dtype=bool)
        self._mask_cache = (self._state_gen, m)
        return m

    def _invalidate_caches(self) -> None:
        self._state_gen += 1
        # No need to clear caches explicitly; the generation check makes
        # stale entries unreachable. The old objects get GC'd next cycle.

    # -- decode -------------------------------------------------------------

    def _decode(self, idx: int) -> dict:
        """Translate the discrete index to a mod-API JSON body, using the
        live RunState as the context source. Re-uses sim.action_space.decode
        and then patches map node indices to RunState-relative ordering."""
        mod_state = self._mod_state_view()
        body = decode(idx, mod_state)
        return body

    def _reachable_map_nodes_cached(self):
        cached = self._map_cache
        if cached is not None and cached[0] == self._state_gen:
            return cached[1]
        nodes = reachable_map_nodes(self.rs)
        self._map_cache = (self._state_gen, nodes)
        return nodes

    def _mod_state_view(self) -> dict:
        """Project RunState into the partial mod-API JSON shape that
        sim.action_space.decode + build_mask consumes.

        Cached per state generation: decode (pre-step) and build_mask
        (post-step) both call this, and within a single frame several
        callers may hit it. Building the dict is non-trivial (allocations
        for every enemy/card), so the cache pays for itself quickly.
        """
        cached = self._view_cache
        if cached is not None and cached[0] == self._state_gen:
            return cached[1]
        rs = self.rs
        assert rs is not None
        view: dict[str, Any] = {"state_type": rs.state_type.value}
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            alive = cs.alive_monsters()
            view["battle"] = {
                "is_play_phase": cs.is_player_turn,
                "enemies": [
                    {
                        "entity_id": m.name,
                        "combat_id": i,
                        "hp": m.hp,
                    }
                    for i, m in enumerate(alive)
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
            opts = self._reachable_map_nodes_cached()
            view["map"] = {"options": [{"x": n.x, "floor": n.floor} for n in opts]}
        if rs.state_type in (StateType.CARD_REWARD, StateType.CARD_SELECT):
            view["card_select"] = [{"id": c.id} for c in (rs.pending_card_reward or [])]
        if rs.state_type is StateType.REST and rs.pending_rest_options is not None:
            view["state_type"] = "rest_site"  # match the live mod's emitted value
            view["rest_site"] = {
                "options": [
                    {"index": i, "id": o["id"], "is_enabled": o["is_enabled"]}
                    for i, o in enumerate(rs.pending_rest_options)
                ],
                "can_proceed": False,  # picks must happen before proceed
            }
        self._view_cache = (self._state_gen, view)
        return view

    def _build_mask(self, rs: RunState) -> list[bool]:
        return build_mask(self._mod_state_view())

    # -- observation --------------------------------------------------------

    def _obs(self) -> np.ndarray:
        """v2 layout — see notes/18_training_gaps.md for the full audit.

        Total 93 used, 35 reserved padding (OBS_DIM = 128). Field order
        is part of the obs contract; renumbering invalidates trained
        policies.
        """
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

        # Deck composition by rarity (5: basic/common/uncommon/rare/total).
        rarity_counts = [0, 0, 0, 0, 0]  # [BASIC, COMMON, UNCOMMON, RARE, ANCIENT]
        _rar_idx = {
            CardRarity.BASIC: 0, CardRarity.COMMON: 1,
            CardRarity.UNCOMMON: 2, CardRarity.RARE: 3,
            CardRarity.ANCIENT: 4,
        }
        for c in rs.deck:
            cid = c.id[:-1] if c.id.endswith("+") else c.id
            rarity_counts[_rar_idx.get(RARITY_OF.get(cid, CardRarity.BASIC), 0)] += 1
        deck_len = len(rs.deck)
        deck_size = max(1, deck_len)
        v[cursor + 0] = rarity_counts[0] / deck_size
        v[cursor + 1] = rarity_counts[1] / deck_size
        v[cursor + 2] = rarity_counts[2] / deck_size
        v[cursor + 3] = rarity_counts[3] / deck_size
        v[cursor + 4] = min(1.0, deck_len / 30)
        cursor += 5

        # Relics owned count (1)
        v[cursor] = min(1.0, len(rs.relics) / 25)
        cursor += 1

        # NEW v2: Pile sizes (3) — draw / discard / exhaust separately.
        # Previously only draw was exposed, glommed onto combat features.
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            v[cursor + 0] = min(1.0, len(cs.draw_pile) / 40.0)
            v[cursor + 1] = min(1.0, len(getattr(cs, "discard_pile", [])) / 40.0)
            v[cursor + 2] = min(1.0, len(getattr(cs, "exhaust_pile", [])) / 20.0)
        cursor += 3

        # In-combat core features (8): hp/block/energy + first-enemy hp/block
        # + round / hand size / draw size (kept for back-compat with v1's
        # general "combat snapshot" layer).
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            v[cursor + 0] = cs.player.hp / max(1, cs.player.max_hp)
            v[cursor + 1] = min(1.0, cs.player.block / 50.0)
            v[cursor + 2] = cs.player.energy / max(1, cs.player.max_energy)
            alive = cs.alive_monsters()
            m1 = alive[0] if alive else None
            if m1 is not None:
                v[cursor + 3] = m1.hp / max(1, m1.max_hp)
                v[cursor + 4] = min(1.0, m1.block / 50.0)
            v[cursor + 5] = min(1.0, cs.turn_number / 20.0)
            v[cursor + 6] = min(1.0, len(cs.hand) / 10.0)
            v[cursor + 7] = min(1.0, len(cs.draw_pile) / 20.0)
        cursor += 8

        # NEW v2: Player powers (5) — strength, vulnerable, weak, dexterity, frail.
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            for i, pid in enumerate(_PLAYER_POWER_IDS):
                v[cursor + i] = min(1.0, _power_amount(cs.player, pid) / 10.0)
        cursor += 5

        # NEW v2: Monster #1 powers (3) — strength, vulnerable, weak.
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            alive = cs.alive_monsters()
            if alive:
                for i, pid in enumerate(_MONSTER_POWER_IDS):
                    v[cursor + i] = min(1.0, _power_amount(alive[0], pid) / 10.0)
        cursor += 3

        # NEW v2: Monster #1 intent (2) — is_attacking, intent_strength.
        # Damage estimation per-monster needs a real Monster.intent_damage()
        # helper; for now a 0.5 placeholder when attack is detected.
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            alive = cs.alive_monsters()
            if alive and getattr(alive[0], "next_move", None) is not None:
                mv = str(alive[0].next_move).upper()
                if any(tok in mv for tok in _ATTACK_MOVE_TOKENS):
                    v[cursor + 0] = 1.0
                    v[cursor + 1] = 0.5
        cursor += 2

        # NEW v2: Monster #2 / #3 minimal features (4 each = 8 total)
        # hp%, block, vulnerable, alive_flag. Enables the policy to learn
        # multi-target prioritization (focus the low-HP one, etc.).
        if rs.in_combat() and rs.combat is not None:
            alive = rs.combat.alive_monsters()
            for ext_idx in range(2):
                slot = ext_idx + 1
                if slot < len(alive):
                    m = alive[slot]
                    v[cursor + 0] = m.hp / max(1, m.max_hp)
                    v[cursor + 1] = min(1.0, m.block / 50.0)
                    v[cursor + 2] = min(1.0, _power_amount(m, "vulnerable") / 10.0)
                    v[cursor + 3] = 1.0  # alive flag
                cursor += 4
        else:
            cursor += 8

        # NEW v2: Hand identity (30 = 10 slots × 3 features).
        # Per slot: normalized cost, is_attack, can_play. Lets the policy
        # tell "play Strike (1-cost attack)" apart from "play Inflame (1-cost
        # power)" — without this, the v1 obs collapsed every legal play to
        # the same shape.
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            for slot in range(10):
                if slot < len(cs.hand):
                    c = cs.hand[slot]
                    cost_norm = (c.cost / 3.0) if c.cost is not None and c.cost >= 0 else 0.0
                    v[cursor + slot * 3 + 0] = min(1.0, cost_norm)
                    v[cursor + slot * 3 + 1] = 1.0 if getattr(c.type, "value", "") == "attack" else 0.0
                    try:
                        v[cursor + slot * 3 + 2] = 1.0 if cs.can_play(slot) else 0.0
                    except Exception:
                        v[cursor + slot * 3 + 2] = 0.0
        cursor += 30

        # Pending card-reward (3) — count, attack share, [reserved]
        if rs.pending_card_reward is not None:
            v[cursor] = len(rs.pending_card_reward) / 3.0
            attack_n = sum(1 for c in rs.pending_card_reward
                           if getattr(c.type, "value", "") == "attack")
            v[cursor + 1] = attack_n / max(1, len(rs.pending_card_reward))
        cursor += 3

        # Map options count (1)
        if rs.state_type is StateType.MAP:
            v[cursor] = min(1.0, len(self._reachable_map_nodes_cached()) / 7.0)
        cursor += 1

        # NEW v2: Potion slot presence (3) — bool for slots 0/1/2.
        # Pairs with the new `_potion_mask` predicate so the policy can
        # actually decide when to drink.
        pots = getattr(rs, "potions", None) or []
        for i in range(min(3, len(pots))):
            if pots[i] is not None:
                v[cursor + i] = 1.0
        cursor += 3

        # Cursor at 93. OBS_DIM = 128. Remaining 35 dims are reserved for
        # round-2 additions (intent damage value per enemy, relic identity
        # one-hot, room-type lookahead, etc.).

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
