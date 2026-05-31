"""Phase 8B.7 — EventRelicPool / boss / Neow / shop-trap relics + the new
primitives that convert documented no-ops into real effects.

Each test asserts the newly-implemented relic's hook fires with the exact
effect (state before/after), using the real numbers from the decompiled
Relics/*.cs and EventRelicPool.cs. Ground truth:
  decompiled/MegaCrit.Sts2.Core.Models.Relics/*.cs
  decompiled/MegaCrit.Sts2.Core.Models.RelicPools/EventRelicPool.cs
  decompiled/MegaCrit.Sts2.Core.Models.Powers/ConfusedPower.cs
"""
from __future__ import annotations

import random

from sim.combat import CombatState
from sim.creatures import Monster, Player
from sim.dsl import CardDef, CardType, X_COST, EffectOp, Target, Effect
from sim.game_state import Character, RelicInstance, RunState, StateType
from sim.relics import (
    RELIC_REGISTRY,
    RELIC_SOURCE_POOLS,
    apply_hand_draw_modifiers,
    relic_gold_multiplier,
    reset_combat_counters,
    trigger_after_room_entered,
    trigger_on_card_played,
    trigger_on_combat_start,
    trigger_on_player_turn_end,
    trigger_on_player_turn_start,
)


# --- helpers ---------------------------------------------------------------

def _card(ctype=CardType.SKILL, cost=1, cid="strike_ironclad", effects=()):
    return CardDef(id=cid, name="C", cost=cost, type=ctype,
                   effects=effects, count=0)


def _combat(relics, *, hp=80, max_hp=80, monster_hp=300, gold=99, draw=None,
            energy=3, state=StateType.MONSTER):
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id=r) for r in (relics if isinstance(relics, list) else [relics])]
    rs.hp = hp
    rs.max_hp = max_hp
    rs.gold = gold
    rs.state_type = state
    p = Player(name="P", hp=hp, max_hp=max_hp, energy=energy, max_energy=energy)
    m = Monster(name="M", hp=monster_hp, max_hp=monster_hp)
    cs = CombatState(player=p, monster=m, monsters=[m],
                     draw_pile=list(draw or []), discard_pile=[], hand=[])
    cs.run_state = rs
    cs.rng = random.Random(7)
    reset_combat_counters(rs)
    return rs, cs


# === Registry / pool coverage ==============================================

EVENT_NEW = [
    "SNECKO_EYE", "FAKE_SNECKO_EYE", "PAELS_BLOOD", "PAELS_HORN",
    "BOOMING_CONCH", "FAKE_ANCHOR", "FAKE_BLOOD_VIAL", "FAKE_MANGO",
    "FAKE_LEES_WAFFLE", "FAKE_ORICHALCUM", "FAKE_HAPPY_FLOWER",
    "FAKE_VENERABLE_TEA_SET", "FAKE_STRIKE_DUMMY", "NEOWS_TALISMAN",
    "NEOWS_TORMENT", "GOLDEN_PEARL", "MAW_BANK", "SWORD_OF_JADE",
    "EMBER_TEA", "BONE_TEA", "NUTRITIOUS_OYSTER",
]


def test_new_event_relics_registered_and_pooled():
    event = set(RELIC_SOURCE_POOLS["event"])
    for rid in EVENT_NEW:
        assert rid in RELIC_REGISTRY, f"{rid} not registered"
        assert rid in event, f"{rid} not in event source pool"


def test_snecko_and_pael_ancient_rarity():
    # SneckoEye / Pael fragments are RelicRarity.Ancient in the decompile.
    for rid in ("SNECKO_EYE", "PAELS_BLOOD", "PAELS_HORN", "BOOMING_CONCH",
                "GOLDEN_PEARL", "NUTRITIOUS_OYSTER", "NEOWS_TALISMAN",
                "NEOWS_TORMENT"):
        assert RELIC_REGISTRY[rid].rarity == "ancient", rid
    # Fake/trap + tea relics are RelicRarity.Event with MerchantCost 50.
    for rid in ("FAKE_ANCHOR", "FAKE_BLOOD_VIAL", "FAKE_MANGO",
                "FAKE_LEES_WAFFLE", "FAKE_ORICHALCUM", "FAKE_HAPPY_FLOWER",
                "FAKE_VENERABLE_TEA_SET", "FAKE_STRIKE_DUMMY",
                "FAKE_SNECKO_EYE"):
        assert RELIC_REGISTRY[rid].rarity == "event", rid
        assert RELIC_REGISTRY[rid].merchant_cost == 50, rid


# === Snecko Eye / Confused (cost randomization) ============================

def test_snecko_eye_applies_confused_and_draws_two():
    rs, cs = _combat("SNECKO_EYE")
    trigger_on_combat_start(rs, cs)
    assert cs.player.get_power("confused") is not None
    # ModifyHandDraw +2.
    assert apply_hand_draw_modifiers(rs, cs, 5) == 7


