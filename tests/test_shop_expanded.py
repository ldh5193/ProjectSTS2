"""Phase 7H tests for the FULL shop — buy cards / relics / potions.

Verifies:
  - Entering a shop stocks cards + relics + potions + card_removal with
    the action-space dict shape {index, category, price, can_afford,
    is_stocked, ...} that _shop_mask + decode read.
  - build_mask(state) marks affordable+stocked slots legal (via the env
    mod-state view) and leave (slot 15).
  - shop_purchase deducts gold and grants card / relic / potion.
  - An unaffordable item is not purchasable.
  - Buying sets is_stocked False and drops the slot from the mask.
  - Card removal still works and unstocks its slot.
"""
from __future__ import annotations

from sim.action_space import build_mask, decode, range_named
from sim.game_state import Character, MapNode, RunState, StateType
from sim.run_engine import _enter_room, step


SHOP = range_named("shop")  # start=138, size=16


def _new_rs_in_shop(gold: int = 1000, ascension: int = 0) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD,
                          ascension=ascension, seed=42)
    rs.gold = gold
    rs.act = 1
    rs.floor = 5
    node = MapNode(floor=5, x=0, room_type=StateType.SHOP)
    _enter_room(rs, node)
    return rs


def _items(rs):
    return rs.pending_shop["items"]


def _first(rs, category):
    return next(it for it in _items(rs) if it["category"] == category)


# --- stocking + dict shape ---------------------------------------------------

def test_shop_stocks_all_categories():
    rs = _new_rs_in_shop()
    assert rs.state_type == StateType.SHOP
    cats = [it["category"] for it in _items(rs)]
    assert cats.count("card") == 7        # 5 colored + 2 colorless
    assert cats.count("relic") == 3
    assert cats.count("potion") == 2
    assert cats.count("card_removal") == 1


def test_item_dict_shape_matches_contract():
    rs = _new_rs_in_shop()
    indices = []
    for it in _items(rs):
        # Exact keys the action space depends on.
        assert set(("index", "category", "price", "can_afford",
                    "is_stocked")).issubset(it.keys())
        assert isinstance(it["index"], int)
        assert isinstance(it["price"], int) and it["price"] > 0
        assert isinstance(it["can_afford"], bool)
        assert it["is_stocked"] is True
        assert 0 <= it["index"] <= 14
        indices.append(it["index"])
    # Stable contiguous indices 0..N-1.
    assert indices == list(range(len(indices)))


def test_prices_in_decompiled_ranges():
    rs = _new_rs_in_shop()
    for it in _items(rs):
        cat, price = it["category"], it["price"]
        if cat == "card":
            # common 50, uncommon 75, rare 150, colorless x1.15, +/-5% jitter.
            # colorless rare ceiling: 150*1.15=172.5 -> 173, *1.05 ~= 182.
            assert 45 <= price <= 185
        elif cat == "relic":
            # merchant_cost (175/250/300) x [0.85,1.15]; default 200.
            assert 140 <= price <= 360
        elif cat == "potion":
            assert 50 <= price <= 75
        elif cat == "card_removal":
            assert price == 75


def test_removal_cost_inflation_a6():
    rs = _new_rs_in_shop(ascension=6)
    assert _first(rs, "card_removal")["price"] == 100
    assert rs.pending_shop["card_removal_cost"] == 100


def test_deterministic_stock():
    a = _new_rs_in_shop()
    b = _new_rs_in_shop()
    assert [(it["category"], it.get("card_id"), it.get("relic_id"),
             it.get("potion_id"), it["price"]) for it in _items(a)] == \
           [(it["category"], it.get("card_id"), it.get("relic_id"),
             it.get("potion_id"), it["price"]) for it in _items(b)]


# --- mask via the env mod-state view ----------------------------------------

def _mask_view(rs):
    from sim.env_run import RunEnv
    env = RunEnv(ascension=int(rs.ascension))
    env.rs = rs
    return env._mod_state_view()


def test_mask_marks_affordable_stocked_legal():
    rs = _new_rs_in_shop(gold=1000)
    mask = build_mask(_mask_view(rs))
    # Every affordable+stocked slot is legal; leave (15) is legal.
    for it in _items(rs):
        legal = mask[SHOP.start + it["index"]]
        assert legal == (it["can_afford"] and it["is_stocked"])
    assert mask[SHOP.start + 15] is True


def test_mask_excludes_unaffordable():
    rs = _new_rs_in_shop(gold=0)
    mask = build_mask(_mask_view(rs))
    for it in _items(rs):
        assert mask[SHOP.start + it["index"]] is False
    assert mask[SHOP.start + 15] is True  # can always leave


# --- purchase path -----------------------------------------------------------

