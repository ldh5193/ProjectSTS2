"""Tier-1 power effects (Thorns / Plating / Poison / Dexterity / Frail)."""
from __future__ import annotations

from sim.creatures import Player
from sim.damage import apply_poison_tick, deal_damage, gain_block
from sim.monsters import SludgeSpinnerWeak
from sim.powers import make_power


def _player(hp: int = 80) -> Player:
    return Player(name="Ironclad", hp=hp, max_hp=hp, energy=3, max_energy=3)


def _monster(hp: int = 40) -> SludgeSpinnerWeak:
    return SludgeSpinnerWeak(name="Sludge Spinner", hp=hp, max_hp=hp)


def test_thorns_reflects_unblocked_damage_to_attacker():
    p, m = _player(80), _monster(40)
    p.add_or_stack_power(make_power("thorns", 3, p))
    # Monster attacks player for 6 → player blocks 0, takes 6, thorns 3 back.
    deal_damage(6, m, p)
    assert p.hp == 74
    assert m.hp == 37  # 40 - 3 thorns


def test_thorns_only_fires_when_unblocked_damage_landed():
    p, m = _player(80), _monster(40)
    p.add_or_stack_power(make_power("thorns", 5, p))
    p.block = 20  # fully absorbs the 6-dmg hit
    deal_damage(6, m, p)
    assert p.hp == 80
    assert p.block == 14
    assert m.hp == 40  # no thorns fired because nothing got through


def test_plating_does_not_reduce_hp_loss_on_hit():
    # Faithful (PlatingPower.cs): Plating is NOT damage reduction. A hit
    # against a Plating owner deals full HP loss; Plating only grants block
    # at the owner's turn end.
    p, m = _player(80), _monster(40)
    p.add_or_stack_power(make_power("plating", 2, p))
    deal_damage(6, m, p)
    assert p.hp == 74  # full 6 damage, no reduction
    plating = p.get_power("plating")
    assert plating is not None and plating.amount == 2  # untouched by the hit


def test_plating_grants_block_and_decays_at_owner_turn_end():
    # Faithful: at the owner's turn end Plating grants Block == amount, then
    # the counter decrements by 1.
    from sim.combat import CombatState
    p = _player(80)
    p.add_or_stack_power(make_power("plating", 2, p))
    CombatState._apply_plating(p)
    assert p.block == 2
    plating = p.get_power("plating")
    assert plating is not None and plating.amount == 1
    # Second turn end: grants 1 more block, counter hits 0, power removed.
    CombatState._apply_plating(p)
    assert p.block == 3
    assert p.get_power("plating") is None


def test_poison_ticks_one_per_owner_turn_end():
    m = _monster(20)
    m.add_or_stack_power(make_power("poison", 5, m))
    loss = apply_poison_tick(m)
    assert loss == 5
    assert m.hp == 15
    assert m.get_power("poison").amount == 4

    loss2 = apply_poison_tick(m)
    assert loss2 == 4
    assert m.hp == 11


def test_dexterity_adds_to_block_gain():
    p = _player(80)
    p.add_or_stack_power(make_power("dexterity", 3, p))
    gain_block(p, 5)
    assert p.block == 8  # 5 + 3


def test_frail_multiplies_block_by_three_quarters():
    p = _player(80)
    p.add_or_stack_power(make_power("frail", 2, p))
    gain_block(p, 8)
    assert p.block == int(8 * 0.75)  # = 6


def test_vigor_added_to_attack_then_consumed():
    # Faithful (VigorPower.cs): +amount on the next powered attack, then the
    # power is removed entirely.
    p, m = _player(80), _monster(40)
    p.add_or_stack_power(make_power("vigor", 5, p))
    deal_damage(6, p, m)
    assert m.hp == 40 - 11  # 6 + 5 vigor
    assert p.get_power("vigor") is None  # consumed
    # A subsequent attack no longer gets the bonus.
    deal_damage(6, p, m)
    assert m.hp == 40 - 11 - 6


def test_poison_ticks_at_start_of_owner_turn():
    # Faithful (PoisonPower.cs AfterSideTurnStart): poison resolves at the
    # START of the owner's turn. Exercised here directly via apply_poison_tick.
    m = _monster(20)
    m.add_or_stack_power(make_power("poison", 3, m))
    loss = apply_poison_tick(m)
    assert loss == 3
    assert m.hp == 17
    assert m.get_power("poison").amount == 2
