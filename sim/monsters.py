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
from .dsl import CardDef, CardType
from .powers import StrengthPower, WeakPower, make_power


def _a8(asc: int, base: int, ascended: int) -> int:
    """Return ascended value if ASC>=8 (ToughEnemies), else base."""
    return ascended if asc >= 8 else base


def _a9(asc: int, base: int, ascended: int) -> int:
    """Return ascended value if ASC>=9 (DeadlyEnemies), else base."""
    return ascended if asc >= 9 else base


# --- Status cards bosses/elites shuffle into the player deck ----------------
# These are *unplayable* status cards (cost == _STATUS_UNPLAYABLE, a sentinel
# distinct from the X_COST=-1 used by playable X-cost cards). They clog the
# hand/draw/discard like the real game's Wound/Burn/FranticEscape. They carry
# no effects and are skipped by the playable-card filter in run_engine
# (`c.cost >= 0`). is_status=True flags them for the obs/deck-profile code.
_STATUS_UNPLAYABLE = -99

WOUND_CARD = CardDef(
    id="wound", name="Wound", cost=_STATUS_UNPLAYABLE, type=CardType.SKILL,
    effects=(), count=0, is_status=True,
)
# Burn deals 2 unblockable damage at end of turn in the real game; here it is
# a deck-clogging status (the end-of-turn tick is left as a TODO — its main
# faithful effect is occupying a hand slot, which this models).
BURN_CARD = CardDef(
    id="burn", name="Burn", cost=_STATUS_UNPLAYABLE, type=CardType.SKILL,
    effects=(), count=0, is_status=True,
)
# FranticEscape (TheInsatiable): a status that shuffles itself; modeled as a
# plain deck-clogging unplayable status.
FRANTIC_ESCAPE_CARD = CardDef(
    id="frantic_escape", name="Frantic Escape", cost=_STATUS_UNPLAYABLE,
    type=CardType.SKILL, effects=(), count=0, is_status=True,
)


def _queue_status(monster: Monster, card: CardDef, pile: str, count: int) -> None:
    """Record `count` copies of a status card to be inserted into a player
    pile ("draw" | "discard" | "hand") at the end of the monster's turn.

    combat.CombatState.monster_turn drains `monster.pending_status_cards`
    after take_turn so the cards land in the live combat piles. In standalone
    monster unit tests (no CombatState) the list is simply inspected."""
    pending = getattr(monster, "pending_status_cards", None)
    if pending is None:
        pending = []
        monster.pending_status_cards = pending  # type: ignore[attr-defined]
    for _ in range(count):
        pending.append((card, pile))


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

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is SludgeMove.OIL_SPRAY:
            return _a9(self.ascension, 8, 9) + str_amt
        if self.next_move is SludgeMove.SLAM:
            return _a9(self.ascension, 11, 12) + str_amt
        if self.next_move is SludgeMove.RAGE:
            return _a9(self.ascension, 6, 7) + str_amt
        return 0

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

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is NibbitMove.BUTT:
            return _a9(self.ascension, 12, 13) + str_amt
        if self.next_move is NibbitMove.SLICE:
            return _a9(self.ascension, 6, 7) + str_amt
        # HISS is a pure self-buff (Strength gain), no damage.
        return 0

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
# 15→17, CrushDmg 17→19, CrushStrength 3→4, PlowAmount 150→160.
BEAST_HP = 252
BEAST_HP_A8 = 262
BEAST_PLOW_AMOUNT = 150
BEAST_PLOW_AMOUNT_A9 = 160

# State machine (CeremonialBeast.cs:127-152), start at STAMP:
#   STAMP -> PLOW
#   PLOW  -> PLOW   (self-loop: the "PLOW-spam" phase)
#   STUN  -> BEAST_CRY
#   BEAST_CRY -> STOMP -> CRUSH -> BEAST_CRY (loop)
# The PLOW spam is interrupted by PlowPower (CeremonialBeast.cs/PlowPower.cs):
# STAMP applies a Plow counter == PlowAmount (150/160). While PLOW-spamming,
# once the player has chipped the beast's HP down to <= PlowAmount, the beast
# is STUNNED (loses its accumulated Strength) and then enters the
# BEAST_CRY -> STOMP -> CRUSH loop. We reproduce that HP gate in
# roll_next_move (PlowPower.AfterDamageReceived: CurrentHp <= Amount).


