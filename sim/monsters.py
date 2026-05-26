"""Monsters porting from `decompiled/MegaCrit.Sts2.Core.Models.Monsters/*`.

Currently modeled:
  - SludgeSpinnerWeak — MVP, RandomBranch with CannotRepeat (notes/05).
  - NibbitWeak — solo Nibbit, deterministic BUTT -> SLICE -> HISS cycle
    (Nibbit.cs + NibbitsWeak.cs, IsAlone=true branch).

Each `spawn(rng, ascension=0)` returns a Monster instance with HP/damage
values scaled per the decompiled `AscensionHelper.GetValueIfAscension`:
  - A8 ToughEnemies  -> swaps to ascended HP (and block on Nibbit/Lagavulin)
  - A9 DeadlyEnemies -> swaps to ascended damage (and some buff amounts)
Per-monster ascended values are extracted verbatim from each *.cs file.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .creatures import Creature, Monster
from .damage import deal_damage
from .powers import StrengthPower, WeakPower, make_power


def _a8(asc: int, base: int, ascended: int) -> int:
    """Return ascended value if ASC>=8 (ToughEnemies), else base."""
    return ascended if asc >= 8 else base


def _a9(asc: int, base: int, ascended: int) -> int:
    """Return ascended value if ASC>=9 (DeadlyEnemies), else base."""
    return ascended if asc >= 9 else base


class SludgeMove(str, Enum):
    OIL_SPRAY = "oil_spray"  # 8 dmg + Weak 1
    SLAM = "slam"            # 11 dmg
    RAGE = "rage"            # 6 dmg + self Strength 3


SLUDGE_MOVES = (SludgeMove.OIL_SPRAY, SludgeMove.SLAM, SludgeMove.RAGE)

# Base / A8 ToughEnemies HP range (decompiled SludgeSpinner.cs:23-25).
SLUDGE_HP_MIN, SLUDGE_HP_MAX = 37, 39
SLUDGE_HP_MIN_A8, SLUDGE_HP_MAX_A8 = 41, 42


@dataclass
class SludgeSpinnerWeak(Monster):
    last_move: SludgeMove | None = None
    next_move: SludgeMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "SludgeSpinnerWeak":
        lo = _a8(ascension, SLUDGE_HP_MIN, SLUDGE_HP_MIN_A8)
        hi = _a8(ascension, SLUDGE_HP_MAX, SLUDGE_HP_MAX_A8)
        hp = rng.randint(lo, hi)
        # First move is fixed to OIL_SPRAY per §B.3 ("initial state").
        m = cls(name="Sludge Spinner", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = SludgeMove.OIL_SPRAY
        return m

    def roll_next_move(self, rng: random.Random) -> SludgeMove:
        # RandomBranchState with CannotRepeat constraint (§B.3).
        candidates = [m for m in SLUDGE_MOVES if m != self.last_move]
        return rng.choice(candidates)

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        """Execute self.next_move against player. Returns event dict for logs/tests."""
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}

        if move is SludgeMove.OIL_SPRAY:
            dmg = _a9(self.ascension, 8, 9)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            player.add_or_stack_power(make_power("weak", 1, player))
        elif move is SludgeMove.SLAM:
            dmg = _a9(self.ascension, 11, 12)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is SludgeMove.RAGE:
            dmg = _a9(self.ascension, 6, 7)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            # Grant +3 Strength to self.
            strength = StrengthPower(amount=3)
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


def spawn_nibbits_normal(rng, ascension: int = 0) -> list[Monster]:
    """NibbitsNormal encounter: 2 Nibbits with IsFront / IsBack starting moves.

    Per notes/16: front opens with SLICE, back opens with HISS. The shared
    BUTT → SLICE → HISS state machine is reused.
    """
    front = NibbitWeak.spawn(rng, ascension=ascension)
    front.name = "Nibbit (Front)"
    front.next_move = NibbitMove.SLICE
    back = NibbitWeak.spawn(rng, ascension=ascension)
    back.name = "Nibbit (Back)"
    back.next_move = NibbitMove.HISS
    return [front, back]


# --- NibbitWeak (NIBBIT_0, IsAlone) -----------------------------------------
# Cites:
#   decompiled/MegaCrit.Sts2.Core.Models.Monsters/Nibbit.cs (lines 23-33)
#   decompiled/MegaCrit.Sts2.Core.Models.Encounters/NibbitsWeak.cs


class NibbitMove(str, Enum):
    BUTT = "butt"    # 12 dmg
    SLICE = "slice"  # 6 dmg + self block 5
    HISS = "hiss"    # self Strength +2


# Base / A8 ToughEnemies HP range + slice block.
NIBBIT_HP_MIN, NIBBIT_HP_MAX = 42, 46
NIBBIT_HP_MIN_A8, NIBBIT_HP_MAX_A8 = 44, 48
_NIBBIT_SLICE_BLOCK = 5
_NIBBIT_SLICE_BLOCK_A8 = 6

# Solo Nibbit (IsAlone branch in NibbitsWeak.cs) opens with BUTT.
# The state machine threads BUTT.FollowUp=SLICE, SLICE.FollowUp=HISS,
# HISS.FollowUp=BUTT — a fixed cycle, no RNG branching.
_NIBBIT_SOLO_FOLLOWUP = {
    NibbitMove.BUTT: NibbitMove.SLICE,
    NibbitMove.SLICE: NibbitMove.HISS,
    NibbitMove.HISS: NibbitMove.BUTT,
}


@dataclass
class NibbitWeak(Monster):
    last_move: NibbitMove | None = None
    next_move: NibbitMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "NibbitWeak":
        lo = _a8(ascension, NIBBIT_HP_MIN, NIBBIT_HP_MIN_A8)
        hi = _a8(ascension, NIBBIT_HP_MAX, NIBBIT_HP_MAX_A8)
        hp = rng.randint(lo, hi)
        m = cls(name="Nibbit", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = NibbitMove.BUTT  # IsAlone branch
        return m

    def roll_next_move(self, rng: random.Random) -> NibbitMove:
        if self.last_move is None:
            return NibbitMove.BUTT
        return _NIBBIT_SOLO_FOLLOWUP[self.last_move]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}

        if move is NibbitMove.BUTT:
            dmg = _a9(self.ascension, 12, 13)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is NibbitMove.SLICE:
            dmg = _a9(self.ascension, 6, 7)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            self.block += _a8(self.ascension, _NIBBIT_SLICE_BLOCK, _NIBBIT_SLICE_BLOCK_A8)
        elif move is NibbitMove.HISS:
            strength = StrengthPower(amount=_a9(self.ascension, 2, 3))
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- CeremonialBeast (Act 1 boss, solo) ------------------------------------
# Cites:
#   decompiled/MegaCrit.Sts2.Core.Models.Monsters/CeremonialBeast.cs (move table)
#   decompiled/MegaCrit.Sts2.Core.Models.Encounters/CeremonialBeastBoss.cs
# Sim is the non-Ascension column; the Plow / Ringing debuffs are
# approximated by Strength / Weak respectively until those powers land.


class BeastMove(str, Enum):
    STAMP = "stamp"       # buff (Plow stack); sim: small strength gain
    PLOW = "plow"         # 18 dmg + Strength +2
    STUN = "stun"         # no-op turn
    BEAST_CRY = "cry"     # apply Weak (sim approximation of Ringing)
    STOMP = "stomp"       # 15 dmg
    CRUSH = "crush"       # 17 dmg + Strength +3


# CeremonialBeast.cs:52-66 — A8 HP 252→262, A9 PlowDmg 18→20, StompDmg
# 15→17, CrushDmg 17→19, CrushStrength 3→4. PlowAmount (Plow stack
# 150→160) is approximated as +1 Strength via STAMP in sim.
BEAST_HP = 252
BEAST_HP_A8 = 262

_BEAST_CYCLE = (
    BeastMove.STAMP, BeastMove.PLOW, BeastMove.STUN,
    BeastMove.BEAST_CRY, BeastMove.STOMP, BeastMove.CRUSH,
)


@dataclass
class CeremonialBeast(Monster):
    last_move: BeastMove | None = None
    next_move: BeastMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "CeremonialBeast":
        hp = _a8(ascension, BEAST_HP, BEAST_HP_A8)
        m = cls(name="Ceremonial Beast", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = _BEAST_CYCLE[0]
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> BeastMove:
        self.cycle_index = (self.cycle_index + 1) % len(_BEAST_CYCLE)
        return _BEAST_CYCLE[self.cycle_index]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}

        if move is BeastMove.PLOW:
            dmg = _a9(self.ascension, 18, 20)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            strength = StrengthPower(amount=2)
            strength._owner = self
            self.add_or_stack_power(strength)
        elif move is BeastMove.STAMP:
            # Plow stack: approximate with +1 Strength.
            strength = StrengthPower(amount=1)
            strength._owner = self
            self.add_or_stack_power(strength)
        elif move is BeastMove.STUN:
            pass  # no-op turn
        elif move is BeastMove.BEAST_CRY:
            # Ringing debuff -> approximate as Weak on player.
            from .powers import make_power
            player.add_or_stack_power(make_power("weak", 2, player))
        elif move is BeastMove.STOMP:
            dmg = _a9(self.ascension, 15, 17)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is BeastMove.CRUSH:
            dmg = _a9(self.ascension, 17, 19)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            strength = StrengthPower(amount=_a9(self.ascension, 3, 4))
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- TheInsatiable (Act 2 boss, solo) -------------------------------------
# Cites: decompiled/MegaCrit.Sts2.Core.Models.Monsters/TheInsatiable.cs
# Simplified — LIQUIFY's SandpitPower + FranticEscape status cards are
# approximated as a single Weak debuff (sim has no status-card system yet).


class InsatiableMove(str, Enum):
    LIQUIFY = "liquify"
    THRASH1 = "thrash1"
    LUNGING_BITE = "bite"
    SALIVATE = "salivate"
    THRASH2 = "thrash2"


# TheInsatiable.cs:54-62 — A8 HP 321→341, A9 Thrash 8→9 per hit, Bite
# 28→31, Salivate strength 2→3.
INSATIABLE_HP = 321
INSATIABLE_HP_A8 = 341

_INSATIABLE_CYCLE = (
    InsatiableMove.LIQUIFY, InsatiableMove.THRASH1, InsatiableMove.LUNGING_BITE,
    InsatiableMove.SALIVATE, InsatiableMove.THRASH2,
)


@dataclass
class TheInsatiable(Monster):
    last_move: InsatiableMove | None = None
    next_move: InsatiableMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "TheInsatiable":
        hp = _a8(ascension, INSATIABLE_HP, INSATIABLE_HP_A8)
        m = cls(name="The Insatiable", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = _INSATIABLE_CYCLE[0]
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> InsatiableMove:
        self.cycle_index = (self.cycle_index + 1) % len(_INSATIABLE_CYCLE)
        return _INSATIABLE_CYCLE[self.cycle_index]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        from .powers import make_power

        if move is InsatiableMove.LIQUIFY:
            # Sim approximation of SandpitPower + 6 FranticEscape statuses.
            player.add_or_stack_power(make_power("weak", 3, player))
        elif move is InsatiableMove.THRASH1 or move is InsatiableMove.THRASH2:
            per_hit = _a9(self.ascension, 8, 9)
            for _ in range(2):
                blocked, hp_loss = deal_damage(per_hit, self, player)
                event["damage"] += per_hit
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is InsatiableMove.LUNGING_BITE:
            dmg = _a9(self.ascension, 28, 31)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is InsatiableMove.SALIVATE:
            strength = StrengthPower(amount=_a9(self.ascension, 2, 3))
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- Doormaker (Act 3 boss, solo) -----------------------------------------
# Cites: decompiled/MegaCrit.Sts2.Core.Models.Monsters/Doormaker.cs
# Simplified — the Hunger/Scrutiny/Grasp power swap visuals aren't
# modeled; the damage cycle is what matters for combat.


class DoormakerMove(str, Enum):
    DRAMATIC_OPEN = "dramatic_open"
    HUNGER = "hunger"
    SCRUTINY = "scrutiny"
    GRASP = "grasp"


# Doormaker.cs:53-63 — A8 HP 489→512, A9 Hunger 30→35, Scrutiny 24→26,
# Grasp 10→11 per hit, Grasp strength 3→4.
DOORMAKER_HP = 489
DOORMAKER_HP_A8 = 512

_DOORMAKER_CYCLE = (
    DoormakerMove.HUNGER, DoormakerMove.SCRUTINY, DoormakerMove.GRASP,
)


@dataclass
class Doormaker(Monster):
    last_move: DoormakerMove | None = None
    next_move: DoormakerMove | None = None
    cycle_index: int = 0
    opened: bool = False
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "Doormaker":
        hp = _a8(ascension, DOORMAKER_HP, DOORMAKER_HP_A8)
        m = cls(name="Doormaker", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = DoormakerMove.DRAMATIC_OPEN
        m.cycle_index = -1  # advances to 0 (HUNGER) after the open move
        return m

    def roll_next_move(self, rng: random.Random) -> DoormakerMove:
        if not self.opened:
            self.opened = True
            self.cycle_index = 0
            return _DOORMAKER_CYCLE[0]
        self.cycle_index = (self.cycle_index + 1) % len(_DOORMAKER_CYCLE)
        return _DOORMAKER_CYCLE[self.cycle_index]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}

        if move is DoormakerMove.DRAMATIC_OPEN:
            pass  # no damage, just the cinematic reveal
        elif move is DoormakerMove.HUNGER:
            dmg = _a9(self.ascension, 30, 35)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is DoormakerMove.SCRUTINY:
            dmg = _a9(self.ascension, 24, 26)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is DoormakerMove.GRASP:
            per_hit = _a9(self.ascension, 10, 11)
            for _ in range(2):
                blocked, hp_loss = deal_damage(per_hit, self, player)
                event["damage"] += per_hit
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
            strength = StrengthPower(amount=_a9(self.ascension, 3, 4))
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- Underdocks bosses (solo): WaterfallGiant, SoulFysh, LagavulinMatriarch
# Cites: decompiled/MegaCrit.Sts2.Core.Models.Monsters/*Boss source. All
# specialty powers (Pressurize, Intangible, Asleep+Plating) are simplified.


class WaterfallMove(str, Enum):
    PRESSURIZE = "pressurize"   # +15 block
    SLAM = "slam"                # 18 dmg
    GUSH = "gush"                # 8 dmg × 3


# WaterfallGiant.cs:67-79 — A8 HP 240→250. A9 affects Pressurize block
# 15→20 (decompiled bumps this under DeadlyEnemies despite being a block
# gain), Stomp 15→16, Ram 10→11, PressureUp 13→14, BasePressureGun 20→23.
# Sim uses Pressurize/Slam/Gush approximations; we apply A9 to Slam and
# Gush damage.
WATERFALL_HP = 240
WATERFALL_HP_A8 = 250


@dataclass
class WaterfallGiant(Monster):
    next_move: WaterfallMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "WaterfallGiant":
        hp = _a8(ascension, WATERFALL_HP, WATERFALL_HP_A8)
        m = cls(name="Waterfall Giant", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = WaterfallMove.PRESSURIZE
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> WaterfallMove:
        cycle = (WaterfallMove.PRESSURIZE, WaterfallMove.GUSH, WaterfallMove.SLAM)
        self.cycle_index = (self.cycle_index + 1) % len(cycle)
        return cycle[self.cycle_index]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is WaterfallMove.PRESSURIZE:
            self.block += _a9(self.ascension, 15, 20)
        elif move is WaterfallMove.SLAM:
            dmg = _a9(self.ascension, 18, 20)  # use Slam~PressureGun~Ram bucket
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is WaterfallMove.GUSH:
            per_hit = _a9(self.ascension, 8, 9)
            for _ in range(3):
                blocked, hp_loss = deal_damage(per_hit, self, player)
                event["damage"] += per_hit
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        self.next_move = self.roll_next_move(rng)
        return event


class SoulFyshMove(str, Enum):
    DE_GAS = "de_gas"     # 16 dmg
    SCREAM = "scream"     # 11 dmg
    GAZE = "gaze"         # 7 dmg + Weak +1


# SoulFysh.cs:42-50 — A8 HP 211→221, A9 DeGas 16→17, Scream 11→12,
# Gaze 7→8.
SOULFYSH_HP = 211
SOULFYSH_HP_A8 = 221


@dataclass
class SoulFysh(Monster):
    next_move: SoulFyshMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "SoulFysh":
        hp = _a8(ascension, SOULFYSH_HP, SOULFYSH_HP_A8)
        m = cls(name="Soul Fysh", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = SoulFyshMove.SCREAM
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> SoulFyshMove:
        cycle = (SoulFyshMove.SCREAM, SoulFyshMove.DE_GAS, SoulFyshMove.GAZE)
        self.cycle_index = (self.cycle_index + 1) % len(cycle)
        return cycle[self.cycle_index]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        from .powers import make_power
        if move is SoulFyshMove.DE_GAS:
            dmg = _a9(self.ascension, 16, 17)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is SoulFyshMove.SCREAM:
            dmg = _a9(self.ascension, 11, 12)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is SoulFyshMove.GAZE:
            dmg = _a9(self.ascension, 7, 8)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            player.add_or_stack_power(make_power("weak", 1, player))
        self.next_move = self.roll_next_move(rng)
        return event


class LagavulinMove(str, Enum):
    SLASH = "slash"        # 19 dmg (sim approximation; real has Asleep)
    DEBILITATE = "debilitate"  # apply Frail / Weak


# LagavulinMatriarch.cs:48-58 — A8 HP 222→233 and Slash2 block 12→14.
# A9 Slash 19→21, Slash2 12→14 dmg, Disembowel 9→10. Sim only models
# SLASH+DEBILITATE; we apply A9 to SLASH.
LAGAVULIN_HP = 222
LAGAVULIN_HP_A8 = 233


@dataclass
class LagavulinMatriarch(Monster):
    next_move: LagavulinMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "LagavulinMatriarch":
        hp = _a8(ascension, LAGAVULIN_HP, LAGAVULIN_HP_A8)
        m = cls(name="Lagavulin Matriarch", hp=hp, max_hp=hp, ascension=ascension)
        # Asleep + Plating simplified: just start with +8 Plating so the
        # opening turns "feel" similar (player needs sustained damage).
        from .powers import make_power
        m.add_or_stack_power(make_power("plating", 8, m))
        m.next_move = LagavulinMove.DEBILITATE
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> LagavulinMove:
        cycle = (LagavulinMove.DEBILITATE, LagavulinMove.SLASH, LagavulinMove.SLASH)
        self.cycle_index = (self.cycle_index + 1) % len(cycle)
        return cycle[self.cycle_index]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        from .powers import make_power
        if move is LagavulinMove.SLASH:
            dmg = _a9(self.ascension, 19, 21)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is LagavulinMove.DEBILITATE:
            player.add_or_stack_power(make_power("frail", 2, player))
            player.add_or_stack_power(make_power("weak", 2, player))
        self.next_move = self.roll_next_move(rng)
        return event


# --- VantomBoss (Act 1 boss, solo) ----------------------------------------
# Cites: decompiled/MegaCrit.Sts2.Core.Models.Monsters/Vantom.cs
# 4-state cycle. Wound-on-DISMEMBER is approximated by Weak (sim has no
# status-card system yet).


class VantomMove(str, Enum):
    INK_BLOT = "ink_blot"      # 7 dmg
    INKY_LANCE = "inky_lance"  # 6 dmg x2 hits
    DISMEMBER = "dismember"    # 27 dmg + Weak (approx for Wound add)
    PREPARE = "prepare"        # Strength +2


# Vantom.cs:56-64 — A8 HP 173→183, A9 InkBlot 7→8, InkyLance 6→7 per hit,
# Dismember 27→30.
VANTOM_HP = 173
VANTOM_HP_A8 = 183

_VANTOM_CYCLE = (
    VantomMove.INK_BLOT, VantomMove.INKY_LANCE,
    VantomMove.DISMEMBER, VantomMove.PREPARE,
)


@dataclass
class Vantom(Monster):
    last_move: VantomMove | None = None
    next_move: VantomMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "Vantom":
        hp = _a8(ascension, VANTOM_HP, VANTOM_HP_A8)
        m = cls(name="Vantom", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = _VANTOM_CYCLE[0]
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> VantomMove:
        self.cycle_index = (self.cycle_index + 1) % len(_VANTOM_CYCLE)
        return _VANTOM_CYCLE[self.cycle_index]

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}

        if move is VantomMove.INK_BLOT:
            dmg = _a9(self.ascension, 7, 8)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is VantomMove.INKY_LANCE:
            per_hit = _a9(self.ascension, 6, 7)
            for _ in range(2):
                blocked, hp_loss = deal_damage(per_hit, self, player)
                event["damage"] += per_hit
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is VantomMove.DISMEMBER:
            dmg = _a9(self.ascension, 27, 30)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            # 3 Wound -> approximate by Weak +1 (sim has no status cards yet).
            from .powers import make_power
            player.add_or_stack_power(make_power("weak", 1, player))
        elif move is VantomMove.PREPARE:
            strength = StrengthPower(amount=2)
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event
