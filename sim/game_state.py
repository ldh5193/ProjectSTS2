"""Top-level run state for the full-game simulator.

This module models *outside* combat — character/ascension select, the
per-act map, the room dispatcher, and the cross-room shared resources
(deck, relics, gold, potions, HP). Combat itself stays in
sim/combat.py and is driven into and out of by RunState.

State machine mirrors the live mod's `state_type` enum
(notes/06_mcp_api.md §2.1) so observation/action wiring stays direct.

Scope of this first slice:
- Ironclad only (other characters are stubbed).
- Ascension 0..10 supported by the data model; only the effects from
  AscensionManager.ApplyEffectsTo and the explicit checks already in
  the decompiled monster classes (ToughEnemies, DeadlyEnemies,
  DoubleBoss) are wired. Other ascensions land as TODO.
- Acts 1..3 framed; act-1 content drives the first working slice.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from .cards import build_starting_deck
from .dsl import CardDef
from .rng import PlayerRngSet, RunRngSet, get_deterministic_hash_code


# Mirrors notes/06_mcp_api.md §2.1 (the mod's `state_type` field) so the
# Discrete(300) action_space mapping in sim/action_space.py applies directly.
class StateType(str, Enum):
    MENU = "menu"
    MAP = "map"
    MONSTER = "monster"           # normal combat
    ELITE = "elite"
    BOSS = "boss"
    EVENT = "event"
    SHOP = "shop"
    REST = "rest"
    TREASURE = "treasure"         # treasure room (post-elite-typical)
    CARD_SELECT = "card_select"   # post-combat card reward / generic card grid
    CARD_REWARD = "card_reward"
    REWARDS = "rewards"           # multi-reward screen (relic/gold/potion)
    RELIC_SELECT = "relic_select"
    HAND_SELECT = "hand_select"
    GAME_OVER = "game_over"
    VICTORY = "victory"           # convenience separate from defeat


# AscensionLevel mirrors decompiled MegaCrit.Sts2.Core.Entities.Ascension.AscensionLevel.
# Values match the int cast used in AscensionManager.HasLevel.
class Ascension(int, Enum):
    NONE = 0
    SWARMING_ELITES = 1
    WEARY_TRAVELER = 2
    POVERTY = 3
    TIGHT_BELT = 4              # -1 potion slot
    ASCENDERS_BANE = 5          # +1 AscendersBane curse in deck
    INFLATION = 6
    SCARCITY = 7
    TOUGH_ENEMIES = 8           # +HP on monsters (per-monster gated)
    DEADLY_ENEMIES = 9          # +damage on monster moves (per-monster gated)
    DOUBLE_BOSS = 10            # act-3 boss replaced with two-boss encounter


class Character(str, Enum):
    IRONCLAD = "ironclad"
    SILENT = "silent"
    DEFECT = "defect"
    NECROBINDER = "necrobinder"
    REGENT = "regent"
    DEPRIVED = "deprived"


# Starting stats per character (decompiled/MegaCrit.Sts2.Core.Models.Characters/*.cs).
# Only Ironclad is wired for the first slice.
_CHARACTER_STARTING_HP: dict[Character, int] = {
    Character.IRONCLAD: 80,
}
_CHARACTER_STARTING_GOLD: dict[Character, int] = {
    Character.IRONCLAD: 99,
}


@dataclass
class RelicInstance:
    """Lightweight relic tag. Full effect dispatch lives in sim/relics.py
    once the relic catalog is populated."""
    id: str
    counter: int | None = None


@dataclass
class PotionInstance:
    id: str


@dataclass
class MapNode:
    """One room on the per-act map. Coordinates are floor (depth) and x
    (lane position within the floor). Edges are explicit successor lists
    rather than implicit from grid math so the generator can match the
    real game's branching."""
    floor: int
    x: int
    room_type: StateType
    children: list[tuple[int, int]] = field(default_factory=list)
    # Encounter resolution is delayed until the player enters — keeps
    # generation cost down and matches how the live game handles it.
    encounter_id: str | None = None


@dataclass
class RunMap:
    """Per-act map. floors[i] is the list of nodes on floor i (1-indexed).
    floor 0 is the implicit "start" with edges into every floor-1 node.
    Boss floor is the last index (typically floor 15 in STS1; STS2 may
    differ — set by the generator)."""
    act: int
    floors: list[list[MapNode]]
    boss_floor: int

    def node(self, floor: int, x: int) -> MapNode:
        return self.floors[floor - 1][x]

    def reachable_from(self, floor: int, x: int) -> list[MapNode]:
        """Successor nodes legal to enter from (floor, x). On floor 0
        (pre-start) returns every floor-1 node."""
        if floor == 0:
            return list(self.floors[0])
        return [self.floors[f - 1][nx] for (f, nx) in self.node(floor, x).children]