@dataclass
class CeremonialBeast(Monster):
    last_move: BeastMove | None = None
    next_move: BeastMove | None = None
    cycle_index: int = 0
    ascension: int = 0
    plow_amount: int = 0      # Plow counter set by STAMP; HP gate for the stun
    plow_phase: bool = False  # True while PLOW-spamming (pre-stun)
    post_stun: bool = False   # True once BEAST_CRY/STOMP/CRUSH loop is entered

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "CeremonialBeast":
        hp = _a8(ascension, BEAST_HP, BEAST_HP_A8)
        m = cls(name="Ceremonial Beast", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = BeastMove.STAMP
        m.cycle_index = 0
        return m

    # BEAST_CRY -> STOMP -> CRUSH -> BEAST_CRY (the post-stun loop).
    _POST_STUN_FOLLOWUP = {
        BeastMove.BEAST_CRY: BeastMove.STOMP,
        BeastMove.STOMP: BeastMove.CRUSH,
        BeastMove.CRUSH: BeastMove.BEAST_CRY,
    }

    def roll_next_move(self, rng: random.Random) -> BeastMove:
        last = self.last_move
        if last is BeastMove.STAMP:
            self.plow_phase = True
            return BeastMove.PLOW
        if last is BeastMove.PLOW:
            # PLOW self-loops until the player breaks the Plow counter, i.e.
            # the beast's HP has dropped to <= the Plow amount (PlowPower.cs:29).
            if self.alive and self.hp <= self.plow_amount:
                self.plow_phase = False
                return BeastMove.STUN
            return BeastMove.PLOW
        if last is BeastMove.STUN:
            self.post_stun = True
            return BeastMove.BEAST_CRY
        # Post-stun loop.
        return self._POST_STUN_FOLLOWUP.get(last, BeastMove.BEAST_CRY)

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is BeastMove.PLOW:
            return _a9(self.ascension, 18, 20) + str_amt
        if self.next_move is BeastMove.STOMP:
            return _a9(self.ascension, 15, 17) + str_amt
        if self.next_move is BeastMove.CRUSH:
            return _a9(self.ascension, 17, 19) + str_amt
        # STAMP (buff), STUN (no-op), BEAST_CRY (debuff) deal no damage.
        return 0

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
            # Apply the Plow counter (CeremonialBeast.cs:159). This is the HP
            # threshold at/below which the PLOW spam ends and the beast stuns.
            self.plow_amount = _a9(self.ascension, BEAST_PLOW_AMOUNT,
                                   BEAST_PLOW_AMOUNT_A9)
        elif move is BeastMove.STUN:
            # PlowPower.cs:33 removes the beast's accumulated Strength on stun.
            st = self.get_power("strength")
            if st is not None:
                self.powers.remove(st)
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

# State machine (TheInsatiable.cs:89-108): start at LIQUIFY, then
#   LIQUIFY -> THRASH1 -> BITE -> SALIVATE -> THRASH2 -> THRASH1 (loop).
# LIQUIFY is performed ONCE at the start and never re-entered — the loop body
# is THRASH1 -> BITE -> SALIVATE -> THRASH2 -> THRASH1. (The old sim wrongly
# re-cast LIQUIFY every 5 turns.)
_INSATIABLE_FOLLOWUP = {
    InsatiableMove.LIQUIFY: InsatiableMove.THRASH1,
    InsatiableMove.THRASH1: InsatiableMove.LUNGING_BITE,
    InsatiableMove.LUNGING_BITE: InsatiableMove.SALIVATE,
    InsatiableMove.SALIVATE: InsatiableMove.THRASH2,
    InsatiableMove.THRASH2: InsatiableMove.THRASH1,
}


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
        m.next_move = InsatiableMove.LIQUIFY
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> InsatiableMove:
        if self.last_move is None:
            return InsatiableMove.LIQUIFY
        return _INSATIABLE_FOLLOWUP[self.last_move]

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is InsatiableMove.THRASH1 or self.next_move is InsatiableMove.THRASH2:
            # 2 hits; Strength applies per hit.
            return (_a9(self.ascension, 8, 9) + str_amt) * 2
        if self.next_move is InsatiableMove.LUNGING_BITE:
            return _a9(self.ascension, 28, 31) + str_amt
        # LIQUIFY (debuff) and SALIVATE (self-buff) deal no damage.
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        from .powers import make_power

        if move is InsatiableMove.LIQUIFY:
            # SandpitPower (TheInsatiable.cs:117-122) approximated as Weak, plus
            # 6 FranticEscape status cards: 3 to Draw, 3 to Discard (lines
            # 123-139). The status cards are drained into the player's piles by
            # combat.monster_turn after this take_turn returns.
            player.add_or_stack_power(make_power("weak", 3, player))
            _queue_status(self, FRANTIC_ESCAPE_CARD, "draw", 3)
            _queue_status(self, FRANTIC_ESCAPE_CARD, "discard", 3)
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

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is DoormakerMove.HUNGER:
            return _a9(self.ascension, 30, 35) + str_amt
        if self.next_move is DoormakerMove.SCRUTINY:
            return _a9(self.ascension, 24, 26) + str_amt
        if self.next_move is DoormakerMove.GRASP:
            # 2 hits; Strength applies per hit.
            return (_a9(self.ascension, 10, 11) + str_amt) * 2
        # DRAMATIC_OPEN is a no-damage cinematic reveal.
        return 0

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

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is WaterfallMove.SLAM:
            return _a9(self.ascension, 18, 20) + str_amt
        if self.next_move is WaterfallMove.GUSH:
            # 3 hits; Strength applies per hit.
            return (_a9(self.ascension, 8, 9) + str_amt) * 3
        # PRESSURIZE is a block gain, no damage.
        return 0

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

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is SoulFyshMove.DE_GAS:
            return _a9(self.ascension, 16, 17) + str_amt
        if self.next_move is SoulFyshMove.SCREAM:
            return _a9(self.ascension, 11, 12) + str_amt
        if self.next_move is SoulFyshMove.GAZE:
            return _a9(self.ascension, 7, 8) + str_amt
        return 0

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

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is LagavulinMove.SLASH:
            return _a9(self.ascension, 19, 21) + str_amt
        # DEBILITATE applies Frail/Weak, no damage.
        return 0

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

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is VantomMove.INK_BLOT:
            return _a9(self.ascension, 7, 8) + str_amt
        if self.next_move is VantomMove.INKY_LANCE:
            # 2 hits; Strength applies per hit.
            return (_a9(self.ascension, 6, 7) + str_amt) * 2
        if self.next_move is VantomMove.DISMEMBER:
            return _a9(self.ascension, 27, 30) + str_amt
        # PREPARE is a self-buff (Strength gain), no damage.
        return 0

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
            # DISMEMBER shuffles 3 Wound status cards into the player's draw
            # pile (Vantom.cs). Drained by combat.monster_turn.
            _queue_status(self, WOUND_CARD, "draw", 3)
        elif move is VantomMove.PREPARE:
            strength = StrengthPower(amount=2)
            strength._owner = self
            self.add_or_stack_power(strength)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# ===========================================================================
# ACT 2 (Hive) ELITES
# ===========================================================================

# --- Entomancer (Hive elite, solo) -----------------------------------------
# Cites: decompiled/.../Monsters/Entomancer.cs + Encounters/EntomancerElite.cs
# HP 145 (A8 155). Start at BEES, loop BEES -> SPEAR -> SPIT -> BEES.
#   BEES   = 3 dmg x7 (A9 x8)        (MultiAttackIntent(BeesDamage, BeesRepeat))
#   SPEAR  = 18 dmg (A9 20)
#   SPIT   = self-buff: Strength +1/+2 (PersonalHive scaling simplified).
# PersonalHivePower is a cosmetic spawn buff; we model only its Strength gain.


class EntomancerMove(str, Enum):
    BEES = "bees"
    SPEAR = "spear"
    SPIT = "spit"


ENTOMANCER_HP = 145
ENTOMANCER_HP_A8 = 155

_ENTOMANCER_FOLLOWUP = {
    EntomancerMove.BEES: EntomancerMove.SPEAR,
    EntomancerMove.SPEAR: EntomancerMove.SPIT,
    EntomancerMove.SPIT: EntomancerMove.BEES,
}


@dataclass
class Entomancer(Monster):
    last_move: EntomancerMove | None = None
    next_move: EntomancerMove | None = None
    ascension: int = 0
    spit_count: int = 0  # PersonalHive grows to 3 then gives +2 Str instead

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "Entomancer":
        hp = _a8(ascension, ENTOMANCER_HP, ENTOMANCER_HP_A8)
        m = cls(name="Entomancer", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = EntomancerMove.BEES  # MoveStateMachine start = BEES_MOVE
        return m

    def roll_next_move(self, rng: random.Random) -> EntomancerMove:
        if self.last_move is None:
            return EntomancerMove.BEES
        return _ENTOMANCER_FOLLOWUP[self.last_move]

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is EntomancerMove.BEES:
            per = _a9(self.ascension, 3, 3) + str_amt
            return per * _a9(self.ascension, 7, 8)
        if self.next_move is EntomancerMove.SPEAR:
            return _a9(self.ascension, 18, 20) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is EntomancerMove.BEES:
            per = _a9(self.ascension, 3, 3)
            for _ in range(_a9(self.ascension, 7, 8)):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is EntomancerMove.SPEAR:
            dmg = _a9(self.ascension, 18, 20)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is EntomancerMove.SPIT:
            # PheromoneSpit (Entomancer.cs:54-68): while PersonalHive < 3 grow
            # it and gain +1 Str; once it caps, gain +2 Str instead.
            gain = 1 if self.spit_count < 2 else 2
            self.spit_count += 1
            strength = StrengthPower(amount=gain)
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- InfestedPrism (Hive elite, solo) --------------------------------------
# Cites: Monsters/InfestedPrism.cs + Encounters/InfestedPrismsElite.cs
# HP 200 (A8 215). Fixed 4-move loop JAB -> RADIATE -> WHIRLWIND -> PULSATE.
#   JAB       = 22 dmg (A9 24)
#   RADIATE   = 16 dmg (A9 18) + 16 block (A9 18)
#   WHIRLWIND = 9 dmg x3 (A9 10)
#   PULSATE   = 20 block (A8 22) + Strength +4 (A9 +5)
# VitalSparkPower (spawn buff) is cosmetic; not modeled.


class PrismMove(str, Enum):
    JAB = "jab"
    RADIATE = "radiate"
    WHIRLWIND = "whirlwind"
    PULSATE = "pulsate"


PRISM_HP = 200
PRISM_HP_A8 = 215

_PRISM_CYCLE = (PrismMove.JAB, PrismMove.RADIATE, PrismMove.WHIRLWIND,
                PrismMove.PULSATE)


@dataclass
class InfestedPrism(Monster):
    last_move: PrismMove | None = None
    next_move: PrismMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "InfestedPrism":
        hp = _a8(ascension, PRISM_HP, PRISM_HP_A8)
        m = cls(name="Infested Prism", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = _PRISM_CYCLE[0]
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> PrismMove:
        self.cycle_index = (self.cycle_index + 1) % len(_PRISM_CYCLE)
        return _PRISM_CYCLE[self.cycle_index]

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is PrismMove.JAB:
            return _a9(self.ascension, 22, 24) + str_amt
        if self.next_move is PrismMove.RADIATE:
            return _a9(self.ascension, 16, 18) + str_amt
        if self.next_move is PrismMove.WHIRLWIND:
            return (_a9(self.ascension, 9, 10) + str_amt) * 3
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is PrismMove.JAB:
            dmg = _a9(self.ascension, 22, 24)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is PrismMove.RADIATE:
            dmg = _a9(self.ascension, 16, 18)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            self.block += _a9(self.ascension, 16, 18)
        elif move is PrismMove.WHIRLWIND:
            per = _a9(self.ascension, 9, 10)
            for _ in range(3):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is PrismMove.PULSATE:
            self.block += _a8(self.ascension, 20, 22)
            strength = StrengthPower(amount=_a9(self.ascension, 4, 5))
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# ===========================================================================
# ACT 3 (Glory) ELITES
# ===========================================================================

# --- MechaKnight (Glory elite, solo) ---------------------------------------
# Cites: Monsters/MechaKnight.cs + Encounters/MechaKnightElite.cs
# HP 300 (A8 320). Start at CHARGE, then
#   CHARGE -> FLAMETHROWER -> WINDUP -> HEAVY_CLEAVE -> FLAMETHROWER (loop).
#   CHARGE       = 25 dmg (A9 30)
#   FLAMETHROWER = 4 Burn status cards to hand (StatusIntent(4))
#   WINDUP       = +15 block, +5 Strength
#   HEAVY_CLEAVE = 35 dmg (A9 40)
# Spawns with Artifact 3 (cosmetic debuff shield; not modeled).


class MechaKnightMove(str, Enum):
    CHARGE = "charge"
    FLAMETHROWER = "flamethrower"
    WINDUP = "windup"
    HEAVY_CLEAVE = "heavy_cleave"


MECHAKNIGHT_HP = 300
MECHAKNIGHT_HP_A8 = 320

_MECHAKNIGHT_FOLLOWUP = {
    MechaKnightMove.CHARGE: MechaKnightMove.FLAMETHROWER,
    MechaKnightMove.FLAMETHROWER: MechaKnightMove.WINDUP,
    MechaKnightMove.WINDUP: MechaKnightMove.HEAVY_CLEAVE,
    MechaKnightMove.HEAVY_CLEAVE: MechaKnightMove.FLAMETHROWER,
}


@dataclass
class MechaKnight(Monster):
    last_move: MechaKnightMove | None = None
    next_move: MechaKnightMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "MechaKnight":
        hp = _a8(ascension, MECHAKNIGHT_HP, MECHAKNIGHT_HP_A8)
        m = cls(name="Mecha Knight", hp=hp, max_hp=hp, ascension=ascension)
        # MechaKnight.cs:72-76 spawns with Artifact 3 (blocks 3 debuffs). The
        # sim has no Artifact power and rarely debuffs monsters, so it is a
        # cosmetic no-op here; left as a documented TODO.
        m.next_move = MechaKnightMove.CHARGE
        return m

    def roll_next_move(self, rng: random.Random) -> MechaKnightMove:
        if self.last_move is None:
            return MechaKnightMove.CHARGE
        return _MECHAKNIGHT_FOLLOWUP[self.last_move]

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is MechaKnightMove.CHARGE:
            return _a9(self.ascension, 25, 30) + str_amt
        if self.next_move is MechaKnightMove.HEAVY_CLEAVE:
            return _a9(self.ascension, 35, 40) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is MechaKnightMove.CHARGE:
            dmg = _a9(self.ascension, 25, 30)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is MechaKnightMove.HEAVY_CLEAVE:
            dmg = _a9(self.ascension, 35, 40)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is MechaKnightMove.WINDUP:
            self.block += 15
            strength = StrengthPower(amount=5)
            strength._owner = self
            self.add_or_stack_power(strength)
        elif move is MechaKnightMove.FLAMETHROWER:
            # 4 Burn status cards to the player's HAND (MechaKnight.cs:131-136).
            _queue_status(self, BURN_CARD, "hand", 4)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- SoulNexus (Glory elite, solo) -----------------------------------------
# Cites: Monsters/SoulNexus.cs + Encounters/SoulNexusElite.cs
# HP 234 (A8 254). RandomBranch with CannotRepeat across all three moves
# (SoulNexus.cs:60-74), opening with SOUL_BURN.
#   SOUL_BURN  = 29 dmg (A9 31)
#   MAELSTROM  = 6 dmg x4 (A9 7)
#   DRAIN_LIFE = 18 dmg (A9 19) + Vulnerable 2 + Weak 2 (strong DebuffIntent)


class SoulNexusMove(str, Enum):
    SOUL_BURN = "soul_burn"
    MAELSTROM = "maelstrom"
    DRAIN_LIFE = "drain_life"


SOULNEXUS_HP = 234
SOULNEXUS_HP_A8 = 254
_SOULNEXUS_MOVES = (SoulNexusMove.SOUL_BURN, SoulNexusMove.MAELSTROM,
                    SoulNexusMove.DRAIN_LIFE)


@dataclass
class SoulNexus(Monster):
    last_move: SoulNexusMove | None = None
    next_move: SoulNexusMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "SoulNexus":
        hp = _a8(ascension, SOULNEXUS_HP, SOULNEXUS_HP_A8)
        m = cls(name="Soul Nexus", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = SoulNexusMove.SOUL_BURN  # state-machine start move
        return m

    def roll_next_move(self, rng: random.Random) -> SoulNexusMove:
        # RandomBranchState with CannotRepeat (SoulNexus.cs:66-69).
        candidates = [mv for mv in _SOULNEXUS_MOVES if mv != self.last_move]
        return rng.choice(candidates)

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is SoulNexusMove.SOUL_BURN:
            return _a9(self.ascension, 29, 31) + str_amt
        if self.next_move is SoulNexusMove.MAELSTROM:
            return (_a9(self.ascension, 6, 7) + str_amt) * 4
        if self.next_move is SoulNexusMove.DRAIN_LIFE:
            return _a9(self.ascension, 18, 19) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is SoulNexusMove.SOUL_BURN:
            dmg = _a9(self.ascension, 29, 31)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is SoulNexusMove.MAELSTROM:
            per = _a9(self.ascension, 6, 7)
            for _ in range(4):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is SoulNexusMove.DRAIN_LIFE:
            dmg = _a9(self.ascension, 18, 19)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            player.add_or_stack_power(make_power("vulnerable", 2, player))
            player.add_or_stack_power(make_power("weak", 2, player))
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# ===========================================================================
# ACT 2/3 NORMAL encounters (most common, solo-modeled)
# ===========================================================================

# --- SpinyToad (Hive normal, solo) -----------------------------------------
# Cites: Monsters/SpinyToad.cs. HP 116-121 (A8 121-124). Fixed loop:
#   SPIKES -> EXPLOSION -> LASH -> SPIKES.
#   SPIKES    = self Thorns 5 (BuffIntent)
#   EXPLOSION = 23 dmg (A9 25), removes the Thorns
#   LASH      = 17 dmg (A9 19)


class SpinyToadMove(str, Enum):
    SPIKES = "spikes"
    EXPLOSION = "explosion"
    LASH = "lash"


SPINYTOAD_HP_MIN, SPINYTOAD_HP_MAX = 116, 121
SPINYTOAD_HP_MIN_A8, SPINYTOAD_HP_MAX_A8 = 121, 124
_SPINYTOAD_CYCLE = (SpinyToadMove.SPIKES, SpinyToadMove.EXPLOSION,
                    SpinyToadMove.LASH)


@dataclass
class SpinyToad(Monster):
    last_move: SpinyToadMove | None = None
    next_move: SpinyToadMove | None = None
    cycle_index: int = 0
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "SpinyToad":
        lo = _a8(ascension, SPINYTOAD_HP_MIN, SPINYTOAD_HP_MIN_A8)
        hi = _a8(ascension, SPINYTOAD_HP_MAX, SPINYTOAD_HP_MAX_A8)
        hp = rng.randint(lo, hi)
        m = cls(name="Spiny Toad", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = _SPINYTOAD_CYCLE[0]
        m.cycle_index = 0
        return m

    def roll_next_move(self, rng: random.Random) -> SpinyToadMove:
        self.cycle_index = (self.cycle_index + 1) % len(_SPINYTOAD_CYCLE)
        return _SPINYTOAD_CYCLE[self.cycle_index]

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is SpinyToadMove.EXPLOSION:
            return _a9(self.ascension, 23, 25) + str_amt
        if self.next_move is SpinyToadMove.LASH:
            return _a9(self.ascension, 17, 19) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is SpinyToadMove.SPIKES:
            self.add_or_stack_power(make_power("thorns", 5, self))
        elif move is SpinyToadMove.EXPLOSION:
            dmg = _a9(self.ascension, 23, 25)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            thorns = self.get_power("thorns")
            if thorns is not None:
                self.powers.remove(thorns)
        elif move is SpinyToadMove.LASH:
            dmg = _a9(self.ascension, 17, 19)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- GlobeHead (Glory normal, solo) ----------------------------------------
# Cites: Monsters/GlobeHead.cs. HP 148 (A8 158). Loop:
#   THUNDER_STRIKE -> GALVANIC_BURST -> SHOCKING_SLAP -> THUNDER_STRIKE.
#   THUNDER_STRIKE = 6 dmg x3 (A9 7)
#   SHOCKING_SLAP  = 13 dmg (A9 14) + Weak (DebuffIntent)
#   GALVANIC_BURST = 16 dmg (A9 17) + Strength (BuffIntent)


class GlobeHeadMove(str, Enum):
    THUNDER_STRIKE = "thunder_strike"
    SHOCKING_SLAP = "shocking_slap"
    GALVANIC_BURST = "galvanic_burst"


GLOBEHEAD_HP = 148
GLOBEHEAD_HP_A8 = 158
_GLOBEHEAD_FOLLOWUP = {
    GlobeHeadMove.THUNDER_STRIKE: GlobeHeadMove.GALVANIC_BURST,
    GlobeHeadMove.GALVANIC_BURST: GlobeHeadMove.SHOCKING_SLAP,
    GlobeHeadMove.SHOCKING_SLAP: GlobeHeadMove.THUNDER_STRIKE,
}


@dataclass
class GlobeHead(Monster):
    last_move: GlobeHeadMove | None = None
    next_move: GlobeHeadMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "GlobeHead":
        hp = _a8(ascension, GLOBEHEAD_HP, GLOBEHEAD_HP_A8)
        m = cls(name="Globe Head", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = GlobeHeadMove.THUNDER_STRIKE
        return m

    def roll_next_move(self, rng: random.Random) -> GlobeHeadMove:
        if self.last_move is None:
            return GlobeHeadMove.THUNDER_STRIKE
        return _GLOBEHEAD_FOLLOWUP[self.last_move]

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is GlobeHeadMove.THUNDER_STRIKE:
            return (_a9(self.ascension, 6, 7) + str_amt) * 3
        if self.next_move is GlobeHeadMove.SHOCKING_SLAP:
            return _a9(self.ascension, 13, 14) + str_amt
        if self.next_move is GlobeHeadMove.GALVANIC_BURST:
            return _a9(self.ascension, 16, 17) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is GlobeHeadMove.THUNDER_STRIKE:
            per = _a9(self.ascension, 6, 7)
            for _ in range(3):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is GlobeHeadMove.SHOCKING_SLAP:
            dmg = _a9(self.ascension, 13, 14)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            player.add_or_stack_power(make_power("weak", 1, player))
        elif move is GlobeHeadMove.GALVANIC_BURST:
            dmg = _a9(self.ascension, 16, 17)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            strength = StrengthPower(amount=1)
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- FrogKnight (Glory normal, solo) ---------------------------------------
# Cites: Monsters/FrogKnight.cs. HP 191 (A8 199). Spawns with Plating 15/19.
# Start at TONGUE_LASH, then state machine:
#   TONGUE_LASH -> STRIKE_DOWN -> FOR_THE_QUEEN -> [HALF_HEALTH branch]
#   HALF_HEALTH branch: if HP < maxHP/2 and not yet charged -> BEETLE_CHARGE,
#                       else TONGUE_LASH.
#   BEETLE_CHARGE -> TONGUE_LASH path resumes (FollowUp = TONGUE_LASH).
#   TONGUE_LASH    = 13 dmg (A9 14) + Frail 2
#   STRIKE_DOWN    = 21 dmg (A9 23)
#   FOR_THE_QUEEN  = +5 Strength
#   BEETLE_CHARGE  = 35 dmg (A9 40), once per fight, when below half HP


class FrogKnightMove(str, Enum):
    TONGUE_LASH = "tongue_lash"
    STRIKE_DOWN = "strike_down"
    FOR_THE_QUEEN = "for_the_queen"
    BEETLE_CHARGE = "beetle_charge"


FROGKNIGHT_HP = 191
FROGKNIGHT_HP_A8 = 199
FROGKNIGHT_PLATING = 15
FROGKNIGHT_PLATING_A8 = 19


@dataclass
class FrogKnight(Monster):
    last_move: FrogKnightMove | None = None
    next_move: FrogKnightMove | None = None
    ascension: int = 0
    has_beetle_charged: bool = False

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "FrogKnight":
        hp = _a8(ascension, FROGKNIGHT_HP, FROGKNIGHT_HP_A8)
        m = cls(name="Frog Knight", hp=hp, max_hp=hp, ascension=ascension)
        m.add_or_stack_power(make_power(
            "plating", _a8(ascension, FROGKNIGHT_PLATING, FROGKNIGHT_PLATING_A8), m))
        m.next_move = FrogKnightMove.TONGUE_LASH  # start move
        return m

    def _half_health_choice(self) -> FrogKnightMove:
        # ConditionalBranchState (FrogKnight.cs:73-75).
        if not self.has_beetle_charged and self.hp < self.max_hp // 2:
            return FrogKnightMove.BEETLE_CHARGE
        return FrogKnightMove.TONGUE_LASH

    def roll_next_move(self, rng: random.Random) -> FrogKnightMove:
        last = self.last_move
        if last is None or last is FrogKnightMove.BEETLE_CHARGE:
            return FrogKnightMove.TONGUE_LASH
        if last is FrogKnightMove.TONGUE_LASH:
            return FrogKnightMove.STRIKE_DOWN
        if last is FrogKnightMove.STRIKE_DOWN:
            return FrogKnightMove.FOR_THE_QUEEN
        # After FOR_THE_QUEEN: the half-health branch.
        return self._half_health_choice()

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is FrogKnightMove.TONGUE_LASH:
            return _a9(self.ascension, 13, 14) + str_amt
        if self.next_move is FrogKnightMove.STRIKE_DOWN:
            return _a9(self.ascension, 21, 23) + str_amt
        if self.next_move is FrogKnightMove.BEETLE_CHARGE:
            return _a9(self.ascension, 35, 40) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is FrogKnightMove.TONGUE_LASH:
            dmg = _a9(self.ascension, 13, 14)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            player.add_or_stack_power(make_power("frail", 2, player))
        elif move is FrogKnightMove.STRIKE_DOWN:
            dmg = _a9(self.ascension, 21, 23)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is FrogKnightMove.FOR_THE_QUEEN:
            strength = StrengthPower(amount=5)
            strength._owner = self
            self.add_or_stack_power(strength)
        elif move is FrogKnightMove.BEETLE_CHARGE:
            self.has_beetle_charged = True
            dmg = _a9(self.ascension, 35, 40)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# ===========================================================================
# ACT 3 (Glory) BOSSES — the A10 second-boss pool besides Doormaker
# ===========================================================================

# --- TestSubject (Glory boss, solo) ----------------------------------------
# Cites: Monsters/TestSubject.cs + Encounters/TestSubjectBoss.cs (solo).
# Three forms via respawn: 100/200/300 HP (A8 111/212/313). Spawns with
# Adaptable + Enrage 2 (A9 3). Phase 1 loops BITE <-> SKULL_BASH; on death it
# Respawns to form 2 (then MULTI_CLAW spam, growing by 1 hit each time); a
# second death respawns to form 3 (LACERATE -> BIG_POUNCE -> BURNING_GROWL
# loop). After the third form dies it is truly dead (ShouldDisappearFromDoom).
#
# Sim modeling of the multi-form respawn: we expose a single combined HP bar
# equal to the sum of the three forms' HP and a 3-phase move machine that
# advances by phase as cumulative HP thresholds are crossed. This keeps the
# fight a single combat (the sim has no monster-revive primitive) while
# preserving the faithful total HP and the per-phase movesets/damage.


class TestSubjectMove(str, Enum):
    BITE = "bite"
    SKULL_BASH = "skull_bash"
    MULTI_CLAW = "multi_claw"
    LACERATE = "lacerate"
    BIG_POUNCE = "big_pounce"
    BURNING_GROWL = "burning_growl"


@dataclass
class TestSubject(Monster):
    # Tell pytest this is not a test class (name starts with "Test").
    __test__ = False
    last_move: TestSubjectMove | None = None
    next_move: TestSubjectMove | None = None
    ascension: int = 0
    form1_hp: int = 0
    form2_hp: int = 0
    multi_claw_count: int = 3  # grows by 1 each MULTI_CLAW (TestSubject.cs:300)

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "TestSubject":
        f1 = _a8(ascension, 100, 111)
        f2 = _a8(ascension, 200, 212)
        f3 = _a8(ascension, 300, 313)
        total = f1 + f2 + f3
        m = cls(name="Test Subject", hp=total, max_hp=total, ascension=ascension)
        m.form1_hp = f1
        m.form2_hp = f2
        # Enrage (gain Strength when hit by an attack) — not modeled as a live
        # trigger in the sim; the per-phase damage already pressures the agent.
        m.next_move = TestSubjectMove.BITE  # machine start = BITE_MOVE
        return m

    def _phase(self) -> int:
        """1 = first form (HP above form2+form3 band), 2 = second, 3 = third.
        Boundaries follow the cumulative form HP from the top of the bar."""
        f3_top = self.max_hp - self.form1_hp - self.form2_hp  # form3 size
        if self.hp > self.form2_hp + f3_top:
            return 1
        if self.hp > f3_top:
            return 2
        return 3

    def roll_next_move(self, rng: random.Random) -> TestSubjectMove:
        phase = self._phase()
        if phase == 1:
            # BITE <-> SKULL_BASH (TestSubject.cs:197-198).
            if self.last_move is TestSubjectMove.BITE:
                return TestSubjectMove.SKULL_BASH
            return TestSubjectMove.BITE
        if phase == 2:
            # MULTI_CLAW self-loops (TestSubject.cs:199).
            return TestSubjectMove.MULTI_CLAW
        # Phase 3: LACERATE -> BIG_POUNCE -> BURNING_GROWL -> LACERATE.
        if self.last_move is TestSubjectMove.LACERATE:
            return TestSubjectMove.BIG_POUNCE
        if self.last_move is TestSubjectMove.BIG_POUNCE:
            return TestSubjectMove.BURNING_GROWL
        return TestSubjectMove.LACERATE

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        mv = self.next_move
        if mv is TestSubjectMove.BITE:
            return _a9(self.ascension, 20, 22) + str_amt
        if mv is TestSubjectMove.SKULL_BASH:
            return _a9(self.ascension, 14, 16) + str_amt
        if mv is TestSubjectMove.MULTI_CLAW:
            return (_a9(self.ascension, 10, 11) + str_amt) * self.multi_claw_count
        if mv is TestSubjectMove.LACERATE:
            return (_a9(self.ascension, 10, 11) + str_amt) * 3
        if mv is TestSubjectMove.BIG_POUNCE:
            return 45 + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is TestSubjectMove.BITE:
            dmg = _a9(self.ascension, 20, 22)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is TestSubjectMove.SKULL_BASH:
            dmg = _a9(self.ascension, 14, 16)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            player.add_or_stack_power(make_power("vulnerable", 1, player))
        elif move is TestSubjectMove.MULTI_CLAW:
            per = _a9(self.ascension, 10, 11)
            for _ in range(self.multi_claw_count):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
            self.multi_claw_count += 1  # grows each cast (TestSubject.cs:300)
        elif move is TestSubjectMove.LACERATE:
            per = _a9(self.ascension, 10, 11)
            for _ in range(3):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is TestSubjectMove.BIG_POUNCE:
            dmg = 45
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is TestSubjectMove.BURNING_GROWL:
            # Burn statuses to discard + Strength (TestSubject.cs:320-327).
            _queue_status(self, BURN_CARD, "discard",
                          _a9(self.ascension, 3, 5))
            strength = StrengthPower(amount=_a9(self.ascension, 2, 3))
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- Queen (Glory boss, solo-modeled) --------------------------------------
# Cites: Monsters/Queen.cs + Encounters/QueenBoss.cs. In the real game the
# Queen fights alongside a TorchHeadAmalgam companion and branches on whether
# the Amalgam is dead. HP 400 (A8 419). The sim models the Queen solo (no
# companion primitive); we fold the Amalgam's presence into a fixed early
# cadence and then run her post-amalgam OFF_WITH_YOUR_HEAD loop, which is the
# damage-relevant phase.
#   PUPPET_STRINGS    = ChainsOfBinding (debuff; approximated as Weak 2)
#   YOURE_MINE        = Frail+Weak+Vulnerable (strong debuff; lasting)
#   OFF_WITH_HEAD     = 3 dmg x5 (A9 4)
#   EXECUTION         = 15 dmg (A9 18)
#   ENRAGE            = +2 Strength


class QueenMove(str, Enum):
    PUPPET_STRINGS = "puppet_strings"
    YOURE_MINE = "youre_mine"
    OFF_WITH_HEAD = "off_with_head"
    EXECUTION = "execution"
    ENRAGE = "enrage"


QUEEN_HP = 400
QUEEN_HP_A8 = 419


@dataclass
class Queen(Monster):
    last_move: QueenMove | None = None
    next_move: QueenMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "Queen":
        hp = _a8(ascension, QUEEN_HP, QUEEN_HP_A8)
        m = cls(name="Queen", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = QueenMove.PUPPET_STRINGS  # machine start
        return m

    def roll_next_move(self, rng: random.Random) -> QueenMove:
        # Opening: PUPPET_STRINGS -> YOURE_MINE, then (Amalgam treated as gone
        # in the solo model) the OFF_WITH_HEAD -> EXECUTION -> ENRAGE loop
        # (Queen.cs:142-144).
        last = self.last_move
        if last is None:
            return QueenMove.PUPPET_STRINGS
        if last is QueenMove.PUPPET_STRINGS:
            return QueenMove.YOURE_MINE
        if last is QueenMove.YOURE_MINE or last is QueenMove.ENRAGE:
            return QueenMove.OFF_WITH_HEAD
        if last is QueenMove.OFF_WITH_HEAD:
            return QueenMove.EXECUTION
        if last is QueenMove.EXECUTION:
            return QueenMove.ENRAGE
        return QueenMove.OFF_WITH_HEAD

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is QueenMove.OFF_WITH_HEAD:
            return (_a9(self.ascension, 3, 4) + str_amt) * 5
        if self.next_move is QueenMove.EXECUTION:
            return _a9(self.ascension, 15, 18) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is QueenMove.PUPPET_STRINGS:
            # ChainsOfBinding (Queen.cs:156-161) approximated as Weak.
            player.add_or_stack_power(make_power("weak", 2, player))
        elif move is QueenMove.YOURE_MINE:
            # Frail + Weak + Vulnerable (Queen.cs:163-172). Long-lasting in the
            # real game (99); here applied as a sizable debuff stack.
            player.add_or_stack_power(make_power("frail", 3, player))
            player.add_or_stack_power(make_power("weak", 3, player))
            player.add_or_stack_power(make_power("vulnerable", 3, player))
        elif move is QueenMove.OFF_WITH_HEAD:
            per = _a9(self.ascension, 3, 4)
            for _ in range(5):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is QueenMove.EXECUTION:
            dmg = _a9(self.ascension, 15, 18)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move is QueenMove.ENRAGE:
            strength = StrengthPower(amount=2)
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event
