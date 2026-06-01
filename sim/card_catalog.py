"""Ironclad card catalog — id / cost / type / rarity for all 87 cards
(notes/10_card_rewards.md §1).

Only a handful have full CardDef effects (sim/cards.py); the rest land
as placeholder defs so the reward / deck systems can enumerate, pick,
and shuffle the full pool. Placeholders default to either a 5-damage
attack, a 5-block skill, or a no-op power — enough to keep combat
running while the real effects are ported one by one.

CardRarity tags here mirror MegaCrit's CardRarity enum.
"""
from __future__ import annotations

from enum import Enum

from .cards import (
    AGGRESSION,
    ANGER,
    ARMAMENTS,
    ASHEN_STRIKE,
    BARRICADE,
    CASCADE,
    COLOSSUS,
    CRIMSON_MANTLE,
    CRUELTY,
    DRUM_OF_BATTLE,
    EVIL_EYE,
    EXPECT_A_FIGHT,
    FORGOTTEN_RITUAL,
    GIANT_ROCK,
    HELLRAISER,
    INFERNO,
    JUGGLING,
    ONE_TWO_PUNCH,
    PRIMAL_FORCE,
    STAMPEDE,
    STOKE,
    THRASH,
    UNMOVABLE,
    VICIOUS,
    BASH,
    BATTLE_TRANCE,
    BERSERK,
    BLOODLETTING,
    BLOOD_WALL,
    BLUDGEON,
    BODY_SLAM,
    BRAND,
    BREAKTHROUGH,
    BREAK_CARD,
    BRUTALITY,
    BULLY,
    BURNING_PACT,
    CINDER,
    COMBUST,
    CONFLAGRATION,
    CORRUPTION,
    DARK_EMBRACE,
    DEFEND_IRONCLAD,
    DEMON_FORM,
    DISMANTLE,
    DOMINATE,
    FEED,
    FIGHT_ME,
    FEEL_NO_PAIN,
    FIEND_FIRE,
    FLAME_BARRIER,
    HAVOC,
    HEADBUTT,
    HEMOKINESIS,
    HOWL_FROM_BEYOND,
    IMPERVIOUS,
    INFERNAL_BLADE,
    INFLAME,
    IRON_WAVE,
    JUGGERNAUT,
    MANGLE,
    METALLICIZE,
    MOLTEN_FIST,
    NOT_YET,
    OFFERING,
    PACTS_END,
    PERFECTED_STRIKE,
    PILLAGE,
    POMMEL_STRIKE,
    PYRE,
    RAGE,
    RAMPAGE,
    RUPTURE,
    SECOND_WIND,
    SETUP_STRIKE,
    SHOCKWAVE,
    SHRUG_IT_OFF,
    SPITE,
    STOMP,
    STONE_ARMOR,
    STRIKE_IRONCLAD,
    STRIKE_SCALING,
    SWORD_BOOMERANG,
    TAUNT,
    TEAR_ASUNDER,
    THUNDERCLAP,
    TREMBLE,
    TRUE_GRIT,
    TWIN_STRIKE,
    UNRELENTING,
    UPPERCUT,
    WHIRLWIND,
)
from .dsl import CardDef, CardType, Effect, EffectOp, Target


class CardRarity(str, Enum):
    BASIC = "basic"
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    ANCIENT = "ancient"


def _placeholder(card_id: str, name: str, cost: int, ctype: CardType,
                 rarity: CardRarity) -> CardDef:
    """Build a CardDef with a generic placeholder effect by card type.

    Used for cards we haven't yet ported the real effect for. Lets the
    reward / deck system enumerate the full Ironclad pool without
    blocking on per-card ports.
    """
    if ctype is CardType.ATTACK:
        effects = (Effect(
            op=EffectOp.DEAL_DAMAGE, target=Target.SELECTED_ENEMY,
            amount=5, scaling=STRIKE_SCALING,
        ),)
    elif ctype is CardType.SKILL:
        effects = (Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF, amount=5),)
    else:  # POWER
        effects = ()
    return CardDef(id=card_id, name=name, cost=cost, type=ctype,
                   effects=effects, count=0)


# --- Per-card metadata ------------------------------------------------------
# (id, name, cost, type, rarity). Costs are best-guess defaults from STS1
# parity where the decompile hasn't been read yet; corrected per-card as the
# real CardDef lands in sim/cards.py.

