"""Phase 8B.6 relics tranche — SharedRelicPool completion (118/118).

Each test asserts the newly-implemented relic's hook fires with the exact
effect (state before/after), using the real numbers from the decompiled
Relics/*.cs. Documented-no-op relics are asserted registered + pooled (so the
pool distribution stays faithful) without claiming a combat effect.

Ground truth: decompiled/MegaCrit.Sts2.Core.Models.Relics/*.cs
              decompiled/MegaCrit.Sts2.Core.Models.RelicPools/SharedRelicPool.cs
"""
from __future__ import annotations

from sim.combat import CombatState
from sim.creatures import Monster, Player
from sim.dsl import CardDef, CardType
from sim.game_state import Character, RelicInstance, RunState, StateType
from sim.relics import (
    RELIC_REGISTRY,
    RELIC_SOURCE_POOLS,
    reset_combat_counters,
    trigger_after_combat_victory,
    trigger_after_room_entered,
    trigger_on_card_exhausted,
    trigger_on_card_played,
    trigger_on_combat_start,
    trigger_on_player_turn_start,
    trigger_on_potion_used,
)


# --- helpers ---------------------------------------------------------------

def _combat(relic: str, *, hp: int = 80, max_hp: int = 80, monster_hp: int = 300,
            gold: int = 99, draw_n: int = 0):
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id=relic)]
    rs.hp = hp
    rs.max_hp = max_hp
    rs.gold = gold
    p = Player(name="P", hp=hp, max_hp=max_hp, energy=3, max_energy=3)
    m = Monster(name="M", hp=monster_hp, max_hp=monster_hp)
    draw = [_card(CardType.SKILL) for _ in range(draw_n)]
    cs = CombatState(player=p, monster=m, monsters=[m],
                     draw_pile=draw, discard_pile=[], hand=[])
    cs.run_state = rs
    reset_combat_counters(rs)
    return rs, cs


def _card(ctype=CardType.ATTACK):
    return CardDef(id="strike_ironclad", name="C", cost=0, type=ctype,
                   effects=(), count=0)


# === Registry / pool coverage ==============================================

SHARED_118 = [
    # All 118 SharedRelicPool ids (UPPER_SNAKE of the decompiled class names).
    "AKABEKO", "AMETHYST_AUBERGINE", "ANCHOR", "ART_OF_WAR", "BAG_OF_MARBLES",
    "BAG_OF_PREPARATION", "BEATING_REMNANT", "BELLOWS", "BELT_BUCKLE",
    "BLOOD_VIAL", "BOOK_OF_FIVE_RINGS", "BOWLER_HAT", "BREAD", "BRONZE_SCALES",
    "BURNING_STICKS", "CANDELABRA", "CAPTAINS_WHEEL", "CAULDRON",
    "CENTENNIAL_PUZZLE", "CHANDELIER", "CHEMICAL_X", "CLOAK_CLASP", "DINGY_RUG",
    "DOLLYS_MIRROR", "DRAGON_FRUIT", "ETERNAL_FEATHER", "FESTIVE_POPPER",
    "FRESNEL_LENS", "FROZEN_EGG", "GAMBLING_CHIP", "GAME_PIECE", "GHOST_SEED",
    "GIRYA", "GNARLED_HAMMER", "GORGET", "GREMLIN_HORN", "HAPPY_FLOWER",
    "HORN_CLEAT", "ICE_CREAM", "INTIMIDATING_HELMET", "JOSS_PAPER",
    "JUZU_BRACELET", "KIFUDA", "KUNAI", "KUSARIGAMA", "LANTERN", "LASTING_CANDY",
    "LAVA_LAMP", "LEES_WAFFLE", "LETTER_OPENER", "LIZARD_TAIL", "LOOMING_FRUIT",
    "LUCKY_FYSH", "MANGO", "MEAL_TICKET", "MEAT_ON_THE_BONE", "MEMBERSHIP_CARD",
    "MERCURY_HOURGLASS", "MINIATURE_CANNON", "MINIATURE_TENT", "MOLTEN_EGG",
    "MUMMIFIED_HAND", "MYSTIC_LIGHTER", "NUNCHAKU", "ODDLY_SMOOTH_STONE",
    "OLD_COIN", "ORICHALCUM", "ORNAMENTAL_FAN", "ORRERY", "PANTOGRAPH",
    "PARRYING_SHIELD", "PEAR", "PEN_NIB", "PENDULUM", "PERMAFROST",
    "PETRIFIED_TOAD", "PLANISPHERE", "POCKETWATCH", "POTION_BELT", "PRAYER_WHEEL",
    "PUNCH_DAGGER", "RAINBOW_RING", "RAZOR_TOOTH", "RED_MASK", "REGAL_PILLOW",
    "REPTILE_TRINKET", "RINGING_TRIANGLE", "RIPPLE_BASIN", "ROYAL_STAMP",
    "SCREAMING_FLAGON", "SHOVEL", "SHURIKEN", "SLING_OF_COURAGE",
    "SPARKLING_ROUGE", "STONE_CALENDAR", "STONE_CRACKER", "STRAWBERRY",
    "STRIKE_DUMMY", "STURDY_CLAMP", "THE_ABACUS", "THE_COURIER", "TINY_MAILBOX",
    "TOOLBOX", "TOXIC_EGG", "TUNGSTEN_ROD", "TUNING_FORK", "UNCEASING_TOP",
    "UNSETTLING_LAMP", "VAJRA", "VAMBRACE", "VENERABLE_TEA_SET", "VERY_HOT_COCOA",
    "VEXING_PUZZLEBOX", "WAR_PAINT", "WHETSTONE", "WHITE_BEAST_STATUE",
    "WHITE_STAR", "WING_CHARM",
]


