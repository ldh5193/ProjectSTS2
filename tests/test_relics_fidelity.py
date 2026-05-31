"""Phase 8 relic-fidelity tests.

Proves:
  1. The fixed wrong-semantics proxies now match the decompiled hooks:
       - Orichalcum: block ONLY at turn-end and ONLY if block == 0,
       - Brimstone: +2 Str self / +1 Str enemies EVERY player turn,
       - Red Skull: +3 Str only while HP <= 50%,
       - Tungsten Rod: HP loss the owner takes reduced by 1,
       - The Boot: small powered hits raised to a 5-damage floor,
       - Ginger / Turnip: Weak / Frail immunity,
       - Charon's Ashes: AoE damage on each card exhaust.
  2. Several newly-added relics apply their real effect (Sai, Nunchaku,
     Letter Opener, Happy Flower, Pendulum, energy relics).
  3. Pool sampling returns real registry ids, de-dups, and energy relics
     raise max_energy through the run engine.
"""
from __future__ import annotations

from sim.combat import CombatState
from sim.creatures import Monster, Player
from sim.damage import deal_damage
from sim.dsl import CardDef, CardType
from sim.game_state import Character, RelicInstance, RunState, StateType
from sim.powers import make_power
from sim.relics import (
    RELIC_POOLS,
    RELIC_REGISTRY,
    grant_relic_reward,
    reset_combat_counters,
    sample_relic_from_pool,
    trigger_on_combat_start,
    trigger_on_player_turn_end,
    trigger_on_player_turn_start,
)
from sim.run_engine import _relic_rng, start_run, step


# --- helpers ---------------------------------------------------------------

def _combat(relic: str, *, hp: int = 80, monster_hp: int = 300):
    rs = RunState.new_run(character=Character.IRONCLAD, seed=1)
    rs.relics = [RelicInstance(id=relic)]
    rs.hp = hp
    p = Player(name="P", hp=hp, max_hp=80, energy=3, max_energy=3)
    m = Monster(name="M", hp=monster_hp, max_hp=monster_hp)
    cs = CombatState(player=p, monster=m, monsters=[m],
                     draw_pile=[], discard_pile=[], hand=[])
    cs.run_state = rs
    reset_combat_counters(rs)
    return rs, cs


def _atk():
    return CardDef(id="strike_ironclad", name="Strike", cost=0,
                   type=CardType.ATTACK, effects=(), count=0)


def _skill():
    return CardDef(id="defend_ironclad", name="Defend", cost=0,
                   type=CardType.SKILL, effects=(), count=0)


# === 1. Fixed proxies ======================================================

def test_orichalcum_turn_end_only_when_zero_block():
    rs, cs = _combat("ORICHALCUM")
    cs.player.block = 0
    trigger_on_player_turn_end(rs, cs)
    assert cs.player.block == 6


def test_orichalcum_no_block_when_already_blocking():
    rs, cs = _combat("ORICHALCUM")
    cs.player.block = 3
    trigger_on_player_turn_end(rs, cs)
    assert cs.player.block == 3  # unchanged


def test_orichalcum_does_not_fire_at_combat_start():
    rs, cs = _combat("ORICHALCUM")
    trigger_on_combat_start(rs, cs)
    assert cs.player.block == 0  # the OLD proxy gave 6 here — must NOT now


def test_brimstone_applies_strength_every_turn():
    rs, cs = _combat("BRIMSTONE")
    trigger_on_player_turn_start(rs, cs)
    trigger_on_player_turn_start(rs, cs)
    # +2 self / +1 enemy per turn -> 4 self, 2 enemy after two turns.
    assert cs.player.get_power("strength").amount == 4
    assert cs.monster.get_power("strength").amount == 2


def test_redskull_strength_only_below_half_hp():
    rs, cs = _combat("RED_SKULL", hp=20)
    trigger_on_combat_start(rs, cs)
    assert cs.player.get_power("strength").amount == 3


def test_redskull_no_strength_above_half_hp():
    rs, cs = _combat("RED_SKULL", hp=80)
    trigger_on_combat_start(rs, cs)
    assert cs.player.get_power("strength") is None


