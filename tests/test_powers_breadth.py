"""Phase 8B — POWER breadth + monster-power fidelity.

Asserts the POWER_REGISTRY grew with the new monster/player powers and
spot-checks ~12 of them fire with .cs-faithful triggers (Curl Up, Ritual,
Regen, Flame Barrier, Reflect, Soar, Slumber, Asleep, Constrict, Crab Rage,
Buffer, Double Damage, Enrage, Painful Stabs), plus that the modeled monsters
that should carry these powers actually spawn / acquire them.

Cites: decompiled/MegaCrit.Sts2.Core.Models.Powers/{CurlUp,Ritual,Regen,
FlameBarrier,Reflect,Soar,Slumber,Asleep,Constrict,CrabRage,Buffer,
DoubleDamage,Enrage,PainfulStabs}Power.cs.
"""
from __future__ import annotations

import random

from sim.combat import CombatState
from sim.creatures import Monster, Player
from sim.damage import deal_damage, gain_block
from sim.dsl import CardDef, CardType, Effect, EffectOp, Target
from sim.monsters import (
    CalcifiedCultist,
    DampCultist,
    DevotedSculptor,
    LouseProgenitor,
    OwlMagistrate,
    SlitheringStrangler,
    SlumberingBeetle,
    TestSubject,
    ThievingHopper,
)
from sim.powers import POWER_REGISTRY, make_power


# --------------------------------------------------------------------------
# Breadth: registry jumped well past the pre-Phase-8B ~46.
# --------------------------------------------------------------------------

# The new monster/player powers added in Phase 8B.
_NEW_POWERS = (
    "curl_up", "ritual", "regen", "enrage", "flame_barrier", "reflect",
    "soar", "flutter", "slumber", "asleep", "constrict", "crab_rage",
    "painful_stabs", "hardened_shell", "double_damage", "buffer", "blur",
    "temporary_strength", "temporary_dexterity", "strength_down", "rage",
    "afterimage", "envenom",
)


def test_registry_count_jumped():
    # Report the new total against the 262 real-game powers.
    print(f"\nPOWER_REGISTRY: {len(POWER_REGISTRY)}/262")
    assert len(POWER_REGISTRY) >= 66
    for pid in _NEW_POWERS:
        assert pid in POWER_REGISTRY, pid


def test_all_new_powers_constructible():
    dummy = Monster(name="d", hp=10, max_hp=10)
    for pid in _NEW_POWERS:
        p = make_power(pid, 1, dummy)
        assert p.id == pid


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _monster(hp: int = 50) -> Monster:
    return Monster(name="M", hp=hp, max_hp=hp)


def _player(hp: int = 50) -> Player:
    return Player(name="P", hp=hp, max_hp=hp, energy=3, max_energy=3)


# --------------------------------------------------------------------------
# Curl Up — block on the FIRST powered hit, then the power is removed.
# --------------------------------------------------------------------------

def test_curl_up_blocks_on_first_hit_only():
    m = _monster(hp=50)
    p = _player()
    m.add_or_stack_power(make_power("curl_up", 14, m))
    assert m.block == 0
    deal_damage(6, p, m)         # first hit: 6 dmg, then +14 block
    assert m.get_power("curl_up") is None        # consumed
    # 50 - 6 = 44 hp; 14 block remains.
    assert m.hp == 44 and m.block == 14
    # Second hit no longer triggers any new block.
    block_before = m.block
    deal_damage(3, p, m)
    assert m.block <= block_before


# --------------------------------------------------------------------------
# Ritual — +Strength at the owner's turn end.
# --------------------------------------------------------------------------

def test_ritual_gains_strength_at_turn_end():
    cs = CombatState.new_combat(seed=0)
    m = cs.monster
    m.add_or_stack_power(make_power("ritual", 2, m))
    cs.start_player_turn()
    cs._fire_power_hook(m, "on_turn_end", cs, m)
    assert m.get_power("strength").amount == 2
    cs._fire_power_hook(m, "on_turn_end", cs, m)
    assert m.get_power("strength").amount == 4


# --------------------------------------------------------------------------
# Regen — heal at turn end, decrement the counter.
# --------------------------------------------------------------------------

def test_regen_heals_and_decays():
    m = Monster(name="M", hp=10, max_hp=20)   # 10 missing HP to heal into
    m.add_or_stack_power(make_power("regen", 3, m))
    m.get_power("regen").on_turn_end(None, m)
    assert m.hp == 13 and m.get_power("regen").amount == 2


