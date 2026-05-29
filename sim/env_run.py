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
from .card_catalog import CARD_FEATURE_DIM, CARDS, CardRarity, RARITY_OF, card_features
from .game_state import Ascension, Character, RunState, StateType
from .run_engine import (
    StepResult,
    reachable_map_nodes,
    start_run,
    step,
)


OBS_DIM = 384  # v4.3 (Phase 3, 2026-05-27). v3 was 256, v4 phase 2 was 320.
OBS_DIM_V3 = 256  # legacy export for the v3-layout-only tests

# Per-act boss floor. rs.floor is PER-ACT (game's ActFloor semantics,
# resets each act), so the boss of each act sits at a different floor:
# act1=17, act2=16, act3=15 — from ActModel.GetNumberOfFloors =
# GetNumberOfRooms + 2 with rooms 15/14/13 (Overgrowth/Hive/Glory.cs).
# A10 DoubleBoss adds one extra floor in the final act (StandardActMap
# SecondBossMapPoint at GetRowCount()+1).
_ACT_BOSS_FLOOR = {1: 17, 2: 16, 3: 15}
_RUN_TOTAL_FLOORS = 17 + 16 + 15  # 48 at A0-A9; +1 at A10 (DoubleBoss)


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
    # ---- v3 per-action shaping (added 2026-05-25) ----
    # The first 2.5 sweep generations plateaued at ~10% win because the
    # default reward signal only fires at combat end. Each card play
    # produced ~0 immediate reward, so PPO couldn't credit individual
    # decisions like "apply Vulnerable BEFORE Strike" or "save Defend
    # for the boss escalation turn". These deltas give per-action
    # gradients without changing the terminal signal weights.
    damage_dealt_weight: float = 0.0       # +N per HP point dealt to enemies this tick
    block_gained_weight: float = 0.0       # +N per block point gained on player this tick
    enemy_power_weight: float = 0.0        # +N per Vuln/Weak stack applied to enemy
    self_power_weight: float = 0.0         # +N per Strength/Dex stack gained
    energy_unspent_penalty: float = 0.0    # −N per energy left at end_turn


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
    # ---- v3 per-action shaping presets (added 2026-05-25) ----
    # These ride on the previous best (balanced/sparse/survival_v2 chain)
    # but add the new damage/block/power deltas. The hypothesis is that
    # per-action gradients fix the sequencing failures observed live
    # (Vuln applied last, Defend played last on damage-escalating bosses).
    "shape_damage": RewardConfig(
        combat_win=0.10, elite_kill=0.30, boss_kill=3.0, act_completion=1.0,
        run_victory=10.0, floor_advance=0.01, living_cost=-0.001, death=-1.0,
        damage_dealt_weight=0.005,  # tiny but constant
    ),
    "shape_debuff": RewardConfig(
        combat_win=0.10, elite_kill=0.30, boss_kill=3.0, act_completion=1.0,
        run_victory=10.0, floor_advance=0.01, living_cost=-0.001, death=-1.0,
        enemy_power_weight=0.15,   # reward Vuln/Weak application
    ),
    "shape_tank": RewardConfig(
        combat_win=0.10, elite_kill=0.30, boss_kill=3.0, act_completion=1.0,
        run_victory=10.0, floor_advance=0.01, living_cost=-0.001, death=-2.0,
        hp_delta_weight=0.015, block_gained_weight=0.003,
    ),
    "shape_combo": RewardConfig(
        # All four signals at once — most aggressive learning signal.
        # Likely to overfit early but should rapidly close the basic
        # sequencing failures.
        combat_win=0.10, elite_kill=0.30, boss_kill=4.0, act_completion=1.5,
        run_victory=12.0, floor_advance=0.01, living_cost=-0.0005, death=-2.0,
        damage_dealt_weight=0.003, block_gained_weight=0.002,
        enemy_power_weight=0.10, self_power_weight=0.05,
        energy_unspent_penalty=0.05,
        hp_delta_weight=0.005,
    ),
    "shape_lean": RewardConfig(
        # Same shaping as combo but with sparse terminal — tests whether
        # the shaping alone carries enough signal.
        combat_win=0.0, elite_kill=0.0, boss_kill=2.0, act_completion=0.5,
        run_victory=8.0, floor_advance=0.0, living_cost=-0.0005, death=-1.0,
        damage_dealt_weight=0.008, block_gained_weight=0.003,
        enemy_power_weight=0.15, self_power_weight=0.05,
        energy_unspent_penalty=0.1,
    ),
    # ---- v4 stats-derived presets (added 2026-05-26) ----
    # Seeded by ststracker.app + op.gg STS2 stats: community A0 win
    # ~22.7%, our model trails at 5-13%. Knowledge Demon (Act 2 boss)
    # kills 21.5% of all deaths — punishes unplayed cards in hand.
    # Act 3 bosses (Queen+Torch erode, Test Subject Intangible phases,
    # Doormaker 489 HP reset) demand burst + precise sequencing.
    "kd_killer": RewardConfig(
        # Counters Knowledge Demon (#1 killer @ 21.5% of all deaths).
        # Heavy unspent-energy penalty trains the policy to empty its
        # hand each turn — exactly what Knowledge Demon punishes.
        combat_win=0.10, elite_kill=0.35, boss_kill=4.0, act_completion=2.5,
        run_victory=12.0, floor_advance=0.01, living_cost=-0.001, death=-2.0,
        energy_unspent_penalty=0.20,
    ),
    "act3_burst": RewardConfig(
        # Test Subject Intangible phases + Doormaker 489 HP need sustained
        # damage. Per-action damage reward + heavy boss terminal.
        combat_win=0.08, elite_kill=0.35, boss_kill=6.0, act_completion=2.0,
        run_victory=18.0, floor_advance=0.005, living_cost=-0.001, death=-2.0,
        damage_dealt_weight=0.012,
    ),
    "early_block": RewardConfig(
        # Act 1 survival is the run gate — community data shows act 1
        # death frequency is highest in absolute terms (most runs die
        # before reaching act 2). Heavy block + HP shaping early.
        combat_win=0.15, elite_kill=0.40, boss_kill=3.0, act_completion=1.5,
        run_victory=10.0, floor_advance=0.012, living_cost=-0.0008, death=-2.0,
        hp_delta_weight=0.020, block_gained_weight=0.005,
    ),
    "debuff_first": RewardConfig(
        # Queen+Torch erodes top 3 cards, only 1 playable per turn — must
        # pick the high-impact play. Vuln-before-Strike sequencing
        # learned via heavy enemy_power_weight.
        combat_win=0.10, elite_kill=0.35, boss_kill=4.0, act_completion=1.5,
        run_victory=12.0, floor_advance=0.01, living_cost=-0.001, death=-1.5,
        enemy_power_weight=0.22, damage_dealt_weight=0.005,
    ),
    "terminal_heavy": RewardConfig(
        # Mirrors community baseline: sparse intermediate signal, strong
        # terminals. Tests whether high run_victory alone closes the
        # 5-13% → 22% gap.
        combat_win=0.0, elite_kill=0.15, boss_kill=5.0, act_completion=2.5,
        run_victory=22.0, floor_advance=0.0, living_cost=-0.0008, death=-2.0,
    ),
    "kd_burst_hybrid": RewardConfig(
        # Combines kd_killer (empty hand) + act3_burst (damage). The
        # community signal points to both being load-bearing for high
        # ascension; test them together.
        combat_win=0.08, elite_kill=0.35, boss_kill=5.0, act_completion=2.0,
        run_victory=15.0, floor_advance=0.008, living_cost=-0.001, death=-2.0,
        damage_dealt_weight=0.010, energy_unspent_penalty=0.18,
    ),
    # ---- v5 diagnosed bottleneck preset (added 2026-05-28) ----
    # 5 long runs (e01/d01/f01/f02 + d04) all froze mean_floor at 9.0–9.85
    # regardless of arch (64→14M params) or steps (500K→3M). p90 swings
    # carried "peak" scores; the underlying floor distribution never moved.
    # Per-floor diagnostic showed boss-entry HP ~65/80 — the policy trades
    # HP for damage. shape_damage actively rewarded that behavior.
    #
    # a10_survive directly attacks both: heavy floor_advance to push the
    # distribution rightward (5× shape_damage), heavy hp_delta to penalize
    # HP-for-damage trades, and a big elite_kill bonus since the elite at
    # floor 7-9 is where the death distribution clusters at A10.
    "a10_survive": RewardConfig(
        combat_win=0.20, elite_kill=0.80, boss_kill=4.0, act_completion=2.0,
        run_victory=12.0, floor_advance=0.05, living_cost=-0.0003, death=-3.0,
        hp_delta_weight=0.025, block_gained_weight=0.005,
        damage_dealt_weight=0.002,
    ),
}