def test_buy_card_deducts_gold_and_adds_to_deck():
    rs = _new_rs_in_shop(gold=1000)
    card = _first(rs, "card")
    pre_deck = len(rs.deck)
    res = step(rs, {"action": "shop_purchase", "index": card["index"]})
    assert not res.invalid_action
    assert rs.gold == 1000 - card["price"]
    assert len(rs.deck) == pre_deck + 1
    assert card["is_stocked"] is False
    assert card["can_afford"] is False


def test_buy_relic_adds_relic():
    rs = _new_rs_in_shop(gold=1000)
    relic = _first(rs, "relic")
    res = step(rs, {"action": "shop_purchase", "index": relic["index"]})
    assert not res.invalid_action
    assert rs.has_relic(relic["relic_id"])
    assert relic["is_stocked"] is False


def test_buy_potion_adds_potion():
    rs = _new_rs_in_shop(gold=1000)
    potion = _first(rs, "potion")
    before = sum(1 for p in rs.potions if p is not None)
    res = step(rs, {"action": "shop_purchase", "index": potion["index"]})
    assert not res.invalid_action
    after = sum(1 for p in rs.potions if p is not None)
    assert after == before + 1
    assert potion["is_stocked"] is False


def test_unaffordable_item_not_purchasable():
    rs = _new_rs_in_shop(gold=1000)
    card = _first(rs, "card")
    rs.gold = card["price"] - 1
    res = step(rs, {"action": "shop_purchase", "index": card["index"]})
    assert res.invalid_action
    assert card["is_stocked"] is True  # not consumed


def test_buying_sets_unstocked_and_drops_from_mask():
    rs = _new_rs_in_shop(gold=1000)
    card = _first(rs, "card")
    step(rs, {"action": "shop_purchase", "index": card["index"]})
    mask = build_mask(_mask_view(rs))
    assert mask[SHOP.start + card["index"]] is False


def test_cannot_rebuy_sold_slot():
    rs = _new_rs_in_shop(gold=1000)
    card = _first(rs, "card")
    step(rs, {"action": "shop_purchase", "index": card["index"]})
    res = step(rs, {"action": "shop_purchase", "index": card["index"]})
    assert res.invalid_action


def test_affordability_refreshes_after_purchase():
    rs = _new_rs_in_shop(gold=1000)
    # Buy the cheapest item, then verify can_afford recomputed from new gold.
    cheapest = min((it for it in _items(rs) if it["category"] != "card_removal"),
                   key=lambda it: it["price"])
    step(rs, {"action": "shop_purchase", "index": cheapest["index"]})
    for it in _items(rs):
        if it["is_stocked"]:
            assert it["can_afford"] == (rs.gold >= it["price"])


def test_removal_still_works_and_unstocks_slot():
    rs = _new_rs_in_shop(gold=1000)
    removal = _first(rs, "card_removal")
    pre_deck = len(rs.deck)
    res = step(rs, {"action": "shop_purchase_removal", "index": 0})
    assert not res.invalid_action
    assert rs.gold == 1000 - 75
    assert len(rs.deck) == pre_deck - 1
    assert rs.pending_shop["removal_used"] is True
    assert removal["is_stocked"] is False
    mask = build_mask(_mask_view(rs))
    assert mask[SHOP.start + removal["index"]] is False


def test_decode_dispatches_removal_vs_buy():
    rs = _new_rs_in_shop(gold=1000)
    view = _mask_view(rs)
    card = _first(rs, "card")
    removal = _first(rs, "card_removal")
    body_card = decode(SHOP.start + card["index"], view)
    assert body_card == {"action": "shop_purchase", "index": card["index"]}
    body_rm = decode(SHOP.start + removal["index"], view)
    assert body_rm["action"] == "shop_purchase_removal"
    assert decode(SHOP.start + 15, view) == {"action": "proceed"}


def test_proceed_leaves_shop():
    rs = _new_rs_in_shop()
    res = step(rs, {"action": "proceed"})
    assert not res.invalid_action
    assert rs.state_type == StateType.MAP
    assert rs.pending_shop is None


def test_potion_purchase_fails_when_belt_full():
    rs = _new_rs_in_shop(gold=1000)
    # Fill the belt.
    for i in range(rs.max_potion_slots):
        rs.potions[i] = rs.potions[i] or __import__(
            "sim.game_state", fromlist=["PotionInstance"]).PotionInstance(id="FIRE_POTION")
    potion = _first(rs, "potion")
    res = step(rs, {"action": "shop_purchase", "index": potion["index"]})
    assert res.invalid_action
    assert potion["is_stocked"] is True  # no gold spent, still stocked


def test_obs_dim_unchanged():
    from sim.env_run import OBS_DIM, RunEnv
    assert OBS_DIM == 504
    env = RunEnv(ascension=0)
    obs, _ = env.reset(seed=3)
    assert obs.shape == (504,)