def test_all_shared_pool_relics_registered():
    assert len(SHARED_118) == 118
    missing = [r for r in SHARED_118 if r not in RELIC_REGISTRY]
    assert not missing, f"missing shared relics: {missing}"


def test_all_shared_relics_in_source_pool():
    shared = set(RELIC_SOURCE_POOLS["shared"])
    missing = [r for r in SHARED_118 if r not in shared]
    assert not missing, f"shared relics not in source pool: {missing}"


def test_registry_count_after_tranche():
    # Baseline was 135; this tranche brings Shared to full coverage.
    assert len(RELIC_REGISTRY) >= 170, len(RELIC_REGISTRY)


# === Implemented combat / run-state effects ================================

def test_amethyst_aubergine_gold_on_victory():
    # AmethystAubergine.cs: GoldVar(15) after a combat room.
    rs, _ = _combat("AMETHYST_AUBERGINE", gold=50)
    trigger_after_combat_victory(rs)
    assert rs.gold == 65


def test_game_piece_draws_on_power_card():
    # GamePiece.cs: AfterCardPlayed (Power) -> draw CardsVar(1).
    rs, cs = _combat("GAME_PIECE", draw_n=3)
    before = len(cs.hand)
    trigger_on_card_played(rs, cs, _card(CardType.POWER))
    assert len(cs.hand) == before + 1
    # Attacks/Skills do not trigger a draw.
    before = len(cs.hand)
    trigger_on_card_played(rs, cs, _card(CardType.ATTACK))
    assert len(cs.hand) == before


def test_joss_paper_draws_every_fifth_exhaust():
    # JossPaper.cs: every ExhaustAmount(5) cards exhausted -> draw CardsVar(1).
    rs, cs = _combat("JOSS_PAPER", draw_n=10)
    start = len(cs.hand)
    for i in range(4):
        trigger_on_card_exhausted(rs, cs, _card())
    assert len(cs.hand) == start, "no draw before the 5th exhaust"
    trigger_on_card_exhausted(rs, cs, _card())
    assert len(cs.hand) == start + 1, "draw 1 on the 5th exhaust"
    for i in range(4):
        trigger_on_card_exhausted(rs, cs, _card())
    assert len(cs.hand) == start + 1
    trigger_on_card_exhausted(rs, cs, _card())
    assert len(cs.hand) == start + 2, "draw again on the 10th exhaust"


def test_reptile_trinket_strength_on_potion_use():
    # ReptileTrinket.cs: AfterPotionUsed in combat -> +PowerVar<Strength>(3).
    rs, cs = _combat("REPTILE_TRINKET")
    assert cs.player.get_power("strength") is None
    trigger_on_potion_used(rs, cs, "STRENGTH_POTION")
    st = cs.player.get_power("strength")
    assert st is not None and st.amount == 3
    # Stacks on a second potion.
    trigger_on_potion_used(rs, cs, "BLOCK_POTION")
    assert cs.player.get_power("strength").amount == 6


def test_ringing_triangle_retains_hand_turn1():
    # RingingTriangle.cs: hand not flushed while RoundNumber == 1.
    rs, cs = _combat("RINGING_TRIANGLE")
    trigger_on_combat_start(rs, cs)
    assert cs.player.get_power("retain_hand") is not None


