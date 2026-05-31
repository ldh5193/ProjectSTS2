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


# --- RNG shims --------------------------------------------------------------
# Monster *spawn* time is driven by the run's `Rng` wrapper (sim/rng.py), while
# in-combat `take_turn` is driven by a stdlib `random.Random`. Neither exposes
# the full API of the other, so these shims normalise the few operations the
# table monsters + group factories need across both.

def _rng_random(rng) -> float:
    if hasattr(rng, "next_float"):
        return rng.next_float(0.0, 1.0)
    return rng.random()


def _rng_choice(rng, items):
    # Both Rng and random.Random expose `choice`.
    return rng.choice(items)


def _rng_choices(rng, names, weights):
    """Weighted single pick that works on Rng or random.Random."""
    if hasattr(rng, "choices"):
        return rng.choices(names, weights=weights)[0]
    total = float(sum(weights))
    r = _rng_random(rng) * total
    upto = 0.0
    for n, w in zip(names, weights):
        upto += w
        if r < upto:
            return n
    return names[-1]


def _rng_sample(rng, items, k):
    """Sample k distinct items, working on Rng or random.Random."""
    if hasattr(rng, "sample"):
        return rng.sample(items, k)
    pool = list(items)
    out = []
    for _ in range(k):
        idx = int(_rng_random(rng) * len(pool))
        if idx >= len(pool):
            idx = len(pool) - 1
        out.append(pool.pop(idx))
    return out


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
# Dazed (EyeWithTeeth illusion DISTRACT): an Unplayable, Ethereal status with
# no effect — pure deck-clog (Dazed.cs). Modeled like Wound.
DAZED_CARD = CardDef(
    id="dazed", name="Dazed", cost=_STATUS_UNPLAYABLE,
    type=CardType.SKILL, effects=(), count=0, is_status=True,
)
# Infection (PhrogParasite INFECT / Wriggler WRIGGLE): an Unplayable Status
# that deals 3 unblockable damage at end of turn while in hand (Infection.cs).
# The sim's status-card system models it as a deck-clog (the turn-end tick is
# the same TODO that BURN carries), which is its main faithful effect — it
# occupies hand slots and bloats the deck.
INFECTION_CARD = CardDef(
    id="infection", name="Infection", cost=_STATUS_UNPLAYABLE,
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
# Doormaker rotates a "phase power" via SwapPhasePower<T>: HungerPower on
# DRAMATIC_OPEN and after GRASP, ScrutinyPower after HUNGER, GraspPower after
# SCRUTINY (Doormaker.cs:129/142/152/164). We wire HungerPower faithfully (it
# afflicts every Attack/Skill card with Devoured+Exhaust — HungerPower.cs); the
# phase power is removed when leaving the Hunger phase, mirroring SwapPhasePower
# which first Remove<HungerPower> then Apply<T>.
# TODO(fidelity): ScrutinyPower (discards a non-draw card — ScrutinyPower.cs
#   ShouldDraw false off-handDraw) and GraspPower (Weighted affliction:
#   +1 energy cost on ALL cards — GraspPower.cs Afflict<Weighted>) are not yet
#   modeled (no ScrutinyPower/GraspPower/Weighted primitive in powers.py). The
#   Hunger phase is the only one whose affliction layer exists. Wire Scrutiny/
#   Grasp once those power+affliction primitives land.


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
    # Combat back-reference (attached by CombatState._attach_combat_refs) so the
    # phase-power swaps can mutate the player's cards via the AfterApplied hook.
    _combat: object = None

    def _swap_phase_power(self, target_id: str | None) -> None:
        """SwapPhasePower<T>: remove the current Hunger phase power (the only
        phase power modeled), then apply `target_id` if it is one we model.
        Mirrors Doormaker.SwapPhasePower which first removes Hunger/Scrutiny/
        Grasp then applies the next phase power."""
        cs = getattr(self, "_combat", None)
        if cs is None:
            return
        cs.remove_player_affliction_power("hunger")
        if target_id == "hunger":
            cs.apply_player_affliction_power("hunger", 1)

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
            # DramaticOpenMove: reveal (no damage), then SwapPhasePower<Hunger>.
            self._swap_phase_power("hunger")
        elif move is DoormakerMove.HUNGER:
            dmg = _a9(self.ascension, 30, 35)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            # HungerMove ends with SwapPhasePower<ScrutinyPower> -> remove Hunger
            # (Scrutiny is not yet modeled; see the TODO above).
            self._swap_phase_power(None)
        elif move is DoormakerMove.SCRUTINY:
            dmg = _a9(self.ascension, 24, 26)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            # ScrutinyMove ends with SwapPhasePower<GraspPower> (not modeled).
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
            # GraspMove ends with SwapPhasePower<HungerPower> -> re-apply Hunger.
            self._swap_phase_power("hunger")

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
        # LagavulinMatriarch.cs:112-113 — spawns with Plating 12 + Asleep 3
        # (AsleepPower: the first unblocked hit wakes it, removing its Plating).
        from .powers import make_power
        m.add_or_stack_power(make_power("plating", 12, m))
        m.add_or_stack_power(make_power("asleep", 3, m))
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
        # Slippery 9 (Vantom.cs:73 Apply<SlipperyPower> amount=9): each of the
        # first 9 damage instances Vantom takes is capped to 1 HP, then the
        # counter decrements. A heavy defensive buff that must be chipped away.
        m.add_or_stack_power(make_power("slippery", 9, m))
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
        # Enrage (EnragePower: gain Strength when the player plays a Skill) and
        # PainfulStabs (PainfulStabsPower: powered attacks add Wounds to the
        # player's discard) are granted at spawn, matching TestSubject.cs:172
        # (EnrageAmount 2 / A9 3) and the Phase-3 PainfulStabs 1.
        m.add_or_stack_power(make_power("enrage", _a9(ascension, 2, 3), m))
        m.add_or_stack_power(make_power("painful_stabs", 1, m))
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


# ===========================================================================
# GENERIC MOVE-TABLE MONSTERS (Phase 8 roster expansion)
# ===========================================================================
# The remaining Overgrowth / Hive / Glory normals + elites all follow the same
# decompiled shape: a fixed-name MoveState set wired into either a
# deterministic FollowUp chain or a RandomBranchState (with CannotRepeat /
# weighted branches). Rather than hand-write a near-identical class per
# monster, we describe each by a declarative move table and an AI graph and
# run them all through one faithful engine (`_TableMonster`).
#
# Each Move carries the decompiled (base, ascended) numbers so _a9 (damage) /
# _a8 (block) scaling stays exact. Effects are limited to powers the sim
# already implements (strength/weak/frail/vulnerable/thorns/plating/poison);
# unmodeled visual powers (Tender, Hex, Slumber, Artifact, CurlUp, ...) are
# documented and approximated or dropped, matching the simplification policy
# used by the boss/elite classes above.


@dataclass
class _Move:
    name: str
    # damage tuple (base, ascended_a9); 0 -> non-attack move.
    dmg: tuple[int, int] = (0, 0)
    hits: int = 1                      # MultiAttackIntent repeat count
    block: tuple[int, int] = (0, 0)    # self block gained (a8 scaled)
    self_strength: tuple[int, int] = (0, 0)   # StrengthPower to self (a9)
    self_thorns: int = 0
    self_plating: int = 0
    self_ritual: int = 0          # gain Ritual (Strength at turn end) — cultists
    self_regen: int = 0           # gain Regen (heal each turn end)
    # generic self-power grants (id, amount) for monster powers without a
    # dedicated _Move field (e.g. flame_barrier, reflect, double_damage).
    self_powers: tuple[tuple[str, int], ...] = ()
    # player debuffs (id -> amount); only sim-registered powers.
    debuffs: tuple[tuple[str, int], ...] = ()
    # card-affliction status powers (id, amount) the move applies to the player
    # (Hex/Hunger/Dampen/Tangled). Unlike `debuffs`, these must fire the power's
    # AfterApplied hook so it mutates the player's cards — they are routed through
    # CombatState.apply_player_affliction_power when a combat is attached.
    card_afflictions: tuple[tuple[str, int], ...] = ()
    status: tuple = ()                 # (card_id, pile, count) or empty
    next: str | None = None            # deterministic follow-up state name


# Status-card id -> CardDef for the table monsters.
_STATUS_CARDS = {
    "wound": WOUND_CARD,
    "burn": BURN_CARD,
    "dazed": DAZED_CARD,
    "infection": INFECTION_CARD,
}


@dataclass
class _TableMonster(Monster):
    """Faithful engine for the declarative move-table monsters.

    Subclasses set class attributes:
      MNAME           display name
      HP / HP_A8      flat HP (or HP_MIN/MAX[/_A8] for a roll)
      MOVES           dict[name -> _Move]
      START           starting move name
      RAND            optional dict[name -> list[(name, weight, cannot_repeat)]]
                      describing RandomBranchState transitions out of `name`.
    """
    last_move: str | None = None
    next_move: str | None = None
    ascension: int = 0
    # Combat back-reference (attached by CombatState._attach_combat_refs). Needed
    # by moves that apply a card-affliction status power (Hex/Hunger/Dampen),
    # which must mutate the player's cards via the engine's AfterApplied hook.
    _combat: object = None

    # NB: the following are plain CLASS attributes (no type annotation) so the
    # dataclass machinery does NOT turn them into instance fields. If they were
    # fields, the generated __init__ would reset them to the base defaults on
    # every instance, shadowing each subclass's overrides.
    MNAME = "Monster"
    HP = 1
    HP_A8 = 1
    HP_MIN = None
    HP_MAX = None
    HP_MIN_A8 = None
    HP_MAX_A8 = None
    MOVES = None
    START = ""
    RAND = None
    # Powers granted at spawn (id, amount): e.g. CurlUp on lice, Slumber on the
    # Slumbering Beetle, PainfulStabs/Enrage on TestSubject. Applied in spawn().
    SPAWN_POWERS: tuple = ()

    @classmethod
    def _roll_hp(cls, rng: random.Random, ascension: int) -> int:
        if cls.HP_MIN is not None:
            lo = _a8(ascension, cls.HP_MIN, cls.HP_MIN_A8 or cls.HP_MIN)
            hi = _a8(ascension, cls.HP_MAX, cls.HP_MAX_A8 or cls.HP_MAX)
            return rng.randint(lo, hi)
        return _a8(ascension, cls.HP, cls.HP_A8)

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0):
        hp = cls._roll_hp(rng, ascension)
        m = cls(name=cls.MNAME, hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = cls.START
        for pid, amt in cls.SPAWN_POWERS:
            # amt may be a flat int or an (base, a8) tuple for ascension scaling.
            value = _a8(ascension, amt[0], amt[1]) if isinstance(amt, tuple) else amt
            m.add_or_stack_power(make_power(pid, value, m))
        return m

    def _branch(self, rng: random.Random, key: str) -> str:
        """Pick from a RandomBranchState; honours CannotRepeat + weights."""
        branches = self.RAND[key]
        pool = [(n, w) for (n, w, cannot) in branches
                if not (cannot and n == self.last_move)]
        if not pool:  # everything would repeat -> allow repeats (bag dry)
            pool = [(n, w) for (n, w, _c) in branches]
        names = [n for n, _w in pool]
        weights = [w for _n, w in pool]
        return _rng_choices(rng, names, weights)

    def roll_next_move(self, rng: random.Random) -> str:
        last = self.last_move
        if last is None:
            return self.START
        mv = self.MOVES[last]
        if mv.next is not None:
            return mv.next
        if self.RAND and last in self.RAND:
            return self._branch(rng, last)
        # Several moves can funnel into one shared RAND node, keyed by "*".
        if self.RAND and "*" in self.RAND:
            return self._branch(rng, "*")
        return self.START

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        mv = self.MOVES[self.next_move]
        if mv.dmg == (0, 0):
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        return (_a9(self.ascension, mv.dmg[0], mv.dmg[1]) + str_amt) * mv.hits

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        name = self.next_move or self.roll_next_move(rng)
        mv = self.MOVES[name]
        event = {"move": name, "damage": 0, "blocked": 0, "hp_loss": 0}

        if mv.dmg != (0, 0):
            per = _a9(self.ascension, mv.dmg[0], mv.dmg[1])
            for _ in range(mv.hits):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        if mv.block != (0, 0):
            self.block += _a8(self.ascension, mv.block[0], mv.block[1])
        if mv.self_plating:
            self.add_or_stack_power(make_power("plating", mv.self_plating, self))
        if mv.self_thorns:
            self.add_or_stack_power(make_power("thorns", mv.self_thorns, self))
        if mv.self_ritual:
            self.add_or_stack_power(make_power("ritual", mv.self_ritual, self))
        if mv.self_regen:
            self.add_or_stack_power(make_power("regen", mv.self_regen, self))
        for pid, amt in mv.self_powers:
            self.add_or_stack_power(make_power(pid, amt, self))
        if mv.self_strength != (0, 0):
            amt = _a9(self.ascension, mv.self_strength[0], mv.self_strength[1])
            st = StrengthPower(amount=amt)
            st._owner = self
            self.add_or_stack_power(st)
        for pid, amt in mv.debuffs:
            player.add_or_stack_power(make_power(pid, amt, player))
        for pid, amt in mv.card_afflictions:
            self._apply_card_affliction(player, pid, amt)
        if mv.status:
            card_id, pile, count = mv.status
            _queue_status(self, _STATUS_CARDS[card_id], pile, count)

        self.last_move = name
        self.next_move = self.roll_next_move(rng)
        return event

    def _apply_card_affliction(self, player, power_id: str, amount: int) -> None:
        """Apply a card-affliction status power (Hex/Hunger/Dampen/Tangled) to
        the player, firing AfterApplied so it mutates the player's cards. Routes
        through the live CombatState (so it can reach all card piles); in
        standalone tests with no combat attached, falls back to a bare power so
        the debuff at least registers on the player."""
        cs = getattr(self, "_combat", None)
        if cs is not None:
            cs.apply_player_affliction_power(power_id, amount)
        else:
            player.add_or_stack_power(make_power(power_id, amount, player))


# --- Overgrowth normals/weaks ---------------------------------------------

class FuzzyWurmCrawler(_TableMonster):
    # FuzzyWurmCrawler.cs: HP 55-57 (A8 58-59). FIRST_ACID_GOOP(4/6) ->
    # INHALE(+7 Str) -> ACID_GOOP(4/6) -> FIRST_ACID_GOOP (loop).
    MNAME = "Fuzzy Wurm Crawler"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 55, 57, 58, 59
    START = "FIRST_ACID_GOOP"
    MOVES = {
        "FIRST_ACID_GOOP": _Move("FIRST_ACID_GOOP", dmg=(4, 6), next="INHALE"),
        "INHALE": _Move("INHALE", self_strength=(7, 7), next="ACID_GOOP"),
        "ACID_GOOP": _Move("ACID_GOOP", dmg=(4, 6), next="FIRST_ACID_GOOP"),
    }


class ShrinkerBeetle(_TableMonster):
    # ShrinkerBeetle.cs: HP 38-40 (A8 40-42). SHRINK(Shrink debuff ~Weak)
    # -> CHOMP(7/8) -> STOMP(13/14) -> CHOMP (loop). Shrink reduces player dmg;
    # approximated by Weak 2 (no Shrink power in sim).
    MNAME = "Shrinker Beetle"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 38, 40, 40, 42
    START = "SHRINK"
    MOVES = {
        "SHRINK": _Move("SHRINK", debuffs=(("weak", 2),), next="CHOMP"),
        "CHOMP": _Move("CHOMP", dmg=(7, 8), next="STOMP"),
        "STOMP": _Move("STOMP", dmg=(13, 14), next="CHOMP"),
    }


class Mawler(_TableMonster):
    # Mawler.cs: HP 72 (A8 76). Start CLAW(4/5 x2); RandomBranch:
    # RIP_AND_TEAR(14/16) CannotRepeat, ROAR(Vuln 3) UseOnlyOnce, CLAW x2.
    MNAME = "Mawler"
    HP, HP_A8 = 72, 76
    START = "CLAW"
    MOVES = {
        "RIP_AND_TEAR": _Move("RIP_AND_TEAR", dmg=(14, 16)),
        "ROAR": _Move("ROAR", debuffs=(("vulnerable", 3),)),
        "CLAW": _Move("CLAW", dmg=(4, 5), hits=2),
    }
    _roared: bool = False

    def roll_next_move(self, rng: random.Random) -> str:
        if self.last_move is None:
            return self.START
        branches = [("RIP_AND_TEAR", 1.0, True), ("CLAW", 1.0, True)]
        if not self._roared:
            branches.append(("ROAR", 1.0, False))  # UseOnlyOnce
        pool = [(n, w) for (n, w, c) in branches
                if not (c and n == self.last_move)]
        if not pool:
            pool = [(n, w) for (n, w, _c) in branches]
        choice = _rng_choices(rng, [n for n, _w in pool],
                              [w for _n, w in pool])
        if choice == "ROAR":
            self._roared = True
        return choice


class VineShambler(_TableMonster):
    # VineShambler.cs: HP 61 (A8 64). Start SWIPE(6/7 x2) -> GRASPING_VINES
    # (8/9 + TangledPower 1 — VineShambler.cs:66 PowerCmd.Apply<TangledPower>
    # (targets, 1m); Entangles every Attack card: +1 energy cost this turn) ->
    # CHOMP(16/18) -> SWIPE (loop).
    MNAME = "Vine Shambler"
    HP, HP_A8 = 61, 64
    START = "SWIPE"
    MOVES = {
        "GRASPING_VINES": _Move("GRASPING_VINES", dmg=(8, 9),
                                card_afflictions=(("tangled", 1),),
                                next="CHOMP"),
        "SWIPE": _Move("SWIPE", dmg=(6, 7), hits=2, next="GRASPING_VINES"),
        "CHOMP": _Move("CHOMP", dmg=(16, 18), next="SWIPE"),
    }


class CubexConstruct(_TableMonster):
    # CubexConstruct.cs: HP 65 (A8 70). Starts with 13 block + Artifact 1
    # (cosmetic). CHARGE_UP(+2 Str) -> REPEATER(7/8 +2Str) -> REPEATER2(7/8
    # +2Str) -> EXPEL(5/6 x2) -> REPEATER (loop).
    MNAME = "Cubex Construct"
    HP, HP_A8 = 65, 70
    START = "CHARGE_UP"
    MOVES = {
        "CHARGE_UP": _Move("CHARGE_UP", self_strength=(2, 2), next="REPEATER"),
        "REPEATER": _Move("REPEATER", dmg=(7, 8), self_strength=(2, 2),
                          next="REPEATER2"),
        "REPEATER2": _Move("REPEATER2", dmg=(7, 8), self_strength=(2, 2),
                           next="EXPEL"),
        "EXPEL": _Move("EXPEL", dmg=(5, 6), hits=2, next="REPEATER"),
    }

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0):
        m = super().spawn(rng, ascension)
        m.block = 13  # AfterAddedToRoom GainBlock(13)
        return m