@dataclass
class RunState:
    """Top-level run state. Drives both the action space and the
    observation. Mutable; one instance per episode.
    """
    character: Character = Character.IRONCLAD
    ascension: Ascension = Ascension.NONE
    run_seed: int = 0                # uint32 from string seed via deterministic hash
    run_seed_string: str = ""        # original user-facing seed string

    state_type: StateType = StateType.MENU

    act: int = 1
    floor: int = 0                   # 0 = pre-map start, increments as rooms entered
    current_node: tuple[int, int] = (0, 0)  # (floor, x). (0, 0) before map start.

    hp: int = 0
    max_hp: int = 0
    gold: int = 0

    deck: list[CardDef] = field(default_factory=list)
    relics: list[RelicInstance] = field(default_factory=list)
    potions: list[Optional[PotionInstance]] = field(default_factory=lambda: [None, None, None])
    max_potion_slots: int = 3
    # Self-adjusting potion-reward odds (decompiled PotionRewardOdds: base 0.4,
    # drifts ±0.1 toward the 0.5 target each combat). Persists across the run.
    potion_reward_odds: float = 0.4

    # Per-act maps; index = act-1.
    maps: list[Optional[RunMap]] = field(default_factory=lambda: [None, None, None])

    # Combat context — None outside of combat. Populated by RunState.enter_combat.
    combat: Any = None  # sim.combat.CombatState (avoid import cycle)

    # Card reward / event / shop overlays — opaque payloads, set when the
    # corresponding room type is entered.
    pending_card_reward: list[CardDef] | None = None
    pending_relic_choice: list[RelicInstance] | None = None
    pending_event: Any = None
    pending_shop: Any = None
    # Rest-site options the policy must pick from. Each entry is a dict
    # {id, is_enabled} mirroring the live mod's rest_site.options shape.
    # None when not at a rest site. Drained by _step_rest.
    pending_rest_options: list[dict] | None = None

    # Anti-repeat memory for the various pools.
    history_monster_encounters: list[str] = field(default_factory=list)
    history_elite_encounters: list[str] = field(default_factory=list)
    history_events: list[str] = field(default_factory=list)
    history_card_rewards: list[str] = field(default_factory=list)
    history_relics: list[str] = field(default_factory=list)

    # PRNG. Built once at run start. PlayerRngSet would be shared across
    # runs in real STS2, but a per-episode set is fine for training and
    # keeps determinism simple.
    run_rng: RunRngSet = field(default=None)        # type: ignore[assignment]
    player_rng: PlayerRngSet = field(default=None)  # type: ignore[assignment]

    # Episode termination markers.
    is_dead: bool = False
    is_victorious: bool = False

    @classmethod
    def new_run(
        cls,
        *,
        character: Character = Character.IRONCLAD,
        ascension: int = 0,
        seed: str | int | None = None,
    ) -> "RunState":
        """Create a fresh run.

        `seed` is either a user-facing seed string (matches how the game
        UI accepts seeds), a raw uint32 seed, or None (caller is
        expected to provide deterministic seeding via training pipeline).
        """
        run_seed_string = ""
        if isinstance(seed, str):
            run_seed_string = seed
            run_seed_uint = get_deterministic_hash_code(seed) & 0xFFFFFFFF
        elif isinstance(seed, int):
            run_seed_uint = seed & 0xFFFFFFFF
            run_seed_string = str(seed)
        else:
            # No seed: use 0; training pipeline should override.
            run_seed_uint = 0

        rs = cls(
            character=character,
            ascension=Ascension(ascension),
            run_seed=run_seed_uint,
            run_seed_string=run_seed_string,
            state_type=StateType.MENU,
            max_hp=_CHARACTER_STARTING_HP.get(character, 70),
            hp=_CHARACTER_STARTING_HP.get(character, 70),
            gold=_CHARACTER_STARTING_GOLD.get(character, 99),
            deck=list(build_starting_deck()) if character is Character.IRONCLAD else [],
            relics=[RelicInstance(id="BURNING_BLOOD")] if character is Character.IRONCLAD else [],
            run_rng=RunRngSet(run_seed_uint),
            player_rng=PlayerRngSet(run_seed_uint),
        )
        _apply_ascension_effects(rs)
        return rs

    # ---- predicates ---------------------------------------------------------

    def is_terminal(self) -> bool:
        return self.is_dead or self.is_victorious

    def in_combat(self) -> bool:
        return self.state_type in (StateType.MONSTER, StateType.ELITE, StateType.BOSS)

    # ---- HP / gold helpers --------------------------------------------------

    def lose_hp(self, amount: int) -> int:
        actual = min(self.hp, max(amount, 0))
        self.hp -= actual
        if self.hp <= 0:
            self.hp = 0
            self.is_dead = True
            self.state_type = StateType.GAME_OVER
        return actual

    def heal(self, amount: int) -> int:
        before = self.hp
        self.hp = min(self.max_hp, self.hp + max(amount, 0))
        return self.hp - before

    def lose_max_hp(self, amount: int) -> int:
        """Permanent max_hp reduction (events like TabletOfTruth). Caps
        current hp to new max. If max_hp would drop to 0, the run ends —
        matches decompiled CreatureCmd.LoseMaxHp guard (Kill if max_hp <= 0).
        """
        actual = max(0, amount)
        if actual >= self.max_hp:
            self.max_hp = 0
            self.hp = 0
            self.is_dead = True
            self.state_type = StateType.GAME_OVER
            return actual
        self.max_hp -= actual
        if self.hp > self.max_hp:
            self.hp = self.max_hp
        return actual

    def gain_max_hp(self, amount: int) -> int:
        """Permanent max_hp increase. Also heals by the same amount —
        matches decompiled CreatureCmd.GainMaxHp behavior."""
        gained = max(0, amount)
        self.max_hp += gained
        self.hp = min(self.max_hp, self.hp + gained)
        return gained

    def gain_gold(self, amount: int) -> None:
        self.gold = max(0, self.gold + amount)

    def has_relic(self, relic_id: str) -> bool:
        return any(r.id == relic_id for r in self.relics)

    def add_relic(self, relic_id: str) -> None:
        """Append a relic. Idempotent (most relics are unique).

        Pickup-time effects (Strawberry +7 max HP, Pomander double-pots,
        etc.) fire here since on-pickup hooks don't fit the lifecycle
        hook system. L1 set: Strawberry only — extend as needed.
        """
        if self.has_relic(relic_id):
            return
        self.relics.append(RelicInstance(id=relic_id))
        # Pickup-time max_hp effects (decompiled MaxHpVar at pickup).
        if relic_id == "STRAWBERRY":
            self.gain_max_hp(7)
        elif relic_id == "PEAR":
            self.gain_max_hp(10)
        elif relic_id == "MANGO":
            self.gain_max_hp(14)
        elif relic_id == "DARKSTONE_PERIAPT":
            self.gain_max_hp(6)

    def add_potion(self, potion_id: str) -> bool:
        """Place a potion in the first empty slot. Returns False if all
        slots are full (mirrors the game's auto-discard behavior — the
        policy decides whether to use one to make room)."""
        for i in range(min(self.max_potion_slots, len(self.potions))):
            if self.potions[i] is None:
                self.potions[i] = PotionInstance(id=potion_id)
                return True
        # Try to extend the list if it's shorter than max_potion_slots.
        if len(self.potions) < self.max_potion_slots:
            self.potions.append(PotionInstance(id=potion_id))
            return True
        return False


