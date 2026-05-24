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
    ANGER,
    BASH,
    BATTLE_TRANCE,
    BLOODLETTING,
    BLUDGEON,
    CINDER,
    DEFEND_IRONCLAD,
    DISMANTLE,
    HEADBUTT,
    INFLAME,
    IRON_WAVE,
    PERFECTED_STRIKE,
    POMMEL_STRIKE,
    RAGE,
    SHRUG_IT_OFF,
    STONE_ARMOR,
    STRIKE_IRONCLAD,
    STRIKE_SCALING,
    TAUNT,
    THUNDERCLAP,
    TREMBLE,
    TWIN_STRIKE,
    UPPERCUT,
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
    ("cinder", "Cinder", 1, CardType.SKILL, CardRarity.COMMON),
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
    ("bully", "Bully", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("burning_pact", "Burning Pact", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("colossus", "Colossus", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("demonic_shield", "Demonic Shield", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("dismantle", "Dismantle", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("dominate", "Dominate", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("drum_of_battle", "Drum of Battle", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("evil_eye", "Evil Eye", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("expect_a_fight", "Expect a Fight", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("feel_no_pain", "Feel No Pain", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("fight_me", "Fight Me", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("flame_barrier", "Flame Barrier", 2, CardType.SKILL, CardRarity.UNCOMMON),
    ("forgotten_ritual", "Forgotten Ritual", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("hemokinesis", "Hemokinesis", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("howl_from_beyond", "Howl from Beyond", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("infernal_blade", "Infernal Blade", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("inferno", "Inferno", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("inflame", "Inflame", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("juggling", "Juggling", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("pillage", "Pillage", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("rage", "Rage", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("rampage", "Rampage", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("rupture", "Rupture", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("second_wind", "Second Wind", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("spite", "Spite", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("stampede", "Stampede", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("stomp", "Stomp", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("stone_armor", "Stone Armor", 1, CardType.POWER, CardRarity.UNCOMMON),
    ("taunt", "Taunt", 0, CardType.SKILL, CardRarity.UNCOMMON),
    ("unrelenting", "Unrelenting", 1, CardType.ATTACK, CardRarity.UNCOMMON),
    ("uppercut", "Uppercut", 2, CardType.ATTACK, CardRarity.UNCOMMON),
    ("vicious", "Vicious", 1, CardType.SKILL, CardRarity.UNCOMMON),
    ("whirlwind", "Whirlwind", -1, CardType.ATTACK, CardRarity.UNCOMMON),  # X-cost
    # --- Rare (25) ---
    ("aggression", "Aggression", 1, CardType.SKILL, CardRarity.RARE),
    ("barricade", "Barricade", 3, CardType.POWER, CardRarity.RARE),
    ("brand", "Brand", 1, CardType.SKILL, CardRarity.RARE),
    ("conflagration", "Conflagration", 2, CardType.ATTACK, CardRarity.RARE),
    ("crimson_mantle", "Crimson Mantle", 1, CardType.SKILL, CardRarity.RARE),
    ("cruelty", "Cruelty", 1, CardType.POWER, CardRarity.RARE),
    ("dark_embrace", "Dark Embrace", 2, CardType.POWER, CardRarity.RARE),
    ("demon_form", "Demon Form", 3, CardType.POWER, CardRarity.RARE),
    ("feed", "Feed", 1, CardType.ATTACK, CardRarity.RARE),
    ("fiend_fire", "Fiend Fire", 2, CardType.ATTACK, CardRarity.RARE),
    ("hellraiser", "Hellraiser", 2, CardType.ATTACK, CardRarity.RARE),
    ("impervious", "Impervious", 2, CardType.SKILL, CardRarity.RARE),
    ("juggernaut", "Juggernaut", 2, CardType.POWER, CardRarity.RARE),
    ("mangle", "Mangle", 1, CardType.ATTACK, CardRarity.RARE),
    ("not_yet", "Not Yet", 1, CardType.SKILL, CardRarity.RARE),
    ("offering", "Offering", 0, CardType.SKILL, CardRarity.RARE),
    ("one_two_punch", "One-Two Punch", 1, CardType.ATTACK, CardRarity.RARE),
    ("pacts_end", "Pact's End", 2, CardType.SKILL, CardRarity.RARE),
    ("primal_force", "Primal Force", 2, CardType.POWER, CardRarity.RARE),
    ("pyre", "Pyre", 2, CardType.ATTACK, CardRarity.RARE),
    ("stoke", "Stoke", 2, CardType.SKILL, CardRarity.RARE),
    ("tank", "Tank", 2, CardType.SKILL, CardRarity.RARE),
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


IRONCLAD_COMMON = ids_by_rarity(CardRarity.COMMON)        # 20
IRONCLAD_UNCOMMON = ids_by_rarity(CardRarity.UNCOMMON)    # 36
IRONCLAD_RARE = ids_by_rarity(CardRarity.RARE)            # 25
