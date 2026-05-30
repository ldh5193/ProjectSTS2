"""Ironclad cards — starting deck (notes/05_mvp_combat_spec.md §C.2) plus
a small library of common/uncommon cards porting verbatim from the
decompile (`decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs`).

Only cards expressible in the current dsl.py are included; anything
that needs new EffectOps (draw, exhaust, conditional triggers,
all-enemy targeting on >1 enemy) is left for a follow-up.
"""
from __future__ import annotations

from .dsl import CardDef, CardType, Effect, EffectOp, Scaling, ScalingKind, Target

STRIKE_SCALING = (
    Scaling(ScalingKind.STRENGTH_ADDITIVE, owner="dealer"),
    Scaling(ScalingKind.WEAK_MULTIPLICATIVE, owner="dealer"),
    Scaling(ScalingKind.VULNERABLE_MULTIPLICATIVE, owner="target"),
)

STRIKE_IRONCLAD = CardDef(
    id="strike_ironclad",
    name="Strike",
    cost=1,
    type=CardType.ATTACK,
    count=5,
    effects=(
        Effect(
            op=EffectOp.DEAL_DAMAGE,
            target=Target.SELECTED_ENEMY,
            amount=6,
            scaling=STRIKE_SCALING,
        ),
    ),
)

DEFEND_IRONCLAD = CardDef(
    id="defend_ironclad",
    name="Defend",
    cost=1,
    type=CardType.SKILL,
    count=4,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
    ),
)

BASH = CardDef(
    id="bash",
    name="Bash",
    cost=2,
    type=CardType.ATTACK,
    count=1,
    effects=(
        Effect(
            op=EffectOp.DEAL_DAMAGE,
            target=Target.SELECTED_ENEMY,
            amount=8,
            scaling=STRIKE_SCALING,
        ),
        Effect(
            op=EffectOp.APPLY_POWER,
            target=Target.SELECTED_ENEMY,
            power_id="vulnerable",
            amount=2,
        ),
    ),
)

IRONCLAD_STARTING_DECK = (STRIKE_IRONCLAD, DEFEND_IRONCLAD, BASH)


# --- Additional Ironclad cards (not in starting deck) ---------------------
# Cites:
#   decompiled/MegaCrit.Sts2.Core.Models.Cards/IronWave.cs
#   decompiled/MegaCrit.Sts2.Core.Models.Cards/Inflame.cs


IRON_WAVE = CardDef(
    id="iron_wave",
    name="Iron Wave",
    cost=1,
    type=CardType.ATTACK,
    count=0,
    effects=(
        # Block-then-damage order matches the OnPlay sequence in the decompile
        # (GainBlock, then Attack).
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),
        Effect(
            op=EffectOp.DEAL_DAMAGE,
            target=Target.SELECTED_ENEMY,
            amount=5,
            scaling=STRIKE_SCALING,
        ),
    ),
)

INFLAME = CardDef(
    id="inflame",
    name="Inflame",
    cost=1,
    type=CardType.POWER,
    count=0,
    effects=(
        Effect(
            op=EffectOp.APPLY_POWER,
            target=Target.SELF,
            power_id="strength",
            amount=2,
        ),
    ),
)

# --- Cycle B: real OnPlay effects for Common SIMPLE cards (notes/14 §IV) ---

POMMEL_STRIKE = CardDef(
    id="pommel_strike", name="Pommel Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=9, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1),
    ),
)

SHRUG_IT_OFF = CardDef(
    id="shrug_it_off", name="Shrug It Off", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=8),
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=1),
    ),
)

THUNDERCLAP = CardDef(
    id="thunderclap", name="Thunderclap", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
               amount=4, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.ALL_ENEMIES,
               power_id="vulnerable", amount=1),
    ),
)

TREMBLE = CardDef(
    id="tremble", name="Tremble", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=3),
        Effect(op=EffectOp.EXHAUST_SELF, target=Target.SELF),
    ),
)

TWIN_STRIKE = CardDef(
    id="twin_strike", name="Twin Strike", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=5, scaling=STRIKE_SCALING, hit_count=2),
    ),
)

BLOODLETTING = CardDef(
    id="bloodletting", name="Bloodletting", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.SELF_HP_LOSE, target=Target.SELF, amount=3),
        Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=2),
    ),
)

ANGER = CardDef(
    id="anger", name="Anger", cost=0, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=6, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.COPY_TO_DISCARD, target=Target.SELF),
    ),
)

CINDER = CardDef(
    id="cinder", name="Cinder", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=18, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.EXHAUST_RANDOM, target=Target.SELF),
    ),
)

INFLAME_HIGH = INFLAME  # alias for callers


# Additional Cycle B cards — depend only on existing Powers / EffectOps.

BLUDGEON = CardDef(
    id="bludgeon", name="Bludgeon", cost=3, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=32, scaling=STRIKE_SCALING),
    ),
)