def _apply_ascension_effects(rs: RunState) -> None:
    """Decompiled MegaCrit.Sts2.Core.Entities.Ascension.AscensionManager
    only applies two start-of-run effects:
      A4 TightBelt     -> max_potion_slots -= 1
      A5 AscendersBane -> insert AscendersBane curse card into deck

    Other ascensions (TOUGH_ENEMIES, DEADLY_ENEMIES, DOUBLE_BOSS, etc.)
    are checked at the point of use elsewhere (monster HP/damage,
    boss room generation, etc.).
    """
    level = int(rs.ascension)
    if level >= int(Ascension.TIGHT_BELT):
        rs.max_potion_slots = max(0, rs.max_potion_slots - 1)
        rs.potions = rs.potions[: rs.max_potion_slots] + \
            [None] * max(0, rs.max_potion_slots - len(rs.potions))
    if level >= int(Ascension.ASCENDERS_BANE):
        # AscendersBane is a curse card. Sim doesn't model curses yet;
        # placeholder so the deck count matches the game.
        from .dsl import CardDef as _CardDef
        from .dsl import CardType, EffectOp, Target
        ascenders_bane = _CardDef(
            id="ascenders_bane",
            name="AscendersBane",
            cost=-1,               # "unplayable" in STS terms
            type=CardType.SKILL,   # curses aren't really skills; placeholder
            effects=(),
            count=0,
        )
        rs.deck.append(ascenders_bane)
