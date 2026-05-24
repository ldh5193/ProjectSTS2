"""Monsters porting from `decompiled/MegaCrit.Sts2.Core.Models.Monsters/*`.

Currently modeled:
  - SludgeSpinnerWeak — MVP, RandomBranch with CannotRepeat (notes/05).
  - NibbitWeak — solo Nibbit, deterministic BUTT -> SLICE -> HISS cycle
    (Nibbit.cs + NibbitsWeak.cs, IsAlone=true branch).

Both expose `spawn(rng) -> Self` and `take_turn(rng, player) -> dict` so
sim/combat.py can hold a `Monster` and call them polymorphically.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

from .creatures import Creature, Monster
from .damage import deal_damage
from .powers import StrengthPower, WeakPower, make_power


class SludgeMove(str, Enum):
    OIL_SPRAY = "oil_spray"  # 8 dmg + Weak 1
    SLAM = "slam"            # 11 dmg
    RAGE = "rage"            # 6 dmg + self Strength 3


SLUDGE_MOVES = (SludgeMove.OIL_SPRAY, SludgeMove.SLAM, SludgeMove.RAGE)

SLUDGE_HP_MIN = 37
SLUDGE_HP_MAX = 39  # inclusive


@dataclass
class SludgeSpinnerWeak(Monster):
    last_move: SludgeMove | None = None
    next_move: SludgeMove | None = None

    @classmethod
    def spawn(cls, rng: random.Random) -> "SludgeSpinnerWeak":
        hp = rng.randint(SLUDGE_HP_MIN, SLUDGE_HP_MAX)
        # First move is fixed to OIL_SPRAY per §B.3 ("initial state").
        m = cls(name="Sludge Spinner", hp=hp, max_hp=hp)
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
            blocked, hp_loss = deal_damage(8, self, player)
            event.update(damage=8, blocked=blocked, hp_loss=hp_loss)
            player.add_or_stack_power(make_power("weak", 1, player))
        elif move is SludgeMove.SLAM:
            blocked, hp_loss = deal_damage(11, self, player)
            event.update(damage=11, blocked=blocked, hp_loss=hp_loss)
        elif move is SludgeMove.RAGE:
            blocked, hp_loss = deal_damage(6, self, player)
            event.update(damage=6, blocked=blocked, hp_loss=hp_loss)
            # Grant +3 Strength to self.
            strength = StrengthPower(amount=3)
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- NibbitWeak (NIBBIT_0, IsAlone) -----------------------------------------
# Cites:
#   decompiled/MegaCrit.Sts2.Core.Models.Monsters/Nibbit.cs
#   decompiled/MegaCrit.Sts2.Core.Models.Encounters/NibbitsWeak.cs


class NibbitMove(str, Enum):
    BUTT = "butt"    # 12 dmg
    SLICE = "slice"  # 6 dmg + self block 5
    HISS = "hiss"    # self Strength +2


NIBBIT_HP_MIN = 42
NIBBIT_HP_MAX = 46  # inclusive (non-Ascension)

_NIBBIT_BUTT_DAMAGE = 12
_NIBBIT_SLICE_DAMAGE = 6
_NIBBIT_SLICE_BLOCK = 5
_NIBBIT_HISS_STRENGTH = 2

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

    @classmethod
    def spawn(cls, rng: random.Random) -> "NibbitWeak":
        hp = rng.randint(NIBBIT_HP_MIN, NIBBIT_HP_MAX)
        m = cls(name="Nibbit", hp=hp, max_hp=hp)
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
            blocked, hp_loss = deal_damage(_NIBBIT_BUTT_DAMAGE, self, player)
            event.update(damage=_NIBBIT_BUTT_DAMAGE, blocked=blocked, hp_loss=hp_loss)
        elif move is NibbitMove.SLICE:
            blocked, hp_loss = deal_damage(_NIBBIT_SLICE_DAMAGE, self, player)
            event.update(damage=_NIBBIT_SLICE_DAMAGE, blocked=blocked, hp_loss=hp_loss)
            self.block += _NIBBIT_SLICE_BLOCK
        elif move is NibbitMove.HISS:
            strength = StrengthPower(amount=_NIBBIT_HISS_STRENGTH)
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


BEAST_HP_MIN = 252
BEAST_HP_MAX = 252

_BEAST_CYCLE = (
    BeastMove.STAMP, BeastMove.PLOW, BeastMove.STUN,
    BeastMove.BEAST_CRY, BeastMove.STOMP, BeastMove.CRUSH,
)


@dataclass
class CeremonialBeast(Monster):
    last_move: BeastMove | None = None
    next_move: BeastMove | None = None
    cycle_index: int = 0

    @classmethod
    def spawn(cls, rng: random.Random) -> "CeremonialBeast":
        m = cls(name="Ceremonial Beast", hp=BEAST_HP_MIN, max_hp=BEAST_HP_MAX)
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
            blocked, hp_loss = deal_damage(18, self, player)
            event.update(damage=18, blocked=blocked, hp_loss=hp_loss)
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
            blocked, hp_loss = deal_damage(15, self, player)
            event.update(damage=15, blocked=blocked, hp_loss=hp_loss)
        elif move is BeastMove.CRUSH:
            blocked, hp_loss = deal_damage(17, self, player)
            event.update(damage=17, blocked=blocked, hp_loss=hp_loss)
            strength = StrengthPower(amount=3)
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


INSATIABLE_HP = 321

_INSATIABLE_CYCLE = (
    InsatiableMove.LIQUIFY, InsatiableMove.THRASH1, InsatiableMove.LUNGING_BITE,
    InsatiableMove.SALIVATE, InsatiableMove.THRASH2,
)


@dataclass
class TheInsatiable(Monster):
    last_move: InsatiableMove | None = None
    next_move: InsatiableMove | None = None
    cycle_index: int = 0

    @classmethod
    def spawn(cls, rng: random.Random) -> "TheInsatiable":
        m = cls(name="The Insatiable", hp=INSATIABLE_HP, max_hp=INSATIABLE_HP)
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
            for _ in range(2):
                blocked, hp_loss = deal_damage(8, self, player)
                event["damage"] += 8
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is InsatiableMove.LUNGING_BITE:
            blocked, hp_loss = deal_damage(28, self, player)
            event.update(damage=28, blocked=blocked, hp_loss=hp_loss)
        elif move is InsatiableMove.SALIVATE:
            strength = StrengthPower(amount=2)
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


DOORMAKER_HP = 489

_DOORMAKER_CYCLE = (
    DoormakerMove.HUNGER, DoormakerMove.SCRUTINY, DoormakerMove.GRASP,
)


@dataclass
class Doormaker(Monster):
    last_move: DoormakerMove | None = None
    next_move: DoormakerMove | None = None
    cycle_index: int = 0
    opened: bool = False

    @classmethod
    def spawn(cls, rng: random.Random) -> "Doormaker":
        m = cls(name="Doormaker", hp=DOORMAKER_HP, max_hp=DOORMAKER_HP)
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
            blocked, hp_loss = deal_damage(30, self, player)
            event.update(damage=30, blocked=blocked, hp_loss=hp_loss)
        elif move is DoormakerMove.SCRUTINY:
            blocked, hp_loss = deal_damage(24, self, player)
            event.update(damage=24, blocked=blocked, hp_loss=hp_loss)
        elif move is DoormakerMove.GRASP:
            for _ in range(2):
                blocked, hp_loss = deal_damage(10, self, player)
                event["damage"] += 10
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
            strength = StrengthPower(amount=3)
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
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


VANTOM_HP = 173

_VANTOM_CYCLE = (
    VantomMove.INK_BLOT, VantomMove.INKY_LANCE,
    VantomMove.DISMEMBER, VantomMove.PREPARE,
)


@dataclass
class Vantom(Monster):
    last_move: VantomMove | None = None
    next_move: VantomMove | None = None
    cycle_index: int = 0

    @classmethod
    def spawn(cls, rng: random.Random) -> "Vantom":
        m = cls(name="Vantom", hp=VANTOM_HP, max_hp=VANTOM_HP)
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
            blocked, hp_loss = deal_damage(7, self, player)
            event.update(damage=7, blocked=blocked, hp_loss=hp_loss)
        elif move is VantomMove.INKY_LANCE:
            for _ in range(2):
                blocked, hp_loss = deal_damage(6, self, player)
                event["damage"] += 6
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is VantomMove.DISMEMBER:
            blocked, hp_loss = deal_damage(27, self, player)
            event.update(damage=27, blocked=blocked, hp_loss=hp_loss)
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