def test_tungsten_rod_reduces_hp_loss_by_one():
    rs, cs = _combat("TUNGSTEN_ROD")
    trigger_on_combat_start(rs, cs)
    hp0 = cs.player.hp
    deal_damage(10, cs.monster, cs.player)
    assert hp0 - cs.player.hp == 9


def test_the_boot_raises_small_powered_hits_to_five():
    rs, cs = _combat("THE_BOOT")
    trigger_on_combat_start(rs, cs)
    mhp = cs.monster.hp
    deal_damage(3, cs.player, cs.monster)
    assert mhp - cs.monster.hp == 5


def test_the_boot_leaves_large_hits_unchanged():
    rs, cs = _combat("THE_BOOT")
    trigger_on_combat_start(rs, cs)
    mhp = cs.monster.hp
    deal_damage(9, cs.player, cs.monster)
    assert mhp - cs.monster.hp == 9


def test_ginger_grants_weak_immunity():
    rs, cs = _combat("GINGER")
    trigger_on_combat_start(rs, cs)
    cs.player.add_or_stack_power(make_power("weak", 2, cs.player))
    assert cs.player.get_power("weak") is None


def test_turnip_grants_frail_immunity():
    rs, cs = _combat("TURNIP")
    trigger_on_combat_start(rs, cs)
    cs.player.add_or_stack_power(make_power("frail", 2, cs.player))
    assert cs.player.get_power("frail") is None


def test_charons_ashes_damages_all_on_exhaust():
    rs, cs = _combat("CHARONS_ASHES")
    trigger_on_combat_start(rs, cs)
    mhp = cs.monster.hp
    cs._exhaust_card(_atk())
    assert mhp - cs.monster.hp == 3


# === 2. Newly-added relics =================================================

def test_sai_grants_block_each_turn():
    rs, cs = _combat("SAI")
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.block == 7
    cs.player.block = 0
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.block == 7  # again next turn


def test_nunchaku_grants_energy_on_tenth_attack():
    rs, cs = _combat("NUNCHAKU")
    cs.player.energy = 3
    for _ in range(9):
        cs.hand = [_atk()]
        cs.play_card(0)
    assert cs.player.energy == 3  # not yet (0-cost cards spend nothing)
    cs.hand = [_atk()]
    cs.play_card(0)  # 10th
    assert cs.player.energy == 4


def test_letter_opener_damages_all_on_third_skill():
    rs, cs = _combat("LETTER_OPENER")
    mhp = cs.monster.hp
    for _ in range(2):
        cs.hand = [_skill()]
        cs.play_card(0)
    assert cs.monster.hp == mhp  # not yet
    cs.hand = [_skill()]
    cs.play_card(0)  # 3rd skill
    assert mhp - cs.monster.hp == 5


def test_letter_opener_ignores_attacks():
    rs, cs = _combat("LETTER_OPENER")
    mhp = cs.monster.hp
    for _ in range(3):
        cs.hand = [_atk()]
        cs.play_card(0)
    assert cs.monster.hp == mhp  # attacks resolve no effects + no relic trigger


def test_happy_flower_energy_every_third_turn():
    rs, cs = _combat("HAPPY_FLOWER")
    cs.player.energy = 3
    for _ in range(2):
        trigger_on_player_turn_start(rs, cs)
    assert cs.player.energy == 3
    trigger_on_player_turn_start(rs, cs)  # 3rd turn
    assert cs.player.energy == 4


def test_pendulum_draws_every_third_turn():
    rs, cs = _combat("PENDULUM")
    cs.draw_pile = [_atk() for _ in range(5)]
    for _ in range(2):
        trigger_on_player_turn_start(rs, cs)
    assert len(cs.hand) == 0
    trigger_on_player_turn_start(rs, cs)  # 3rd turn -> draw 1
    assert len(cs.hand) == 1


def test_captains_wheel_block_on_third_turn_only():
    rs, cs = _combat("CAPTAINS_WHEEL")
    cs.turn_number = 1
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.block == 0
    cs.turn_number = 3
    trigger_on_player_turn_start(rs, cs)
    assert cs.player.block == 18


