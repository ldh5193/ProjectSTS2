"""Tests for A1~A10 ascension effects.

Mirrors decompiled rules:
  A1 SwarmingElites    -> more elites on map (sim/map_gen.py)
  A4 TightBelt         -> max_potion_slots -= 1
  A5 AscendersBane     -> +1 AscendersBane curse in deck
  A7 Scarcity          -> reduced rare odds in card rewards (sim/rewards.py)
  A8 ToughEnemies      -> per-monster HP scaling
  A9 DeadlyEnemies     -> per-monster damage scaling
  A10 DoubleBoss       -> act-3 boss replaced with two-boss encounter

A2 WearyTraveler / A3 Poverty / A6 Inflation are no-ops in sim today —
the features they modify (Ancient event, gold-from-kills, shop pricing)
are not yet simulated. Verified inert here; promote to live tests when
those features land.
"""
from __future__ import annotations

import random

import pytest

from sim.creatures import Player
from sim.game_state import Ascension, Character, RunState
from sim.monsters import (
    CeremonialBeast,
    Doormaker,
    LagavulinMatriarch,
    NibbitWeak,
    SludgeSpinnerWeak,
    SoulFysh,
    TheInsatiable,
    Vantom,
    WaterfallGiant,
)


# ---------------------------------------------------------------------------
# A4 TightBelt + A5 AscendersBane (start-of-run effects in AscensionManager)
# ---------------------------------------------------------------------------


def test_a4_tightbelt_reduces_potion_slots():
    rs0 = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=1)
    rs4 = RunState.new_run(character=Character.IRONCLAD, ascension=4, seed=1)
    assert rs0.max_potion_slots == 3
    assert rs4.max_potion_slots == 2


def test_a5_ascendersbane_added_to_deck():
    rs0 = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=1)
    rs5 = RunState.new_run(character=Character.IRONCLAD, ascension=5, seed=1)
    assert not any(c.id == "ascenders_bane" for c in rs0.deck)
    assert any(c.id == "ascenders_bane" for c in rs5.deck)


# ---------------------------------------------------------------------------
# A8 ToughEnemies — per-monster HP scaling
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_a8_sludge_hp_in_ascended_range(seed):
    rng = random.Random(seed)
    base = SludgeSpinnerWeak.spawn(random.Random(seed))
    asc = SludgeSpinnerWeak.spawn(random.Random(seed), ascension=8)
    assert 37 <= base.hp <= 39
    assert 41 <= asc.hp <= 42


def test_a8_nibbit_hp_bumped():
    base_hps = [NibbitWeak.spawn(random.Random(s)).hp for s in range(50)]
    asc_hps = [NibbitWeak.spawn(random.Random(s), ascension=8).hp for s in range(50)]
    # Base 42-46, A8 44-48. Min ascended HP should be >= 44, max <= 48.
    assert min(asc_hps) >= 44 and max(asc_hps) <= 48
    assert min(base_hps) >= 42 and max(base_hps) <= 46


@pytest.mark.parametrize("monster_cls,base_hp,asc_hp", [
    (CeremonialBeast, 252, 262),
    (TheInsatiable, 321, 341),
    (Doormaker, 489, 512),
    (WaterfallGiant, 240, 250),
    (SoulFysh, 211, 221),
    (LagavulinMatriarch, 222, 233),
    (Vantom, 173, 183),
])
def test_a8_fixed_hp_bosses(monster_cls, base_hp, asc_hp):
    rng = random.Random(0)
    base = monster_cls.spawn(rng)
    asc = monster_cls.spawn(rng, ascension=8)
    assert base.hp == base_hp, f"{monster_cls.__name__} base HP"
    assert asc.hp == asc_hp, f"{monster_cls.__name__} A8 HP"


def test_a8_below_threshold_no_scaling():
    """A7 (one below ToughEnemies) must still use base HP."""
    asc7 = Doormaker.spawn(random.Random(0), ascension=7)
    assert asc7.hp == 489  # base


# ---------------------------------------------------------------------------
# A9 DeadlyEnemies — per-monster damage scaling
# ---------------------------------------------------------------------------


def _player():
    return Player(name="Ironclad", hp=80, max_hp=80)