_META: list[tuple[str, str, int, CardType, CardRarity]] = [
    # --- Basic ---
    ("strike_ironclad", "Strike", 1, CardType.ATTACK, CardRarity.BASIC),
    ("defend_ironclad", "Defend", 1, CardType.SKILL, CardRarity.BASIC),
    ("bash", "Bash", 2, CardType.ATTACK, CardRarity.BASIC),
    # --- Common (20) ---
    ("anger", "Anger", 0, CardType.ATTACK, CardRarity.COMMON),
    ("armaments", "Armaments", 1, CardType.SKILL, CardRarity.COMMON),
    ("blood_wall", "Blood Wall", 1, CardType.SKILL, CardRarity.COMMON),
    ("bloodletting", "Bloodletting", 0, CardType.SKILL, CardRarity.COMMON),
    ("body_slam", "Body Slam", 1, CardType.ATTACK, CardRarity.COMMON),
    ("breakthrough", "Breakthrough", 1, CardType.ATTACK, CardRarity.COMMON),
    ("cinder", "Cinder", 2, CardType.ATTACK, CardRarity.COMMON),
    ("havoc", "Havoc", 1, CardType.SKILL, CardRarity.COMMON),
    ("headbutt", "Headbutt", 1, CardType.ATTACK, CardRarity.COMMON),
    ("iron_wave", "Iron Wave", 1, CardType.ATTACK, CardRarity.COMMON),
    ("molten_fist", "Molten Fist", 1, CardType.ATTACK, CardRarity.COMMON),
    ("perfected_strike", "Perfected Strike", 2, CardType.ATTACK, CardRarity.COMMON),
    ("pommel_strike", "Pommel Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("setup_strike", "Setup Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("shrug_it_off", "Shrug It Off", 1, CardType.SKILL, CardRarity.COMMON),
    ("sword_boomerang", "Sword Boomerang", 1, CardType.ATTACK, CardRarity.COMMON),
    ("thunderclap", "Thunderclap", 1, CardType.ATTACK, CardRarity.COMMON),
    ("tremble", "Tremble", 0, CardType.SKILL, CardRarity.COMMON),
    ("true_grit", "True Grit", 1, CardType.SKILL, CardRarity.COMMON),
    ("twin_strike", "Twin Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    # --- Uncommon (36) ---
    ("ashen_strike", "Ashen Strike", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("battle_trance", "Battle Trance", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("bludgeon", "Bludgeon", 3, CardType.ATTACK, CardRarity.UNCOMMON),
    ("bully", "Bully", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("burning_pact", "Burning Pact", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("colossus", "Colossus", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("demonic_shield", "Demonic Shield", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("dismantle", "Dismantle", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("dominate", "Dominate", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("drum_of_battle", "Drum of Battle", 0, CardType.POWER, CardRarity.UNCOMMON),
    ("evil_eye", "Evil Eye", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("expect_a_fight", "Expect a Fight", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("feel_no_pain", "Feel No Pain", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("fight_me", "Fight Me", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("flame_barrier", "Flame Barrier", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("forgotten_ritual", "Forgotten Ritual", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("hemokinesis", "Hemokinesis", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("howl_from_beyond", "Howl from Beyond", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("infernal_blade", "Infernal Blade", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("inferno", "Inferno", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("inflame", "Inflame", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("juggling", "Juggling", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("pillage", "Pillage", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("rage", "Rage", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("rampage", "Rampage", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("rupture", "Rupture", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("second_wind", "Second Wind", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("spite", "Spite", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("stampede", "Stampede", 2, CardType.POWER, CardRarity.UNCOMMON),
    ("stomp", "Stomp", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("stone_armor", "Stone Armor", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("taunt", "Taunt", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("unrelenting", "Unrelenting", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("uppercut", "Uppercut", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("vicious", "Vicious", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("whirlwind", "Whirlwind", -1, CardType.ATTACK, CardRarity.UNCOMMON),  # X-cost
    # Engine powers without an STS2 card model (faithful STS1 semantics).
    ("metallicize", "Metallicize", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("combust", "Combust", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("berserk", "Berserk", 0, CardType.POWER, CardRarity.UNCOMMON),
    ("brutality", "Brutality", 0, CardType.POWER, CardRarity.UNCOMMON),
    # --- Rare (25) ---
    ("aggression", "Aggression", 1, CardType.POWER, CardRarity.RARE),
    ("barricade", "Barricade", 3, CardType.POWER, CardRarity.RARE),
    ("cascade", "Cascade", -1, CardType.SKILL, CardRarity.RARE),  # X-cost
    ("brand", "Brand", 1, CardType.SKILL, CardRarity.RARE),
    ("conflagration", "Conflagration", 2, CardType.ATTACK, CardRarity.RARE),
    ("crimson_mantle", "Crimson Mantle", 1, CardType.POWER, CardRarity.RARE),
    ("cruelty", "Cruelty", 1, CardType.POWER, CardRarity.RARE),
    ("dark_embrace", "Dark Embrace", 2, CardType.POWER, CardRarity.RARE),
    ("demon_form", "Demon Form", 3, CardType.POWER, CardRarity.RARE),
    ("feed", "Feed", 1, CardType.ATTACK, CardRarity.RARE),
    ("fiend_fire", "Fiend Fire", 2, CardType.ATTACK, CardRarity.RARE),
    ("hellraiser", "Hellraiser", 2, CardType.POWER, CardRarity.RARE),
    ("impervious", "Impervious", 2, CardType.SKILL, CardRarity.RARE),
    ("juggernaut", "Juggernaut", 2, CardType.POWER, CardRarity.RARE),
    ("mangle", "Mangle", 1, CardType.ATTACK, CardRarity.RARE),
    ("not_yet", "Not Yet", 1, CardType.SKILL, CardRarity.RARE),
    ("offering", "Offering", 0, CardType.SKILL, CardRarity.RARE),
    ("one_two_punch", "One-Two Punch", 1, CardType.SKILL, CardRarity.RARE),
    ("pacts_end", "Pact's End", 0, CardType.ATTACK, CardRarity.RARE),
    ("primal_force", "Primal Force", 0, CardType.SKILL, CardRarity.RARE),
    ("pyre", "Pyre", 2, CardType.ATTACK, CardRarity.RARE),
    ("stoke", "Stoke", 1, CardType.SKILL, CardRarity.RARE),
    ("tank", "Tank", 1, CardType.POWER, CardRarity.RARE),
    ("tear_asunder", "Tear Asunder", 2, CardType.ATTACK, CardRarity.RARE),
    ("thrash", "Thrash", 1, CardType.ATTACK, CardRarity.RARE),
    ("unmovable", "Unmovable", 2, CardType.POWER, CardRarity.RARE),
    # --- Ancient (2; excluded from reward gen) ---
    ("break", "Break", 1, CardType.SKILL, CardRarity.ANCIENT),
    ("corruption", "Corruption", 3, CardType.POWER, CardRarity.ANCIENT),
]


# Map of fully-implemented CardDefs from sim/cards.py.
_IMPLEMENTED: dict[str, CardDef] = {
    STRIKE_IRONCLAD.id: STRIKE_IRONCLAD,
    DEFEND_IRONCLAD.id: DEFEND_IRONCLAD,
    BASH.id: BASH,
    IRON_WAVE.id: IRON_WAVE,
    INFLAME.id: INFLAME,
    POMMEL_STRIKE.id: POMMEL_STRIKE,
    SHRUG_IT_OFF.id: SHRUG_IT_OFF,
    THUNDERCLAP.id: THUNDERCLAP,
    TREMBLE.id: TREMBLE,
    TWIN_STRIKE.id: TWIN_STRIKE,
    BLOODLETTING.id: BLOODLETTING,
    ANGER.id: ANGER,
    CINDER.id: CINDER,
    BLUDGEON.id: BLUDGEON,
    UPPERCUT.id: UPPERCUT,
    TAUNT.id: TAUNT,
    STONE_ARMOR.id: STONE_ARMOR,
    RAGE.id: RAGE,
    BATTLE_TRANCE.id: BATTLE_TRANCE,
    HEADBUTT.id: HEADBUTT,
    DISMANTLE.id: DISMANTLE,
    PERFECTED_STRIKE.id: PERFECTED_STRIKE,
    # Phase 7B engine power cards
    DEMON_FORM.id: DEMON_FORM,
    METALLICIZE.id: METALLICIZE,
    FEEL_NO_PAIN.id: FEEL_NO_PAIN,
    DARK_EMBRACE.id: DARK_EMBRACE,
    JUGGERNAUT.id: JUGGERNAUT,
    RUPTURE.id: RUPTURE,
    COMBUST.id: COMBUST,
    BARRICADE.id: BARRICADE,
    BERSERK.id: BERSERK,
    BRUTALITY.id: BRUTALITY,
    CORRUPTION.id: CORRUPTION,
    # Phase 7C STS2 pool completion
    ARMAMENTS.id: ARMAMENTS,
    BLOOD_WALL.id: BLOOD_WALL,
    BODY_SLAM.id: BODY_SLAM,
    BREAKTHROUGH.id: BREAKTHROUGH,
    HAVOC.id: HAVOC,
    MOLTEN_FIST.id: MOLTEN_FIST,
    SETUP_STRIKE.id: SETUP_STRIKE,
    SWORD_BOOMERANG.id: SWORD_BOOMERANG,
    TRUE_GRIT.id: TRUE_GRIT,
    WHIRLWIND.id: WHIRLWIND,
    ASHEN_STRIKE.id: ASHEN_STRIKE,
    BULLY.id: BULLY,
    BURNING_PACT.id: BURNING_PACT,
    FLAME_BARRIER.id: FLAME_BARRIER,
    HEMOKINESIS.id: HEMOKINESIS,
    HOWL_FROM_BEYOND.id: HOWL_FROM_BEYOND,
    INFERNAL_BLADE.id: INFERNAL_BLADE,
    PILLAGE.id: PILLAGE,
    RAMPAGE.id: RAMPAGE,
    SECOND_WIND.id: SECOND_WIND,
    SHOCKWAVE.id: SHOCKWAVE,
    SPITE.id: SPITE,
    STOMP.id: STOMP,
    UNRELENTING.id: UNRELENTING,
    BRAND.id: BRAND,
    CONFLAGRATION.id: CONFLAGRATION,
    FEED.id: FEED,
    FIEND_FIRE.id: FIEND_FIRE,
    IMPERVIOUS.id: IMPERVIOUS,
    MANGLE.id: MANGLE,
    NOT_YET.id: NOT_YET,
    OFFERING.id: OFFERING,
    PACTS_END.id: PACTS_END,
    PYRE.id: PYRE,
    TEAR_ASUNDER.id: TEAR_ASUNDER,
    BREAK_CARD.id: BREAK_CARD,
    FIGHT_ME.id: FIGHT_ME,
    DOMINATE.id: DOMINATE,
    # Phase 8 Track A — history-conditional + persistent-power cards
    COLOSSUS.id: COLOSSUS,
    DRUM_OF_BATTLE.id: DRUM_OF_BATTLE,
    EVIL_EYE.id: EVIL_EYE,
    EXPECT_A_FIGHT.id: EXPECT_A_FIGHT,
    FORGOTTEN_RITUAL.id: FORGOTTEN_RITUAL,
    INFERNO.id: INFERNO,
    JUGGLING.id: JUGGLING,
    STAMPEDE.id: STAMPEDE,
    VICIOUS.id: VICIOUS,
    AGGRESSION.id: AGGRESSION,
    CRIMSON_MANTLE.id: CRIMSON_MANTLE,
    CRUELTY.id: CRUELTY,
    HELLRAISER.id: HELLRAISER,
    ONE_TWO_PUNCH.id: ONE_TWO_PUNCH,
    PRIMAL_FORCE.id: PRIMAL_FORCE,
    STOKE.id: STOKE,
    THRASH.id: THRASH,
    UNMOVABLE.id: UNMOVABLE,
    GIANT_ROCK.id: GIANT_ROCK,
    CASCADE.id: CASCADE,
}

# Phase 9.0 scaffold: register the per-character starting cards (Strike/Defend
# basics + TODO-stubbed signature starters for Silent/Defect/Necrobinder/Regent)
# so CARDS[<id>] resolves for obs/reward/deck paths. These are NOT in the _META
# reward pools (RARITY_OF) — they only enter a deck via the character's starting
# deck, exactly like the Ironclad basics today.
from .cards import _P9_SCAFFOLD_CARDS as _P9_SCAFFOLD_CARDS  # noqa: E402
for _scaf in _P9_SCAFFOLD_CARDS:
    _IMPLEMENTED.setdefault(_scaf.id, _scaf)

# Phase 9.1: register the fully-implemented Silent cards + Shiv token so
# CARDS[<id>] resolves for obs/reward/deck/generation paths.
from .cards import _SILENT_IMPLEMENTED as _SILENT_IMPLEMENTED  # noqa: E402
for _sc in _SILENT_IMPLEMENTED:
    _IMPLEMENTED.setdefault(_sc.id, _sc)

# Phase 9.2: register the fully-implemented Defect cards. The scaffold already
# registered StrikeDefect/DefendDefect/Zap/Dualcast (Zap/Dualcast now carry real
# orb effects); use plain assignment so those four pick up the real effects.
from .cards import _DEFECT_IMPLEMENTED as _DEFECT_IMPLEMENTED  # noqa: E402
from .cards import ZAP as _ZAP_DEFECT, DUALCAST as _DUALCAST_DEFECT  # noqa: E402
_IMPLEMENTED[_ZAP_DEFECT.id] = _ZAP_DEFECT
_IMPLEMENTED[_DUALCAST_DEFECT.id] = _DUALCAST_DEFECT
for _dc in _DEFECT_IMPLEMENTED:
    _IMPLEMENTED.setdefault(_dc.id, _dc)

# Phase 9.3: register the fully-implemented Necrobinder cards. The scaffold
# registered StrikeNecrobinder/DefendNecrobinder/Bodyguard/Unleash; Bodyguard/
# Unleash now carry real Osty effects, so use plain assignment for those two.
from .cards import _NECROBINDER_IMPLEMENTED as _NECROBINDER_IMPLEMENTED  # noqa: E402
from .cards import BODYGUARD as _BODYGUARD_NB, UNLEASH as _UNLEASH_NB  # noqa: E402
_IMPLEMENTED[_BODYGUARD_NB.id] = _BODYGUARD_NB
_IMPLEMENTED[_UNLEASH_NB.id] = _UNLEASH_NB
for _nc in _NECROBINDER_IMPLEMENTED:
    _IMPLEMENTED.setdefault(_nc.id, _nc)


def _build_registry() -> tuple[dict[str, CardDef], dict[str, CardRarity]]:
    by_id: dict[str, CardDef] = {}
    rarity_by_id: dict[str, CardRarity] = {}
    for card_id, name, cost, ctype, rarity in _META:
        rarity_by_id[card_id] = rarity
        if card_id in _IMPLEMENTED:
            by_id[card_id] = _IMPLEMENTED[card_id]
        else:
            by_id[card_id] = _placeholder(card_id, name, cost, ctype, rarity)
    # Token cards (generated mid-combat, e.g. GiantRock) are implemented but
    # are not part of the reward pool (_META / RARITY_OF), so they're added to
    # the lookup without a rarity. Card-generation ops resolve them via CARDS.
    for card_id, card in _IMPLEMENTED.items():
        if card_id not in by_id:
            by_id[card_id] = card
    return by_id, rarity_by_id


CARDS: dict[str, CardDef]
RARITY_OF: dict[str, CardRarity]
CARDS, RARITY_OF = _build_registry()


def ids_by_rarity(rarity: CardRarity) -> list[str]:
    return [cid for cid, r in RARITY_OF.items() if r is rarity]


def is_implemented(card_id: str) -> bool:
    """True if the card has a real effect ported in sim/cards.py.
    Placeholder cards register as False even though they appear in CARDS."""
    return card_id in _IMPLEMENTED


CARD_FEATURE_DIM = 12

_RARITY_VALUE: dict[CardRarity, float] = {
    CardRarity.BASIC: 0.0,
    CardRarity.COMMON: 0.25,
    CardRarity.UNCOMMON: 0.50,
    CardRarity.RARE: 0.75,
    CardRarity.ANCIENT: 1.0,
}
_ENEMY_DEBUFF_IDS = frozenset({"vulnerable", "weak", "frail"})
_SELF_BUFF_IDS = frozenset({"strength", "dexterity", "intangible", "ritual",
                             "rage", "metallicize", "plated_armor", "thorns",
                             # Phase 7B engine powers
                             "demon_form", "feel_no_pain", "dark_embrace",
                             "juggernaut", "rupture", "combust", "barricade",
                             "berserk", "brutality", "corruption", "plating",
                             # Phase 8 Track A persistent powers
                             "colossus", "cruelty", "crimson_mantle", "inferno",
                             "drum_of_battle", "stampede", "one_two_punch",
                             "juggling", "aggression", "hellraiser", "unmovable",
                             "vicious"})


def card_features(card_id: str) -> list[float]:
    """Return a CARD_FEATURE_DIM-wide vector describing the card's
    gameplay shape. Used by RunEnv obs v3 to let the policy distinguish
    cards in hand and card_reward without exploding the obs into a
    full one-hot over the ~90-card pool.

    Layout (12):
      0  cost (normalized cost/3; X-cost/unknown → 0)
      1  is_attack
      2  is_skill
      3  is_power
      4  damage_total (sum deal_damage × hit_count / 30, capped 1)
      5  block_total (sum gain_block / 20, capped 1)
      6  has_enemy_debuff (apply vuln/weak/frail to enemy)
      7  has_self_buff (apply strength/dex/intangible/etc to self)
      8  has_draw
      9  has_energy_gain
     10  rarity 0..1
     11  upgraded (id ends with '+')
    """
    upgraded = card_id.endswith("+")
    base_id = card_id[:-1] if upgraded else card_id
    card = CARDS.get(base_id)
    if card is None:
        return [0.0] * CARD_FEATURE_DIM
    if upgraded:
        # Read the UPGRADED effects so damage/block/buff dims reflect the
        # real upgraded numbers (not just the upgraded flag bit).
        from .cards import upgrade_card
        card = upgrade_card(card)
    rarity = RARITY_OF.get(base_id, CardRarity.BASIC)

    cost = card.cost if card.cost is not None and card.cost >= 0 else 0
    feats = [0.0] * CARD_FEATURE_DIM
    feats[0] = min(1.0, cost / 3.0)
    feats[1] = 1.0 if card.type is CardType.ATTACK else 0.0
    feats[2] = 1.0 if card.type is CardType.SKILL else 0.0
    feats[3] = 1.0 if card.type is CardType.POWER else 0.0

    dmg = 0
    blk = 0
    has_debuff = False
    has_buff = False
    has_draw = False
    has_egain = False
    for eff in card.effects:
        if eff.op is EffectOp.DEAL_DAMAGE:
            dmg += eff.amount * max(1, eff.hit_count)
        elif eff.op is EffectOp.GAIN_BLOCK:
            blk += eff.amount
        elif eff.op is EffectOp.APPLY_POWER and eff.power_id:
            pid = eff.power_id.lower()
            if eff.target is Target.SELF and pid in _SELF_BUFF_IDS:
                has_buff = True
            elif eff.target is not Target.SELF and pid in _ENEMY_DEBUFF_IDS:
                has_debuff = True
        elif eff.op is EffectOp.DRAW_CARD:
            has_draw = True
        elif eff.op is EffectOp.ENERGY_GAIN:
            has_egain = True

    feats[4] = min(1.0, dmg / 30.0)
    feats[5] = min(1.0, blk / 20.0)
    feats[6] = 1.0 if has_debuff else 0.0
    feats[7] = 1.0 if has_buff else 0.0
    feats[8] = 1.0 if has_draw else 0.0
    feats[9] = 1.0 if has_egain else 0.0
    feats[10] = _RARITY_VALUE.get(rarity, 0.0)
    feats[11] = 1.0 if upgraded else 0.0
    return feats


IRONCLAD_COMMON = ids_by_rarity(CardRarity.COMMON)        # 20
IRONCLAD_UNCOMMON = ids_by_rarity(CardRarity.UNCOMMON)    # 36
IRONCLAD_RARE = ids_by_rarity(CardRarity.RARE)            # 25


# ===========================================================================
# Phase 9.1 — SILENT card metadata (SilentCardPool.cs, 88 cards). Each entry is
# (id, name, cost, type, rarity), .cs-exact. Implemented effects live in
# sim/cards.py (_SILENT_IMPLEMENTED); the rest fall back to by-type placeholders
# with the correct cost/type/rarity so the reward/deck pool enumerates the full
# Silent set. Basics (Strike/Defend/Neutralize/Survivor) come from the scaffold.
# Ancients (Suppress/WraithForm) are excluded from reward generation, like
# Ironclad's Break/Corruption.
# ===========================================================================
_X = -1  # X-cost sentinel (matches dsl.X_COST)
_SILENT_META: list[tuple[str, str, int, CardType, CardRarity]] = [
    # --- Basics (registered via scaffold; included here for rarity lookup) ---
    ("strike_silent", "Strike", 1, CardType.ATTACK, CardRarity.BASIC),
    ("defend_silent", "Defend", 1, CardType.SKILL, CardRarity.BASIC),
    ("neutralize", "Neutralize", 0, CardType.ATTACK, CardRarity.BASIC),
    ("survivor", "Survivor", 1, CardType.SKILL, CardRarity.BASIC),
    # --- Common ---
    ("slice", "Slice", 0, CardType.ATTACK, CardRarity.COMMON),
    ("dagger_throw", "Dagger Throw", 1, CardType.ATTACK, CardRarity.COMMON),
    ("dagger_spray", "Dagger Spray", 1, CardType.ATTACK, CardRarity.COMMON),
    ("flick_flack", "Flick Flack", 1, CardType.ATTACK, CardRarity.COMMON),
    ("follow_through", "Follow Through", 1, CardType.ATTACK, CardRarity.COMMON),
    ("leading_strike", "Leading Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("poisoned_stab", "Poisoned Stab", 1, CardType.ATTACK, CardRarity.COMMON),
    ("ricochet", "Ricochet", 2, CardType.ATTACK, CardRarity.COMMON),
    ("sucker_punch", "Sucker Punch", 1, CardType.ATTACK, CardRarity.COMMON),
    ("deadly_poison", "Deadly Poison", 1, CardType.SKILL, CardRarity.COMMON),
    ("snakebite", "Snakebite", 2, CardType.SKILL, CardRarity.COMMON),
    ("blade_dance", "Blade Dance", 1, CardType.SKILL, CardRarity.COMMON),
    ("cloak_and_dagger", "Cloak and Dagger", 1, CardType.SKILL, CardRarity.COMMON),
    ("deflect", "Deflect", 0, CardType.SKILL, CardRarity.COMMON),
    ("dodge_and_roll", "Dodge and Roll", 1, CardType.SKILL, CardRarity.COMMON),
    ("prepared", "Prepared", 0, CardType.SKILL, CardRarity.COMMON),
    ("untouchable", "Untouchable", 2, CardType.SKILL, CardRarity.COMMON),
    # --- Uncommon ---
    ("backstab", "Backstab", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("dash", "Dash", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("predator", "Predator", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("pounce", "Pounce", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("pinpoint", "Pinpoint", 3, CardType.ATTACK, CardRarity.UNCOMMON),
    ("skewer", "Skewer", _X, CardType.ATTACK, CardRarity.UNCOMMON),
    ("finisher", "Finisher", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("flechettes", "Flechettes", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("memento_mori", "Memento Mori", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("precise_cut", "Precise Cut", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("blur", "Blur", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("backflip", "Backflip", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("leg_sweep", "Leg Sweep", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("escape_plan", "Escape Plan", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("expertise", "Expertise", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("calculated_gamble", "Calculated Gamble", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("acrobatics", "Acrobatics", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("haze", "Haze", 3, CardType.SKILL, CardRarity.UNCOMMON),
    ("bubble_bubble", "Bubble Bubble", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("bouncing_flask", "Bouncing Flask", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("hand_trick", "Hand Trick", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("hidden_daggers", "Hidden Daggers", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("expose", "Expose", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("reflex", "Reflex", 3, CardType.SKILL, CardRarity.UNCOMMON),
    ("flanking", "Flanking", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("up_my_sleeve", "Up My Sleeve", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("tactician", "Tactician", 3, CardType.SKILL, CardRarity.UNCOMMON),
    ("anticipate", "Anticipate", 0, CardType.SKILL, CardRarity.COMMON),
    ("accuracy", "Accuracy", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("footwork", "Footwork", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("noxious_fumes", "Noxious Fumes", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("outbreak", "Outbreak", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("infinite_blades", "Infinite Blades", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("phantom_blades", "Phantom Blades", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("speedster", "Speedster", 2, CardType.POWER, CardRarity.UNCOMMON),
    ("well_laid_plans", "Well-Laid Plans", 1, CardType.POWER, CardRarity.UNCOMMON),
    # --- Rare ---
    ("backflip", "Backflip", 1, CardType.SKILL, CardRarity.UNCOMMON),  # dedup-safe
    ("the_hunt", "The Hunt", 1, CardType.ATTACK, CardRarity.RARE),
    ("echoing_slash", "Echoing Slash", 1, CardType.ATTACK, CardRarity.RARE),
    ("grand_finale", "Grand Finale", 0, CardType.ATTACK, CardRarity.RARE),
    ("assassinate", "Assassinate", 0, CardType.ATTACK, CardRarity.RARE),
    ("murder", "Murder", 3, CardType.ATTACK, CardRarity.RARE),
    ("envenom", "Envenom", 2, CardType.POWER, CardRarity.RARE),
    ("accelerant", "Accelerant", 1, CardType.POWER, CardRarity.RARE),
    ("sneaky", "Sneaky", 2, CardType.POWER, CardRarity.RARE),
    ("serpent_form", "Serpent Form", 3, CardType.POWER, CardRarity.RARE),
    ("fan_of_knives", "Fan of Knives", 2, CardType.POWER, CardRarity.RARE),
    ("tools_of_the_trade", "Tools of the Trade", 1, CardType.POWER, CardRarity.RARE),
    ("abrasive", "Abrasive", 3, CardType.POWER, CardRarity.RARE),
    ("blade_of_ink", "Blade of Ink", 1, CardType.SKILL, CardRarity.RARE),
    ("bullet_time", "Bullet Time", 3, CardType.SKILL, CardRarity.RARE),
    ("corrosive_wave", "Corrosive Wave", 1, CardType.SKILL, CardRarity.RARE),
    ("adrenaline", "Adrenaline", 0, CardType.SKILL, CardRarity.RARE),
    ("knife_trap", "Knife Trap", 2, CardType.SKILL, CardRarity.RARE),
    ("malaise", "Malaise", 0, CardType.SKILL, CardRarity.RARE),
    ("master_planner", "Master Planner", 2, CardType.POWER, CardRarity.RARE),
    ("mirage", "Mirage", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("nightmare", "Nightmare", 3, CardType.SKILL, CardRarity.RARE),
    ("phantom_blades", "Phantom Blades", 1, CardType.POWER, CardRarity.UNCOMMON),  # dedup
    ("shadow_step", "Shadow Step", 1, CardType.SKILL, CardRarity.RARE),
    ("shadowmeld", "Shadowmeld", 1, CardType.SKILL, CardRarity.RARE),
    ("storm_of_steel", "Storm of Steel", 1, CardType.SKILL, CardRarity.RARE),
    ("afterimage_silent", "Afterimage", 1, CardType.POWER, CardRarity.RARE),
    ("burst", "Burst", 1, CardType.SKILL, CardRarity.RARE),
    ("piercing_wail", "Piercing Wail", 1, CardType.SKILL, CardRarity.COMMON),
    ("strangle", "Strangle", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    # --- Ancient (excluded from reward gen) ---
    ("suppress", "Suppress", 0, CardType.ATTACK, CardRarity.ANCIENT),
    ("wraith_form", "Wraith Form", 3, CardType.POWER, CardRarity.ANCIENT),
    # --- Token (not in reward pool) ---
    ("shiv", "Shiv", 0, CardType.ATTACK, CardRarity.BASIC),
]


def _build_silent_registry() -> None:
    """Merge Silent metadata into the global CARDS / RARITY_OF registries:
    implemented CardDefs are kept; everything else gets a by-type placeholder
    with the correct cost/type. De-dups on id (some entries repeat for safety)."""
    seen: set[str] = set()
    for cid, name, cost, ctype, rarity in _SILENT_META:
        if cid in seen:
            continue
        seen.add(cid)
        RARITY_OF.setdefault(cid, rarity)
        if cid not in CARDS:
            CARDS[cid] = _placeholder(cid, name, cost, ctype, rarity)


_build_silent_registry()

SILENT_COMMON = [c for (c, _n, _co, _t, r) in _SILENT_META
                 if r is CardRarity.COMMON]
SILENT_UNCOMMON = [c for (c, _n, _co, _t, r) in _SILENT_META
                   if r is CardRarity.UNCOMMON]
SILENT_RARE = [c for (c, _n, _co, _t, r) in _SILENT_META
               if r is CardRarity.RARE]
# De-dup while preserving order (some ids appear twice in _SILENT_META).
def _dedup(seq):
    out, seen = [], set()
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
SILENT_COMMON = _dedup(SILENT_COMMON)
SILENT_UNCOMMON = _dedup(SILENT_UNCOMMON)
SILENT_RARE = _dedup(SILENT_RARE)


# ===========================================================================
# Phase 9.2 — DEFECT card metadata (DefectCardPool.cs, 88 cards). (id, name,
# cost, type, rarity), .cs-exact. Implemented effects live in sim/cards.py
# (_DEFECT_IMPLEMENTED); a few that need an absent card-selection/transform
# primitive register as by-type placeholders with the right cost/type/rarity.
# Basics (StrikeDefect/DefendDefect) come from the scaffold. Ancients
# (Quadcast/BiasedCognition) are excluded from reward generation.
# ===========================================================================
_DEFECT_META: list[tuple[str, str, int, CardType, CardRarity]] = [
    # --- Basics (registered via scaffold; here for rarity lookup) ---
    ("strike_defect", "Strike", 1, CardType.ATTACK, CardRarity.BASIC),
    ("defend_defect", "Defend", 1, CardType.SKILL, CardRarity.BASIC),
    ("zap", "Zap", 1, CardType.SKILL, CardRarity.BASIC),
    ("dualcast", "Dualcast", 1, CardType.SKILL, CardRarity.BASIC),
    # --- Common ---
    ("ball_lightning", "Ball Lightning", 1, CardType.ATTACK, CardRarity.COMMON),
    ("barrage", "Barrage", 1, CardType.ATTACK, CardRarity.COMMON),
    ("beam_cell", "Beam Cell", 0, CardType.ATTACK, CardRarity.COMMON),
    ("claw", "Claw", 0, CardType.ATTACK, CardRarity.COMMON),
    ("cold_snap", "Cold Snap", 1, CardType.ATTACK, CardRarity.COMMON),
    ("compile_driver", "Compile Driver", 1, CardType.ATTACK, CardRarity.COMMON),
    ("go_for_the_eyes", "Go for the Eyes", 0, CardType.ATTACK, CardRarity.COMMON),
    ("gunk_up", "Gunk Up", 1, CardType.ATTACK, CardRarity.COMMON),
    ("momentum_strike", "Momentum Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("sweeping_beam", "Sweeping Beam", 1, CardType.ATTACK, CardRarity.COMMON),
    ("focused_strike", "Focused Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("charge_battery", "Charge Battery", 1, CardType.SKILL, CardRarity.COMMON),
    ("coolheaded", "Coolheaded", 1, CardType.SKILL, CardRarity.COMMON),
    ("hologram", "Hologram", 1, CardType.SKILL, CardRarity.COMMON),
    ("leap", "Leap", 1, CardType.SKILL, CardRarity.COMMON),
    ("turbo", "Turbo", 0, CardType.SKILL, CardRarity.COMMON),
    ("boost_away", "Boost Away", 0, CardType.SKILL, CardRarity.COMMON),
    # --- Uncommon ---
    ("compact", "Compact", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("ftl", "FTL", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("refract", "Refract", 3, CardType.ATTACK, CardRarity.UNCOMMON),
    ("rocket_punch", "Rocket Punch", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("scrape", "Scrape", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("sunder", "Sunder", 3, CardType.ATTACK, CardRarity.UNCOMMON),
    ("synthesis", "Synthesis", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("tesla_coil", "Tesla Coil", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("uproar", "Uproar", 2, CardType.ATTACK, CardRarity.COMMON),
    ("null", "Null", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("boot_sequence", "Boot Sequence", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("capacitor", "Capacitor", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("chaos", "Chaos", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("chill", "Chill", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("darkness", "Darkness", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("double_energy", "Double Energy", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("fight_through", "Fight Through", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("fusion", "Fusion", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("glacier", "Glacier", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("glasswork", "Glasswork", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("overclock", "Overclock", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("scavenge", "Scavenge", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("shadow_shield_defect", "Shadow Shield", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("skim", "Skim", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("tempest", "Tempest", _X, CardType.SKILL, CardRarity.UNCOMMON),
    ("white_noise", "White Noise", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("bulk_up", "Bulk Up", 2, CardType.POWER, CardRarity.UNCOMMON),
    ("feral", "Feral", 2, CardType.POWER, CardRarity.UNCOMMON),
    ("hailstorm", "Hailstorm", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("iteration", "Iteration", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("loop", "Loop", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("smokestack", "Smokestack", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("storm", "Storm", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("subroutine", "Subroutine", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("lightning_rod", "Lightning Rod", 1, CardType.SKILL, CardRarity.COMMON),
    ("thunder", "Thunder", 1, CardType.POWER, CardRarity.UNCOMMON),
    # --- Rare ---
    ("adaptive_strike", "Adaptive Strike", 2, CardType.ATTACK, CardRarity.RARE),
    ("all_for_one", "All for One", 2, CardType.ATTACK, CardRarity.RARE),
    ("hyperbeam", "Hyperbeam", 2, CardType.ATTACK, CardRarity.RARE),
    ("ice_lance", "Ice Lance", 3, CardType.ATTACK, CardRarity.RARE),
    ("meteor_strike", "Meteor Strike", 5, CardType.ATTACK, CardRarity.RARE),
    ("shatter", "Shatter", 1, CardType.ATTACK, CardRarity.RARE),
    ("flak_cannon", "Flak Cannon", 2, CardType.ATTACK, CardRarity.RARE),
    ("helix_drill", "Helix Drill", 0, CardType.ATTACK, CardRarity.RARE),
    ("buffer", "Buffer", 2, CardType.POWER, CardRarity.RARE),
    ("coolant", "Coolant", 1, CardType.POWER, CardRarity.RARE),
    ("creative_ai", "Creative AI", 3, CardType.POWER, CardRarity.RARE),
    ("defragment", "Defragment", 1, CardType.POWER, CardRarity.RARE),
    ("echo_form", "Echo Form", 3, CardType.POWER, CardRarity.RARE),
    ("consuming_shadow", "Consuming Shadow", 2, CardType.POWER, CardRarity.RARE),
    ("machine_learning", "Machine Learning", 1, CardType.POWER, CardRarity.RARE),
    ("signal_boost", "Signal Boost", 1, CardType.SKILL, CardRarity.RARE),
    ("spinner", "Spinner", 1, CardType.POWER, CardRarity.RARE),
    ("supercritical", "Supercritical", 0, CardType.SKILL, CardRarity.RARE),
    ("synchronize", "Synchronize", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("trash_to_treasure", "Trash to Treasure", 1, CardType.POWER, CardRarity.RARE),
    ("reboot", "Reboot", 0, CardType.SKILL, CardRarity.RARE),
    ("rainbow", "Rainbow", 2, CardType.SKILL, CardRarity.RARE),
    ("multi_cast", "Multi-Cast", 0, CardType.SKILL, CardRarity.RARE),
    ("voltaic", "Voltaic", 3, CardType.SKILL, CardRarity.RARE),
    ("hotfix", "Hotfix", 0, CardType.SKILL, CardRarity.COMMON),
    ("ignition", "Ignition", 1, CardType.SKILL, CardRarity.RARE),
    ("modded", "Modded", 0, CardType.SKILL, CardRarity.RARE),
    ("genetic_algorithm", "Genetic Algorithm", 1, CardType.SKILL, CardRarity.RARE),
    ("energy_surge", "Energy Surge", 0, CardType.SKILL, CardRarity.UNCOMMON),
    # --- Ancient (excluded from reward gen) ---
    ("biased_cognition", "Biased Cognition", 1, CardType.POWER, CardRarity.ANCIENT),
    ("quadcast", "Quadcast", 1, CardType.SKILL, CardRarity.ANCIENT),
]


def _build_defect_registry() -> None:
    seen: set[str] = set()
    for cid, name, cost, ctype, rarity in _DEFECT_META:
        if cid in seen:
            continue
        seen.add(cid)
        RARITY_OF.setdefault(cid, rarity)
        if cid not in CARDS:
            CARDS[cid] = _placeholder(cid, name, cost, ctype, rarity)


_build_defect_registry()

DEFECT_COMMON = _dedup([c for (c, _n, _co, _t, r) in _DEFECT_META
                        if r is CardRarity.COMMON])
DEFECT_UNCOMMON = _dedup([c for (c, _n, _co, _t, r) in _DEFECT_META
                          if r is CardRarity.UNCOMMON])
DEFECT_RARE = _dedup([c for (c, _n, _co, _t, r) in _DEFECT_META
                      if r is CardRarity.RARE])


# ===========================================================================
# Phase 9.3 — NECROBINDER card metadata (NecrobinderCardPool.cs, 88 cards).
# (id, name, cost, type, rarity), .cs-exact. Implemented effects live in
# sim/cards.py (_NECROBINDER_IMPLEMENTED); cards needing an absent primitive
# (Soul token gen, card-select-exhaust, Ethereal, X-cost loop, History-count
# scaling) register as by-type placeholders with the right cost/type/rarity.
# Basics (StrikeNecrobinder/DefendNecrobinder/Bodyguard/Unleash) come from the
# scaffold. Ancients (ForbiddenGrimoire/Protector) are excluded from reward gen.
# ===========================================================================
_NECROBINDER_META: list[tuple[str, str, int, CardType, CardRarity]] = [
    # --- Basics (registered via scaffold; here for rarity lookup) ---
    ("strike_necrobinder", "Strike", 1, CardType.ATTACK, CardRarity.BASIC),
    ("defend_necrobinder", "Defend", 1, CardType.SKILL, CardRarity.BASIC),
    ("bodyguard", "Bodyguard", 1, CardType.SKILL, CardRarity.BASIC),
    ("unleash", "Unleash", 1, CardType.ATTACK, CardRarity.BASIC),
    # --- Common ---
    ("blight_strike", "Blight Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("sculpting_strike", "Sculpting Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("graveblast", "Graveblast", 1, CardType.ATTACK, CardRarity.COMMON),
    ("defile", "Defile", 1, CardType.ATTACK, CardRarity.COMMON),
    ("reave", "Reave", 1, CardType.ATTACK, CardRarity.COMMON),
    ("drain_power", "Drain Power", 1, CardType.ATTACK, CardRarity.COMMON),
    ("fear_nb", "Fear", 1, CardType.ATTACK, CardRarity.COMMON),
    ("reap", "Reap", 3, CardType.ATTACK, CardRarity.COMMON),
    ("poke", "Poke", 0, CardType.ATTACK, CardRarity.COMMON),
    ("snap", "Snap", 1, CardType.ATTACK, CardRarity.COMMON),
    ("sow", "Sow", 1, CardType.ATTACK, CardRarity.COMMON),
    ("afterlife", "Afterlife", 1, CardType.SKILL, CardRarity.COMMON),
    ("defy", "Defy", 1, CardType.SKILL, CardRarity.COMMON),
    ("grave_warden", "Grave Warden", 1, CardType.SKILL, CardRarity.COMMON),
    ("pull_aggro", "Pull Aggro", 2, CardType.SKILL, CardRarity.COMMON),
    ("scourge", "Scourge", 1, CardType.SKILL, CardRarity.COMMON),
    ("invoke", "Invoke", 1, CardType.SKILL, CardRarity.COMMON),
    ("negative_pulse", "Negative Pulse", 1, CardType.SKILL, CardRarity.COMMON),
    ("flatten", "Flatten", 2, CardType.ATTACK, CardRarity.COMMON),
    ("wisp", "Wisp", 0, CardType.SKILL, CardRarity.COMMON),
    # --- Uncommon ---
    ("severance", "Severance", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("veilpiercer", "Veilpiercer", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("debilitate_nb", "Debilitate", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("bury", "Bury", 4, CardType.ATTACK, CardRarity.UNCOMMON),
    ("bone_shards", "Bone Shards", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("sic_em", "Sic 'Em", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("high_five", "High Five", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("right_hand_hand", "Right Hand, Hand", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("fetch", "Fetch", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("rattle", "Rattle", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("death_march", "Death March", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("pull_from_below", "Pull from Below", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("enfeebling_touch", "Enfeebling Touch", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("putrefy", "Putrefy", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("spur", "Spur", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("deaths_door", "Death's Door", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("delay", "Delay", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("melancholy", "Melancholy", 3, CardType.SKILL, CardRarity.UNCOMMON),
    ("cleanse_nb", "Cleanse", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("dirge", "Dirge", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("legion_of_bone", "Legion of Bone", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("deathbringer", "Deathbringer", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("borrowed_time", "Borrowed Time", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("capture_spirit", "Capture Spirit", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("dredge", "Dredge", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("no_escape", "No Escape", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("parse", "Parse", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("haunt", "Haunt", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("calcify", "Calcify", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("friendship", "Friendship", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("lethality", "Lethality", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("danse_macabre", "Danse Macabre", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("countdown", "Countdown", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("pagestorm", "Pagestorm", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("shroud", "Shroud", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("sleight_of_flesh", "Sleight of Flesh", 2, CardType.POWER, CardRarity.UNCOMMON),
    # --- Rare ---
    ("eradicate", "Eradicate", 0, CardType.ATTACK, CardRarity.RARE),
    ("hang", "Hang", 1, CardType.ATTACK, CardRarity.RARE),
    ("misery", "Misery", 0, CardType.ATTACK, CardRarity.RARE),
    ("the_scythe", "The Scythe", 2, CardType.ATTACK, CardRarity.RARE),
    ("squeeze", "Squeeze", 3, CardType.ATTACK, CardRarity.RARE),
    ("banshees_cry", "Banshee's Cry", 9, CardType.ATTACK, CardRarity.RARE),
    ("times_up", "Time's Up", 2, CardType.ATTACK, CardRarity.RARE),
    ("soul_storm", "Soul Storm", 1, CardType.ATTACK, CardRarity.RARE),
    ("sacrifice", "Sacrifice", 1, CardType.SKILL, CardRarity.RARE),
    ("reanimate", "Reanimate", 3, CardType.SKILL, CardRarity.RARE),
    ("necro_mastery", "Necro Mastery", 2, CardType.POWER, CardRarity.RARE),
    ("demesne", "Demesne", 3, CardType.POWER, CardRarity.RARE),
    ("devour_life", "Devour Life", 1, CardType.POWER, CardRarity.RARE),
    ("spirit_of_ash", "Spirit of Ash", 1, CardType.POWER, CardRarity.RARE),
    ("shared_fate", "Shared Fate", 0, CardType.SKILL, CardRarity.RARE),
    ("oblivion", "Oblivion", 0, CardType.SKILL, CardRarity.RARE),
    ("end_of_days", "End of Days", 3, CardType.SKILL, CardRarity.RARE),
    ("eidolon", "Eidolon", 2, CardType.SKILL, CardRarity.RARE),
    ("call_of_the_void", "Call of the Void", 1, CardType.POWER, CardRarity.RARE),
    ("glimpse_beyond", "Glimpse Beyond", 1, CardType.SKILL, CardRarity.RARE),
    ("neurosurge", "Neurosurge", 0, CardType.POWER, CardRarity.RARE),
    ("reaper_form", "Reaper Form", 3, CardType.POWER, CardRarity.RARE),
    ("seance", "Seance", 1, CardType.SKILL, CardRarity.RARE),
    ("sentry_mode", "Sentry Mode", 2, CardType.POWER, CardRarity.RARE),
    ("transfigure", "Transfigure", 1, CardType.SKILL, CardRarity.RARE),
    ("undeath", "Undeath", 0, CardType.SKILL, CardRarity.RARE),
    # --- Ancient (excluded from reward gen) ---
    ("forbidden_grimoire", "Forbidden Grimoire", 2, CardType.POWER, CardRarity.ANCIENT),
    ("protector", "Protector", 1, CardType.ATTACK, CardRarity.ANCIENT),
]


def _build_necrobinder_registry() -> None:
    seen: set[str] = set()
    for cid, name, cost, ctype, rarity in _NECROBINDER_META:
        if cid in seen:
            continue
        seen.add(cid)
        RARITY_OF.setdefault(cid, rarity)
        if cid not in CARDS:
            CARDS[cid] = _placeholder(cid, name, cost, ctype, rarity)


_build_necrobinder_registry()

NECROBINDER_COMMON = _dedup([c for (c, _n, _co, _t, r) in _NECROBINDER_META
                             if r is CardRarity.COMMON])
NECROBINDER_UNCOMMON = _dedup([c for (c, _n, _co, _t, r) in _NECROBINDER_META
                               if r is CardRarity.UNCOMMON])
NECROBINDER_RARE = _dedup([c for (c, _n, _co, _t, r) in _NECROBINDER_META
                           if r is CardRarity.RARE])


# ===========================================================================
# Phase 9.4 — REGENT 88-card pool meta (RegentCardPool.cs). cost/type/rarity
# (and star-cost where it applies) are .cs-exact from each card's base(...) ctor
# and CanonicalStarCost. Cards needing an absent primitive (Forge upgrade-in-
# combat, card-select, retain, history-count scaling, colorless-gen) register as
# by-type placeholders with the right cost/type/rarity. Basics (StrikeRegent/
# DefendRegent/FallingStar/Venerate) come from the scaffold.
# ===========================================================================
_REGENT_META: list[tuple[str, str, int, CardType, CardRarity]] = [
    # --- Basics (registered via scaffold; here for rarity lookup) ---
    ("strike_regent", "Strike", 1, CardType.ATTACK, CardRarity.BASIC),
    ("defend_regent", "Defend", 1, CardType.SKILL, CardRarity.BASIC),
    ("falling_star", "Falling Star", 0, CardType.ATTACK, CardRarity.BASIC),
    ("venerate", "Venerate", 1, CardType.SKILL, CardRarity.BASIC),
    # --- Common ---
    ("astral_pulse", "Astral Pulse", 0, CardType.ATTACK, CardRarity.COMMON),
    ("collision_course", "Collision Course", 0, CardType.ATTACK, CardRarity.COMMON),
    ("crescent_spear", "Crescent Spear", 1, CardType.ATTACK, CardRarity.COMMON),
    ("crush_under", "Crush Under", 1, CardType.ATTACK, CardRarity.COMMON),
    ("guiding_star", "Guiding Star", 1, CardType.ATTACK, CardRarity.COMMON),
    ("photon_cut", "Photon Cut", 1, CardType.ATTACK, CardRarity.COMMON),
    ("solar_strike", "Solar Strike", 1, CardType.ATTACK, CardRarity.COMMON),
    ("wrought_in_war", "Wrought in War", 1, CardType.ATTACK, CardRarity.COMMON),
    ("begone", "Begone", 1, CardType.SKILL, CardRarity.COMMON),
    ("cloak_of_stars", "Cloak of Stars", 0, CardType.SKILL, CardRarity.COMMON),
    ("cosmic_indifference", "Cosmic Indifference", 1, CardType.SKILL, CardRarity.COMMON),
    ("gather_light", "Gather Light", 1, CardType.SKILL, CardRarity.COMMON),
    ("glitterstream", "Glitterstream", 2, CardType.SKILL, CardRarity.COMMON),
    ("glow", "Glow", 1, CardType.SKILL, CardRarity.COMMON),
    ("hidden_cache", "Hidden Cache", 1, CardType.SKILL, CardRarity.COMMON),
    ("know_thy_place", "Know Thy Place", 0, CardType.SKILL, CardRarity.COMMON),
    ("patter", "Patter", 1, CardType.SKILL, CardRarity.COMMON),
    ("refine_blade", "Refine Blade", 1, CardType.SKILL, CardRarity.COMMON),
    ("spoils_of_battle", "Spoils of Battle", 1, CardType.SKILL, CardRarity.COMMON),
    # --- Uncommon ---
    ("celestial_might", "Celestial Might", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("devastate", "Devastate", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("gamma_blast", "Gamma Blast", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("hegemony", "Hegemony", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("kingly_kick", "Kingly Kick", 4, CardType.ATTACK, CardRarity.UNCOMMON),
    ("kingly_punch", "Kingly Punch", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("knockout_blow", "Knockout Blow", 3, CardType.ATTACK, CardRarity.UNCOMMON),
    ("lunar_blast", "Lunar Blast", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("radiate", "Radiate", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("shining_strike", "Shining Strike", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("stardust", "Stardust", 0, CardType.ATTACK, CardRarity.UNCOMMON),
    ("supermassive", "Supermassive", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("alignment", "Alignment", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("bulwark", "Bulwark", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("charge", "Charge", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("conqueror", "Conqueror", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("convergence", "Convergence", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("glimmer", "Glimmer", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("largesse", "Largesse", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("manifest_authority", "Manifest Authority", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("monologue", "Monologue", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("particle_wall", "Particle Wall", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("prophesize", "Prophesize", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("quasar", "Quasar", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("reflect", "Reflect", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("resonance", "Resonance", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("royal_gamble", "Royal Gamble", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("summon_forth", "Summon Forth", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("terraforming", "Terraforming", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("black_hole", "Black Hole", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("child_of_the_stars", "Child of the Stars", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("furnace", "Furnace", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("orbit", "Orbit", 2, CardType.POWER, CardRarity.UNCOMMON),
    ("pale_blue_dot", "Pale Blue Dot", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("parry", "Parry", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("pillar_of_creation", "Pillar of Creation", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("spectrum_shift", "Spectrum Shift", 2, CardType.POWER, CardRarity.UNCOMMON),
    # --- Rare ---
    ("beat_into_shape", "Beat into Shape", 1, CardType.ATTACK, CardRarity.RARE),
    ("bombardment", "Bombardment", 3, CardType.ATTACK, CardRarity.RARE),
    ("comet", "Comet", 0, CardType.ATTACK, CardRarity.RARE),
    ("crash_landing", "Crash Landing", 1, CardType.ATTACK, CardRarity.RARE),
    ("dying_star", "Dying Star", 1, CardType.ATTACK, CardRarity.RARE),
    ("heavenly_drill", "Heavenly Drill", 0, CardType.ATTACK, CardRarity.RARE),
    ("heirloom_hammer", "Heirloom Hammer", 2, CardType.ATTACK, CardRarity.RARE),
    ("make_it_so", "Make It So", 0, CardType.ATTACK, CardRarity.RARE),
    ("seven_stars", "Seven Stars", 2, CardType.ATTACK, CardRarity.RARE),
    ("arsenal", "Arsenal", 1, CardType.POWER, CardRarity.RARE),
    ("big_bang", "Big Bang", 0, CardType.SKILL, CardRarity.RARE),
    ("bundle_of_joy", "Bundle of Joy", 1, CardType.SKILL, CardRarity.RARE),
    ("decisions_decisions", "Decisions, Decisions", 0, CardType.SKILL, CardRarity.RARE),
    ("foregone_conclusion", "Foregone Conclusion", 1, CardType.SKILL, CardRarity.RARE),
    ("guards", "Guards", 2, CardType.SKILL, CardRarity.RARE),
    ("i_am_invincible", "I Am Invincible", 1, CardType.SKILL, CardRarity.RARE),
    ("the_smith", "The Smith", 1, CardType.SKILL, CardRarity.RARE),
    ("genesis", "Genesis", 2, CardType.POWER, CardRarity.RARE),
    ("hammer_time", "Hammer Time", 2, CardType.POWER, CardRarity.RARE),
    ("monarchs_gaze", "Monarch's Gaze", 3, CardType.POWER, CardRarity.RARE),
    ("neutron_aegis", "Neutron Aegis", 1, CardType.POWER, CardRarity.RARE),
    ("royalties", "Royalties", 1, CardType.POWER, CardRarity.RARE),
    ("seeking_edge", "Seeking Edge", 1, CardType.POWER, CardRarity.RARE),
    ("sword_sage", "Sword Sage", 2, CardType.POWER, CardRarity.RARE),
    ("tyranny", "Tyranny", 1, CardType.POWER, CardRarity.RARE),
    ("void_form", "Void Form", 3, CardType.POWER, CardRarity.RARE),
    # --- Ancient (excluded from reward gen) ---
    ("meteor_shower", "Meteor Shower", 0, CardType.ATTACK, CardRarity.ANCIENT),
    ("the_sealed_throne", "The Sealed Throne", 1, CardType.POWER, CardRarity.ANCIENT),
]


def _build_regent_registry() -> None:
    seen: set[str] = set()
    for cid, name, cost, ctype, rarity in _REGENT_META:
        if cid in seen:
            continue
        seen.add(cid)
        RARITY_OF.setdefault(cid, rarity)
        if cid not in CARDS:
            CARDS[cid] = _placeholder(cid, name, cost, ctype, rarity)


_build_regent_registry()

# Phase 9.4: register the fully-implemented Regent cards into the live CARDS
# registry (this block runs AFTER _build_registry, so we assign directly). The
# scaffold registered StrikeRegent/DefendRegent/FallingStar/Venerate; FallingStar
# and Venerate now carry real star effects, so overwrite those too.
from .cards import _REGENT_IMPLEMENTED as _REGENT_IMPLEMENTED  # noqa: E402
for _rc in _REGENT_IMPLEMENTED:
    CARDS[_rc.id] = _rc
    _IMPLEMENTED.setdefault(_rc.id, _rc)

REGENT_COMMON = _dedup([c for (c, _n, _co, _t, r) in _REGENT_META
                        if r is CardRarity.COMMON])
REGENT_UNCOMMON = _dedup([c for (c, _n, _co, _t, r) in _REGENT_META
                          if r is CardRarity.UNCOMMON])
REGENT_RARE = _dedup([c for (c, _n, _co, _t, r) in _REGENT_META
                      if r is CardRarity.RARE])


# ===========================================================================
# Phase 9.0 — per-character card-reward POOL registry (SCAFFOLD).
# ===========================================================================
#
# Keyed by the Character enum *value* string. Each entry is a per-rarity
# dict the reward generator draws from. Ironclad is fully populated (today's
# pools); the other four are EMPTY (their 88-card pools land in P9.1-P9.4).
# An empty pool makes generate_card_reward fall back to the Ironclad pool so
# the env never produces an empty / crashing reward during scaffold training
# (a character with no cards yet still gets *a* reward) — flagged TODO(P9.x).
#
# When a character's cards are implemented, fill its dict with that
# character's COMMON/UNCOMMON/RARE id lists (e.g. SILENT_COMMON = ...).
CHARACTER_CARD_POOLS: dict[str, dict[CardRarity, list[str]]] = {
    "ironclad": {
        CardRarity.COMMON: list(IRONCLAD_COMMON),
        CardRarity.UNCOMMON: list(IRONCLAD_UNCOMMON),
        CardRarity.RARE: list(IRONCLAD_RARE),
    },
    # P9.1: Silent 88-card pool (SilentCardPool.cs).
    "silent": {
        CardRarity.COMMON: list(SILENT_COMMON),
        CardRarity.UNCOMMON: list(SILENT_UNCOMMON),
        CardRarity.RARE: list(SILENT_RARE),
    },
    # P9.2: Defect 88-card pool (DefectCardPool.cs).
    "defect": {
        CardRarity.COMMON: list(DEFECT_COMMON),
        CardRarity.UNCOMMON: list(DEFECT_UNCOMMON),
        CardRarity.RARE: list(DEFECT_RARE),
    },
    # P9.3: Necrobinder 88-card pool (NecrobinderCardPool.cs).
    "necrobinder": {
        CardRarity.COMMON: list(NECROBINDER_COMMON),
        CardRarity.UNCOMMON: list(NECROBINDER_UNCOMMON),
        CardRarity.RARE: list(NECROBINDER_RARE),
    },
    # P9.4: Regent 88-card pool (RegentCardPool.cs).
    "regent": {
        CardRarity.COMMON: list(REGENT_COMMON),
        CardRarity.UNCOMMON: list(REGENT_UNCOMMON),
        CardRarity.RARE: list(REGENT_RARE),
    },
    # Deprived (debug): borrows nothing real; falls back to Ironclad.
    "deprived": {CardRarity.COMMON: [], CardRarity.UNCOMMON: [], CardRarity.RARE: []},
}


def character_card_pool(character: str) -> dict[CardRarity, list[str]]:
    """Return the per-rarity card-reward pool for `character` (Character enum
    value string). Falls back to the Ironclad pool when the character's pool
    is unregistered or still empty (scaffold), so the reward path always has
    cards to draw — TODO(P9.x) replace the fallback once each pool is filled."""
    pool = CHARACTER_CARD_POOLS.get(character)
    if pool is None:
        pool = CHARACTER_CARD_POOLS["ironclad"]
    # If every rarity is empty (scaffold characters), fall back to Ironclad's.
    if not any(pool.get(r) for r in (CardRarity.COMMON, CardRarity.UNCOMMON,
                                     CardRarity.RARE)):
        return CHARACTER_CARD_POOLS["ironclad"]
    return pool