class Flyconid(_TableMonster):
    # Flyconid.cs: HP 47-49 (A8 51-53). Initial RAND: FRAIL_SPORES(8/9 + Frail)
    # w2 / SMASH(11/12) w1. Main RAND: VULN_SPORES(Vuln) w3 / FRAIL_SPORES w2 /
    # SMASH w1, all CannotRepeat.
    MNAME = "Flyconid"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 47, 49, 51, 53
    START = "__INITIAL__"
    MOVES = {
        "VULN_SPORES": _Move("VULN_SPORES", debuffs=(("vulnerable", 2),)),
        "FRAIL_SPORES": _Move("FRAIL_SPORES", dmg=(8, 9),
                              debuffs=(("frail", 2),)),
        "SMASH": _Move("SMASH", dmg=(11, 12)),
    }
    RAND = {
        "*": [("VULN_SPORES", 3.0, True), ("FRAIL_SPORES", 2.0, True),
              ("SMASH", 1.0, True)],
    }

    def roll_next_move(self, rng: random.Random) -> str:
        if self.last_move is None or self.last_move == "__INITIAL__":
            # INITIAL RandomBranch: FRAIL_SPORES w2, SMASH w1.
            return _rng_choices(rng, ["FRAIL_SPORES", "SMASH"], [2.0, 1.0])
        return self._branch(rng, "*")

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0):
        m = super().spawn(rng, ascension)
        m.next_move = m.roll_next_move(rng)  # resolve INITIAL branch up front
        m.last_move = None
        return m


class SnappingJaxfruit(_TableMonster):
    # SnappingJaxfruit.cs: HP 31-33 (A8 34-36). Single move ENERGY_ORB(3/4 +2
    # Str) self-loop.
    MNAME = "Snapping Jaxfruit"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 31, 33, 34, 36
    START = "ENERGY_ORB"
    MOVES = {
        "ENERGY_ORB": _Move("ENERGY_ORB", dmg=(3, 4), self_strength=(2, 2),
                            next="ENERGY_ORB"),
    }


class Inklet(_TableMonster):
    # Inklet.cs: HP 11-17 (A8 12-18). Small minion. JAB(3/4) w2 / WHIRLWIND
    # (2/3 x3) random attacker; PIERCING_GAZE(10/11) for the middle inklet.
    # Slippery 1 (Inklet.cs:57 Apply<SlipperyPower> amount=1): the FIRST damage
    # instance it takes is capped to 1 HP, then Slippery expires.
    MNAME = "Inklet"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 11, 17, 12, 18
    START = "JAB"
    SPAWN_POWERS = (("slippery", 1),)
    MOVES = {
        "JAB": _Move("JAB", dmg=(3, 4)),
        "WHIRLWIND": _Move("WHIRLWIND", dmg=(2, 3), hits=3),
        "PIERCING_GAZE": _Move("PIERCING_GAZE", dmg=(10, 11)),
    }
    RAND = {"*": [("JAB", 2.0, False), ("WHIRLWIND", 1.0, True)]}


class SlitheringStrangler(_TableMonster):
    # SlitheringStrangler.cs: HP 53-55 (A8 54-56). CONSTRICT applies Constrict 3
    # (ConstrictPower: player takes 3 unblockable at its turn end) -> RAND{THWACK
    # (7/8 +5blk), LASH(12/13)} -> CONSTRICT.
    MNAME = "Slithering Strangler"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 53, 55, 54, 56
    START = "CONSTRICT"
    MOVES = {
        "CONSTRICT": _Move("CONSTRICT", debuffs=(("constrict", 3),)),
        "THWACK": _Move("THWACK", dmg=(7, 8), block=(5, 5), next="CONSTRICT"),
        "LASH": _Move("LASH", dmg=(12, 13), next="CONSTRICT"),
    }
    RAND = {"CONSTRICT": [("THWACK", 1.0, False), ("LASH", 1.0, False)]}


# Slimes — Overgrowth SlimesNormal/Weak + Flyconid/Strangler add-ons.
class LeafSlimeS(_TableMonster):
    # LeafSlimeS.cs: HP 11-15 (A8 12-16). RAND BUTT(3/4) / GOOP(status).
    MNAME = "Leaf Slime (S)"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 11, 15, 12, 16
    START = "BUTT"
    MOVES = {
        "BUTT": _Move("BUTT", dmg=(3, 4)),
        "GOOP": _Move("GOOP", status=("wound", "discard", 1)),
    }
    RAND = {"*": [("BUTT", 1.0, True), ("GOOP", 1.0, True)]}


class TwigSlimeS(_TableMonster):
    # TwigSlimeS.cs: HP 7-11 (A8 8-12). BUTT(4/5) self-loop.
    MNAME = "Twig Slime (S)"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 7, 11, 8, 12
    START = "BUTT"
    MOVES = {"BUTT": _Move("BUTT", dmg=(4, 5), next="BUTT")}


