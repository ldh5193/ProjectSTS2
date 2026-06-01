"""Phase 9.2 — Defect card / relic / power tests (decompile-exact values)."""
import random

import pytest

from sim.combat import CombatState
from sim.orbs import OrbQueue, OrbType
from sim.card_catalog import (
    CARDS, RARITY_OF, CHARACTER_CARD_POOLS, CardRarity, is_implemented,
)
from sim.cards import upgrade_card, build_starting_deck
from sim.dsl import CardType
from sim.game_state import Character, RunState
from sim.powers import make_power


def _combat(capacity=3, n_monsters=1, monster_hp=300):
    cs = CombatState.new_combat(seed=2)
    from sim.creatures import Monster
    mons = [Monster(name=f"D{i}", hp=monster_hp, max_hp=monster_hp)
            for i in range(n_monsters)]
    cs.monster = mons[0]
    cs.monsters = mons
    cs.orb_queue = OrbQueue(capacity=capacity)
    cs.player.energy = 99
    cs.player.block = 0
    return cs


def _play(cs, card, target=0):
    cs.hand.append(card)
    cs.target_index = target
    cs.play_card(len(cs.hand) - 1)


# ---- starting deck / setup ------------------------------------------------

def test_defect_starting_deck_exact():
    deck = build_starting_deck("defect")
    from collections import Counter
    c = Counter(card.id for card in deck)
    assert c["strike_defect"] == 4
    assert c["defend_defect"] == 4
    assert c["zap"] == 1
    assert c["dualcast"] == 1
    assert len(deck) == 10


def test_defect_run_setup():
    rs = RunState.new_run(character=Character.DEFECT, ascension=0, seed=1)
    assert rs.max_hp == 75 and rs.hp == 75          # Defect.cs StartingHp
    assert rs.gold == 99
    assert rs.orb_slots == 3                          # BaseOrbSlotCount
    assert rs.has_relic("CRACKED_CORE")


# ---- signature cards ------------------------------------------------------

def test_zap_channels_one_lightning():
    cs = _combat()
    _play(cs, CARDS["zap"])
    assert [o.type for o in cs.orb_queue.orbs] == [OrbType.LIGHTNING]


def test_dualcast_evokes_front_twice():
    # Dualcast evokes the front orb twice. With one Lightning queued, it evokes
    # it (8 dmg), then the queue is empty so the 2nd evoke is a no-op.
    cs = _combat(monster_hp=300)
    cs.channel_orb("lightning")
    hp = cs.monster.hp
    _play(cs, CARDS["dualcast"])
    assert cs.monster.hp == hp - 8
    assert cs.orb_queue.is_empty()


def test_ball_lightning_damage_and_channel():
    cs = _combat(monster_hp=300)
    hp = cs.monster.hp
    _play(cs, CARDS["ball_lightning"])
    assert cs.monster.hp == hp - 7                    # 7 dmg
    assert [o.type for o in cs.orb_queue.orbs] == [OrbType.LIGHTNING]


def test_cold_snap_damage_and_frost():
    cs = _combat(monster_hp=300)
    hp = cs.monster.hp
    _play(cs, CARDS["cold_snap"])
    assert cs.monster.hp == hp - 6
    assert [o.type for o in cs.orb_queue.orbs] == [OrbType.FROST]


def test_glacier_block_and_two_frost():
    cs = _combat()
    _play(cs, CARDS["glacier"])
    assert cs.player.block == 6
    assert [o.type for o in cs.orb_queue.orbs] == [OrbType.FROST, OrbType.FROST]


def test_chill_channels_frost_per_enemy():
    cs = _combat(n_monsters=3)
    _play(cs, CARDS["chill"])
    assert [o.type for o in cs.orb_queue.orbs] == [OrbType.FROST] * 3


def test_capacitor_adds_two_slots():
    cs = _combat(capacity=3)
    _play(cs, CARDS["capacitor"])
    assert cs.orb_queue.capacity == 5


def test_defragment_grants_focus():
    cs = _combat()
    _play(cs, CARDS["defragment"])
    assert cs.player.get_power("focus").amount == 1


def test_tempest_x_cost_channels_lightning_per_energy():
    cs = _combat(capacity=10)
    cs.player.energy = 3
    _play(cs, CARDS["tempest"])
    assert len([o for o in cs.orb_queue.orbs if o.type is OrbType.LIGHTNING]) == 3
    assert cs.player.energy == 0


