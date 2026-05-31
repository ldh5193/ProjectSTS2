"""Phase 1 tests for sim/relics.py — L1 relic additions.

Covers the 8 new relics added in Phase 1 (BagOfPreparation, ArcaneScroll,
Strawberry, Ginger, Girya, BlessedAntler, DreamCatcher, EternalFeather,
MawBank, CursedPearl, LeadPaperweight) plus category lookup.
"""
from __future__ import annotations

from sim.game_state import Character, RunState, StateType
from sim.relics import (
    RELIC_CATEGORIES, RELIC_REGISTRY, apply_hand_draw_modifiers,
    relic_category, relic_category_index,
    trigger_after_room_entered,
)


def _new_rs() -> RunState:
    return RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=42)


def test_strawberry_pickup_grants_max_hp():
    rs = _new_rs()
    pre_max = rs.max_hp
    rs.add_relic("STRAWBERRY")
    assert rs.max_hp == pre_max + 7
    assert rs.hp == pre_max + 7  # also healed


def test_add_relic_idempotent():
    rs = _new_rs()
    rs.add_relic("ANCHOR")
    rs.add_relic("ANCHOR")
    n = sum(1 for r in rs.relics if r.id == "ANCHOR")
    assert n == 1


def test_bag_of_preparation_extra_draw_first_turn():
    rs = _new_rs()
    rs.add_relic("BAG_OF_PREPARATION")

    class _FakeCombat:
        turn_number = 1
    drew = apply_hand_draw_modifiers(rs, _FakeCombat(), base_draw=5)
    assert drew == 7  # +2 first turn


def test_bag_of_preparation_no_bonus_round_2():
    rs = _new_rs()
    rs.add_relic("BAG_OF_PREPARATION")

    class _FakeCombat:
        turn_number = 2
    drew = apply_hand_draw_modifiers(rs, _FakeCombat(), base_draw=5)
    assert drew == 5


def test_arcane_scroll_every_turn():
    rs = _new_rs()
    rs.add_relic("ARCANE_SCROLL")

    class _FakeCombat:
        turn_number = 4
    drew = apply_hand_draw_modifiers(rs, _FakeCombat(), base_draw=5)
    assert drew == 6  # +1 every turn


def test_eternal_feather_heals_at_rest():
    rs = _new_rs()
    rs.add_relic("ETERNAL_FEATHER")
    rs.hp = rs.max_hp - 20  # take damage
    trigger_after_room_entered(rs, StateType.REST)
    assert rs.hp == rs.max_hp - 17  # +3 heal


def test_maw_bank_grants_gold_non_shop():
    rs = _new_rs()
    rs.add_relic("MAW_BANK")
    pre_gold = rs.gold
    trigger_after_room_entered(rs, StateType.MONSTER)
    assert rs.gold == pre_gold + 12


def test_maw_bank_stops_after_gold_spent():
    # MawBank.cs grants +12 on each room entered (BaseRoom == room) until the
    # owner spends gold at a shop (AfterItemPurchased -> HasItemBeenBought),
    # which disables it. There is NO room-type filter in the decompile.
    rs = _new_rs()
    rs.add_relic("MAW_BANK")
    pre_gold = rs.gold
    trigger_after_room_entered(rs, StateType.SHOP)
    assert rs.gold == pre_gold + 12  # faithful: gains on shop entry too
    # Once gold is spent at a shop, the relic is used up.
    rs.maw_bank_spent = True
    pre_gold2 = rs.gold
    trigger_after_room_entered(rs, StateType.MONSTER)
    assert rs.gold == pre_gold2  # no further gains


def test_lead_paperweight_grants_gold_non_shop():
    rs = _new_rs()
    rs.add_relic("LEAD_PAPERWEIGHT")
    pre_gold = rs.gold
    trigger_after_room_entered(rs, StateType.MONSTER)
    assert rs.gold == pre_gold + 5


def test_relic_category_known():
    assert relic_category("BURNING_BLOOD") == "heal_combat"
    assert relic_category("ANCHOR") == "block_start"
    assert relic_category("BAG_OF_MARBLES") == "vuln_start"
    assert relic_category("BAG_OF_PREPARATION") == "draw_card"
    assert relic_category("GIRYA") == "strength"
    assert relic_category("MAW_BANK") == "gold"


def test_relic_category_unknown_is_misc():
    assert relic_category("NONEXISTENT_RELIC_XYZ") == "misc"


def test_relic_category_index_in_range():
    for relic_id in RELIC_REGISTRY:
        idx = relic_category_index(relic_id)
        assert 0 <= idx < len(RELIC_CATEGORIES)


def test_l1_registry_size():
    """Phase 1 brings the registry to 22 relics (12 original + 10 new
    after the BAG_OF_PREPARATION/ARCANE_SCROLL/STRAWBERRY/GINGER/GIRYA/
    BLESSED_ANTLER/DREAM_CATCHER/ETERNAL_FEATHER/MAW_BANK/CURSED_PEARL/
    LEAD_PAPERWEIGHT additions). Adjust if more relics ship."""
    assert len(RELIC_REGISTRY) >= 20  # at least 20 — the L1 target


def test_all_l1_relics_have_category():
    for relic_id, rd in RELIC_REGISTRY.items():
        assert rd.category in RELIC_CATEGORIES, (
            f"{relic_id} has category {rd.category!r} not in RELIC_CATEGORIES")