class LeafSlimeM(_TableMonster):
    # LeafSlimeM.cs: HP 32-35 (A8 33-36). STICKY(status) -> CLUMP(8/9) ->
    # STICKY (loop).
    MNAME = "Leaf Slime (M)"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 32, 35, 33, 36
    START = "STICKY"
    MOVES = {
        "STICKY": _Move("STICKY", status=("wound", "discard", 2), next="CLUMP"),
        "CLUMP": _Move("CLUMP", dmg=(8, 9), next="STICKY"),
    }


class TwigSlimeM(_TableMonster):
    # TwigSlimeM.cs: HP 26-28 (A8 27-29). RAND STICKY(status1)/CLUMP(11/12).
    MNAME = "Twig Slime (M)"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 26, 28, 27, 29
    START = "STICKY"
    MOVES = {
        "STICKY": _Move("STICKY", status=("wound", "discard", 1)),
        "CLUMP": _Move("CLUMP", dmg=(11, 12)),
    }
    RAND = {"*": [("STICKY", 1.0, True), ("CLUMP", 1.0, True)]}


# RubyRaiders (Overgrowth RubyRaidersNormal: 3 distinct raiders).
class AxeRubyRaider(_TableMonster):
    # AxeRubyRaider.cs: HP 20-22 (A8 21-23). SWING(5/6 +blk) -> SWING2 ->
    # BIG_SWING(12/13) -> SWING.
    MNAME = "Axe Ruby Raider"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 20, 22, 21, 23
    START = "SWING1"
    MOVES = {
        "SWING1": _Move("SWING1", dmg=(5, 6), block=(5, 5), next="SWING2"),
        "SWING2": _Move("SWING2", dmg=(5, 6), block=(5, 5), next="BIG_SWING"),
        "BIG_SWING": _Move("BIG_SWING", dmg=(12, 13), next="SWING1"),
    }


class AssassinRubyRaider(_TableMonster):
    # AssassinRubyRaider.cs: HP 18-23 (A8 19-24). KILLSHOT(11/12) self-loop.
    MNAME = "Assassin Ruby Raider"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 18, 23, 19, 24
    START = "KILLSHOT"
    MOVES = {"KILLSHOT": _Move("KILLSHOT", dmg=(11, 12), next="KILLSHOT")}


class BruteRubyRaider(_TableMonster):
    # BruteRubyRaider.cs: HP 30-33 (A8 31-34). BEAT(7/8) -> ROAR(+Str) -> BEAT.
    MNAME = "Brute Ruby Raider"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 30, 33, 31, 34
    START = "BEAT"
    MOVES = {
        "BEAT": _Move("BEAT", dmg=(7, 8), next="ROAR"),
        "ROAR": _Move("ROAR", self_strength=(3, 3), next="BEAT"),
    }


class CrossbowRubyRaider(_TableMonster):
    # CrossbowRubyRaider.cs: HP 18-21 (A8 19-22). RELOAD(+blk) -> FIRE(14/16)
    # -> RELOAD.
    MNAME = "Crossbow Ruby Raider"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 18, 21, 19, 22
    START = "RELOAD"
    MOVES = {
        "RELOAD": _Move("RELOAD", block=(6, 6), next="FIRE"),
        "FIRE": _Move("FIRE", dmg=(14, 16), next="RELOAD"),
    }


class TrackerRubyRaider(_TableMonster):
    # TrackerRubyRaider.cs: HP 21-25 (A8 22-26). TRACK(Vuln) -> HOUNDS(1 x N)
    # self-loop. Hounds modeled as 1 dmg x4 plus the Vulnerable from track.
    MNAME = "Tracker Ruby Raider"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 21, 25, 22, 26
    START = "TRACK"
    MOVES = {
        "TRACK": _Move("TRACK", debuffs=(("vulnerable", 2),), next="HOUNDS"),
        "HOUNDS": _Move("HOUNDS", dmg=(1, 1), hits=4, next="HOUNDS"),
    }


# --- Hive normals/weaks ----------------------------------------------------

class HunterKiller(_TableMonster):
    # HunterKiller.cs: HP 121 (A8 126). Start GOOP(Tender~Vuln1) -> RAND
    # BITE(17/19) CannotRepeat / PUNCTURE(7/8 x3) w2.
    MNAME = "Hunter Killer"
    HP, HP_A8 = 121, 126
    START = "GOOP"
    MOVES = {
        "GOOP": _Move("GOOP", debuffs=(("vulnerable", 1),)),
        "BITE": _Move("BITE", dmg=(17, 19)),
        "PUNCTURE": _Move("PUNCTURE", dmg=(7, 8), hits=3),
    }
    RAND = {"*": [("BITE", 1.0, True), ("PUNCTURE", 2.0, False)],
            "GOOP": [("BITE", 1.0, True), ("PUNCTURE", 2.0, False)]}


class Ovicopter(_TableMonster):
    # Ovicopter.cs: HP 124-130 (A8 126-132). LAY_EGGS(summon; sim: +3/+4 Str
    # proxy for the egg threat) -> SMASH(16/17) -> TENDERIZER(7/8 + Vuln2) ->
    # SMASH (loop). We fold the summon into a self-strength gain.
    MNAME = "Ovicopter"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 124, 130, 126, 132
    START = "LAY_EGGS"
    MOVES = {
        "LAY_EGGS": _Move("LAY_EGGS", self_strength=(3, 4), next="SMASH"),
        "SMASH": _Move("SMASH", dmg=(16, 17), next="TENDERIZER"),
        "TENDERIZER": _Move("TENDERIZER", dmg=(7, 8),
                            debuffs=(("vulnerable", 2),), next="SMASH"),
    }


class SlumberingBeetle(_TableMonster):
    # SlumberingBeetle.cs: HP 86 (A8 89). Spawns Plating 15/18 + Slumber 3
    # (SlumberPower: each own turn-end or unblocked hit decrements it; at 0 it
    # wakes). While asleep it SNOREs (no-op); once Slumber expires it ROLL_OUTs
    # (16/18 +2Str) on a self-loop.
    MNAME = "Slumbering Beetle"
    HP, HP_A8 = 86, 89
    START = "SNORE"
    SPAWN_POWERS = (("slumber", 3),)
    MOVES = {
        "SNORE": _Move("SNORE", next="SNORE"),
        "ROLL_OUT": _Move("ROLL_OUT", dmg=(16, 18), self_strength=(2, 2),
                          next="ROLL_OUT"),
    }

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0):
        m = super().spawn(rng, ascension)
        m.add_or_stack_power(make_power("plating", _a8(ascension, 15, 18), m))
        return m

    def roll_next_move(self, rng: random.Random) -> str:
        # Stay asleep (SNORE) until Slumber wears off, then begin ROLL_OUT.
        if self.get_power("slumber") is not None:
            return "SNORE"
        return "ROLL_OUT"


class TheObscura(_TableMonster):
    # TheObscura.cs: HP 123 (A8 129). ILLUSION(summon; sim: +3 Str proxy) ->
    # RAND PIERCING_GAZE(10/11) / WAIL(team Str -> self +3 Str) /
    # HARDENING_STRIKE(6/7 +6/7 blk), all CannotRepeat.
    MNAME = "The Obscura"
    HP, HP_A8 = 123, 129
    START = "ILLUSION"
    MOVES = {
        "ILLUSION": _Move("ILLUSION", self_strength=(3, 3)),
        "PIERCING_GAZE": _Move("PIERCING_GAZE", dmg=(10, 11)),
        "WAIL": _Move("WAIL", self_strength=(3, 3)),
        "HARDENING_STRIKE": _Move("HARDENING_STRIKE", dmg=(6, 7),
                                  block=(6, 7)),
    }
    RAND = {"*": [("PIERCING_GAZE", 1.0, True), ("WAIL", 1.0, True),
                  ("HARDENING_STRIKE", 1.0, True)],
            "ILLUSION": [("PIERCING_GAZE", 1.0, True), ("WAIL", 1.0, True),
                         ("HARDENING_STRIKE", 1.0, True)]}


class Tunneler(_TableMonster):
    # Tunneler.cs: HP 87 (A8 92). BITE(13/15) -> BURROW(+blk 32/37) ->
    # BELOW(23/26) self-loop. (DIZZY stun branch not reached in main chain.)
    MNAME = "Tunneler"
    HP, HP_A8 = 87, 92
    START = "BITE"
    MOVES = {
        "BITE": _Move("BITE", dmg=(13, 15), next="BURROW"),
        "BURROW": _Move("BURROW", block=(32, 37), next="BELOW"),
        "BELOW": _Move("BELOW", dmg=(23, 26), next="BELOW"),
    }


class ThievingHopper(_TableMonster):
    # ThievingHopper.cs: HP 79 (A8 84). THIEVERY(17/19) -> FLUTTER grants Flutter
    # 5 (FlutterPower: powered attacks on it are halved; 5 powered hits stun it)
    # -> HAT_TRICK(21/23) -> NAB(14/16) -> ESCAPE(flees; sim: no-op looping NAB).
    MNAME = "Thieving Hopper"
    HP, HP_A8 = 79, 84
    START = "THIEVERY"
    MOVES = {
        "THIEVERY": _Move("THIEVERY", dmg=(17, 19), next="FLUTTER"),
        "FLUTTER": _Move("FLUTTER", self_powers=(("flutter", 5),),
                         next="HAT_TRICK"),
        "HAT_TRICK": _Move("HAT_TRICK", dmg=(21, 23), next="NAB"),
        "NAB": _Move("NAB", dmg=(14, 16), next="ESCAPE"),
        "ESCAPE": _Move("ESCAPE", next="NAB"),
    }


class Myte(_TableMonster):
    # Myte.cs: HP 61-67 (A8 64-69). TOXIC(status2) -> BITE(13/15) -> SUCK(4/6
    # +2/3 Str) -> TOXIC (loop).
    MNAME = "Myte"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 61, 67, 64, 69
    START = "TOXIC"
    MOVES = {
        "TOXIC": _Move("TOXIC", status=("wound", "discard", 2), next="BITE"),
        "BITE": _Move("BITE", dmg=(13, 15), next="SUCK"),
        "SUCK": _Move("SUCK", dmg=(4, 6), self_strength=(2, 3), next="TOXIC"),
    }


class LouseProgenitor(_TableMonster):
    # LouseProgenitor.cs: HP 134-136 (A8 138-141). Spawns with CurlUp 14 (A8 18)
    # — gains that much Block the FIRST time it is hit by a powered attack. WEB
    # (9/10 + Frail2) -> CURL_AND_GROW(+blk 14/18 +5 Str) -> POUNCE(14/16) -> WEB.
    MNAME = "Louse Progenitor"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 134, 136, 138, 141
    START = "WEB"
    SPAWN_POWERS = (("curl_up", (14, 18)),)
    MOVES = {
        "WEB": _Move("WEB", dmg=(9, 10), debuffs=(("frail", 2),),
                     next="CURL_AND_GROW"),
        "CURL_AND_GROW": _Move("CURL_AND_GROW", block=(14, 18),
                               self_strength=(5, 5), next="POUNCE"),
        "POUNCE": _Move("POUNCE", dmg=(14, 16), next="WEB"),
    }


class Chomper(_TableMonster):
    # Chomper.cs: HP 60-64 (A8 63-67). Spawns Artifact 2 (cosmetic).
    # CLAMP(8/9 x2) -> SCREECH(status3) -> CLAMP (loop).
    MNAME = "Chomper"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 60, 64, 63, 67
    START = "CLAMP"
    MOVES = {
        "CLAMP": _Move("CLAMP", dmg=(8, 9), hits=2, next="SCREECH"),
        "SCREECH": _Move("SCREECH", status=("wound", "discard", 3),
                         next="CLAMP"),
    }