def test_confused_randomizes_drawn_card_cost():
    # Pin the test override on the ConfusedPower so the cost is deterministic.
    rs, cs = _combat("SNECKO_EYE",
                     draw=[_card(CardType.ATTACK, cost=2, cid="bash") for _ in range(3)])
    trigger_on_combat_start(rs, cs)
    conf = cs.player.get_power("confused")
    conf.test_energy_cost_override = 0  # every drawn card costs 0
    cs.draw(3)
    # All three drawn cards now have an effective cost of 0 (was 2).
    for c in cs.hand:
        assert cs.effective_cost(c) == 0


def test_confused_skips_xcost_cards():
    rs, cs = _combat("SNECKO_EYE", draw=[_card(CardType.ATTACK, cost=X_COST, cid="whirlwind")])
    trigger_on_combat_start(rs, cs)
    conf = cs.player.get_power("confused")
    conf.test_energy_cost_override = 0
    cs.draw(1)
    # X-cost card's effective cost == all energy (unchanged by Confused).
    assert cs.effective_cost(cs.hand[0]) == cs.player.energy


def test_fake_snecko_eye_confused_no_bonus_draw():
    rs, cs = _combat("FAKE_SNECKO_EYE")
    trigger_on_combat_start(rs, cs)
    assert cs.player.get_power("confused") is not None
    # No ModifyHandDraw bonus.
    assert apply_hand_draw_modifiers(rs, cs, 5) == 5


# === Pael fragments ========================================================

def test_paels_blood_draws_one_extra():
    rs, cs = _combat("PAELS_BLOOD")
    assert apply_hand_draw_modifiers(rs, cs, 5) == 6


def test_booming_conch_only_elite_turn_one():
    # Elite, turn 1 -> +2.
    rs, cs = _combat("BOOMING_CONCH", state=StateType.ELITE)
    cs.turn_number = 1
    assert apply_hand_draw_modifiers(rs, cs, 5) == 7
    # Non-elite -> no bonus.
    rs2, cs2 = _combat("BOOMING_CONCH", state=StateType.MONSTER)
    cs2.turn_number = 1
    assert apply_hand_draw_modifiers(rs2, cs2, 5) == 5
    # Elite, turn 2 -> no bonus.
    rs3, cs3 = _combat("BOOMING_CONCH", state=StateType.ELITE)
    cs3.turn_number = 2
    assert apply_hand_draw_modifiers(rs3, cs3, 5) == 5


def test_paels_tears_energy_only_with_leftover():
    rs, cs = _combat("PAELS_TEARS")
    # Turn end with leftover energy arms the bonus.
    cs.player.energy = 1
    trigger_on_player_turn_end(rs, cs)
    assert getattr(rs, "_pael_tears_armed") is True
    cs.player.energy = 3
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == 5  # +2
    # Next turn end with NO leftover energy -> not armed.
    cs.player.energy = 0
    trigger_on_player_turn_end(rs, cs)
    cs.player.energy = 3
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == 3  # unchanged


# === Fake (shop-trap) combat relics ========================================

def test_fake_anchor_block_4():
    rs, cs = _combat("FAKE_ANCHOR")
    trigger_on_combat_start(rs, cs)
    assert cs.player.block == 4


def test_fake_blood_vial_heals_turn_one_only():
    rs, cs = _combat("FAKE_BLOOD_VIAL", hp=70, max_hp=80)
    cs.turn_number = 1
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.hp == 71
    cs.turn_number = 2
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.hp == 71  # no heal turn 2


def test_fake_orichalcum_block_3_if_zero_block():
    rs, cs = _combat("FAKE_ORICHALCUM")
    cs.player.block = 0
    trigger_on_player_turn_end(rs, cs)
    assert cs.player.block == 3
    # With existing block, no trigger.
    rs2, cs2 = _combat("FAKE_ORICHALCUM")
    cs2.player.block = 5
    trigger_on_player_turn_end(rs2, cs2)
    assert cs2.player.block == 5


def test_fake_happy_flower_energy_every_five_turns():
    rs, cs = _combat("FAKE_HAPPY_FLOWER")
    for t in range(1, 5):
        trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == 3  # no bonus yet (4 turns)
    trigger_on_player_turn_start(rs, cs)  # 5th turn
    assert cs.player.energy == 4  # +1


def test_fake_strike_dummy_plus_one_strike_damage():
    rs, cs = _combat("FAKE_STRIKE_DUMMY", monster_hp=50)
    before = cs.monster.hp
    trigger_on_card_played(rs, cs, _card(CardType.ATTACK, cid="strike_ironclad"))
    assert cs.monster.hp == before - 1
    # Non-strike attack: no bonus.
    before2 = cs.monster.hp
    trigger_on_card_played(rs, cs, _card(CardType.ATTACK, cid="bash"))
    assert cs.monster.hp == before2