def test_barrage_hits_per_orb():
    cs = _combat(monster_hp=300)
    cs.channel_orb("lightning")
    cs.channel_orb("frost")  # 2 orbs -> 2 hits of 5
    hp = cs.monster.hp
    _play(cs, CARDS["barrage"])
    assert cs.monster.hp == hp - 10


def test_multicast_evokes_all_orbs():
    cs = _combat(capacity=3, monster_hp=300)
    cs.channel_orb("lightning")  # 8
    cs.channel_orb("lightning")  # 8
    hp = cs.monster.hp
    _play(cs, CARDS["multi_cast"])
    assert cs.orb_queue.is_empty()
    assert cs.monster.hp == hp - 16


def test_double_energy_doubles_current():
    # DoubleEnergy costs 1: pay 1 (4 -> 3), then double current energy (3 -> 6).
    cs = _combat()
    cs.player.energy = 4
    _play(cs, CARDS["double_energy"])
    assert cs.player.energy == 6


def test_rainbow_channels_three_orb_types():
    cs = _combat(capacity=5)
    _play(cs, CARDS["rainbow"])
    assert [o.type for o in cs.orb_queue.orbs] == [
        OrbType.LIGHTNING, OrbType.FROST, OrbType.DARK]


# ---- Defect powers --------------------------------------------------------

def test_thunder_power_damages_on_evoke():
    cs = _combat(monster_hp=300)
    cs.player.add_or_stack_power(make_power("thunder", 6, cs.player))
    cs.channel_orb("frost")  # evoke gives block; Thunder adds 6 dmg to targets
    # Frost evoke targets the player (block); Thunder deals to those targets,
    # which is the player — so use Lightning to verify enemy damage instead.
    cs.orb_queue.orbs.clear()
    cs.channel_orb("lightning")
    hp = cs.monster.hp
    cs.evoke_front_orb()  # 8 (lightning) + 6 (thunder) to the same enemy
    assert cs.monster.hp == hp - 14


def test_storm_channels_lightning_on_power_play():
    cs = _combat()
    cs.player.add_or_stack_power(make_power("storm", 1, cs.player))
    # Playing a POWER card channels a Lightning orb.
    _play(cs, CARDS["defragment"])  # a Power card
    assert any(o.type is OrbType.LIGHTNING for o in cs.orb_queue.orbs)


def test_loop_retriggers_front_orb_at_turn_start():
    cs = _combat(monster_hp=300)
    cs.player.add_or_stack_power(make_power("loop", 1, cs.player))
    cs.channel_orb("lightning")
    hp = cs.monster.hp
    cs._fire_power_hook(cs.player, "on_turn_start", cs, cs.player)
    # Loop triggers the front orb's passive once (3 dmg).
    assert cs.monster.hp == hp - 3


def test_biased_cognition_grants_focus_and_decays():
    cs = _combat()
    _play(cs, CARDS["biased_cognition"])
    assert cs.player.get_power("focus").amount == 4
    # At turn end, BiasedCognition removes 1 Focus.
    cs._fire_power_hook(cs.player, "on_turn_end", cs, cs.player)
    assert cs.player.get_power("focus").amount == 3


def test_hailstorm_aoe_per_frost_orb_at_turn_end():
    cs = _combat(n_monsters=2, monster_hp=300)
    cs.player.add_or_stack_power(make_power("hailstorm", 6, cs.player))
    cs.channel_orb("frost")
    cs.channel_orb("frost")  # 2 frost orbs -> 6 dmg ×2 to all
    hp0, hp1 = cs.monsters[0].hp, cs.monsters[1].hp
    cs._fire_power_hook(cs.player, "on_turn_end", cs, cs.player)
    assert cs.monsters[0].hp == hp0 - 12
    assert cs.monsters[1].hp == hp1 - 12


# ---- upgrades -------------------------------------------------------------

def test_upgrade_zap_cost_zero():
    z = upgrade_card(CARDS["zap"])
    assert z.cost == 0


def test_upgrade_ball_lightning_damage():
    bl = upgrade_card(CARDS["ball_lightning"])
    dmg = next(e.amount for e in bl.effects if e.op.name == "DEAL_DAMAGE")
    assert dmg == 10  # 7 -> 10