class Exoskeleton(_TableMonster):
    # Exoskeleton.cs: HP 24-28 (A8 25-29). HardToKill 9 — caps the HP it loses
    # to any single damage instance at 9 (Exoskeleton.cs:48 Apply<HardToKillPower>
    # amount=9 at spawn). RAND SKITTER(1 x3) / MANDIBLES(8/9 -> ENRAGE +2 Str).
    # MANDIBLES funnels into ENRAGE, then back to RAND.
    MNAME = "Exoskeleton"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 24, 28, 25, 29
    START = "__ENTRY__"
    SPAWN_POWERS = (("hard_to_kill", 9),)
    MOVES = {
        "SKITTER": _Move("SKITTER", dmg=(1, 1), hits=3),
        "MANDIBLES": _Move("MANDIBLES", dmg=(8, 9), next="ENRAGE"),
        "ENRAGE": _Move("ENRAGE", self_strength=(2, 2)),
    }
    RAND = {"*": [("SKITTER", 1.0, True), ("MANDIBLES", 1.0, True)]}

    def roll_next_move(self, rng: random.Random) -> str:
        if self.last_move is None or self.last_move == "__ENTRY__":
            return self._branch(rng, "*")
        if self.last_move == "MANDIBLES":
            return "ENRAGE"
        return self._branch(rng, "*")

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0):
        m = super().spawn(rng, ascension)
        m.next_move = m._branch(rng, "*")
        m.last_move = None
        return m


# Bowlbug family (Hive Bowlbugs encounters).
class BowlbugRock(_TableMonster):
    # BowlbugRock.cs: HP 45-48 (A8 46-49). HEADBUTT(15/16) -> DIZZY(stun) ->
    # HEADBUTT. Modeled as HEADBUTT -> DIZZY(no-op) -> HEADBUTT.
    MNAME = "Bowlbug Rock"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 45, 48, 46, 49
    START = "HEADBUTT"
    MOVES = {
        "HEADBUTT": _Move("HEADBUTT", dmg=(15, 16), next="DIZZY"),
        "DIZZY": _Move("DIZZY", next="HEADBUTT"),
    }


class BowlbugEgg(_TableMonster):
    # BowlbugEgg.cs: HP 21-22 (A8 23-24). BITE(7/8 + 7/8 block) self-loop.
    MNAME = "Bowlbug Egg"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 21, 22, 23, 24
    START = "BITE"
    MOVES = {
        "BITE": _Move("BITE", dmg=(7, 8), block=(7, 8), next="BITE"),
    }


class BowlbugNectar(_TableMonster):
    # BowlbugNectar.cs: HP 35-38 (A8 36-39). THRASH(3) -> BUFF(+15/16 Str) ->
    # THRASH2(3) self-loop.
    MNAME = "Bowlbug Nectar"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 35, 38, 36, 39
    START = "THRASH"
    MOVES = {
        "THRASH": _Move("THRASH", dmg=(3, 3), next="BUFF"),
        "BUFF": _Move("BUFF", self_strength=(15, 16), next="THRASH2"),
        "THRASH2": _Move("THRASH2", dmg=(3, 3), next="THRASH2"),
    }


class BowlbugSilk(_TableMonster):
    # BowlbugSilk.cs: HP 40-43 (A8 41-44). TOXIC_SPIT(Weak1) -> THRASH(4/5 x2)
    # -> TOXIC_SPIT (loop). Starts at TOXIC_SPIT.
    MNAME = "Bowlbug Silk"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 40, 43, 41, 44
    START = "TOXIC_SPIT"
    MOVES = {
        "TOXIC_SPIT": _Move("TOXIC_SPIT", debuffs=(("weak", 1),),
                            next="THRASH"),
        "THRASH": _Move("THRASH", dmg=(4, 5), hits=2, next="TOXIC_SPIT"),
    }


# --- Glory normals ---------------------------------------------------------

class Axebot(_TableMonster):
    # Axebot.cs: HP 40-44 (A8 42-46). BOOT_UP(+10 blk +1 Str) -> RAND
    # ONE_TWO(5/6 x2) w2 / SHARPEN(+4 Str) CannotRepeat / HAMMER_UPPERCUT(8/10
    # + Weak1 Frail1) w2.
    MNAME = "Axebot"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 40, 44, 42, 46
    START = "BOOT_UP"
    MOVES = {
        "BOOT_UP": _Move("BOOT_UP", block=(10, 10), self_strength=(1, 1)),
        "ONE_TWO": _Move("ONE_TWO", dmg=(5, 6), hits=2),
        "SHARPEN": _Move("SHARPEN", self_strength=(4, 4)),
        "HAMMER_UPPERCUT": _Move("HAMMER_UPPERCUT", dmg=(8, 10),
                                 debuffs=(("weak", 1), ("frail", 1))),
    }
    RAND = {"*": [("ONE_TWO", 2.0, False), ("SHARPEN", 1.0, True),
                  ("HAMMER_UPPERCUT", 2.0, False)]}

    def roll_next_move(self, rng: random.Random) -> str:
        if self.last_move is None:
            return self.START
        return self._branch(rng, "*")


class SlimedBerserker(_TableMonster):
    # SlimedBerserker.cs: HP 266 (A8 276). VOMIT_ICHOR(status10) ->
    # FURIOUS_PUMMELING(4/5 x4) -> LEECHING_HUG(Weak3 + self Str3) ->
    # SMOTHER(30/33) -> VOMIT_ICHOR (loop).
    MNAME = "Slimed Berserker"
    HP, HP_A8 = 266, 276
    START = "VOMIT_ICHOR"
    MOVES = {
        "VOMIT_ICHOR": _Move("VOMIT_ICHOR", status=("wound", "discard", 10),
                             next="FURIOUS_PUMMELING"),
        "FURIOUS_PUMMELING": _Move("FURIOUS_PUMMELING", dmg=(4, 5), hits=4,
                                   next="LEECHING_HUG"),
        "LEECHING_HUG": _Move("LEECHING_HUG", debuffs=(("weak", 3),),
                              self_strength=(3, 3), next="SMOTHER"),
        "SMOTHER": _Move("SMOTHER", dmg=(30, 33), next="VOMIT_ICHOR"),
    }


class OwlMagistrate(_TableMonster):
    # OwlMagistrate.cs: HP 234 (A8 243). SCRUTINY(16/17) -> PECK_ASSAULT(4 x6)
    # -> JUDICIAL_FLIGHT grants Soar (SoarPower: powered attacks on it are
    # halved while aloft) -> VERDICT(33/36 + Vuln4) -> SCRUTINY (loop).
    MNAME = "Owl Magistrate"
    HP, HP_A8 = 234, 243
    START = "SCRUTINY"
    MOVES = {
        "SCRUTINY": _Move("SCRUTINY", dmg=(16, 17), next="PECK_ASSAULT"),
        "PECK_ASSAULT": _Move("PECK_ASSAULT", dmg=(4, 4), hits=6,
                              next="JUDICIAL_FLIGHT"),
        "JUDICIAL_FLIGHT": _Move("JUDICIAL_FLIGHT", self_powers=(("soar", 1),),
                                 next="VERDICT"),
        "VERDICT": _Move("VERDICT", dmg=(33, 36), debuffs=(("vulnerable", 4),),
                         next="SCRUTINY"),
    }


class PunchConstruct(_TableMonster):
    # PunchConstruct.cs: HP 55 (A8 60). Spawns Artifact 1 (cosmetic).
    # READY(+10 blk) -> STRONG_PUNCH(14/16) -> FAST_PUNCH(5/6 x2 + Weak1) ->
    # READY (loop).
    MNAME = "Punch Construct"
    HP, HP_A8 = 55, 60
    START = "READY"
    MOVES = {
        "READY": _Move("READY", block=(10, 10), next="STRONG_PUNCH"),
        "STRONG_PUNCH": _Move("STRONG_PUNCH", dmg=(14, 16), next="FAST_PUNCH"),
        "FAST_PUNCH": _Move("FAST_PUNCH", dmg=(5, 6), hits=2,
                            debuffs=(("weak", 1),), next="READY"),
    }


class TheLost(_TableMonster):
    # TheLost.cs: HP 93 (A8 99). DEBILITATING_SMOG(steal 2 Str: self +2 Str
    # + player Weak proxy) -> EYE_LASERS(4/5 x2) -> SMOG (loop).
    MNAME = "The Lost"
    HP, HP_A8 = 93, 99
    START = "DEBILITATING_SMOG"
    MOVES = {
        "DEBILITATING_SMOG": _Move("DEBILITATING_SMOG", self_strength=(2, 2),
                                   debuffs=(("weak", 1),), next="EYE_LASERS"),
        "EYE_LASERS": _Move("EYE_LASERS", dmg=(4, 5), hits=2,
                            next="DEBILITATING_SMOG"),
    }


class TheForgotten(_TableMonster):
    # TheForgotten.cs: HP 106 (A8 111). MIASMA(steal Dex: +8 blk + Frail proxy)
    # -> DREAD(13/15) -> MIASMA (loop).
    MNAME = "The Forgotten"
    HP, HP_A8 = 106, 111
    START = "MIASMA"
    MOVES = {
        "MIASMA": _Move("MIASMA", block=(8, 8), debuffs=(("frail", 1),),
                        next="DREAD"),
        "DREAD": _Move("DREAD", dmg=(13, 15), next="MIASMA"),
    }


# --- Knights (Glory KnightsElite trio) -------------------------------------

class FlailKnight(_TableMonster):
    # FlailKnight.cs: HP 101 (A8 108). Start RAM(15/17); RAND WAR_CHANT(+3 Str)
    # CannotRepeat / FLAIL(9/10 x2) w2 / RAM(15/17) w2.
    MNAME = "Flail Knight"
    HP, HP_A8 = 101, 108
    START = "RAM"
    MOVES = {
        "WAR_CHANT": _Move("WAR_CHANT", self_strength=(3, 3)),
        "FLAIL": _Move("FLAIL", dmg=(9, 10), hits=2),
        "RAM": _Move("RAM", dmg=(15, 17)),
    }
    RAND = {"*": [("WAR_CHANT", 1.0, True), ("FLAIL", 2.0, False),
                  ("RAM", 2.0, False)]}

    def roll_next_move(self, rng: random.Random) -> str:
        if self.last_move is None:
            return self.START
        return self._branch(rng, "*")


class SpectralKnight(_TableMonster):
    # SpectralKnight.cs: HP 93 (A8 97). HEX applies HexPower 2 (PowerCmd.Apply
    # <HexPower>(target, 2m) — SpectralKnight.cs:66) -> SOUL_SLASH(15/17) ->
    # RAND SOUL_SLASH(15/17) w2 / SOUL_FLAME(3/4 x3) CannotRepeat. Hex afflicts
    # every player card with Ethereal (HexPower.cs).
    MNAME = "Spectral Knight"
    HP, HP_A8 = 93, 97
    START = "HEX"
    MOVES = {
        "HEX": _Move("HEX", card_afflictions=(("hex", 2),), next="SOUL_SLASH"),
        "SOUL_SLASH": _Move("SOUL_SLASH", dmg=(15, 17)),
        "SOUL_FLAME": _Move("SOUL_FLAME", dmg=(3, 4), hits=3),
    }
    RAND = {"*": [("SOUL_SLASH", 2.0, False), ("SOUL_FLAME", 1.0, True)]}

    def roll_next_move(self, rng: random.Random) -> str:
        last = self.last_move
        if last is None:
            return self.START
        if last == "HEX":
            return "SOUL_SLASH"
        return self._branch(rng, "*")


class MagiKnight(_TableMonster):
    # MagiKnight.cs: HP 82 (A8 89). POWER_SHIELD(6/7 + 5/9 blk) -> DAMPEN
    # applies DampenPower 1 (MagiKnight.cs:89 PowerCmd.Apply(dampen, target, 1m)
    # — downgrades every upgraded player card) -> SPEAR(10/11) -> PREP(+blk) ->
    # MAGIC_BOMB(35/40) -> SPEAR (loop).
    MNAME = "Magi Knight"
    HP, HP_A8 = 82, 89
    START = "POWER_SHIELD"
    MOVES = {
        "POWER_SHIELD": _Move("POWER_SHIELD", dmg=(6, 7), block=(5, 9),
                              next="DAMPEN"),
        "DAMPEN": _Move("DAMPEN", card_afflictions=(("dampen", 1),),
                        next="SPEAR"),
        "SPEAR": _Move("SPEAR", dmg=(10, 11), next="PREP"),
        "PREP": _Move("PREP", block=(9, 9), next="MAGIC_BOMB"),
        "MAGIC_BOMB": _Move("MAGIC_BOMB", dmg=(35, 40), next="SPEAR"),
    }


