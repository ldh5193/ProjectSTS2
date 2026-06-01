"""Phase 9.2 — Defect orb-system tests (decompile-exact values).

Ground truth: decompiled/MegaCrit.Sts2.Core.Entities.Orbs/OrbQueue.cs,
Models/OrbModel.cs, Models.Orbs/{Lightning,Frost,Dark,Plasma,Glass}Orb.cs,
Models.Powers/FocusPower.cs.
"""
import random

import pytest

from sim.combat import CombatState
from sim.orbs import Orb, OrbQueue, OrbType
from sim.powers import make_power


def _combat(capacity=3, n_monsters=1, monster_hp=200):
    cs = CombatState.new_combat(seed=1)
    # Strip the default monster down to a single fat dummy (or several) so orb
    # damage is observable without killing the target.
    from sim.creatures import Monster
    mons = [Monster(name=f"D{i}", hp=monster_hp, max_hp=monster_hp)
            for i in range(n_monsters)]
    cs.monster = mons[0]
    cs.monsters = mons
    cs.orb_queue = OrbQueue(capacity=capacity)
    cs.player.block = 0
    return cs


# ---- orb value model (Focus scaling, Plasma immunity) --------------------

def test_base_orb_values():
    f = 0
    assert Orb(OrbType.LIGHTNING).passive_value(f) == 3
    assert Orb(OrbType.LIGHTNING).evoke_value(f) == 8
    assert Orb(OrbType.FROST).passive_value(f) == 2
    assert Orb(OrbType.FROST).evoke_value(f) == 5
    assert Orb(OrbType.DARK).passive_value(f) == 6
    assert Orb(OrbType.DARK).evoke_value(f) == 6  # starting accumulator
    assert Orb(OrbType.PLASMA).passive_value(f) == 1
    assert Orb(OrbType.PLASMA).evoke_value(f) == 2
    assert Orb(OrbType.GLASS).passive_value(f) == 4
    assert Orb(OrbType.GLASS).evoke_value(f) == 8  # passive*2


def test_focus_scales_lightning_frost_dark_glass_not_plasma():
    f = 3
    assert Orb(OrbType.LIGHTNING).passive_value(f) == 6   # 3+3
    assert Orb(OrbType.LIGHTNING).evoke_value(f) == 11    # 8+3
    assert Orb(OrbType.FROST).passive_value(f) == 5       # 2+3
    assert Orb(OrbType.FROST).evoke_value(f) == 8         # 5+3
    assert Orb(OrbType.DARK).passive_value(f) == 9        # 6+3 (passive Focus-scaled)
    assert Orb(OrbType.GLASS).passive_value(f) == 7       # 4+3
    assert Orb(OrbType.GLASS).evoke_value(f) == 14        # (4+3)*2
    # Plasma is Focus-IMMUNE (PlasmaOrb returns raw 1m/2m).
    assert Orb(OrbType.PLASMA).passive_value(f) == 1
    assert Orb(OrbType.PLASMA).evoke_value(f) == 2


def test_focus_clamps_value_at_zero():
    # FocusPower.ModifyOrbValue: max(value + Amount, 0).
    assert Orb(OrbType.FROST).passive_value(-10) == 0
    assert Orb(OrbType.LIGHTNING).evoke_value(-100) == 0


# ---- queue capacity / channel / overflow ---------------------------------

def test_capacity_zero_channel_is_noop():
    cs = _combat(capacity=0)
    cs.channel_orb("lightning")
    assert cs.orb_queue.orbs == []


def test_channel_appends_in_order():
    cs = _combat(capacity=3)
    cs.channel_orb("lightning")
    cs.channel_orb("frost")
    assert [o.type for o in cs.orb_queue.orbs] == [OrbType.LIGHTNING, OrbType.FROST]


