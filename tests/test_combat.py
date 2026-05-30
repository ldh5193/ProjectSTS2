"""End-to-end smoke tests for the MVP combat simulator.

Validates damage pipeline against numeric examples in notes/05_mvp_combat_spec.md.
"""
from __future__ import annotations

import random

from sim.cards import BASH, STRIKE_IRONCLAD
from sim.combat import CombatState
from sim.creatures import Player
from sim.damage import compute_modified_damage, deal_damage, gain_block
from sim.dsl import EffectOp
from sim.monsters import SludgeSpinnerWeak, SludgeMove
from sim.powers import StrengthPower, VulnerablePower, WeakPower, make_power


def _ironclad():
    return Player(name="Ironclad", hp=80, max_hp=80, energy=3, max_energy=3)


def _sludge(hp: int = 38):
    return SludgeSpinnerWeak(name="Sludge Spinner", hp=hp, max_hp=hp)


def test_strike_no_powers_does_6_damage():
    p, m = _ironclad(), _sludge()
    assert compute_modified_damage(6, p, m) == 6


def test_strike_vs_vulnerable_does_9_damage():
    # 6 base × 1.5 (Vulnerable, stack-independent) = 9
    p, m = _ironclad(), _sludge()
    m.add_or_stack_power(make_power("vulnerable", 2, m))
    assert compute_modified_damage(6, p, m) == 9


def test_strength_3_adds_3_to_attack():
    # 11 base + 3 Strength = 14
    p, m = _ironclad(), _sludge()
    str_power = StrengthPower(amount=3)
    str_power._owner = m  # monster has Strength, attacks player
    m.powers.append(str_power)
    assert compute_modified_damage(11, m, p) == 14


def test_weak_reduces_dealer_damage_by_25_percent():
    # 8 base × 0.75 (Weak on dealer) = 6
    p, m = _ironclad(), _sludge()
    p.add_or_stack_power(make_power("weak", 1, p))
    assert compute_modified_damage(8, p, m) == 6


def test_block_absorbs_then_hp_takes_rest():
    p, m = _ironclad(), _sludge()
    p.block = 5
    blocked, hp_loss = deal_damage(11, m, p)
    assert blocked == 5
    assert hp_loss == 6
    assert p.hp == 74
    assert p.block == 0


def test_sludge_hp_in_range():
    rng = random.Random(0)
    for _ in range(50):
        m = SludgeSpinnerWeak.spawn(rng)
        assert 37 <= m.hp <= 39


def test_sludge_first_move_is_oil_spray():
    m = SludgeSpinnerWeak.spawn(random.Random(0))
    assert m.next_move is SludgeMove.OIL_SPRAY


def test_sludge_cannot_repeat_move():
    rng = random.Random(0)
    m = SludgeSpinnerWeak.spawn(rng)
    p = _ironclad()
    for _ in range(20):
        prev = m.next_move
        m.take_turn(rng, p)
        assert m.last_move == prev
        assert m.next_move != prev


def test_combat_round_trip_player_strike_then_monster_attack():
    cs = CombatState.new_combat(seed=42)
    cs.start_player_turn()
    # Find a Strike in hand and play it on the monster.
    strike_idx = next(i for i, c in enumerate(cs.hand) if c.id == "strike_ironclad")
    monster_hp_before = cs.monster.hp
    cs.play_card(strike_idx)
    assert cs.monster.hp == monster_hp_before - 6
    cs.end_player_turn()
    # Monster's first move (OIL_SPRAY) deals 8 and applies Weak.
    assert cs.player.hp == 80 - 8
    assert cs.player.get_power("weak") is not None


def test_bash_applies_vulnerable_and_next_strike_scaled():
    cs = CombatState.new_combat(seed=42)
    cs.start_player_turn()
    # Force a known hand by replacing it: 1 Bash + 1 Strike.
    cs.hand = [BASH, STRIKE_IRONCLAD]
    cs.player.energy = 3  # Bash(2) + Strike(1) = 3
    hp_before = cs.monster.hp
    cs.play_card(0)  # Bash: 8 dmg + Vulnerable 2
    assert cs.monster.hp == hp_before - 8
    assert cs.monster.get_power("vulnerable").amount == 2
    # Next Strike: 6 base × 1.5 = 9
    cs.play_card(0)  # Strike now at index 0
    assert cs.monster.hp == hp_before - 8 - 9


def test_player_frail_and_weak_decay_at_end_of_player_turn():
    # Faithful per-bearer rule: debuffs the PLAYER bears decay at the end of
    # the PLAYER's own turn (Frail applied by DEBILITATE must decay, not stick).
    # Tested in isolation so a monster's move can't re-apply the debuff.
    cs = CombatState.new_combat(seed=7)
    cs.player.add_or_stack_power(make_power("frail", 2, cs.player))
    cs.player.add_or_stack_power(make_power("weak", 2, cs.player))
    cs._end_of_turn_effects(cs.player)  # the player's own turn-end decay
    assert cs.player.get_power("frail").amount == 1
    assert cs.player.get_power("weak").amount == 1


def test_monster_vulnerable_and_weak_decay_at_end_of_monster_turn():
    # Faithful per-bearer rule: debuffs a MONSTER bears decay at the end of
    # that MONSTER's own turn.
    cs = CombatState.new_combat(seed=7)
    cs.start_player_turn()
    cs.monster.add_or_stack_power(make_power("vulnerable", 2, cs.monster))
    cs.monster.add_or_stack_power(make_power("weak", 2, cs.monster))
    cs.monster_turn()  # monster acts then decays its own debuffs
    assert cs.monster.get_power("vulnerable").amount == 1
    assert cs.monster.get_power("weak").amount == 1


def test_frail_fully_decays_over_two_player_turns():
    cs = CombatState.new_combat(seed=11)
    cs.start_player_turn()
    cs.player.add_or_stack_power(make_power("frail", 2, cs.player))
    cs.end_player_turn()
    assert cs.player.get_power("frail").amount == 1
    cs.end_player_turn()
    assert cs.player.get_power("frail") is None  # gone after 2 player turns