# --- Decimillipede segments (Hive DecimillipedeElite, 3 segments) ----------
# DecimillipedeSegment.cs: each segment HP 40-46 (A8 46-52). WRITHE(5/6 x2) ->
# CONSTRICT(8/9 + Weak1) -> BULK(6/7 + Str) -> WRITHE (loop). The Front /
# Middle / Back start at staggered indices (StarterMoveIdx % 3). Reattach /
# Doom mechanics (segments revive each other) are cosmetic-complex and omitted;
# each segment fights as an independent monster, which combat already supports.

class DecimillipedeSegment(_TableMonster):
    MNAME = "Decimillipede Segment"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 40, 46, 46, 52
    START = "WRITHE"
    MOVES = {
        "WRITHE": _Move("WRITHE", dmg=(5, 6), hits=2, next="CONSTRICT"),
        "CONSTRICT": _Move("CONSTRICT", dmg=(8, 9), debuffs=(("weak", 1),),
                           next="BULK"),
        "BULK": _Move("BULK", dmg=(6, 7), self_strength=(1, 1), next="WRITHE"),
    }


class ScrollOfBiting(_TableMonster):
    # ScrollOfBiting.cs: HP 31-38 (A8 32-39). CHOMP(14/16) -> MORE_TEETH(+2
    # Str) -> CHEW(5/6 x2) -> RAND{CHOMP CannotRepeat, CHEW w2}. PaperCuts 2 —
    # each powered attack that lands unblocked on the player costs the player 2
    # MAX HP (ScrollOfBiting.cs:75 Apply<PaperCutsPower> amount=2 at spawn).
    # Different scrolls start at staggered indices.
    MNAME = "Scroll of Biting"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 31, 38, 32, 39
    START = "CHOMP"
    SPAWN_POWERS = (("paper_cuts", 2),)
    MOVES = {
        "CHOMP": _Move("CHOMP", dmg=(14, 16), next="MORE_TEETH"),
        "MORE_TEETH": _Move("MORE_TEETH", self_strength=(2, 2), next="CHEW"),
        "CHEW": _Move("CHEW", dmg=(5, 6), hits=2),
    }
    RAND = {"CHEW": [("CHOMP", 1.0, True), ("CHEW", 2.0, False)]}


class DevotedSculptor(_TableMonster):
    # DevotedSculptor.cs: HP 162 (A8 172). FORBIDDEN_INCANTATION grants Ritual 2
    # (RitualPower: +Strength each turn end) -> SAVAGE(12/15) self-loop.
    MNAME = "Devoted Sculptor"
    HP, HP_A8 = 162, 172
    START = "FORBIDDEN_INCANTATION"
    MOVES = {
        "FORBIDDEN_INCANTATION": _Move("FORBIDDEN_INCANTATION",
                                       self_ritual=2, next="SAVAGE"),
        "SAVAGE": _Move("SAVAGE", dmg=(12, 15), next="SAVAGE"),
    }


class BygoneEffigy(_TableMonster):
    # BygoneEffigy.cs (Overgrowth elite): HP 127 (A8 132). INITIAL_SLEEP(no-op)
    # -> WAKE(+10 Str) -> SLASHES(13/15) self-loop. Slow power cosmetic.
    MNAME = "Bygone Effigy"
    HP, HP_A8 = 127, 132
    START = "INITIAL_SLEEP"
    MOVES = {
        "INITIAL_SLEEP": _Move("INITIAL_SLEEP", next="WAKE"),
        "WAKE": _Move("WAKE", self_strength=(10, 10), next="SLASHES"),
        "SLASHES": _Move("SLASHES", dmg=(13, 15), next="SLASHES"),
    }


class Byrdonis(_TableMonster):
    # Byrdonis.cs (Overgrowth elite): HP 81-84 (A8 90). Territorial — gains
    # Strength 1 at the end of EVERY turn (Byrdonis.cs:36 Apply<TerritorialPower>
    # amount=1 at spawn). SWOOP(17/19) -> PECK(3/4 x3) -> SWOOP (loop). Starts
    # at SWOOP.
    MNAME = "Byrdonis"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 81, 84, 90, 90
    START = "SWOOP"
    SPAWN_POWERS = (("territorial", 1),)
    MOVES = {
        "SWOOP": _Move("SWOOP", dmg=(17, 19), next="PECK"),
        "PECK": _Move("PECK", dmg=(3, 4), hits=3, next="SWOOP"),
    }


class Fabricator(_TableMonster):
    # Fabricator.cs (Glory normal): HP 150 (A8 155). FABRICATE(summon; sim: +3
    # Str proxy) / FABRICATING_STRIKE(18/21 + summon) random, then
    # DISINTEGRATE(11/13). Modeled as a fixed FABRICATING_STRIKE -> DISINTEGRATE
    # -> FABRICATE loop (the damage-relevant moves) for determinism.
    MNAME = "Fabricator"
    HP, HP_A8 = 150, 155
    START = "FABRICATING_STRIKE"
    MOVES = {
        "FABRICATING_STRIKE": _Move("FABRICATING_STRIKE", dmg=(18, 21),
                                    self_strength=(3, 3), next="DISINTEGRATE"),
        "DISINTEGRATE": _Move("DISINTEGRATE", dmg=(11, 13), next="FABRICATE"),
        "FABRICATE": _Move("FABRICATE", self_strength=(3, 3),
                           next="FABRICATING_STRIKE"),
    }


# --- Underdocks (Act-1 variant) normals/weaks/elites ----------------------
# HP convention: HP_MIN/MAX are the A0 InitialHp range; *_A8 are the
# ToughEnemies (A8) range. Damage tuples are (base, DeadlyEnemies A9). Values
# read verbatim from the decompiled MonsterModel classes.

class CorpseSlug(_TableMonster):
    # CorpseSlug.cs: HP 25-27 (A8 27-29). WhipSlap(3 x2) -> Glomp(8/9) ->
    # Goop(Frail 2) self-loop. Ravenous (gain Str) at spawn is cosmetic here;
    # the encounter spawns 3 (CorpseSlugsNormal) / 2 (CorpseSlugsWeak).
    MNAME = "Corpse Slug"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 25, 27, 27, 29
    START = "WHIP_SLAP"
    MOVES = {
        "WHIP_SLAP": _Move("WHIP_SLAP", dmg=(3, 3), hits=2, next="GLOMP"),
        "GLOMP": _Move("GLOMP", dmg=(8, 9), next="GOOP"),
        "GOOP": _Move("GOOP", debuffs=(("frail", 2),), next="WHIP_SLAP"),
    }


class Seapunk(_TableMonster):
    # Seapunk.cs: HP 44-46 (A8 47-49). SeaKick(11/13) -> SpinningKick(2 x4)
    # -> BubbleBurp(block 7/8 + Str 1/2) loop. Starts at SeaKick.
    MNAME = "Seapunk"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 44, 46, 47, 49
    START = "SEA_KICK"
    MOVES = {
        "SEA_KICK": _Move("SEA_KICK", dmg=(11, 13), next="SPINNING_KICK"),
        "SPINNING_KICK": _Move("SPINNING_KICK", dmg=(2, 2), hits=4,
                               next="BUBBLE_BURP"),
        "BUBBLE_BURP": _Move("BUBBLE_BURP", block=(7, 8), self_strength=(1, 2),
                             next="SEA_KICK"),
    }


class CalcifiedCultist(_TableMonster):
    # CalcifiedCultist.cs: HP 38-41 (A8 39-42). Incantation grants Ritual 2
    # (RitualPower: +Strength at every turn end) -> DarkStrike(9/11) self-loop.
    MNAME = "Calcified Cultist"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 38, 41, 39, 42
    START = "INCANTATION"
    MOVES = {
        "INCANTATION": _Move("INCANTATION", self_ritual=2, next="DARK_STRIKE"),
        "DARK_STRIKE": _Move("DARK_STRIKE", dmg=(9, 11), next="DARK_STRIKE"),
    }


class DampCultist(_TableMonster):
    # DampCultist.cs: HP 51-53 (A8 52-54). Incantation grants Ritual 5/6
    # (RitualPower: +Strength each turn end) -> DarkStrike(1/3) self-loop.
    MNAME = "Damp Cultist"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 51, 53, 52, 54
    START = "INCANTATION"
    MOVES = {
        "INCANTATION": _Move("INCANTATION", self_ritual=5, next="DARK_STRIKE"),
        "DARK_STRIKE": _Move("DARK_STRIKE", dmg=(1, 3), next="DARK_STRIKE"),
    }


class FossilStalker(_TableMonster):
    # FossilStalker.cs: HP 51-53 (A8 54-56). Gains Suck 3 at spawn (cosmetic
    # leech, omitted). Random branch among Tackle(9/11 + Frail debuff),
    # Latch(12/14), Lash(3/4 x2) at equal weight, CannotRepeat. Starts Latch.
    MNAME = "Fossil Stalker"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 51, 53, 54, 56
    START = "LATCH"
    MOVES = {
        "TACKLE": _Move("TACKLE", dmg=(9, 11), debuffs=(("frail", 1),)),
        "LATCH": _Move("LATCH", dmg=(12, 14)),
        "LASH": _Move("LASH", dmg=(3, 4), hits=2),
    }
    RAND = {
        "*": [("TACKLE", 2, True), ("LATCH", 2, True), ("LASH", 2, True)],
    }


class SewerClam(_TableMonster):
    # SewerClam.cs: HP 56 (A8 58). Gains Plating 8 (A8 9) ONCE at spawn
    # (AfterAddedToRoom) — recurring +block each turn-end. Pressurize(+4 Str)
    # -> Jet(10/11) loop. Starts at Jet.
    MNAME = "Sewer Clam"
    HP, HP_A8 = 56, 58
    START = "JET"
    MOVES = {
        "PRESSURIZE": _Move("PRESSURIZE", self_strength=(4, 4), next="JET"),
        "JET": _Move("JET", dmg=(10, 11), next="PRESSURIZE"),
    }

    @classmethod
    def spawn(cls, rng, ascension: int = 0):
        m = super().spawn(rng, ascension=ascension)
        m.add_or_stack_power(make_power("plating", _a8(ascension, 8, 9), m))
        return m


class Toadpole(_TableMonster):
    # Toadpole.cs: HP 21-25 (A8 22-26). Front toadpole starts at Spiken
    # (Thorns 2), back at Whirl. SpikeSpit(3/4 x3) / Whirl(7/8) / Spiken loop.
    # ToadpolesWeak spawns 2 (front + back).
    MNAME = "Toadpole"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 21, 25, 22, 26
    START = "WHIRL"  # overridden per-spawn for the front toadpole
    MOVES = {
        "SPIKE_SPIT": _Move("SPIKE_SPIT", dmg=(3, 4), hits=3, next="WHIRL"),
        "WHIRL": _Move("WHIRL", dmg=(7, 8), next="SPIKEN"),
        "SPIKEN": _Move("SPIKEN", self_thorns=2, next="SPIKE_SPIT"),
    }


class TwoTailedRat(_TableMonster):
    # TwoTailedRat.cs: HP 17-21 (A8 18-22). Scratch(8/9) / DiseaseBite(6/7) /
    # Screech(Frail 1) / CallForBackup(summon, omitted). Three spawn with
    # staggered starter moves; we deterministically cycle Scratch->Bite->
    # Screech (the damage-relevant moves) for stability.
    MNAME = "Two-Tailed Rat"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 17, 21, 18, 22
    START = "SCRATCH"
    MOVES = {
        "SCRATCH": _Move("SCRATCH", dmg=(8, 9), next="DISEASE_BITE"),
        "DISEASE_BITE": _Move("DISEASE_BITE", dmg=(6, 7), next="SCREECH"),
        "SCREECH": _Move("SCREECH", debuffs=(("frail", 1),), next="SCRATCH"),
    }