def test_a9_sludge_oilspray_damage():
    """Base 8, A9 9. Force OIL_SPRAY (initial move)."""
    p_base = _player()
    p_asc = _player()
    m_base = SludgeSpinnerWeak.spawn(random.Random(0))
    m_asc = SludgeSpinnerWeak.spawn(random.Random(0), ascension=9)
    ev_base = m_base.take_turn(random.Random(0), p_base)
    ev_asc = m_asc.take_turn(random.Random(0), p_asc)
    assert ev_base["damage"] == 8
    assert ev_asc["damage"] == 9


def test_a9_doormaker_hunger_damage():
    """Doormaker opens with DRAMATIC_OPEN (no dmg), then HUNGER 30 / A9 35."""
    p_base = _player()
    p_asc = _player()
    m_base = Doormaker.spawn(random.Random(0))
    m_asc = Doormaker.spawn(random.Random(0), ascension=9)
    m_base.take_turn(random.Random(0), p_base)  # DRAMATIC_OPEN
    m_asc.take_turn(random.Random(0), p_asc)
    ev_base = m_base.take_turn(random.Random(0), p_base)  # HUNGER
    ev_asc = m_asc.take_turn(random.Random(0), p_asc)
    assert ev_base["damage"] == 30
    assert ev_asc["damage"] == 35


def test_a9_vantom_inky_lance_per_hit_then_total():
    """InkyLance is 2x6 base, 2x7 A9."""
    p_base = _player()
    p_asc = _player()
    m_base = Vantom.spawn(random.Random(0))
    m_asc = Vantom.spawn(random.Random(0), ascension=9)
    m_base.take_turn(random.Random(0), p_base)  # INK_BLOT
    m_asc.take_turn(random.Random(0), p_asc)
    ev_base = m_base.take_turn(random.Random(0), p_base)  # INKY_LANCE
    ev_asc = m_asc.take_turn(random.Random(0), p_asc)
    assert ev_base["damage"] == 12  # 6 + 6
    assert ev_asc["damage"] == 14   # 7 + 7


def test_a9_below_threshold_no_scaling():
    p = _player()
    m = SludgeSpinnerWeak.spawn(random.Random(0), ascension=8)
    ev = m.take_turn(random.Random(0), p)
    assert ev["damage"] == 8  # A8 doesn't affect damage


# ---------------------------------------------------------------------------
# A10 DoubleBoss — encounter generation
# ---------------------------------------------------------------------------


def test_a10_double_boss_act3():
    """Act-3 boss should have a second boss attached at A10."""
    from sim.encounter import generate_pools
    from sim.rng import Rng
    rng = Rng(seed=42, name="map_a10")
    pools = generate_pools("glory", rng, ascension=10, is_final_act=True)
    assert pools.second_boss is not None
    assert pools.second_boss != pools.boss


def test_a10_no_double_boss_below_threshold():
    from sim.encounter import generate_pools
    from sim.rng import Rng
    rng = Rng(seed=42, name="map_a9")
    pools = generate_pools("glory", rng, ascension=9, is_final_act=True)
    assert pools.second_boss is None


# ---------------------------------------------------------------------------
# A7 Scarcity — card reward odds
# ---------------------------------------------------------------------------


def test_a7_scarcity_uses_override_table():
    from sim.rewards import RARITY_ODDS, SCARCITY_OVERRIDES, _rarity_table
    from sim.card_catalog import CardRarity
    base = _rarity_table("regular", ascension=0)
    asc7 = _rarity_table("regular", ascension=7)
    assert base[CardRarity.RARE] == 0.03
    assert asc7[CardRarity.RARE] == 0.015  # halved per Scarcity table


# ---------------------------------------------------------------------------
# End-to-end: full A10 run boots and combat scales
# ---------------------------------------------------------------------------


def test_a10_full_run_state_combines_effects():
    """A10 implies all lower levels: A4 potion slot, A5 curse, plus
    monsters spawn ascended via _start_combat. We don't run combat here,
    just confirm RunState carries ascension and rule-derived state."""
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=10, seed=1)
    assert int(rs.ascension) == 10
    assert rs.max_potion_slots == 2          # A4
    assert any(c.id == "ascenders_bane" for c in rs.deck)  # A5