# --------------------------------------------------------------------------
# Flame Barrier — retaliate when hit by a powered attack.
# --------------------------------------------------------------------------

def test_flame_barrier_retaliates():
    p = _player(hp=50)
    m = _monster(hp=50)
    p.add_or_stack_power(make_power("flame_barrier", 4, p))
    deal_damage(6, m, p)          # monster hits player; barrier burns it for 4
    assert m.hp == 46


# --------------------------------------------------------------------------
# Reflect — deal the BLOCKED amount back to the attacker.
# --------------------------------------------------------------------------

def test_reflect_returns_blocked_amount():
    p = _player(hp=50)
    m = _monster(hp=50)
    p.block = 10
    p.add_or_stack_power(make_power("reflect", 1, p))
    deal_damage(6, m, p)          # fully blocked (6); reflect 6 back
    assert m.hp == 44


# --------------------------------------------------------------------------
# Soar — incoming damage to the owner is halved.
# --------------------------------------------------------------------------

def test_soar_halves_incoming():
    p = _player()
    m = _monster(hp=50)
    m.add_or_stack_power(make_power("soar", 1, m))
    deal_damage(10, p, m)         # 10 -> 5
    assert m.hp == 45


# --------------------------------------------------------------------------
# Slumber — decrements on unblocked hits / turn end; wakes (removed) at 0.
# --------------------------------------------------------------------------

def test_slumber_decrements_and_wakes():
    p = _player()
    m = _monster(hp=50)
    m.add_or_stack_power(make_power("slumber", 2, m))
    deal_damage(3, p, m)
    assert m.get_power("slumber").amount == 1
    deal_damage(3, p, m)
    assert m.get_power("slumber") is None   # woke up


# --------------------------------------------------------------------------
# Asleep — first unblocked hit removes the owner's Plating + the Asleep power.
# --------------------------------------------------------------------------

def test_asleep_wakes_and_drops_plating():
    p = _player()
    m = _monster(hp=50)
    m.add_or_stack_power(make_power("plating", 12, m))
    m.add_or_stack_power(make_power("asleep", 3, m))
    deal_damage(5, p, m)
    assert m.get_power("asleep") is None
    assert m.get_power("plating") is None


# --------------------------------------------------------------------------
# Constrict — owner takes unblockable damage at its turn end.
# --------------------------------------------------------------------------

def test_constrict_ticks_at_turn_end():
    p = _player(hp=50)
    p.add_or_stack_power(make_power("constrict", 3, p))
    p.get_power("constrict").on_turn_end(None, p)
    assert p.hp == 47


# --------------------------------------------------------------------------
# Crab Rage — Strength + Block when an ally dies (via play_card death fan-out).
# --------------------------------------------------------------------------

def test_crab_rage_triggers_on_ally_death():
    crab = _monster(hp=50)
    crab.add_or_stack_power(make_power("crab_rage", 6, crab))
    ally = _monster(hp=1)
    cs = CombatState.new_combat(seed=0)
    cs.monster = crab
    cs.monsters = [crab, ally]
    cs.start_player_turn()
    # A 5-damage attack that targets all enemies kills the 1-hp ally.
    card = CardDef(id="aoe", name="AoE", cost=0, type=CardType.ATTACK,
                   effects=(Effect(op=EffectOp.DEAL_DAMAGE, target=Target.ALL_ENEMIES,
                                   amount=5),))
    cs.hand.insert(0, card)
    cs.play_card(0)
    assert not ally.alive
    assert crab.get_power("strength").amount == 6
    assert crab.block >= 99
    assert crab.get_power("crab_rage") is None


# --------------------------------------------------------------------------
# Double Damage — the owner's powered attacks deal ×2.
# --------------------------------------------------------------------------

def test_double_damage_doubles_owner_attacks():
    m = _monster(hp=50)
    p = _player(hp=80)
    m.add_or_stack_power(make_power("double_damage", 1, m))
    deal_damage(10, m, p)         # 10 -> 20
    assert p.hp == 60


# --------------------------------------------------------------------------
# Buffer — fully prevents the next instance of HP loss.
# --------------------------------------------------------------------------

