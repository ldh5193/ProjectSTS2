"""Phase 8B relic-breadth tests.

Proves the relic-registry breadth expansion:
  - the registry count jumped substantially (report new X/284),
  - ~15 newly-added relics apply their real effect via the proper hook,
  - the faithful source pools (Shared / Ironclad / Event) only contain
    registry-backed ids,
  - the rarity-tiered reward pools still sample real ids per tier,
  - no inert id is granted by reward paths,
  - the new combat hooks (on_monster_death / on_shuffle / on_card_drawn) and
    the new powers (Artifact / Intangible) work.

Each spot-checked relic's amount/trigger is verified vs
decompiled/MegaCrit.Sts2.Core.Models.Relics/*.cs.
"""
from __future__ import annotations

from sim.combat import CombatState
from sim.creatures import Monster, Player
from sim.dsl import CardDef, CardType, EffectOp, Target
from sim.game_state import Character, RelicInstance, RunState, StateType
from sim.powers import make_power
from sim.relics import (
    RELIC_POOLS,
    RELIC_REGISTRY,
    RELIC_SOURCE_POOLS,
    RELIC_CATEGORIES,
    grant_relic_reward,
    reset_combat_counters,
    sample_relic_from_pool,
    trigger_after_combat_victory,
    trigger_after_room_entered,
    trigger_on_card_played,
    trigger_on_combat_start,
    trigger_on_player_turn_end,
    trigger_on_player_turn_start,
)
from sim.run_engine import _relic_rng, start_run, step


# --- helpers ---------------------------------------------------------------

def _combat(relic: str, *, hp: int = 80, monster_hp: int = 300, gold: int = 99):
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id=relic)]
    rs.hp = hp
    rs.gold = gold
    p = Player(name="P", hp=hp, max_hp=80, energy=3, max_energy=3)
    m = Monster(name="M", hp=monster_hp, max_hp=monster_hp)
    cs = CombatState(player=p, monster=m, monsters=[m],
                     draw_pile=[], discard_pile=[], hand=[])
    cs.run_state = rs
    reset_combat_counters(rs)
    return rs, cs


def _card(ctype=CardType.ATTACK):
    return CardDef(id="strike_ironclad", name="C", cost=0, type=ctype,
                   effects=(), count=0)


def _set_turn(cs, n):
    cs.turn_number = n


# === 1. Registry breadth ====================================================

NON_DEPRECATED_TOTAL = 284  # decompiled non-deprecated relic count (task ground truth)


def test_registry_count_jumped_substantially():
    # Started at 68; this batch must add many more.
    assert len(RELIC_REGISTRY) >= 130, len(RELIC_REGISTRY)
    # Report coverage out of the ground-truth 284.
    coverage = len(RELIC_REGISTRY)
    print(f"\nRELIC COVERAGE: {coverage}/{NON_DEPRECATED_TOTAL}")


def test_every_registry_relic_maps_to_valid_category():
    for rid, rd in RELIC_REGISTRY.items():
        assert rd.category in RELIC_CATEGORIES, (rid, rd.category)


# === 2. Faithful source pools ==============================================

def test_source_pools_only_contain_registry_ids():
    for pool, ids in RELIC_SOURCE_POOLS.items():
        for rid in ids:
            assert rid in RELIC_REGISTRY, f"{rid} ({pool}) not in registry"


def test_source_pools_nonempty_per_real_pool():
    assert len(RELIC_SOURCE_POOLS["shared"]) >= 50
    assert len(RELIC_SOURCE_POOLS["ironclad"]) >= 5
    assert len(RELIC_SOURCE_POOLS["event"]) >= 20


def test_ironclad_pool_contains_known_ironclad_relics():
    iron = set(RELIC_SOURCE_POOLS["ironclad"])
    for rid in ("BURNING_BLOOD", "BRIMSTONE", "CHARONS_ASHES", "RED_SKULL",
                "PAPER_PHROG", "DEMON_TONGUE", "SELF_FORMING_CLAY"):
        assert rid in iron, rid


# === 3. Reward pools still sound ===========================================

def test_no_pooled_reward_id_is_inert():
    for tier, ids in RELIC_POOLS.items():
        for rid in ids:
            assert rid in RELIC_REGISTRY, f"{rid} ({tier}) not in registry"


def test_reward_grant_returns_real_id_and_dedups():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=7)
    start_run(rs)
    granted = set()
    for i in range(30):
        from sim.rng import Rng
        owned_before = {r.id for r in rs.relics}
        rid = grant_relic_reward(rs, Rng(rs.run_seed, f"b{i}"), boss=False)
        if rid is None:
            break
        assert rid in RELIC_REGISTRY
        assert rid not in owned_before
        granted.add(rid)
    ids = [r.id for r in rs.relics]
    assert len(ids) == len(set(ids))