def test_per_combat_counter_resets_between_combats():
    rs, cs = _combat("NUNCHAKU")
    cs.player.energy = 3
    for _ in range(5):
        cs.hand = [_atk()]
        cs.play_card(0)
    inst = next(r for r in rs.relics if r.id == "NUNCHAKU")
    assert inst.counter == 5
    reset_combat_counters(rs)
    assert inst.counter == 0


# === 3. Energy relics raise max_energy (run-engine path) ===================

def _start_combat_run(relic: str) -> CombatState:
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=5)
    rs.relics.append(RelicInstance(id=relic))
    start_run(rs)
    step(rs, {"action": "choose_map_node", "node_index": 0})
    return rs.combat


def test_spiked_gauntlets_raises_max_energy():
    cs = _start_combat_run("SPIKED_GAUNTLETS")
    assert cs is not None
    assert cs.player.max_energy == 4
    assert cs.player.energy == 4


def test_philosophers_stone_raises_energy_and_buffs_enemies():
    cs = _start_combat_run("PHILOSOPHERS_STONE")
    assert cs.player.max_energy == 4
    # downside: every monster starts with +1 Strength.
    assert all(m.get_power("strength") is not None
               and m.get_power("strength").amount >= 1
               for m in cs.monsters)


def test_all_energy_relics_are_energy_category():
    energy_ids = [rid for rid, rd in RELIC_REGISTRY.items()
                  if rd.category == "energy"]
    # The classic energy relics must be present and categorised.
    for rid in ("ECTOPLASM", "SOZU", "SPIKED_GAUNTLETS",
                "WHISPERING_EARRING", "PRISMATIC_GEM"):
        assert rid in energy_ids


# === 4. Pools + rarity =====================================================

def test_pools_only_contain_real_registry_ids():
    for tier, ids in RELIC_POOLS.items():
        for rid in ids:
            assert rid in RELIC_REGISTRY, f"{rid} ({tier}) not in registry"


def test_pools_derived_from_rarity():
    # Every common/uncommon/rare-rarity relic lands in the matching tier.
    for rid, rd in RELIC_REGISTRY.items():
        if rd.rarity == "common":
            assert rid in RELIC_POOLS["common"]
        elif rd.rarity == "uncommon":
            assert rid in RELIC_POOLS["uncommon"]
        elif rd.rarity == "ancient":
            assert rid in RELIC_POOLS["boss"]


def test_boss_pool_holds_ancient_energy_relics():
    for rid in ("ECTOPLASM", "SOZU"):
        assert rid in RELIC_POOLS["boss"]


def test_sample_returns_real_registry_id():
    from sim.rng import Rng
    rid = sample_relic_from_pool(Rng(0, "x"), owned=set(), boss=False)
    assert rid in RELIC_REGISTRY


def test_sample_dedups_owned():
    from sim.rng import Rng
    rs = RunState.new_run(character=Character.IRONCLAD, seed=42)
    granted = set()
    for i in range(60):
        owned = {r.id for r in rs.relics}
        rid = grant_relic_reward(rs, Rng(rs.run_seed, f"dedup_{i}"), boss=False)
        if rid is None:
            break
        assert rid not in owned
        granted.add(rid)
    ids = [r.id for r in rs.relics]
    assert len(ids) == len(set(ids))  # no duplicates ever added


def test_boss_grant_from_boss_pool():
    from sim.rng import Rng
    rs = RunState.new_run(character=Character.IRONCLAD, seed=3)
    rid = grant_relic_reward(rs, Rng(rs.run_seed, "boss"), boss=True)
    assert rid in RELIC_POOLS["boss"]


def test_combat_start_dispatch_never_raises():
    for rid, rd in RELIC_REGISTRY.items():
        if rd.on_combat_start is None:
            continue
        rs, cs = _combat(rid)
        trigger_on_combat_start(rs, cs)


def test_turn_hooks_dispatch_never_raise():
    for rid, rd in RELIC_REGISTRY.items():
        rs, cs = _combat(rid)
        cs.draw_pile = [_atk() for _ in range(5)]
        trigger_on_player_turn_start(rs, cs)
        trigger_on_player_turn_end(rs, cs)
