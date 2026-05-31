"""Faithful POTION system tests.

Proves: the registry has many potions with distinct effects; combat drops are
real pooled potions (rarity-weighted, not always FIRE_POTION); representative
potions apply their real effect; the shop stocks real potions; belt-full +
discard still work.

Ground truth: decompiled MegaCrit.Sts2.Core.Models.Potions/* +
Models.PotionPools/* + Factories.PotionFactory.cs + Odds.PotionRewardOdds.cs.
"""
from __future__ import annotations

from sim import potions as P
from sim.combat import CombatState
from sim.game_state import RunState, StateType, Character, PotionInstance
from sim.rng import Rng
from sim import run_engine

_ACT1 = run_engine._ACT_ORDER[0]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_has_many_potions():
    # Far more than the 3 legacy proxies; covers all common+uncommon+rare.
    assert len(P.POTION_REGISTRY) >= 50
    # Each rarity bucket is non-trivially populated.
    assert len(P._POOL_BY_RARITY[P.PotionRarity.COMMON]) >= 10
    assert len(P._POOL_BY_RARITY[P.PotionRarity.UNCOMMON]) >= 10
    assert len(P._POOL_BY_RARITY[P.PotionRarity.RARE]) >= 10


def test_registry_effects_are_distinct():
    # The effect closures must not all be the same object — distinct effects.
    applies = {id(d.apply) for d in P.POTION_REGISTRY.values()}
    assert len(applies) >= 20


def test_known_high_impact_potions_present():
    for pid in (
        "FAIRY_IN_A_BOTTLE", "BLOOD_POTION", "ENTROPIC_BREW", "ENERGY_POTION",
        "BLOCK_POTION", "FIRE_POTION", "STRENGTH_POTION", "DEXTERITY_POTION",
        "WEAK_POTION", "SWIFT_POTION", "DISTILLED_CHAOS", "LIQUID_BRONZE",
        "REGEN_POTION",
    ):
        assert pid in P.POTION_REGISTRY, pid


# ---------------------------------------------------------------------------
# Drop RNG (PotionFactory + PotionRewardOdds)
# ---------------------------------------------------------------------------


def test_roll_potion_is_not_always_fire():
    rng = Rng(424242, "drops")
    drops = [P.roll_potion(rng) for _ in range(60)]
    # Real pooled draw: many distinct ids, not a single fixed proxy.
    assert len(set(drops)) >= 8
    assert drops.count("FIRE_POTION") < len(drops)
    # Every draw is a real registered, pooled potion.
    for d in drops:
        assert d in P.POTION_REGISTRY
        assert d in P._POOL_IDS


def test_roll_potion_respects_rarity_thresholds():
    # NextFloat below 0.10 -> Rare bucket; above 0.35 -> Common bucket.
    class _Fixed:
        def __init__(self, f):
            self._f = f

        def next_float(self, lo=0.0, hi=1.0):
            return self._f

        def next_item(self, items):
            return list(items)[0]

    assert P.roll_potion(_Fixed(0.05)) in P._POOL_BY_RARITY[P.PotionRarity.RARE]
    assert P.roll_potion(_Fixed(0.20)) in P._POOL_BY_RARITY[P.PotionRarity.UNCOMMON]
    assert P.roll_potion(_Fixed(0.90)) in P._POOL_BY_RARITY[P.PotionRarity.COMMON]


def test_combat_drop_uses_real_pool_and_odds():
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed="potiondrop")
    run_engine._generate_act(rs, _ACT1)
    rs.state_type = StateType.MONSTER
    rs.floor = 1
    # Force a guaranteed drop by maxing the persistent odds.
    rs.potion_reward_odds = 1.0
    cs = CombatState.new_combat(seed=7)
    # Kill the monster so player_won() is true on the next combat action.
    for m in cs.monsters:
        m.hp = 0
        m.alive = False
    rs.combat = cs
    before = sum(1 for p in rs.potions if p is not None)
    res = run_engine._step_combat(rs, {"action": "end_turn"}, run_engine.StepResult())
    assert res.combat_won
    after = sum(1 for p in rs.potions if p is not None)
    assert after == before + 1
    dropped = next(p for p in rs.potions if p is not None)
    assert dropped.id in P.POTION_REGISTRY
    assert dropped.id in P._POOL_IDS


# ---------------------------------------------------------------------------
# Use (real effects in combat)
# ---------------------------------------------------------------------------


def _fresh_combat():
    cs = CombatState.new_combat(seed=1)
    cs.start_player_turn()
    return cs


def test_block_potion_grants_12_block():
    cs = _fresh_combat()
    before = cs.player.block
    P.apply_potion(None, cs, "BLOCK_POTION", 0)
    assert cs.player.block - before == 12