CLOTHESLINE = CardDef(  # represents "Headbutt"-shaped 12-dmg + weak combo if it existed
    id="clothesline", name="Clothesline", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=12, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="weak", amount=2),
    ),
)

UPPERCUT = CardDef(
    id="uppercut", name="Uppercut", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=13, scaling=STRIKE_SCALING),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="weak", amount=1),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=1),
    ),
)

TAUNT = CardDef(
    id="taunt", name="Taunt", cost=1, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=7),
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELECTED_ENEMY,
               power_id="vulnerable", amount=1),
    ),
)

STONE_ARMOR = CardDef(
    id="stone_armor", name="Stone Armor", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="plating", amount=4),
    ),
)

RAGE = CardDef(  # simplified: +3 strength (real Rage applies RagePower)
    id="rage", name="Rage", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="strength", amount=3),
    ),
)

BATTLE_TRANCE = CardDef(
    id="battle_trance", name="Battle Trance", cost=0, type=CardType.SKILL, count=0,
    effects=(
        Effect(op=EffectOp.DRAW_CARD, target=Target.SELF, amount=3),
        # NoDraw power deferred — skip for now (still draws 3 unconditionally).
    ),
)

HEADBUTT = CardDef(
    id="headbutt", name="Headbutt", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=9, scaling=STRIKE_SCALING),
        # "move card from discard to draw top" — needs new EffectOp; skip second effect.
    ),
)

DISMANTLE = CardDef(
    id="dismantle", name="Dismantle", cost=1, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=8, scaling=STRIKE_SCALING, hit_count=2),
    ),
)

PERFECTED_STRIKE = CardDef(
    id="perfected_strike", name="Perfected Strike", cost=2, type=CardType.ATTACK, count=0,
    effects=(
        Effect(op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
               amount=6, scaling=STRIKE_SCALING + (
                   __import__("sim.dsl", fromlist=["Scaling", "ScalingKind"]).Scaling(
                       kind=__import__("sim.dsl", fromlist=["ScalingKind"]).ScalingKind.STRIKE_TAG_COUNT,
                       owner="dealer"),
               )),
    ),
)


# --- Engine "deck-power" cards (Phase 7B) ---------------------------------
# Costs/amounts verified against decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs.
# Metallicize / Combust / Berserk / Brutality have no STS2 card model (STS2
# uses Furnace instead of Metallicize); they use faithful STS1 numbers.

DEMON_FORM = CardDef(
    id="demon_form", name="Demon Form", cost=3, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="demon_form", amount=2),  # DemonForm.cs: Strength 2/turn
    ),
)

METALLICIZE = CardDef(
    id="metallicize", name="Metallicize", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="metallicize", amount=3),  # STS1: 3 block/turn end
    ),
)

FEEL_NO_PAIN = CardDef(
    id="feel_no_pain", name="Feel No Pain", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="feel_no_pain", amount=3),  # FeelNoPain.cs: Power 3
    ),
)

DARK_EMBRACE = CardDef(
    id="dark_embrace", name="Dark Embrace", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="dark_embrace", amount=1),  # DarkEmbrace.cs: draw 1/exhaust
    ),
)

JUGGERNAUT = CardDef(
    id="juggernaut", name="Juggernaut", cost=2, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="juggernaut", amount=5),  # Juggernaut.cs: 5 dmg/block gain
    ),
)

RUPTURE = CardDef(
    id="rupture", name="Rupture", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="rupture", amount=1),  # Rupture.cs: Strength 1 per card HP-loss
    ),
)

COMBUST = CardDef(
    id="combust", name="Combust", cost=1, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="combust", amount=5),  # STS1: lose 1 HP, 5 AoE dmg/turn end
    ),
)

BARRICADE = CardDef(
    id="barricade", name="Barricade", cost=3, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="barricade", amount=1),  # Barricade.cs: block persists
    ),
)

BERSERK = CardDef(
    id="berserk", name="Berserk", cost=0, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="berserk", amount=1),  # STS1: +1 energy/turn (self-Vuln omitted)
    ),
)

BRUTALITY = CardDef(
    id="brutality", name="Brutality", cost=0, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="brutality", amount=1),  # STS1: lose 1 HP, draw 1/turn
    ),
)

CORRUPTION = CardDef(
    id="corruption", name="Corruption", cost=3, type=CardType.POWER, count=0,
    effects=(
        Effect(op=EffectOp.APPLY_POWER, target=Target.SELF,
               power_id="corruption", amount=1),  # Corruption.cs: skills cost 0, exhaust
    ),
)

ENGINE_POWER_CARDS = (DEMON_FORM, METALLICIZE, FEEL_NO_PAIN, DARK_EMBRACE,
                      JUGGERNAUT, RUPTURE, COMBUST, BARRICADE, BERSERK,
                      BRUTALITY, CORRUPTION)


