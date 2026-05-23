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