class GremlinMerc(_TableMonster):
    # GremlinMerc.cs (GremlinMercNormal solo): HP 47-49 (A8 51-53).
    # Gimme(7/8 x2) -> DoubleSmash(6/7 x2 + Weak 2) -> Hehe(8/9 + Str 2) loop.
    MNAME = "Gremlin Merc"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 47, 49, 51, 53
    START = "GIMME"
    MOVES = {
        "GIMME": _Move("GIMME", dmg=(7, 8), hits=2, next="DOUBLE_SMASH"),
        "DOUBLE_SMASH": _Move("DOUBLE_SMASH", dmg=(6, 7), hits=2,
                              debuffs=(("weak", 2),), next="HEHE"),
        "HEHE": _Move("HEHE", dmg=(8, 9), self_strength=(2, 2), next="GIMME"),
    }


class HauntedShip(_TableMonster):
    # HauntedShip.cs: HP 63 (A8 67). RammingSpeed(10/11 + Weak 1) / Swipe(13/14)
    # / Stomp(4/5 x?) random each odd round; Haunt(Dazed status) start. Modeled
    # as RammingSpeed -> Swipe -> Stomp loop (damage-relevant). Stomp single hit.
    MNAME = "Haunted Ship"
    HP, HP_A8 = 63, 67
    START = "RAMMING_SPEED"
    MOVES = {
        "RAMMING_SPEED": _Move("RAMMING_SPEED", dmg=(10, 11),
                               debuffs=(("weak", 1),), next="SWIPE"),
        "SWIPE": _Move("SWIPE", dmg=(13, 14), next="STOMP"),
        "STOMP": _Move("STOMP", dmg=(4, 5), next="RAMMING_SPEED"),
    }


class LivingFog(_TableMonster):
    # LivingFog.cs: HP 80 (A8 82). AdvancedGas(8/9 + Smoggy status) ->
    # Bloat(5/6 + summon) -> SuperGasBlast(8/9) -> Bloat loop. Starts AdvancedGas.
    MNAME = "Living Fog"
    HP, HP_A8 = 80, 82
    START = "ADVANCED_GAS"
    MOVES = {
        "ADVANCED_GAS": _Move("ADVANCED_GAS", dmg=(8, 9), next="BLOAT"),
        "BLOAT": _Move("BLOAT", dmg=(5, 6), next="SUPER_GAS_BLAST"),
        "SUPER_GAS_BLAST": _Move("SUPER_GAS_BLAST", dmg=(8, 9), next="BLOAT"),
    }


class PhantasmalGardener(_TableMonster):
    # PhantasmalGardener.cs (PhantasmalGardenersElite, 4 spawn): HP 26-31
    # (A8 27-32). Gains Skittish 6/7 at spawn (cosmetic). Bite(5) / Lash(7) /
    # Flail(1 x3) / Enlarge(+2/3 Str) cycle, starting move keyed by slot.
    MNAME = "Phantasmal Gardener"
    HP_MIN, HP_MAX, HP_MIN_A8, HP_MAX_A8 = 26, 31, 27, 32
    START = "FLAIL"  # overridden per-slot at spawn
    MOVES = {
        "BITE": _Move("BITE", dmg=(5, 5), next="LASH"),
        "LASH": _Move("LASH", dmg=(7, 7), next="FLAIL"),
        "FLAIL": _Move("FLAIL", dmg=(1, 1), hits=3, next="ENLARGE"),
        "ENLARGE": _Move("ENLARGE", self_strength=(2, 3), next="BITE"),
    }


class SkulkingColony(_TableMonster):
    # SkulkingColony.cs (SkulkingColonyElite solo): HP 70 (A8 75). Gains
    # HardenedShell 15 at spawn (a decaying damage-reduction power, not
    # modeled in the sim — omitted, like other unmodeled spawn buffs).
    # Smash(12/13) -> Zoom(14/16 + block 10/13) -> Inertia(9/11 + Str 2/3) ->
    # PiercingStabs(7/8 x2) loop. Starts at Smash.
    MNAME = "Skulking Colony"
    HP, HP_A8 = 70, 75
    START = "SMASH"
    MOVES = {
        "SMASH": _Move("SMASH", dmg=(12, 13), next="ZOOM"),
        "ZOOM": _Move("ZOOM", dmg=(14, 16), block=(10, 13), next="INERTIA"),
        "INERTIA": _Move("INERTIA", dmg=(9, 11), self_strength=(2, 3),
                         next="PIERCING_STABS"),
        "PIERCING_STABS": _Move("PIERCING_STABS", dmg=(7, 8), hits=2,
                                next="SMASH"),
    }


class TerrorEel(_TableMonster):
    # TerrorEel.cs (TerrorEelElite solo): HP 140 (A8 150). Crash(16/18) <->
    # Thrash(3/4 x? + Vigor 6 buff) loop. Stun/Terror (Vulnerable 99) branch is
    # situational; modeled as the Crash<->Thrash core. Thrash single hit.
    MNAME = "Terror Eel"
    HP, HP_A8 = 140, 150
    START = "CRASH"
    MOVES = {
        "CRASH": _Move("CRASH", dmg=(16, 18), next="THRASH"),
        "THRASH": _Move("THRASH", dmg=(3, 4), next="CRASH"),
    }


# ===========================================================================
# MULTI-MONSTER GROUP FACTORIES
# ===========================================================================

def spawn_corpse_slugs_normal(rng, ascension: int = 0) -> list[Monster]:
    """CorpseSlugsNormal: 3 Corpse Slugs (staggered starter moves)."""
    return _spawn_corpse_slugs(rng, ascension, 3)


def spawn_corpse_slugs_weak(rng, ascension: int = 0) -> list[Monster]:
    """CorpseSlugsWeak: 2 Corpse Slugs."""
    return _spawn_corpse_slugs(rng, ascension, 2)


def _spawn_corpse_slugs(rng, ascension: int, count: int) -> list[Monster]:
    # EnsureCorpseSlugsStartWithDifferentMoves: stagger the starting move
    # across WhipSlap/Glomp/Goop by consuming one Rng pick (NextInt(3)).
    starts = ["WHIP_SLAP", "GLOMP", "GOOP"]
    base = rng.next_int(0, 3)
    out: list[Monster] = []
    for i in range(count):
        m = CorpseSlug.spawn(rng, ascension=ascension)
        m.next_move = starts[(base + i) % 3]
        m.name = f"Corpse Slug ({i + 1})"
        out.append(m)
    return out


def spawn_cultists_normal(rng, ascension: int = 0) -> list[Monster]:
    """CultistsNormal: 1 Calcified + 1 Damp cultist. CultistsNormal.cs."""
    return [
        CalcifiedCultist.spawn(rng, ascension=ascension),
        DampCultist.spawn(rng, ascension=ascension),
    ]


def spawn_seapunk_normal(rng, ascension: int = 0) -> list[Monster]:
    """SeapunkNormal: 1 Calcified Cultist + 1 Seapunk. SeapunkNormal.cs."""
    return [
        CalcifiedCultist.spawn(rng, ascension=ascension),
        Seapunk.spawn(rng, ascension=ascension),
    ]


def spawn_toadpoles_weak(rng, ascension: int = 0) -> list[Monster]:
    """ToadpolesWeak: 2 Toadpoles (front starts at Spiken, back at Whirl)."""
    front = Toadpole.spawn(rng, ascension=ascension)
    front.next_move = "SPIKEN"
    front.name = "Toadpole (front)"
    back = Toadpole.spawn(rng, ascension=ascension)
    back.next_move = "WHIRL"
    back.name = "Toadpole (back)"
    return [front, back]


def spawn_two_tailed_rats_normal(rng, ascension: int = 0) -> list[Monster]:
    """TwoTailedRatsNormal: 3 rats with staggered starter moves (Scratch/
    DiseaseBite/Screech). TwoTailedRatsNormal.cs (StarterMoveIndex stagger)."""
    starts = ["SCRATCH", "DISEASE_BITE", "SCREECH"]
    base = rng.next_int(0, 3)
    out: list[Monster] = []
    for i in range(3):
        m = TwoTailedRat.spawn(rng, ascension=ascension)
        m.next_move = starts[(base + i) % 3]
        m.name = f"Two-Tailed Rat ({i + 1})"
        out.append(m)
    return out


def spawn_living_fog_normal(rng, ascension: int = 0) -> list[Monster]:
    """LivingFogNormal: solo Living Fog (GasBomb minions summoned mid-combat
    are not modeled). LivingFogNormal.cs."""
    return [LivingFog.spawn(rng, ascension=ascension)]


def spawn_phantasmal_gardeners_elite(rng, ascension: int = 0) -> list[Monster]:
    """PhantasmalGardenersElite: 4 Gardeners with slot-keyed starting moves
    (first=Flail, second=Bite, third=Lash, fourth=Enlarge)."""
    slot_starts = ["FLAIL", "BITE", "LASH", "ENLARGE"]
    out: list[Monster] = []
    for i in range(4):
        m = PhantasmalGardener.spawn(rng, ascension=ascension)
        m.next_move = slot_starts[i]
        m.name = f"Phantasmal Gardener ({i + 1})"
        out.append(m)
    return out


def spawn_slimes_normal(rng, ascension: int = 0) -> list[Monster]:
    """SlimesNormal: TwigSlimeM + LeafSlimeM + 2 small slimes (one Leaf, one
    Twig, order RNG'd). SlimesNormal.cs GenerateMonsters."""
    flag = _rng_random(rng) < 0.5
    small_a = LeafSlimeS if flag else TwigSlimeS
    small_b = TwigSlimeS if flag else LeafSlimeS
    return [
        TwigSlimeM.spawn(rng, ascension=ascension),
        LeafSlimeM.spawn(rng, ascension=ascension),
        small_a.spawn(rng, ascension=ascension),
        small_b.spawn(rng, ascension=ascension),
    ]


def spawn_slimes_weak(rng, ascension: int = 0) -> list[Monster]:
    """SlimesWeak: 2 distinct small slimes + 1 medium slime. SlimesWeak.cs."""
    smalls = [LeafSlimeS, TwigSlimeS]
    first = rng.choice(smalls)
    second = LeafSlimeS if first is TwigSlimeS else TwigSlimeS
    medium = rng.choice([LeafSlimeM, TwigSlimeM])
    return [
        first.spawn(rng, ascension=ascension),
        medium.spawn(rng, ascension=ascension),
        second.spawn(rng, ascension=ascension),
    ]


def spawn_inklets_normal(rng, ascension: int = 0) -> list[Monster]:
    """InkletsNormal: 3 Inklets (middle one uses the PiercingGaze branch).
    InkletsNormal.cs."""
    a = Inklet.spawn(rng, ascension=ascension)
    a.name = "Inklet (1)"
    mid = Inklet.spawn(rng, ascension=ascension)
    mid.name = "Inklet (Middle)"
    mid.next_move = "PIERCING_GAZE"
    b = Inklet.spawn(rng, ascension=ascension)
    b.name = "Inklet (3)"
    return [a, mid, b]


def spawn_ruby_raiders_normal(rng, ascension: int = 0) -> list[Monster]:
    """RubyRaidersNormal: 3 distinct raiders sampled without repeat (each has
    valid count 1). RubyRaidersNormal.cs."""
    raiders = [AxeRubyRaider, AssassinRubyRaider, BruteRubyRaider,
               CrossbowRubyRaider, TrackerRubyRaider]
    chosen = _rng_sample(rng, raiders, 3)
    return [c.spawn(rng, ascension=ascension) for c in chosen]


def spawn_chompers_normal(rng, ascension: int = 0) -> list[Monster]:
    """ChompersNormal: 2 Chompers. ChompersNormal.cs."""
    a = Chomper.spawn(rng, ascension=ascension)
    a.name = "Chomper (1)"
    b = Chomper.spawn(rng, ascension=ascension)
    b.name = "Chomper (2)"
    return [a, b]


def spawn_tunneler_normal(rng, ascension: int = 0) -> list[Monster]:
    """TunnelerNormal: 1 Chomper + 1 Tunneler. TunnelerNormal.cs."""
    return [Chomper.spawn(rng, ascension=ascension),
            Tunneler.spawn(rng, ascension=ascension)]