IRONCLAD_LIBRARY_EXT = (BLUDGEON, CLOTHESLINE, UPPERCUT, TAUNT, STONE_ARMOR, RAGE,
                        BATTLE_TRANCE, HEADBUTT, DISMANTLE, PERFECTED_STRIKE)


# Catalog of every CardDef this module knows about. Keep in sync with the
# additions above so consumers (env builders, future card-reward systems)
# can enumerate without re-importing each constant.
IRONCLAD_LIBRARY: tuple[CardDef, ...] = (
    STRIKE_IRONCLAD,
    DEFEND_IRONCLAD,
    BASH,
    IRON_WAVE,
    INFLAME,
    POMMEL_STRIKE,
    SHRUG_IT_OFF,
    THUNDERCLAP,
    TREMBLE,
    TWIN_STRIKE,
    BLOODLETTING,
    ANGER,
    CINDER,
    # Cycle B extras
    BLUDGEON, UPPERCUT, TAUNT, STONE_ARMOR, RAGE, BATTLE_TRANCE,
    HEADBUTT, DISMANTLE, PERFECTED_STRIKE,
    # Phase 7B engine power cards
    DEMON_FORM, METALLICIZE, FEEL_NO_PAIN, DARK_EMBRACE, JUGGERNAUT,
    RUPTURE, COMBUST, BARRICADE, BERSERK, BRUTALITY, CORRUPTION,
)


def build_starting_deck() -> list[CardDef]:
    deck: list[CardDef] = []
    for c in IRONCLAD_STARTING_DECK:
        deck.extend([c] * c.count)
    return deck


# ===========================================================================
# Card upgrade system (Phase 7B) — real stat changes per decompiled Upgrade().
# ===========================================================================
#
# Ground truth: decompiled/MegaCrit.Sts2.Core.Models.Cards/<Card>.cs OnUpgrade().
# Each upgrade is expressed as a tuple of mutation primitives applied to the
# base CardDef's effects/cost. The result is tagged id+"+" / name+"+" so
# card_features() and the "+"-stripping rarity lookup keep working.
#
# Mutation primitives (all operate on a fresh copy of the effects list):
#   ("dmg", n)            -> +n to every DEAL_DAMAGE effect's amount (per hit)
#   ("block", n)          -> +n to every GAIN_BLOCK effect's amount
#   ("power", pid, n)     -> +n to APPLY_POWER effects whose power_id == pid
#   ("any_power", n)      -> +n to every APPLY_POWER effect's amount
#   ("draw", n)           -> +n to every DRAW_CARD effect's amount
#   ("cost", n)           -> add n to cost (n negative reduces cost; floored 0)
#
# Decompiled-verified per-card deltas (base -> upgraded shown for clarity):
#   strike_ironclad : dmg+3   (6 -> 9)
#   defend_ironclad : block+3 (5 -> 8)
#   bash            : dmg+2, vulnerable+1   (8/2 -> 10/3)
#   iron_wave       : dmg+2, block+2        (5/5 -> 7/7)
#   inflame         : strength+1            (2 -> 3)
#   pommel_strike   : dmg+1, draw+1         (9/draw1 -> 10/draw2)
#   shrug_it_off    : block+3               (8 -> 11)
#   thunderclap     : dmg+3                 (4 -> 7)
#   tremble         : vulnerable+1          (3 -> 4)
#   twin_strike     : dmg+2 per hit         (5x2 -> 7x2)
#   bloodletting    : energy+1 (energy_gain amount)  (2 -> 3)
#   anger           : dmg+2                 (6 -> 8)
#   cinder          : dmg+6                 (18 -> 24)
#   bludgeon        : dmg+10                (32 -> 42)
#   uppercut        : weak+1, vulnerable+1  (1/1 -> 2/2)
#   taunt           : block+1, vulnerable+1 (7/1 -> 8/2)
#   stone_armor     : plating+2             (4 -> 6)
#   rage            : strength+2            (3 -> 5)
#   battle_trance   : draw+1                (3 -> 4)
#   headbutt        : dmg+3                 (9 -> 12)
#   dismantle       : dmg+2 per hit         (8x2 -> 10x2)
#   perfected_strike: base dmg+1 (ExtraDamage per-Strike not modeled; +1 to base)
#   demon_form      : strength/turn +1      (2 -> 3)
#   metallicize     : block/turn +1 (STS1 3 -> 4)
#   feel_no_pain    : amount+1              (3 -> 4)
#   dark_embrace    : cost-1                (2 -> 1)
#   juggernaut      : amount+2              (5 -> 7)
#   rupture         : amount+1              (1 -> 2)
#   combust         : amount+2 (STS1 5 -> 7)
#   barricade       : cost-1                (3 -> 2)
#   berserk         : amount unchanged; cost-0 already (STS1 reduces self-vuln) -> no stat delta
#   brutality       : amount unchanged (STS1 upgrade = innate) -> no stat delta
#   corruption      : cost-1                (3 -> 2)