def test_strength_potion_grants_2_strength():
    cs = _fresh_combat()
    P.apply_potion(None, cs, "STRENGTH_POTION", 0)
    st = cs.player.get_power("strength")
    assert st is not None and st.amount == 2


def test_energy_potion_grants_2_energy():
    cs = _fresh_combat()
    before = cs.player.energy
    P.apply_potion(None, cs, "ENERGY_POTION", 0)
    assert cs.player.energy - before == 2


def test_fire_potion_damages_enemy():
    cs = _fresh_combat()
    enemy = cs.alive_monsters()[0]
    hp_before = enemy.hp
    P.apply_potion(None, cs, "FIRE_POTION", 0)
    assert enemy.hp < hp_before


def test_swift_potion_draws_cards():
    cs = _fresh_combat()
    before = len(cs.hand)
    P.apply_potion(None, cs, "SWIFT_POTION", 0)
    # Draws up to 3 (may be capped by pile sizes, but should draw at least 1).
    assert len(cs.hand) > before


def test_weak_potion_debuffs_enemy():
    cs = _fresh_combat()
    enemy = cs.alive_monsters()[0]
    P.apply_potion(None, cs, "WEAK_POTION", 0)
    w = enemy.get_power("weak")
    assert w is not None and w.amount == 3


def test_fairy_in_a_bottle_heals_30pct():
    cs = _fresh_combat()
    cs.player.max_hp = 80
    cs.player.hp = 10
    P.apply_potion(None, cs, "FAIRY_IN_A_BOTTLE", 0)
    # 30% of 80 = 24 -> heal to 34.
    assert cs.player.hp == 34


def test_blood_potion_heals_20pct():
    cs = _fresh_combat()
    cs.player.max_hp = 80
    cs.player.hp = 10
    P.apply_potion(None, cs, "BLOOD_POTION", 0)
    # 20% of 80 = 16 -> heal to 26.
    assert cs.player.hp == 26


def test_liquid_bronze_grants_thorns():
    cs = _fresh_combat()
    P.apply_potion(None, cs, "LIQUID_BRONZE", 0)
    t = cs.player.get_power("thorns")
    assert t is not None and t.amount == 3


def test_use_potion_through_engine_clears_slot_and_syncs_hp():
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed="usepot")
    rs.state_type = StateType.MONSTER
    cs = CombatState.new_combat(seed=3)
    cs.start_player_turn()
    cs.player.max_hp = 80
    cs.player.hp = 10
    rs.combat = cs
    rs.hp = 10
    rs.max_hp = 80
    rs.potions[0] = PotionInstance(id="BLOOD_POTION")
    res = run_engine._step_combat(
        rs, {"action": "use_potion", "slot": 0}, run_engine.StepResult())
    assert not res.invalid_action
    assert rs.potions[0] is None         # slot freed
    assert rs.hp == 26                    # run HP synced from combat heal


# ---------------------------------------------------------------------------
# Shop
# ---------------------------------------------------------------------------


def test_shop_stocks_real_potions():
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed="shop1")
    run_engine._generate_act(rs, _ACT1)
    rs.gold = 999
    rs.state_type = StateType.SHOP
    rs.floor = 5
    shop = run_engine._stock_shop(rs)
    pots = [it for it in shop["items"] if it.get("category") == "potion"]
    assert len(pots) == 2
    for it in pots:
        assert it["potion_id"] in P.POTION_REGISTRY
        assert it["potion_id"] in P._POOL_IDS
        # Price is the rarity base × jitter (50/75/100 ± 5%).
        base = P.POTION_SHOP_BASE_COST[P.potion_rarity(it["potion_id"])]
        assert round(base * 0.95) - 1 <= it["price"] <= round(base * 1.05) + 1


# ---------------------------------------------------------------------------
# Belt-full + discard
# ---------------------------------------------------------------------------


def test_belt_full_add_returns_false():
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed="belt")
    for _ in range(rs.max_potion_slots):
        assert rs.add_potion("BLOCK_POTION")
    # Belt full -> further adds rejected.
    assert rs.add_potion("FIRE_POTION") is False


def test_discard_potion_frees_slot():
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed="disc")
    rs.state_type = StateType.MONSTER
    cs = CombatState.new_combat(seed=2)
    rs.combat = cs
    rs.potions[0] = PotionInstance(id="FIRE_POTION")
    res = run_engine._step_combat(
        rs, {"action": "discard_potion", "slot": 0}, run_engine.StepResult())
    assert not res.invalid_action
    assert rs.potions[0] is None


def test_tight_belt_reduces_slots():
    # A4 TightBelt -> one fewer slot (still works with real potions).
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=4, seed="tight")
    assert rs.max_potion_slots == 2