def test_buffer_prevents_one_hit():
    p = _player(hp=50)
    m = _monster(hp=50)
    p.add_or_stack_power(make_power("buffer", 1, p))
    deal_damage(20, m, p)
    assert p.hp == 50                       # prevented
    assert p.get_power("buffer") is None
    deal_damage(7, m, p)
    assert p.hp == 43                       # next hit lands


# --------------------------------------------------------------------------
# Enrage — monster gains Strength when the PLAYER plays a Skill.
# --------------------------------------------------------------------------

def test_enrage_gains_strength_on_player_skill():
    cs = CombatState.new_combat(seed=0)
    m = cs.monster
    m.add_or_stack_power(make_power("enrage", 2, m))
    cs.start_player_turn()
    skill = CardDef(id="skill", name="Skill", cost=0, type=CardType.SKILL,
                    effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF,
                                    amount=5),))
    cs.hand.insert(0, skill)
    cs.play_card(0)
    assert m.get_power("strength").amount == 2
    # Playing an Attack does NOT trigger Enrage.
    atk = CardDef(id="atk", name="Atk", cost=0, type=CardType.ATTACK,
                  effects=(Effect(op=EffectOp.DEAL_DAMAGE,
                                  target=Target.SELECTED_ENEMY, amount=4),))
    cs.hand.insert(0, atk)
    cs.play_card(0)
    assert m.get_power("strength").amount == 2


# --------------------------------------------------------------------------
# Painful Stabs — powered attack queues Wounds to the player's discard.
# --------------------------------------------------------------------------

def test_painful_stabs_queues_wounds():
    cs = CombatState.new_combat(seed=0)
    m = cs.monster
    m.add_or_stack_power(make_power("painful_stabs", 1, m))
    cs.start_player_turn()
    cs.end_player_turn()          # monster attacks the player
    # After the monster turn, the player's discard should hold >=1 Wound.
    assert any(c.id == "wound" for c in cs.discard_pile)


# --------------------------------------------------------------------------
# Monster-power wiring: the modeled monsters carry their real powers.
# --------------------------------------------------------------------------

def test_louse_progenitor_spawns_with_curl_up():
    m = LouseProgenitor.spawn(random.Random(1))
    assert m.get_power("curl_up") is not None
    # A8 raises the CurlUp block to 18.
    m8 = LouseProgenitor.spawn(random.Random(1), ascension=8)
    assert m8.get_power("curl_up").amount == 18


def test_slumbering_beetle_spawns_asleep_with_plating():
    m = SlumberingBeetle.spawn(random.Random(1))
    assert m.get_power("slumber") is not None
    assert m.get_power("plating") is not None
    # It SNOREs (no-op) while asleep rather than attacking.
    assert m.next_move == "SNORE"


def test_test_subject_spawns_with_enrage_and_painful_stabs():
    m = TestSubject.spawn(random.Random(1))
    assert m.get_power("enrage") is not None
    assert m.get_power("painful_stabs") is not None


def test_cultists_gain_ritual_via_incantation():
    for cls in (CalcifiedCultist, DampCultist, DevotedSculptor):
        m = cls.spawn(random.Random(1))
        # The opening Incantation move grants Ritual.
        m.take_turn(random.Random(1), _player())
        assert m.get_power("ritual") is not None, cls.__name__


def test_thieving_hopper_gains_flutter():
    m = ThievingHopper.spawn(random.Random(1))
    rng = random.Random(1)
    p = _player(hp=200)
    # THIEVERY -> FLUTTER: take two turns to reach + apply the Flutter buff.
    m.take_turn(rng, p)           # THIEVERY
    m.take_turn(rng, p)           # FLUTTER (grants Flutter)
    assert m.get_power("flutter") is not None


def test_owl_magistrate_gains_soar_on_flight():
    m = OwlMagistrate.spawn(random.Random(1))
    rng = random.Random(1)
    p = _player(hp=400)
    m.take_turn(rng, p)           # SCRUTINY
    m.take_turn(rng, p)           # PECK_ASSAULT
    m.take_turn(rng, p)           # JUDICIAL_FLIGHT -> Soar
    assert m.get_power("soar") is not None


def test_slithering_strangler_applies_constrict():
    m = SlitheringStrangler.spawn(random.Random(1))
    p = _player(hp=50)
    m.take_turn(random.Random(1), p)     # CONSTRICT move
    assert p.get_power("constrict") is not None