def spawn_exoskeletons_normal(rng, ascension: int = 0) -> list[Monster]:
    """ExoskeletonsNormal: 4 Exoskeletons. ExoskeletonsNormal.cs."""
    out = []
    for i in range(4):
        e = Exoskeleton.spawn(rng, ascension=ascension)
        e.name = f"Exoskeleton ({i + 1})"
        out.append(e)
    return out


def spawn_exoskeletons_weak(rng, ascension: int = 0) -> list[Monster]:
    """ExoskeletonsWeak: 3 Exoskeletons. ExoskeletonsWeak.cs."""
    out = []
    for i in range(3):
        e = Exoskeleton.spawn(rng, ascension=ascension)
        e.name = f"Exoskeleton ({i + 1})"
        out.append(e)
    return out


def spawn_bowlbugs_normal(rng, ascension: int = 0) -> list[Monster]:
    """BowlbugsNormal: 1 BowlbugRock + 2 of {Egg, Silk, Nectar}.
    BowlbugsNormal.cs."""
    bugs = [BowlbugEgg, BowlbugSilk, BowlbugNectar]
    picks = [rng.choice(bugs) for _ in range(2)]
    return [BowlbugRock.spawn(rng, ascension=ascension)] + \
           [p.spawn(rng, ascension=ascension) for p in picks]


def spawn_bowlbugs_weak(rng, ascension: int = 0) -> list[Monster]:
    """BowlbugsWeak: 1 BowlbugRock + 1 of {Egg, Nectar}. BowlbugsWeak.cs."""
    other = rng.choice([BowlbugEgg, BowlbugNectar])
    return [BowlbugRock.spawn(rng, ascension=ascension),
            other.spawn(rng, ascension=ascension)]


def spawn_axebots_normal(rng, ascension: int = 0) -> list[Monster]:
    """AxebotsNormal: 2 Axebots (front/back). AxebotsNormal.cs."""
    a = Axebot.spawn(rng, ascension=ascension)
    a.name = "Axebot (Front)"
    b = Axebot.spawn(rng, ascension=ascension)
    b.name = "Axebot (Back)"
    return [a, b]


def spawn_construct_menagerie_normal(rng, ascension: int = 0) -> list[Monster]:
    """ConstructMenagerieNormal: PunchConstruct + 2 CubexConstructs.
    ConstructMenagerieNormal.cs."""
    out = [PunchConstruct.spawn(rng, ascension=ascension)]
    for i in range(2):
        c = CubexConstruct.spawn(rng, ascension=ascension)
        c.name = f"Cubex Construct ({i + 1})"
        out.append(c)
    return out


def spawn_lost_and_forgotten_normal(rng, ascension: int = 0) -> list[Monster]:
    """TheLostAndForgottenNormal: TheLost + TheForgotten.
    TheLostAndForgottenNormal.cs."""
    return [TheLost.spawn(rng, ascension=ascension),
            TheForgotten.spawn(rng, ascension=ascension)]


def spawn_decimillipede_elite(rng, ascension: int = 0) -> list[Monster]:
    """DecimillipedeElite: 3 segments (front/middle/back) starting at staggered
    move indices. DecimillipedeElite.cs / DecimillipedeSegment.cs."""
    cycle = ["WRITHE", "CONSTRICT", "BULK"]
    out = []
    for i, label in enumerate(("Front", "Middle", "Back")):
        seg = DecimillipedeSegment.spawn(rng, ascension=ascension)
        seg.name = f"Decimillipede ({label})"
        seg.next_move = cycle[i % 3]  # StarterMoveIdx % 3
        out.append(seg)
    return out


def spawn_knights_elite(rng, ascension: int = 0) -> list[Monster]:
    """KnightsElite: FlailKnight + SpectralKnight + MagiKnight.
    KnightsElite.cs."""
    return [FlailKnight.spawn(rng, ascension=ascension),
            SpectralKnight.spawn(rng, ascension=ascension),
            MagiKnight.spawn(rng, ascension=ascension)]


def spawn_slithering_strangler_normal(rng, ascension: int = 0) -> list[Monster]:
    """SlitheringStranglerNormal: 1 Strangler + a secondary group (Jaxfruit /
    medium slime / 2 small slimes). SlitheringStranglerNormal.cs."""
    kind = rng.choice(["jaxfruit", "medium", "smalls"])
    extras: list[Monster] = []
    if kind == "jaxfruit":
        extras = [SnappingJaxfruit.spawn(rng, ascension=ascension)]
    elif kind == "medium":
        med = rng.choice([LeafSlimeM, TwigSlimeM])
        extras = [med.spawn(rng, ascension=ascension)]
    else:
        for _ in range(2):
            sm = rng.choice([LeafSlimeS, TwigSlimeS])
            extras.append(sm.spawn(rng, ascension=ascension))
    return extras + [SlitheringStrangler.spawn(rng, ascension=ascension)]


def spawn_snapping_jaxfruit_normal(rng, ascension: int = 0) -> list[Monster]:
    """SnappingJaxfruitNormal: 1 Jaxfruit + 1 Flyconid.
    SnappingJaxfruitNormal.cs."""
    return [SnappingJaxfruit.spawn(rng, ascension=ascension),
            Flyconid.spawn(rng, ascension=ascension)]


def spawn_flyconid_normal(rng, ascension: int = 0) -> list[Monster]:
    """FlyconidNormal: 1 medium slime + 1 Flyconid. FlyconidNormal.cs."""
    med = rng.choice([LeafSlimeM, TwigSlimeM])
    return [med.spawn(rng, ascension=ascension),
            Flyconid.spawn(rng, ascension=ascension)]


def _spawn_scrolls(rng, ascension: int, n: int) -> list[Monster]:
    """n Scrolls of Biting at staggered starting moves (CHOMP / CHEW /
    MORE_TEETH cycle the StarterMoveIdx)."""
    starts = ["CHOMP", "CHEW", "MORE_TEETH"]
    out = []
    for i in range(n):
        s = ScrollOfBiting.spawn(rng, ascension=ascension)
        s.name = f"Scroll of Biting ({i + 1})"
        s.next_move = starts[i % 3]
        out.append(s)
    return out


def spawn_scrolls_normal(rng, ascension: int = 0) -> list[Monster]:
    """ScrollsOfBitingNormal: 4 Scrolls of Biting. ScrollsOfBitingNormal.cs."""
    return _spawn_scrolls(rng, ascension, 4)


def spawn_scrolls_weak(rng, ascension: int = 0) -> list[Monster]:
    """ScrollsOfBitingWeak: 3 Scrolls of Biting. ScrollsOfBitingWeak.cs."""
    return _spawn_scrolls(rng, ascension, 3)


# ===========================================================================
# PHASE 8B.4 — remaining played-path fallbacks (Fogmog / PhrogParasite /
# TurretOperator) + their companion/illusion sub-entities.
# Cites:
#   Monsters/Fogmog.cs, Monsters/EyeWithTeeth.cs, Encounters/FogmogNormal.cs
#   Monsters/PhrogParasite.cs, Monsters/Wriggler.cs, Powers/InfestedPower.cs
#   Monsters/TurretOperator.cs, Monsters/LivingShield.cs, Powers/RampartPower.cs
# ===========================================================================


# --- EyeWithTeeth (Fogmog's summoned illusion) ----------------------------
# EyeWithTeeth.cs: flat 6 HP. Gains IllusionPower at spawn. Single repeating
# DISTRACT_MOVE: adds 3 Dazed status cards to the player's discard each turn
# (StatusIntent(3), CardPileCmd.AddToCombatAndPreview<Dazed>). Deals no damage.

class EyeWithTeethMove(str, Enum):
    DISTRACT = "distract"  # 3 Dazed -> discard


@dataclass
class EyeWithTeeth(Monster):
    next_move: EyeWithTeethMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "EyeWithTeeth":
        m = cls(name="Eye With Teeth", hp=6, max_hp=6, ascension=ascension)
        m.add_or_stack_power(make_power("illusion", 1, m))
        m.next_move = EyeWithTeethMove.DISTRACT
        return m

    def roll_next_move(self, rng: random.Random) -> EyeWithTeethMove:
        return EyeWithTeethMove.DISTRACT  # FollowUpState = itself

    def intent_damage(self) -> int:
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        event = {"move": EyeWithTeethMove.DISTRACT, "damage": 0,
                 "blocked": 0, "hp_loss": 0}
        _queue_status(self, DAZED_CARD, "discard", 3)
        self.next_move = EyeWithTeethMove.DISTRACT
        return event


# --- Fogmog (FogmogNormal, summons EyeWithTeeth illusions) -----------------
# Fogmog.cs: MinHp==MaxHp == 74 (A8 78). Swipe 8 (A9 9) + self Strength 1.
# Headbutt 14 (A9 16). State machine (Fogmog.cs:33-53):
#   ILLUSION_MOVE (summon EyeWithTeeth) -> SWIPE_MOVE
#   SWIPE_MOVE -> BRANCH(0.4 SWIPE_RANDOM cannot-repeat, 0.6 HEADBUTT
#                        cannot-repeat)
#   SWIPE_RANDOM -> HEADBUTT
#   HEADBUTT -> SWIPE_MOVE
# Both SWIPE_MOVE and SWIPE_RANDOM are the same SwipeMove (dmg + Strength 1).

class FogmogMove(str, Enum):
    ILLUSION = "illusion"
    SWIPE = "swipe"
    SWIPE_RANDOM = "swipe_random"
    HEADBUTT = "headbutt"


FOGMOG_HP = 74
FOGMOG_HP_A8 = 78


@dataclass
class Fogmog(Monster):
    last_move: FogmogMove | None = None
    next_move: FogmogMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "Fogmog":
        hp = _a8(ascension, FOGMOG_HP, FOGMOG_HP_A8)
        m = cls(name="Fogmog", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = FogmogMove.ILLUSION  # MoveStateMachine start
        return m

    def roll_next_move(self, rng: random.Random) -> FogmogMove:
        last = self.last_move
        if last is FogmogMove.ILLUSION:
            return FogmogMove.SWIPE
        if last is FogmogMove.SWIPE:
            # RandomBranchState: 0.4 SWIPE_RANDOM, 0.6 HEADBUTT (CannotRepeat).
            names = [FogmogMove.SWIPE_RANDOM, FogmogMove.HEADBUTT]
            weights = [0.4, 0.6]
            pool = [(n, w) for n, w in zip(names, weights) if n != last]
            return _rng_choices(rng, [n for n, _ in pool], [w for _, w in pool])
        if last is FogmogMove.SWIPE_RANDOM:
            return FogmogMove.HEADBUTT
        if last is FogmogMove.HEADBUTT:
            return FogmogMove.SWIPE
        return FogmogMove.SWIPE

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move in (FogmogMove.SWIPE, FogmogMove.SWIPE_RANDOM):
            return _a9(self.ascension, 8, 9) + str_amt
        if self.next_move is FogmogMove.HEADBUTT:
            return _a9(self.ascension, 14, 16) + str_amt
        # ILLUSION is a summon, no damage.
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}

        if move is FogmogMove.ILLUSION:
            # Summon one EyeWithTeeth illusion. Queued on pending_spawns; the
            # combat engine drains it into the live monster list after the turn.
            eye = EyeWithTeeth.spawn(rng, ascension=self.ascension)
            pending = getattr(self, "pending_spawns", None)
            if pending is None:
                pending = []
                self.pending_spawns = pending  # type: ignore[attr-defined]
            pending.append(eye)
        elif move in (FogmogMove.SWIPE, FogmogMove.SWIPE_RANDOM):
            dmg = _a9(self.ascension, 8, 9)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            strength = StrengthPower(amount=1)
            strength._owner = self
            self.add_or_stack_power(strength)
        elif move is FogmogMove.HEADBUTT:
            dmg = _a9(self.ascension, 14, 16)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)

        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