def test_fake_venerable_tea_set_one_energy_after_rest():
    rs, cs = _combat("FAKE_VENERABLE_TEA_SET")
    trigger_after_room_entered(rs, StateType.REST)
    trigger_on_combat_start(rs, cs)
    assert cs.player.energy == 4  # +1


# === Strength / pickup relics ==============================================

def test_sword_of_jade_three_strength():
    rs, cs = _combat("SWORD_OF_JADE")
    trigger_on_combat_start(rs, cs)
    st = cs.player.get_power("strength")
    assert st is not None and st.amount == 3


def test_ember_tea_five_combats_then_used_up():
    rs, cs = _combat("EMBER_TEA")
    for combat in range(5):
        cs.player.powers = []
        trigger_on_combat_start(rs, cs)
        st = cs.player.get_power("strength")
        assert st is not None and st.amount == 2, f"combat {combat}"
    # 6th combat: used up, no strength.
    cs.player.powers = []
    trigger_on_combat_start(rs, cs)
    assert cs.player.get_power("strength") is None


# === Pickup-effect relics (RunState.add_relic) =============================

def test_golden_pearl_pickup_gold():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.gold = 100
    rs.add_relic("GOLDEN_PEARL")
    assert rs.gold == 250


def test_fake_mango_pickup_max_hp():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    before = rs.max_hp
    rs.add_relic("FAKE_MANGO")
    assert rs.max_hp == before + 3


def test_nutritious_oyster_pickup_max_hp():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    before = rs.max_hp
    rs.add_relic("NUTRITIOUS_OYSTER")
    assert rs.max_hp == before + 11


def test_fake_lees_waffle_pickup_heal():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.max_hp = 80
    rs.hp = 50
    rs.add_relic("FAKE_LEES_WAFFLE")
    assert rs.hp == 58  # +10% of 80 = 8


def test_neows_talisman_upgrades_strike_and_defend():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    ids_before = [c.id for c in rs.deck]
    assert any("strike" in i for i in ids_before)
    rs.add_relic("NEOWS_TALISMAN")
    ids_after = [c.id for c in rs.deck]
    assert any(i.endswith("+") and "strike" in i for i in ids_after)
    assert any(i.endswith("+") and "defend" in i for i in ids_after)


# === New primitives: gold-multiplier, deck-add, X-value, death-prevent =====

def test_bowler_hat_gold_multiplier():
    assert relic_gold_multiplier("BOWLER_HAT") == 1.25
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id="BOWLER_HAT")]
    rs.gold = 0
    rs.gain_gold(100)
    assert rs.gold == 125  # 100 * 1.25
    # Spends are NOT scaled.
    rs.gain_gold(-25)
    assert rs.gold == 100


def test_lucky_fysh_gold_on_card_added():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id="LUCKY_FYSH")]
    rs.gold = 0
    rs.add_card_to_deck(_card())
    assert rs.gold == 15


def test_book_of_five_rings_heal_every_fifth_add():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id="BOOK_OF_FIVE_RINGS")]
    rs.max_hp = 80
    rs.hp = 40
    for _ in range(4):
        rs.add_card_to_deck(_card())
    assert rs.hp == 40  # no heal yet
    rs.add_card_to_deck(_card())  # 5th add
    assert rs.hp == 60  # +20


def test_chemical_x_adds_two_to_x_value():
    # An X-cost attack hitting once per energy spent; Chemical X gives +2 hits.
    xeff = Effect(op=EffectOp.DEAL_DAMAGE, amount=5, target=Target.SELECTED_ENEMY,
                  hit_count=1)
    xcard = CardDef(id="whirlwind", name="Whirlwind", cost=X_COST,
                    type=CardType.ATTACK, effects=(xeff,), count=0)
    rs, cs = _combat("CHEMICAL_X", monster_hp=500, energy=2)
    trigger_on_combat_start(rs, cs)
    assert cs.chemical_x_bonus == 2
    cs.hand = [xcard]
    before = cs.monster.hp
    cs.play_card(0)
    # X = 2 energy + 2 (Chemical X) = 4 hits of 5 = 20 damage.
    assert before - cs.monster.hp == 20


def test_lizard_tail_revives_once_per_run():
    from sim.relics import trigger_on_player_would_die
    rs, cs = _combat("LIZARD_TAIL", hp=80, max_hp=80)
    cs.player.hp = 0
    cs.player.alive = False
    trigger_on_player_would_die(rs, cs)
    assert cs.player.alive is True
    assert cs.player.hp == 40  # 50% of max
    # Second death this run -> no revive (counter used up).
    cs.player.hp = 0
    cs.player.alive = False
    trigger_on_player_would_die(rs, cs)
    assert cs.player.alive is False
