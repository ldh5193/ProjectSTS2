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