def spawn_fogmog_normal(rng, ascension: int = 0) -> list[Monster]:
    """FogmogNormal: solo Fogmog. The EyeWithTeeth illusions are summoned
    mid-combat by the Fogmog's ILLUSION_MOVE (FogmogNormal.cs GenerateMonsters
    returns only the Fogmog; the illusion slot is filled during combat)."""
    return [Fogmog.spawn(rng, ascension=ascension)]


# --- Wriggler (spawned by PhrogParasite's InfestedPower on death) ----------
# Wriggler.cs: HP 17-21 (A8 18-22). Bite 6 (A9 7). Wriggle: 1 Infection ->
# discard + self Strength 2. When spawned via InfestedPower it StartStunned:
# a one-time no-op SPAWNED_MOVE (StunIntent), then a slot-keyed INIT branch.
# Odd slots (wriggler1/3) open on Bite; even slots (wriggler2/4) on Wriggle.
# After that the two moves alternate (Bite <-> Wriggle).

class WrigglerMove(str, Enum):
    SPAWNED = "spawned"  # stunned no-op (first turn after death-spawn)
    BITE = "bite"
    WRIGGLE = "wriggle"


WRIGGLER_HP_MIN, WRIGGLER_HP_MAX = 17, 21
WRIGGLER_HP_MIN_A8, WRIGGLER_HP_MAX_A8 = 18, 22


@dataclass
class Wriggler(Monster):
    last_move: str | None = None
    next_move: str | None = None
    ascension: int = 0
    _slot_kind: str = "bite"  # "bite" (odd slots) or "wriggle" (even slots)

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "Wriggler":
        lo = _a8(ascension, WRIGGLER_HP_MIN, WRIGGLER_HP_MIN_A8)
        hi = _a8(ascension, WRIGGLER_HP_MAX, WRIGGLER_HP_MAX_A8)
        hp = rng.randint(lo, hi)
        m = cls(name="Wriggler", hp=hp, max_hp=hp, ascension=ascension)
        # Default (non-stunned) start = its slot-keyed INIT move.
        m.next_move = WrigglerMove.BITE
        return m

    def _init_move(self) -> str:
        return WrigglerMove.BITE if self._slot_kind == "bite" else WrigglerMove.WRIGGLE

    def roll_next_move(self, rng: random.Random) -> str:
        last = self.last_move
        if last == WrigglerMove.SPAWNED:
            return self._init_move()  # FollowUp = INIT branch (slot-keyed)
        if last == WrigglerMove.BITE:
            return WrigglerMove.WRIGGLE
        if last == WrigglerMove.WRIGGLE:
            return WrigglerMove.BITE
        return self._init_move()

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move == WrigglerMove.BITE:
            return _a9(self.ascension, 6, 7) + str_amt
        return 0  # SPAWNED (stun) and WRIGGLE deal no damage.

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move == WrigglerMove.SPAWNED:
            pass  # stunned: no-op
        elif move == WrigglerMove.BITE:
            dmg = _a9(self.ascension, 6, 7)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
        elif move == WrigglerMove.WRIGGLE:
            _queue_status(self, INFECTION_CARD, "discard", 1)
            strength = StrengthPower(amount=2)
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- PhrogParasite (PhrogParasiteElite, solo; spawns 4 Wrigglers on death) -
# PhrogParasite.cs: HP 61-64 (A8 66-68). Lash 4 (A9 5) x4. Infect: 3 Infection
# status cards -> discard (StatusIntent(3)). Gains InfestedPower 4 at spawn
# (AfterAddedToRoom) which spawns 4 stunned Wrigglers when the Phrog dies.
# State machine (PhrogParasite.cs:39-53): start INFECT_MOVE; INFECT <-> LASH
# deterministic FollowUp (the RandomBranchState is unreachable from the start
# chain — the wired FollowUps form a simple INFECT <-> LASH alternation).

class PhrogMove(str, Enum):
    INFECT = "infect"  # 3 Infection -> discard
    LASH = "lash"      # 4 (A9 5) x4


PHROG_HP_MIN, PHROG_HP_MAX = 61, 64
PHROG_HP_MIN_A8, PHROG_HP_MAX_A8 = 66, 68


@dataclass
class PhrogParasite(Monster):
    last_move: PhrogMove | None = None
    next_move: PhrogMove | None = None
    ascension: int = 0

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "PhrogParasite":
        lo = _a8(ascension, PHROG_HP_MIN, PHROG_HP_MIN_A8)
        hi = _a8(ascension, PHROG_HP_MAX, PHROG_HP_MAX_A8)
        hp = rng.randint(lo, hi)
        m = cls(name="Phrog Parasite", hp=hp, max_hp=hp, ascension=ascension)
        # AfterAddedToRoom: InfestedPower 4 (-> 4 Wrigglers on death).
        m.add_or_stack_power(make_power("infested", 4, m))
        m.next_move = PhrogMove.INFECT  # MoveStateMachine start
        return m

    def roll_next_move(self, rng: random.Random) -> PhrogMove:
        # INFECT <-> LASH alternation (FollowUpState wiring).
        if self.last_move is PhrogMove.INFECT:
            return PhrogMove.LASH
        return PhrogMove.INFECT

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is PhrogMove.LASH:
            return (_a9(self.ascension, 4, 5) + str_amt) * 4
        return 0  # INFECT is a status-card add, no damage.

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is PhrogMove.LASH:
            per = _a9(self.ascension, 4, 5)
            for _ in range(4):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is PhrogMove.INFECT:
            _queue_status(self, INFECTION_CARD, "discard", 3)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- LivingShield (guards the TurretOperator in TurretOperatorWeak) --------
# LivingShield.cs: HP 55 (A8 65). Gains RampartPower 25 at spawn (re-armors its
# Turret Operator ally 25 Block at the start of every player turn). ShieldSlam
# 6 while it still has allies; once alone, switches to Smash 18 (A9 16... note:
# the .cs base is 16, A9 18) + self Strength 3, repeating Smash thereafter.

class LivingShieldMove(str, Enum):
    SHIELD_SLAM = "shield_slam"  # 6 dmg (allies alive)
    SMASH = "smash"              # 16 (A9 18) + Strength 3 (alone)


LIVING_SHIELD_HP = 55
LIVING_SHIELD_HP_A8 = 65


@dataclass
class LivingShield(Monster):
    last_move: LivingShieldMove | None = None
    next_move: LivingShieldMove | None = None
    ascension: int = 0
    # Set by the spawn factory so GetAllyCount can be evaluated in-combat: the
    # combat engine is the source of truth, but for standalone tests we fall
    # back to this flag (True while the Turret Operator is presumed alive).
    _combat: object = None

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "LivingShield":
        hp = _a8(ascension, LIVING_SHIELD_HP, LIVING_SHIELD_HP_A8)
        m = cls(name="Living Shield", hp=hp, max_hp=hp, ascension=ascension)
        # AfterAddedToRoom: RampartPower 25 (block to the Turret Operator each
        # player turn). The combat engine fires RampartPower.on_player_turn_start.
        m.add_or_stack_power(make_power("rampart", 25, m))
        m.next_move = LivingShieldMove.SHIELD_SLAM  # start
        return m

    def _has_allies(self) -> bool:
        cs = getattr(self, "_combat", None)
        if cs is None:
            return False  # standalone: behave as if alone (Smash branch)
        return any(m is not self and m.alive for m in cs.alive_monsters())

    def roll_next_move(self, rng: random.Random) -> LivingShieldMove:
        # ConditionalBranchState after ShieldSlam: ShieldSlam while allies > 0,
        # else Smash (and Smash self-loops forever once alone).
        if self.last_move is LivingShieldMove.SMASH:
            return LivingShieldMove.SMASH
        if self._has_allies():
            return LivingShieldMove.SHIELD_SLAM
        return LivingShieldMove.SMASH

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move is LivingShieldMove.SHIELD_SLAM:
            return 6 + str_amt
        if self.next_move is LivingShieldMove.SMASH:
            return _a9(self.ascension, 16, 18) + str_amt
        return 0

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move is LivingShieldMove.SHIELD_SLAM:
            blocked, hp_loss = deal_damage(6, self, player)
            event.update(damage=6, blocked=blocked, hp_loss=hp_loss)
        elif move is LivingShieldMove.SMASH:
            dmg = _a9(self.ascension, 16, 18)
            blocked, hp_loss = deal_damage(dmg, self, player)
            event.update(damage=dmg, blocked=blocked, hp_loss=hp_loss)
            strength = StrengthPower(amount=3)
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


# --- TurretOperator (TurretOperatorWeak, guarded by the Living Shield) -----
# TurretOperator.cs: MinHp==MaxHp == 41 (A8 51). Fire 3 (A9 4) x5. State
# machine: UNLOAD_1 -> UNLOAD_2 -> RELOAD(+1 Strength) -> UNLOAD_1 (loop).
# Flagged is_turret_operator so RampartPower (on the Living Shield) grants it
# Block at each player turn start.

class TurretMove(str, Enum):
    UNLOAD_1 = "unload_1"
    UNLOAD_2 = "unload_2"
    RELOAD = "reload"


TURRET_HP = 41
TURRET_HP_A8 = 51


@dataclass
class TurretOperator(Monster):
    last_move: TurretMove | None = None
    next_move: TurretMove | None = None
    ascension: int = 0
    is_turret_operator: bool = True  # RampartPower targets this flag

    @classmethod
    def spawn(cls, rng: random.Random, ascension: int = 0) -> "TurretOperator":
        hp = _a8(ascension, TURRET_HP, TURRET_HP_A8)
        m = cls(name="Turret Operator", hp=hp, max_hp=hp, ascension=ascension)
        m.next_move = TurretMove.UNLOAD_1  # start
        return m

    _CYCLE_NEXT = {
        TurretMove.UNLOAD_1: TurretMove.UNLOAD_2,
        TurretMove.UNLOAD_2: TurretMove.RELOAD,
        TurretMove.RELOAD: TurretMove.UNLOAD_1,
    }

    def roll_next_move(self, rng: random.Random) -> TurretMove:
        if self.last_move is None:
            return TurretMove.UNLOAD_1
        return self._CYCLE_NEXT[self.last_move]

    def intent_damage(self) -> int:
        if self.next_move is None:
            return 0
        str_amt = self.get_power("strength").amount if self.get_power("strength") else 0
        if self.next_move in (TurretMove.UNLOAD_1, TurretMove.UNLOAD_2):
            return (_a9(self.ascension, 3, 4) + str_amt) * 5
        return 0  # RELOAD is a self-buff (Strength), no damage.

    def take_turn(self, rng: random.Random, player: Creature) -> dict:
        move = self.next_move or self.roll_next_move(rng)
        event = {"move": move, "damage": 0, "blocked": 0, "hp_loss": 0}
        if move in (TurretMove.UNLOAD_1, TurretMove.UNLOAD_2):
            per = _a9(self.ascension, 3, 4)
            for _ in range(5):
                blocked, hp_loss = deal_damage(per, self, player)
                event["damage"] += per
                event["blocked"] += blocked
                event["hp_loss"] += hp_loss
        elif move is TurretMove.RELOAD:
            strength = StrengthPower(amount=1)
            strength._owner = self
            self.add_or_stack_power(strength)
        self.last_move = move
        self.next_move = self.roll_next_move(rng)
        return event


def spawn_phrog_parasite_elite(rng, ascension: int = 0) -> list[Monster]:
    """PhrogParasiteElite: solo Phrog Parasite. Its 4 Wrigglers are NOT present
    at the start — they are spawned by InfestedPower when the Phrog dies
    (PhrogParasiteElite.cs GenerateMonsters returns only the phrog)."""
    return [PhrogParasite.spawn(rng, ascension=ascension)]


def spawn_turret_operator_weak(rng, ascension: int = 0) -> list[Monster]:
    """TurretOperatorWeak: 1 Living Shield (front) + 1 Turret Operator
    (TurretOperatorWeak.cs GenerateMonsters). The shield guards the turret,
    granting it 25 Block each player turn (RampartPower) and tanking until it
    dies, at which point it switches to its Smash attack."""
    shield = LivingShield.spawn(rng, ascension=ascension)
    turret = TurretOperator.spawn(rng, ascension=ascension)
    return [shield, turret]