def test_upgrade_glacier_block_and_channel_preserved():
    g = upgrade_card(CARDS["glacier"])
    blk = next(e.amount for e in g.effects if e.op.name == "GAIN_BLOCK")
    assert blk == 9  # 6 -> 9
    chans = [e for e in g.effects if e.op.name == "CHANNEL_ORB"]
    assert chans and chans[0].amount == 2


# ---- card pool ------------------------------------------------------------

def test_defect_pool_has_88_cards():
    import sim.card_catalog as cc
    ids = set(m[0] for m in cc._DEFECT_META)
    assert len(ids) == 88


def test_defect_reward_pool_populated():
    pool = CHARACTER_CARD_POOLS["defect"]
    assert len(pool[CardRarity.COMMON]) > 0
    assert len(pool[CardRarity.UNCOMMON]) > 0
    assert len(pool[CardRarity.RARE]) > 0


# ---- CrackedCore + relic pool --------------------------------------------

def test_cracked_core_channels_lightning_on_combat_start():
    from sim.relics import trigger_on_combat_start
    rs = RunState.new_run(character=Character.DEFECT, ascension=0, seed=3)
    cs = _combat()
    cs.run_state = rs
    trigger_on_combat_start(rs, cs)
    assert any(o.type is OrbType.LIGHTNING for o in cs.orb_queue.orbs)


def test_symbiotic_virus_channels_dark():
    from sim.relics import RELIC_REGISTRY
    cs = _combat()
    RELIC_REGISTRY["SYMBIOTIC_VIRUS"].on_combat_start(None, cs)
    assert any(o.type is OrbType.DARK for o in cs.orb_queue.orbs)


def test_runic_capacitor_adds_three_slots():
    from sim.relics import RELIC_REGISTRY
    cs = _combat(capacity=3)
    RELIC_REGISTRY["RUNIC_CAPACITOR"].on_combat_start(None, cs)
    assert cs.orb_queue.capacity == 6


def test_gold_plated_cables_front_orb_extra_trigger():
    from sim.relics import RELIC_REGISTRY
    cs = _combat(monster_hp=300)
    rs = RunState.new_run(character=Character.DEFECT, seed=4)
    rs.add_relic("GOLD_PLATED_CABLES")
    cs.run_state = rs
    cs.channel_orb("lightning")  # front
    cs.channel_orb("lightning")
    hp = cs.monster.hp
    cs._fire_orb_passives("turn_end")
    # Front orb fires 2× (3+3=6), second fires 1× (3) -> 9 total.
    assert cs.monster.hp == hp - 9


def test_metronome_seventh_orb_aoe():
    from sim.relics import RELIC_REGISTRY
    cs = _combat(capacity=10, n_monsters=1, monster_hp=300)
    rs = RunState.new_run(character=Character.DEFECT, seed=5)
    rs.add_relic("METRONOME")
    cs.run_state = rs
    hp = cs.monster.hp
    for _ in range(6):
        cs.channel_orb("frost")  # frost passive only fires at turn end; safe
    assert cs.monster.hp == hp  # no AoE yet
    cs.channel_orb("frost")      # 7th -> 30 AoE
    assert cs.monster.hp == hp - 30


def test_defect_relic_pool_has_seven_droppable():
    from sim.relics import character_relic_pool_ids
    ids = character_relic_pool_ids("defect")
    assert len(ids) == 7
    assert "RUNIC_CAPACITOR" in ids and "METRONOME" in ids


# ---- A0 integration run ---------------------------------------------------

def test_defect_a0_integration_reaches_deep_floors():
    """A random-legal-action Defect run at A0 advances through several floors
    drawing from the orb-driven Defect deck without exceptions."""
    from sim.env_run import RunEnv
    env = RunEnv(ascension=0, character=Character.DEFECT)
    obs, info = env.reset(seed=777)
    max_floor = 0
    for _ in range(4000):
        mask = env.action_masks()
        legal = [i for i, m in enumerate(mask) if m]
        if not legal:
            break
        a = random.Random(env.rs.floor * 7 + len(legal)).choice(legal)
        obs, r, term, trunc, info = env.step(a)
        max_floor = max(max_floor, env.rs.floor)
        if term or trunc:
            obs, info = env.reset(seed=778)
    assert max_floor >= 3