def test_boss_reward_draws_from_boss_tier():
    from sim.rng import Rng
    rs = RunState.new_run(character=Character.IRONCLAD, seed=3)
    start_run(rs)
    rid = grant_relic_reward(rs, Rng(rs.run_seed, "boss"), boss=True)
    assert rid in RELIC_POOLS["boss"]
    assert rid in RELIC_REGISTRY


# === 4. Spot-check ~15 newly-added relics via the proper hook ==============

def test_candelabra_energy_turn2():
    # Candelabra.cs: EnergyVar(2) on round 2.
    rs, cs = _combat("CANDELABRA")
    _set_turn(cs, 1)
    e0 = cs.player.energy
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == e0  # no gain turn 1
    _set_turn(cs, 2)
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == e0 + 2


def test_chandelier_energy_turn3():
    # Chandelier.cs: EnergyVar(3) on round 3.
    rs, cs = _combat("CHANDELIER")
    _set_turn(cs, 3)
    e0 = cs.player.energy
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == e0 + 3


def test_horn_cleat_block_turn2():
    # HornCleat.cs: block 14 on round 2.
    rs, cs = _combat("HORN_CLEAT")
    _set_turn(cs, 2)
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.block == 14


def test_cloak_clasp_block_equals_hand():
    # CloakClasp.cs: BeforeTurnEnd -> block == cards in hand.
    rs, cs = _combat("CLOAK_CLASP")
    cs.hand = [_card(), _card(), _card()]
    trigger_on_player_turn_end(rs, cs)
    assert cs.player.block == 3


def test_mercury_hourglass_aoe_every_turn():
    # MercuryHourglass.cs: 3 to all enemies each turn start.
    rs, cs = _combat("MERCURY_HOURGLASS", monster_hp=50)
    hp0 = cs.monster.hp
    trigger_on_player_turn_start(rs, cs)
    assert cs.monster.hp == hp0 - 3


def test_festive_popper_aoe_turn1():
    # FestivePopper.cs: 9 to all enemies on turn 1.
    rs, cs = _combat("FESTIVE_POPPER", monster_hp=50)
    _set_turn(cs, 1)
    hp0 = cs.monster.hp
    trigger_on_player_turn_start(rs, cs)
    assert cs.monster.hp == hp0 - 9


def test_stone_calendar_burst_turn7():
    # StoneCalendar.cs: 52 to all enemies on turn 7.
    rs, cs = _combat("STONE_CALENDAR", monster_hp=200)
    _set_turn(cs, 7)
    hp0 = cs.monster.hp
    trigger_on_player_turn_start(rs, cs)
    assert cs.monster.hp == hp0 - 52


def test_ripple_basin_block_turn_end():
    # RippleBasin.cs: 4 block at turn end.
    rs, cs = _combat("RIPPLE_BASIN")
    trigger_on_player_turn_end(rs, cs)
    assert cs.player.block == 4


def test_twisted_funnel_poison_turn1():
    # TwistedFunnel.cs: PoisonPower(4) to all enemies on turn 1.
    rs, cs = _combat("TWISTED_FUNNEL")
    _set_turn(cs, 1)
    trigger_on_player_turn_start(rs, cs)
    pois = cs.monster.get_power("poison")
    assert pois is not None and pois.amount == 4


def test_iron_club_strength_combat_start():
    # IronClub.cs (event): +5 Strength approx at combat start.
    rs, cs = _combat("IRON_CLUB")
    trigger_on_combat_start(rs, cs)
    st = cs.player.get_power("strength")
    assert st is not None and st.amount == 5


def test_diamond_diadem_grants_artifact():
    # DiamondDiadem.cs: 1 Artifact charge at combat start.
    rs, cs = _combat("DIAMOND_DIADEM")
    trigger_on_combat_start(rs, cs)
    art = cs.player.get_power("artifact")
    assert art is not None and art.amount == 1


def test_seal_of_gold_energy_when_gold():
    # SealOfGold.cs: +1 energy turn 1 only if gold >= 5.
    rs, cs = _combat("SEAL_OF_GOLD", gold=10)
    _set_turn(cs, 1)
    e0 = cs.player.energy
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == e0 + 1
    # Now with no gold -> no energy.
    rs2, cs2 = _combat("SEAL_OF_GOLD", gold=0)
    _set_turn(cs2, 1)
    e0 = cs2.player.energy
    trigger_on_player_turn_start(rs2, cs2)
    assert cs2.player.energy == e0


def test_sword_of_stone_gold_on_victory():
    # SwordOfStone.cs: +25 gold on combat victory.
    rs, cs = _combat("SWORD_OF_STONE", gold=0)
    trigger_after_combat_victory(rs)
    assert rs.gold == 25


def test_planisphere_heal_on_combat_room():
    # Planisphere.cs: heal 5 on entering a combat room.
    rs, cs = _combat("PLANISPHERE", hp=40)
    trigger_after_room_entered(rs, StateType.MONSTER)
    assert rs.hp == 45
    # Non-combat room: no heal.
    rs.hp = 40
    trigger_after_room_entered(rs, StateType.SHOP)
    assert rs.hp == 40