def test_sparkling_rouge_str_dex_on_turn3():
    # SparklingRouge.cs: round 3 -> +1 Strength, +1 Dexterity.
    rs, cs = _combat("SPARKLING_ROUGE")
    cs.turn_number = 2
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.get_power("strength") is None
    cs.turn_number = 3
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.get_power("strength").amount == 1
    assert cs.player.get_power("dexterity").amount == 1


def test_sturdy_clamp_caps_block_retention():
    # SturdyClamp.cs: block not cleared at turn start; capped to BlockVar(10).
    rs, cs = _combat("STURDY_CLAMP")
    trigger_on_combat_start(rs, cs)
    cs.player.block = 25
    cs.start_player_turn()
    assert cs.player.block == 10, "retained block capped at 10"
    # Below the cap, all block is retained.
    cs.player.block = 6
    cs.start_player_turn()
    assert cs.player.block == 6


def test_beating_remnant_caps_turn_hp_loss():
    # BeatingRemnant.cs: total unblocked HP loss per turn capped to 20.
    from sim.damage import deal_damage
    rs, cs = _combat("BEATING_REMNANT", hp=80, max_hp=80)
    trigger_on_combat_start(rs, cs)
    cs.start_player_turn()  # resets the per-turn accumulator
    hp0 = cs.player.hp
    deal_damage(15, cs.monster, cs.player)   # 15 of the 20 budget
    deal_damage(15, cs.monster, cs.player)   # only 5 more should land
    assert hp0 - cs.player.hp == 20, (hp0, cs.player.hp)
    # Next turn the budget refreshes.
    cs.start_player_turn()
    hp1 = cs.player.hp
    deal_damage(15, cs.monster, cs.player)
    assert hp1 - cs.player.hp == 15


def test_venerable_tea_set_energy_after_rest():
    # VenerableTeaSet.cs: rest -> +EnergyVar(2) at next combat's energy reset.
    rs, cs = _combat("VENERABLE_TEA_SET")
    # Not armed yet: no bonus.
    e0 = cs.player.energy
    trigger_on_combat_start(rs, cs)
    assert cs.player.energy == e0
    # Arm via rest, then a fresh combat grants +2.
    trigger_after_room_entered(rs, StateType.REST)
    assert rs.venerable_tea_armed is True
    rs2, cs2 = _combat("VENERABLE_TEA_SET")
    rs2.venerable_tea_armed = True
    e1 = cs2.player.energy
    trigger_on_combat_start(rs2, cs2)
    assert cs2.player.energy == e1 + 2
    assert rs2.venerable_tea_armed is False  # consumed


def test_looming_fruit_max_hp_on_pickup():
    # LoomingFruit.cs: MaxHpVar(31) on pickup.
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.hp = rs.max_hp = 80
    rs.add_relic("LOOMING_FRUIT")
    assert rs.max_hp == 111
    assert rs.hp == 111


def test_cauldron_grants_potions_on_pickup():
    # Cauldron.cs: Potions(5) on pickup.
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.potions = [None, None, None]
    rs.max_potion_slots = 3
    rs.add_relic("CAULDRON")
    filled = [p for p in rs.potions if p is not None]
    assert len(filled) == 3, "fills all 3 starting slots"


# === Documented no-ops stay inert in combat ================================

NOOP_RELICS = [
    "BOOK_OF_FIVE_RINGS", "RAZOR_TOOTH", "STONE_CRACKER", "LAVA_LAMP",
    "GHOST_SEED", "BURNING_STICKS", "DINGY_RUG", "DOLLYS_MIRROR", "FRESNEL_LENS",
    "GNARLED_HAMMER", "KIFUDA", "PUNCH_DAGGER", "ROYAL_STAMP", "WING_CHARM",
    "MYSTIC_LIGHTER", "LASTING_CANDY", "ORRERY", "MINIATURE_TENT", "TINY_MAILBOX",
    "LUCKY_FYSH", "BOWLER_HAT", "CHEMICAL_X", "LIZARD_TAIL", "VEXING_PUZZLEBOX",
]


def test_documented_noops_registered_and_pooled():
    shared = set(RELIC_SOURCE_POOLS["shared"])
    for rid in NOOP_RELICS:
        assert rid in RELIC_REGISTRY, rid
        assert rid in shared, rid


def test_documented_noops_have_no_combat_hooks():
    # The no-op relics must NOT silently fire a combat effect — they have no
    # on_combat_start / on_player_turn_start / per-card hooks wired.
    for rid in NOOP_RELICS:
        rd = RELIC_REGISTRY[rid]
        assert rd.on_combat_start is None, rid
        assert rd.on_player_turn_start is None, rid
        assert rd.on_card_played is None, rid
        assert rd.on_player_turn_end is None, rid