_UPGRADE_DELTAS: dict[str, tuple[tuple, ...]] = {
    "strike_ironclad": (("dmg", 3),),
    "defend_ironclad": (("block", 3),),
    "bash": (("dmg", 2), ("power", "vulnerable", 1)),
    "iron_wave": (("dmg", 2), ("block", 2)),
    "inflame": (("power", "strength", 1),),
    "pommel_strike": (("dmg", 1), ("draw", 1)),
    "shrug_it_off": (("block", 3),),
    "thunderclap": (("dmg", 3),),
    "tremble": (("power", "vulnerable", 1),),
    "twin_strike": (("dmg", 2),),
    "bloodletting": (("energy", 1),),
    "anger": (("dmg", 2),),
    "cinder": (("dmg", 6),),
    "bludgeon": (("dmg", 10),),
    "clothesline": (("dmg", 2), ("power", "weak", 1)),  # TODO: no STS2 model
    "uppercut": (("power", "weak", 1), ("power", "vulnerable", 1)),
    "taunt": (("block", 1), ("power", "vulnerable", 1)),
    "stone_armor": (("power", "plating", 2),),
    "rage": (("power", "strength", 2),),
    "battle_trance": (("draw", 1),),
    "headbutt": (("dmg", 3),),
    "dismantle": (("dmg", 2),),
    "perfected_strike": (("dmg", 1),),
    "demon_form": (("power", "demon_form", 1),),
    "metallicize": (("power", "metallicize", 1),),  # STS1 3 -> 4
    "feel_no_pain": (("power", "feel_no_pain", 1),),
    "dark_embrace": (("cost", -1),),
    "juggernaut": (("power", "juggernaut", 2),),
    "rupture": (("power", "rupture", 1),),
    "combust": (("power", "combust", 2),),  # STS1 5 -> 7
    "barricade": (("cost", -1),),
    "berserk": (),    # STS1 upgrade only reduces self-Vulnerable (not modeled)
    "brutality": (),  # STS1 upgrade makes it Innate; no stat delta
    "corruption": (("cost", -1),),
}

# Default deltas for any implemented card not in the table above:
# attacks +3 damage, blocks +3 block. TODO: replace with the card's real
# OnUpgrade() values once that card's effect is ported.
_DEFAULT_ATTACK_DELTA: tuple[tuple, ...] = (("dmg", 3),)
_DEFAULT_BLOCK_DELTA: tuple[tuple, ...] = (("block", 3),)


def _apply_delta(effects: tuple[Effect, ...], delta: tuple) -> tuple[Effect, ...]:
    from dataclasses import replace as _replace
    kind = delta[0]
    out: list[Effect] = []
    for eff in effects:
        new_eff = eff
        if kind == "dmg" and eff.op is EffectOp.DEAL_DAMAGE:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "block" and eff.op is EffectOp.GAIN_BLOCK:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "draw" and eff.op is EffectOp.DRAW_CARD:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "energy" and eff.op is EffectOp.ENERGY_GAIN:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif kind == "any_power" and eff.op is EffectOp.APPLY_POWER:
            new_eff = _replace(eff, amount=eff.amount + delta[1])
        elif (kind == "power" and eff.op is EffectOp.APPLY_POWER
              and eff.power_id == delta[1]):
            new_eff = _replace(eff, amount=eff.amount + delta[2])
        out.append(new_eff)
    return tuple(out)


def upgrade_card(card: CardDef) -> CardDef:
    """Return the UPGRADED version of `card` with real stat changes.

    Idempotent: a card whose id already ends with '+' is returned unchanged.
    The result carries upgraded EFFECTS (and possibly reduced cost) so combat
    resolves the better numbers, and is tagged id+"+" / name+"+" so
    card_features() and the rarity lookup (which strips '+') keep working.
    """
    from dataclasses import replace as _replace
    if card.id.endswith("+"):
        return card

    deltas = _UPGRADE_DELTAS.get(card.id)
    if deltas is None:
        # Fallback default for an implemented card without an explicit table
        # entry: attacks gain damage, everything else gains block.
        deltas = (_DEFAULT_ATTACK_DELTA if card.type is CardType.ATTACK
                  else _DEFAULT_BLOCK_DELTA)

    effects = card.effects
    cost = card.cost
    for delta in deltas:
        if delta[0] == "cost":
            if cost is not None and cost >= 0:
                cost = max(0, cost + delta[1])
        else:
            effects = _apply_delta(effects, delta)

    return _replace(card, id=card.id + "+", name=card.name + "+",
                    effects=effects, cost=cost)