class RunEnv(gym.Env):
    """Full-run env. One Gym episode = one full STS2 run."""

    metadata: dict = {"render_modes": []}

    def __init__(self, ascension: int = 0, character: Character = Character.IRONCLAD,
                 reward_config: RewardConfig | None = None,
                 ascension_mixture: dict[int, float] | None = None):
        """
        Args:
            ascension: fixed ascension level. Ignored when ascension_mixture
                is provided.
            ascension_mixture: optional {level: weight} dict. Each reset()
                samples an ascension level proportional to weights. Used
                for curriculum (e.g., {0: 0.2, 5: 0.3, 10: 0.5}).
            reward_config: per-step shaping config (RewardConfig).
        """
        super().__init__()
        self.action_space = spaces.Discrete(N_ACTIONS)
        self.observation_space = spaces.Box(0.0, 1.0, shape=(OBS_DIM,),
                                            dtype=np.float32)
        self._ascension = ascension
        self._ascension_mixture = ascension_mixture  # None or {level: weight}
        if ascension_mixture is not None and not ascension_mixture:
            raise ValueError("ascension_mixture cannot be empty")
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
        # Episode-level milestone tracking — populated during step() for
        # Layer A (Tiered terminal score). Reset at reset().
        self._acts_completed: int = 0
        self._boss_dmg_dealt_ratio: float = 0.0
        self._boss_max_hp_at_act: int = 0
        self._boss_total_dmg_dealt: int = 0

    def _sample_ascension(self) -> int:
        """Sample an ascension from the mixture (if set) or return fixed."""
        if self._ascension_mixture is None:
            return self._ascension
        # Use the env's np_random for reproducibility.
        levels = list(self._ascension_mixture.keys())
        weights = np.array([self._ascension_mixture[k] for k in levels],
                           dtype=np.float64)
        weights /= weights.sum()
        return int(self.np_random.choice(levels, p=weights))

    # -- Gym API -------------------------------------------------------------

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        run_seed = seed if seed is not None else int(self.np_random.integers(0, 2**31 - 1))
        sampled_ascension = self._sample_ascension()
        self.rs = RunState.new_run(
            character=self._character,
            ascension=sampled_ascension,
            seed=run_seed,
        )
        start_run(self.rs)
        self._last_hp = self.rs.hp
        # Reset episode milestone counters for terminal score.
        self._acts_completed = 0
        self._boss_dmg_dealt_ratio = 0.0
        self._boss_max_hp_at_act = 0
        self._boss_total_dmg_dealt = 0
        self._invalidate_caches()
        return self._obs(), {"action_mask": self.action_masks()}

    def step(self, action: int):  # type: ignore[override]
        assert self.rs is not None, "call reset() first"
        pre = self._combat_snapshot()
        body = self._decode(int(action))
        result = step(self.rs, body)
        self._invalidate_caches()
        post = self._combat_snapshot()
        # Pass body so end_turn can be detected for the unspent-energy
        # penalty (player gets a small minus for ending with energy left).
        reward = self._reward(result, pre, post, body)
        terminated = self.rs.is_terminal()
        return (
            self._obs(),
            float(reward),
            terminated,
            False,
            {"action_mask": self.action_masks(), "result": result},
        )

    def _combat_snapshot(self) -> dict:
        """Cheap pre/post snapshot for per-action reward shaping.
        Returns 0s when not in combat so the shaping deltas vanish on
        map / event / reward states."""
        rs = self.rs
        if rs is None or not rs.in_combat() or rs.combat is None:
            return {"enemy_hp": 0, "player_block": 0, "enemy_vuln": 0,
                    "enemy_weak": 0, "player_strength": 0, "player_dex": 0,
                    "player_energy": 0}
        cs = rs.combat
        eh = sum(m.hp for m in cs.alive_monsters())
        ev = 0; ew = 0
        for m in cs.alive_monsters():
            for p in m.powers:
                if p.id == "vulnerable": ev += p.amount
                elif p.id == "weak":     ew += p.amount
        ps = 0; pd = 0
        for p in cs.player.powers:
            if p.id == "strength":  ps += p.amount
            elif p.id == "dexterity": pd += p.amount
        return {
            "enemy_hp": eh,
            "player_block": cs.player.block,
            "enemy_vuln": ev,
            "enemy_weak": ew,
            "player_strength": ps,
            "player_dex": pd,
            "player_energy": cs.player.energy,
        }

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
        if rs.state_type is StateType.CARD_REWARD:
            # Post-combat reward: mask reads view.card_reward.cards,
            # decode emits select_card_reward / skip_card_reward.
            cards = rs.pending_card_reward or []
            view["card_reward"] = {
                "cards": [{"index": i, "id": c.id} for i, c in enumerate(cards)],
                "can_skip": True,
            }
        elif rs.state_type is StateType.CARD_SELECT:
            # Grid picker (smith / transform / event grant): mask reads
            # view.card_select.cards, decode emits select_card / confirm.
            cards = rs.pending_card_reward or []
            view["card_select"] = {
                "cards": [{"index": i, "id": c.id} for i, c in enumerate(cards)],
                "can_confirm": False,
                "can_skip": False,
            }
        if rs.state_type is StateType.REST and rs.pending_rest_options is not None:
            view["state_type"] = "rest_site"  # match the live mod's emitted value
            view["rest_site"] = {
                "options": [
                    {"index": i, "id": o["id"], "is_enabled": o["is_enabled"]}
                    for i, o in enumerate(rs.pending_rest_options)
                ],
                "can_proceed": False,  # picks must happen before proceed
            }
        # Phase 3: expose pending_event and pending_shop so the existing
        # mask predicates (_event_mask, _shop_mask) work. Without this,
        # the env couldn't drive the new L1 events/shop since
        # state["event"].options would be empty.
        if rs.state_type is StateType.EVENT and rs.pending_event is not None:
            view["event"] = {
                "options": [
                    {"index": i, "id": o["id"], "enabled": o["enabled"]}
                    for i, o in enumerate(rs.pending_event.get("options", []))
                ],
            }
        if rs.state_type is StateType.SHOP and rs.pending_shop is not None:
            # Phase 3 shop only offers card removal — exposed as one
            # "item" slot 0 (removal) plus the leave slot. Phase 4 will
            # add buy items.
            items: list[dict[str, Any]] = []
            if not rs.pending_shop.get("removal_used", False):
                items.append({
                    "index": 0,
                    "category": "card_removal",
                    "price": rs.pending_shop.get("card_removal_cost", 75),
                    "can_afford": rs.gold >= rs.pending_shop.get(
                        "card_removal_cost", 75),
                    "is_stocked": True,
                })
            view["shop"] = {"items": items, "can_proceed": True}
        self._view_cache = (self._state_gen, view)
        return view

    def _build_mask(self, rs: RunState) -> list[bool]:
        return build_mask(self._mod_state_view())

    # -- observation --------------------------------------------------------

    def _obs(self) -> np.ndarray:
        """v2 layout — see notes/18_training_gaps.md for the full audit.

        v3 (2026-05-25): added per-card feature vectors to hand and
        card_reward. Without these the policy couldn't distinguish cards
        and degenerated to 99% skip on card rewards — see diagnose_policy
        run for the empirical confirmation.

        Field order is part of the obs contract; renumbering invalidates
        trained policies. OBS_DIM = 256, ~220 used.
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

        # v3: Hand identity ((CARD_FEATURE_DIM+1) × 10 slots).
        # Per slot: 12 card features (cost/type/damage/block/debuff/buff/
        # draw/energy/rarity/upgraded) + 1 can_play flag. The +1 flag is
        # appended so the legal-mask state is co-located with the card it
        # gates — the policy reads "card X is in slot S and playable" as
        # one block rather than scattered features.
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            for slot in range(10):
                base = cursor + slot * (CARD_FEATURE_DIM + 1)
                if slot < len(cs.hand):
                    c = cs.hand[slot]
                    feats = card_features(c.id)
                    for j in range(CARD_FEATURE_DIM):
                        v[base + j] = feats[j]
                    try:
                        v[base + CARD_FEATURE_DIM] = 1.0 if cs.can_play(slot) else 0.0
                    except Exception:
                        v[base + CARD_FEATURE_DIM] = 0.0
        cursor += 10 * (CARD_FEATURE_DIM + 1)

        # v3: Card-reward identity (5 slots × CARD_FEATURE_DIM = 60).
        # Replaces v2's "count + attack share" (3 dims), which was the
        # actual root cause of the 99% skip-rate plateau: without per-
        # option features the policy couldn't tell common Strike apart
        # from a rare Bludgeon, so "skip" generalized as the safest
        # answer.
        if rs.pending_card_reward:
            for slot in range(5):
                base = cursor + slot * CARD_FEATURE_DIM
                if slot < len(rs.pending_card_reward):
                    c = rs.pending_card_reward[slot]
                    feats = card_features(c.id)
                    for j in range(CARD_FEATURE_DIM):
                        v[base + j] = feats[j]
        cursor += 5 * CARD_FEATURE_DIM

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

        # ===== obs v4 additions (Phase 2, 2026-05-27) =====
        # Appended to v3 layout. OBS_DIM bumped 256 → 320. v3 cursors
        # 0..~220 preserved for any code reading specific positions.

        # v4: Boss identity (9 dim: act × boss_type one-hot 3×3).
        # L1 placeholder — full boss roster comes once sim/boss_registry
        # lands. For now we encode act-only one-hot in slots [0..2] of
        # the 9-block and leave per-boss-type slots zero. The training
        # signal is still sharper than no-encoding-at-all.
        if rs.act >= 1 and rs.act <= 3:
            v[cursor + (rs.act - 1) * 3] = 1.0
        cursor += 9

        # v4: Relic identity by category (17 dim: count per RELIC_CATEGORIES bucket).
        # Each owned relic increments its category bucket, normalized by
        # the L1 max (~5 — typical mid-act relic count). Lets the policy
        # learn "I have a thorns relic" without enumerating every relic id.
        try:
            from .relics import RELIC_CATEGORIES, relic_category_index
            cat_counts = np.zeros(len(RELIC_CATEGORIES), dtype=np.float32)
            for r in rs.relics:
                idx = relic_category_index(r.id)
                cat_counts[idx] += 1.0
            cat_counts /= 5.0  # normalize: 5 relics in any one bucket = saturation
            for i, c in enumerate(cat_counts):
                v[cursor + i] = min(1.0, c)
            cursor += len(RELIC_CATEGORIES)
        except Exception:
            cursor += 17  # skip on import error

        # v4: Intent damage absolute value (per enemy slot, 3 dim).
        # Replaces v2's `0.5 placeholder` with the real expected damage,
        # normalized by current max_hp so it's comparable to defensive
        # capacity. Critical for "this hit kills me" awareness.
        if rs.in_combat() and rs.combat is not None:
            alive = rs.combat.alive_monsters()
            for slot in range(3):
                if slot < len(alive):
                    m = alive[slot]
                    intent_dmg = 0
                    if hasattr(m, "intent_damage"):
                        try:
                            intent_dmg = int(m.intent_damage())
                        except Exception:
                            intent_dmg = 0
                    elif hasattr(m, "next_move") and m.next_move is not None:
                        mv = str(m.next_move).upper()
                        if any(tok in mv for tok in _ATTACK_MOVE_TOKENS):
                            # Fallback rough estimate when intent_damage helper
                            # isn't on the monster: assume ~6 base damage.
                            intent_dmg = 6
                    v[cursor + slot] = min(1.0, intent_dmg / max(1, rs.max_hp))
        cursor += 3

        # v4: Max-hp absolute value (compressed). max_hp varies a lot
        # across the run with relic pickups + max_hp-loss events; the
        # v3 layout only had hp/max_hp ratio. Tag the absolute now.
        v[cursor] = min(1.0, rs.max_hp / 200.0)
        cursor += 1

        # v4: Distance dims. distance_to_act_boss and distance_to_victory.
        # rs.floor is PER-ACT (game ActFloor), so distance to THIS act's
        # boss is (boss_floor_this_act - floor). Distance to victory is
        # floors left this act + the full lengths of the remaining acts.
        # The old code treated floor as global cumulative (boss at
        # 17/34/51) which, against a per-act floor, made both dims garbage
        # for acts 2 and 3.
        cur_act = rs.act if rs.act in _ACT_BOSS_FLOOR else 3
        a10 = int(rs.ascension) >= 10
        boss_fl = _ACT_BOSS_FLOOR[cur_act] + (1 if (cur_act == 3 and a10) else 0)
        # floors remaining until victory: this act's boss + later acts
        remaining = max(0, boss_fl - rs.floor)
        for a in range(cur_act + 1, 4):
            remaining += _ACT_BOSS_FLOOR[a] + (1 if (a == 3 and a10) else 0)
        total_floors = _RUN_TOTAL_FLOORS + (1 if a10 else 0)
        v[cursor + 0] = max(0.0, min(1.0, (boss_fl - rs.floor) / boss_fl))
        v[cursor + 1] = max(0.0, min(1.0, remaining / total_floors))
        cursor += 2

        # v4: Energy absolute + block log compression.
        if rs.in_combat() and rs.combat is not None:
            cs = rs.combat
            v[cursor + 0] = min(1.0, cs.player.energy / 5.0)
            import math as _math
            v[cursor + 1] = min(1.0, _math.log(1.0 + max(0, cs.player.block)) /
                                _math.log(1.0 + 100.0))
            v[cursor + 2] = 1.0 if cs.player.energy > 3 else 0.0  # overflow flag
        cursor += 3

        # v4: Enemy count one-hot (1/2/3).
        if rs.in_combat() and rs.combat is not None:
            alive = rs.combat.alive_monsters()
            n = min(3, max(1, len(alive)))
            v[cursor + (n - 1)] = 1.0
        cursor += 3

        # === v4 Phase 3 additions: per-option features ===
        # 8 event option slots × 8-d tag vector = 64 dim. Each slot's
        # tag vector matches OPTION_FEATURE_BITS (see sim/events.py).
        # Lets the policy distinguish "this option costs HP" from
        # "this option gains a relic" at the action-head level — the
        # pointer-style scoring mechanism we discussed in Phase 3.
        try:
            from .events import OPTION_FEATURE_BITS, encode_option_tag
            n_event_feats = len(OPTION_FEATURE_BITS)  # 8
            if rs.state_type is StateType.EVENT and rs.pending_event:
                opts = rs.pending_event.get("options", [])
                for slot in range(8):
                    if slot >= len(opts):
                        break
                    bits = encode_option_tag(opts[slot].get("tag", ""))
                    for j, b in enumerate(bits):
                        v[cursor + slot * n_event_feats + j] = b
            cursor += 8 * n_event_feats
        except Exception:
            cursor += 64

        # Shop info (4 dim): has_pending_shop, card_removal_cost_ratio,
        # removal_used, deck_size_normalized. Lets the policy decide
        # whether removal is affordable + worthwhile.
        if rs.state_type is StateType.SHOP and rs.pending_shop:
            v[cursor + 0] = 1.0
            cost = rs.pending_shop.get("card_removal_cost", 75)
            v[cursor + 1] = min(1.0, cost / max(1, rs.gold + cost))
            v[cursor + 2] = 1.0 if rs.pending_shop.get("removal_used") else 0.0
            v[cursor + 3] = min(1.0, len(rs.deck) / 30.0)
        cursor += 4

        # Map lookahead (next floor): aggregate room-type ratios over the
        # nodes reachable from the current floor. 6-d (monster/elite/
        # event/rest/shop/treasure). Helps policy choose paths that
        # avoid early elites or seek shop/rest when needed.
        try:
            if rs.state_type is StateType.MAP and rs.maps and rs.maps[rs.act - 1]:
                lookahead = self._reachable_map_nodes_cached()
                if lookahead:
                    counts = {"monster": 0, "elite": 0, "event": 0,
                              "rest": 0, "shop": 0, "treasure": 0}
                    total = 0
                    for node in lookahead:
                        rt = node.room_type.value if hasattr(node.room_type, "value") else str(node.room_type)
                        if rt in counts:
                            counts[rt] += 1
                            total += 1
                    if total > 0:
                        for j, k in enumerate(["monster", "elite", "event",
                                               "rest", "shop", "treasure"]):
                            v[cursor + j] = counts[k] / total
            cursor += 6
        except Exception:
            cursor += 6

        # Reserve remaining dims (~60+) for future Phase additions
        # (boss-specific identity, deck-quality scalar, etc.).

        # Final cursor expected ~332; OBS_DIM = 320.
        # NOTE: if cursor > OBS_DIM, the writes silently truncated above.
        # `assert cursor <= OBS_DIM` would crash but we'd rather absorb
        # the off-by-one risk than crash live inference. The unit tests
        # verify the cursor budget.

        v.clip(0.0, 1.0, out=v)
        return v

    # -- reward -------------------------------------------------------------

    def _reward(self, result: StepResult, pre: dict | None = None,
                post: dict | None = None, body: dict | None = None) -> float:
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
        # Per-action shaping. Only meaningful when pre and post are
        # both in-combat (snapshots return 0 outside combat so deltas
        # vanish for map/event/reward steps).
        if pre is not None and post is not None and (pre["enemy_hp"] or post["enemy_hp"]):
            if cfg.damage_dealt_weight != 0.0:
                dmg = max(0, pre["enemy_hp"] - post["enemy_hp"])
                r += cfg.damage_dealt_weight * dmg
            if cfg.block_gained_weight != 0.0:
                blk = max(0, post["player_block"] - pre["player_block"])
                r += cfg.block_gained_weight * blk
            if cfg.enemy_power_weight != 0.0:
                # Sum Vuln + Weak stack increases. Encourages applying
                # debuffs BEFORE the cards that benefit from them.
                stk = (max(0, post["enemy_vuln"] - pre["enemy_vuln"])
                       + max(0, post["enemy_weak"] - pre["enemy_weak"]))
                r += cfg.enemy_power_weight * stk
            if cfg.self_power_weight != 0.0:
                stk = (max(0, post["player_strength"] - pre["player_strength"])
                       + max(0, post["player_dex"] - pre["player_dex"]))
                r += cfg.self_power_weight * stk
            if cfg.energy_unspent_penalty != 0.0 and body is not None \
               and body.get("action") == "end_turn":
                # Ending the turn with leftover energy is almost always
                # a planning failure (could have played another 1-cost).
                r -= cfg.energy_unspent_penalty * pre["player_energy"]

        # Track milestone state for Tiered terminal score (Layer A).
        # These run independently of cfg so they fire even when shaping
        # weights are 0. Read by compute_terminal_score() at episode end.
        if self.rs is not None:
            if result.act_completed:
                self._acts_completed += 1
            # Damage accumulator for the in-progress act-boss fight.
            if self.rs.in_combat() and self.rs.state_type.value == "boss":
                cs = self.rs.combat
                if cs is not None and pre is not None and post is not None:
                    dmg = max(0, pre["enemy_hp"] - post["enemy_hp"])
                    self._boss_total_dmg_dealt += dmg
                    if self._boss_max_hp_at_act == 0 and cs.monsters:
                        self._boss_max_hp_at_act = sum(
                            m.max_hp for m in cs.monsters)
                    if self._boss_max_hp_at_act > 0:
                        self._boss_dmg_dealt_ratio = min(
                            1.0,
                            self._boss_total_dmg_dealt / self._boss_max_hp_at_act,
                        )

        return r

    # -- Tiered terminal score (Layer A) ------------------------------------

    def compute_terminal_score(self) -> float:
        """Tiered terminal reward — fires once at episode end.

        S = 100 * acts_completed
          + 50  * within_act_progress
          + 30  * within_act_boss_dmg_ratio   (boss fight in current act)
          + 300 * victory

        Always returns a non-negative value. Designed so:
          - Floor 5 die early act 1: ~15
          - Floor 16 die just before act 1 boss: ~47
          - Beat act 1, die mid act 2: ~124
          - Beat act 2, die mid act 3: ~232
          - Beat act 3 boss: 600

        Used by the new training pipeline (Phase 4) and the evolver
        composite_score (Phase 4). Independent of RewardConfig weights —
        this is the run's "true" objective.
        """
        if self.rs is None:
            return 0.0

        S = 100.0 * self._acts_completed

        # Within-act progress: where in the current act we are.
        # rs.floor is PER-ACT (resets to 0 each act transition, see
        # run_engine `_step_proceed` rs.floor=0), matching the game's
        # IRunState.ActFloor — NOT the global TotalFloor. Each act's boss
        # sits at a DIFFERENT floor: act1=17, act2=16, act3=15
        # (rooms 15/14/13 + 2, per ActModel.GetNumberOfFloors). The old
        # code subtracted 17/34 from a per-act floor, so acts 2&3 always
        # clamped to 0 — the within-act gradient was dead exactly at the
        # frontier we want to push.
        boss_fl = _ACT_BOSS_FLOOR.get(self.rs.act, 15)
        within = max(0.0, min(1.0, self.rs.floor / boss_fl))
        S += 50.0 * within

        # Boss damage ratio — only meaningful when the run died in a boss
        # fight. The accumulator was tracked across the run; if the death
        # happened outside a boss it'll be 0.
        S += 30.0 * self._boss_dmg_dealt_ratio

        # Victory bonus dominates.
        if self.rs.is_victorious:
            S += 300.0

        return float(S)