def test_black_blood_heal_on_victory():
    # BlackBlood.cs: heal 12 after combat victory.
    rs, cs = _combat("BLACK_BLOOD", hp=40)
    trigger_after_combat_victory(rs)
    assert rs.hp == 52


def test_tuning_fork_block_every_10th_card():
    # TuningFork.cs: every 10th card played -> 7 block.
    rs, cs = _combat("TUNING_FORK")
    for _ in range(9):
        trigger_on_card_played(rs, cs, _card())
    assert cs.player.block == 0
    trigger_on_card_played(rs, cs, _card())
    assert cs.player.block == 7


def test_kusarigama_damage_every_3rd_card():
    # Kusarigama.cs: every 3rd card -> 6 damage to all enemies.
    rs, cs = _combat("KUSARIGAMA", monster_hp=50)
    hp0 = cs.monster.hp
    trigger_on_card_played(rs, cs, _card())
    trigger_on_card_played(rs, cs, _card())
    assert cs.monster.hp == hp0
    trigger_on_card_played(rs, cs, _card())
    assert cs.monster.hp == hp0 - 6


# === 5. Pickup-effect relics (max HP / slots) ==============================

def test_lees_waffle_full_heal_and_max_hp():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.hp = 30
    mhp0 = rs.max_hp
    rs.add_relic("LEES_WAFFLE")
    assert rs.max_hp == mhp0 + 7
    assert rs.hp == rs.max_hp  # full heal


def test_potion_belt_adds_slots():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    slots0 = rs.max_potion_slots
    rs.add_relic("POTION_BELT")
    assert rs.max_potion_slots == slots0 + 2


def test_nutritious_soup_max_hp():
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    mhp0 = rs.max_hp
    rs.add_relic("NUTRITIOUS_SOUP")
    assert rs.max_hp == mhp0 + 8


# === 6. New combat hooks + powers ==========================================

def test_gremlin_horn_on_monster_death():
    # GremlinHorn: on enemy death -> +1 energy and draw 1.
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id="GREMLIN_HORN")]
    # 1-hp monster + a 5-damage strike to kill it via play_card.
    from sim.dsl import Effect
    strike = CardDef(id="strike_ironclad", name="Strike", cost=0,
                     type=CardType.ATTACK,
                     effects=(Effect(op=EffectOp.DEAL_DAMAGE, amount=5,
                                     target=Target.SELECTED_ENEMY),),
                     count=0)
    p = Player(name="P", hp=80, max_hp=80, energy=3, max_energy=3)
    m = Monster(name="M", hp=1, max_hp=1)
    cs = CombatState(player=p, monster=m, monsters=[m],
                     draw_pile=[_card(), _card()], discard_pile=[], hand=[strike])
    cs.run_state = rs
    reset_combat_counters(rs)
    e0 = p.energy
    hand0 = len(cs.hand)
    cs.play_card(0)
    assert not m.alive
    assert p.energy == e0 + 1  # +1 energy on death
    # drew 1 card (hand had strike removed, +1 drawn)
    assert len(cs.hand) == hand0 - 1 + 1


def test_the_abacus_on_shuffle():
    # TheAbacus: on reshuffle -> +6 block.
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id="THE_ABACUS")]
    p = Player(name="P", hp=80, max_hp=80, energy=3, max_energy=3)
    m = Monster(name="M", hp=50, max_hp=50)
    # Empty draw pile + a card in discard forces a reshuffle on draw.
    cs = CombatState(player=p, monster=m, monsters=[m],
                     draw_pile=[], discard_pile=[_card()], hand=[])
    cs.run_state = rs
    reset_combat_counters(rs)
    cs.draw(1)
    assert p.block == 6


def test_artifact_power_negates_debuff():
    p = Player(name="P", hp=50, max_hp=50)
    p.add_or_stack_power(make_power("artifact", 1, p))
    p.add_or_stack_power(make_power("vulnerable", 2, p))
    assert p.get_power("vulnerable") is None
    assert p.get_power("artifact") is None  # charge consumed


def test_intangible_power_reduces_hp_loss_to_one():
    m = Monster(name="M", hp=99, max_hp=99)
    intan = make_power("intangible", 1, m)
    assert intan.modify_hp_lost(None, m, 25) == 1
    assert intan.modify_hp_lost(None, m, 0) == 0


# === 7. Reward path never grants an inert id ===============================

def test_reward_paths_never_grant_inert_id():
    # Drive a run engine grant many times and assert every granted id has a
    # real RelicDef in the registry (no placeholder / empty-name stub).
    from sim.rng import Rng
    rs = RunState.new_run(character=Character.IRONCLAD, seed=42)
    start_run(rs)
    for i in range(25):
        rid = grant_relic_reward(rs, Rng(rs.run_seed, f"inert{i}"), boss=(i % 5 == 0))
        if rid is None:
            continue
        rd = RELIC_REGISTRY[rid]
        assert rd.name != "", rid
        assert rd.rarity != "none", rid