def test_overflow_evokes_front_orb():
    # A full queue channeling a new orb evokes the FRONT (oldest) orb first.
    cs = _combat(capacity=2, monster_hp=200)
    cs.channel_orb("lightning")  # front
    cs.channel_orb("frost")
    hp_before = cs.monster.hp
    cs.channel_orb("dark")       # full -> evoke front Lightning (8 dmg)
    assert cs.monster.hp == hp_before - 8
    assert [o.type for o in cs.orb_queue.orbs] == [OrbType.FROST, OrbType.DARK]


# ---- passive timing ------------------------------------------------------

def test_lightning_passive_fires_at_turn_end():
    cs = _combat(capacity=3, monster_hp=200)
    cs.channel_orb("lightning")
    hp = cs.monster.hp
    cs._fire_orb_passives("turn_end")
    assert cs.monster.hp == hp - 3


def test_frost_passive_gives_block_at_turn_end():
    cs = _combat(capacity=3)
    cs.channel_orb("frost")
    cs.player.block = 0
    cs._fire_orb_passives("turn_end")
    assert cs.player.block == 2


def test_dark_passive_accumulates_then_evoke_hits_lowest_hp():
    cs = _combat(capacity=3, n_monsters=2, monster_hp=200)
    cs.monsters[1].hp = 50  # lowest-HP target
    cs.channel_orb("dark")
    orb = cs.orb_queue.orbs[0]
    assert orb.dark_evoke == 6
    cs._fire_orb_passives("turn_end")   # +6 -> 12
    assert orb.dark_evoke == 12
    cs._fire_orb_passives("turn_end")   # +6 -> 18
    assert orb.dark_evoke == 18
    cs.evoke_front_orb()                # hits the 50-HP enemy for 18
    assert cs.monsters[1].hp == 50 - 18


def test_plasma_passive_gives_energy_at_turn_start_not_end():
    cs = _combat(capacity=3)
    cs.channel_orb("plasma")
    cs.player.energy = 3
    cs._fire_orb_passives("turn_end")   # Plasma does NOT fire at turn end
    assert cs.player.energy == 3
    cs._fire_orb_passives("turn_start") # +1 energy
    assert cs.player.energy == 4


def test_glass_passive_decrements_and_hits_all():
    cs = _combat(capacity=3, n_monsters=2, monster_hp=200)
    cs.channel_orb("glass")
    orb = cs.orb_queue.orbs[0]
    cs._fire_orb_passives("turn_end")   # 4 dmg to all, passive -> 3
    assert cs.monsters[0].hp == 200 - 4
    assert cs.monsters[1].hp == 200 - 4
    assert orb.glass_passive == 3


# ---- evoke ----------------------------------------------------------------

def test_lightning_evoke_8_to_one_enemy():
    cs = _combat(capacity=3, monster_hp=200)
    cs.channel_orb("lightning")
    hp = cs.monster.hp
    cs.evoke_front_orb()
    assert cs.monster.hp == hp - 8
    assert cs.orb_queue.is_empty()


def test_frost_evoke_5_block():
    cs = _combat(capacity=3)
    cs.channel_orb("frost")
    cs.player.block = 0
    cs.evoke_front_orb()
    assert cs.player.block == 5


def test_plasma_evoke_2_energy():
    cs = _combat(capacity=3)
    cs.channel_orb("plasma")
    cs.player.energy = 0
    cs.evoke_front_orb()
    assert cs.player.energy == 2


def test_focus_power_scales_passive_and_evoke():
    cs = _combat(capacity=3, monster_hp=200)
    cs.player.add_or_stack_power(make_power("focus", 2, cs.player))
    assert cs.orb_focus() == 2
    cs.channel_orb("lightning")
    hp = cs.monster.hp
    cs._fire_orb_passives("turn_end")   # 3+2 = 5
    assert cs.monster.hp == hp - 5
    hp = cs.monster.hp
    cs.evoke_front_orb()                 # 8+2 = 10
    assert cs.monster.hp == hp - 10


def test_capacity_add_via_card_op():
    cs = _combat(capacity=3)
    cs.add_orb_slots(2)
    assert cs.orb_queue.capacity == 5
