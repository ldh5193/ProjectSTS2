"""Phase 8B.4 — fidelity tests for the 3 remaining played-path monster
fallbacks (Fogmog / PhrogParasite / TurretOperator) and their companion
sub-entities (EyeWithTeeth illusion, Wriggler, Living Shield).

Proves each encounter now resolves to its REAL monster class(es) (not the
37-HP Sludge Spinner placeholder), with decompiled-accurate HP, first-turn
intent, multi-turn move sequence, A8 (HP) / A9 (damage) ascension scaling, and
the special spawn mechanics (Fogmog illusion summon, Phrog death-spawn of 4
Wrigglers, Living Shield Rampart block on the Turret Operator).

Decompiled refs (MegaCrit.Sts2.Core.Models.Monsters/* + Models.Encounters/* +
Models.Powers/*) are noted inline.
"""
from __future__ import annotations

import random

from sim.combat import CombatState
from sim.creatures import Player
from sim.damage import deal_damage
from sim.encounter import _MULTI_FACTORY_BY_ID, build_monsters_for, is_modeled
from sim.monsters import (
    EyeWithTeeth,
    Fogmog,
    FogmogMove,
    LivingShield,
    LivingShieldMove,
    PhrogMove,
    PhrogParasite,
    TurretMove,
    TurretOperator,
    Wriggler,
    WrigglerMove,
    spawn_fogmog_normal,
    spawn_phrog_parasite_elite,
    spawn_turret_operator_weak,
)


def _player(hp: int = 9999) -> Player:
    return Player(name="p", hp=hp, max_hp=hp, energy=3)


def _resolved(eid: str) -> bool:
    return is_modeled(eid) or eid in _MULTI_FACTORY_BY_ID


# ---------------------------------------------------------------------------
# Encounter wiring — all three escape the Sludge fallback.
# ---------------------------------------------------------------------------

def test_fallback_encounters_are_now_resolved():
    for eid in ("FogmogNormal", "PhrogParasiteElite", "TurretOperatorWeak"):
        assert _resolved(eid), eid


def test_fogmog_normal_builds_solo_fogmog():
    rng = random.Random(0)
    ms = build_monsters_for("FogmogNormal", rng, ascension=0)
    assert len(ms) == 1
    assert isinstance(ms[0], Fogmog)


def test_phrog_elite_builds_solo_phrog():
    rng = random.Random(0)
    ms = build_monsters_for("PhrogParasiteElite", rng, ascension=0)
    assert len(ms) == 1
    assert isinstance(ms[0], PhrogParasite)


def test_turret_operator_weak_builds_shield_plus_turret():
    rng = random.Random(0)
    ms = build_monsters_for("TurretOperatorWeak", rng, ascension=0)
    assert len(ms) == 2
    assert isinstance(ms[0], LivingShield)
    assert isinstance(ms[1], TurretOperator)


# ---------------------------------------------------------------------------
# Fogmog (Fogmog.cs) + EyeWithTeeth (EyeWithTeeth.cs).
# ---------------------------------------------------------------------------

def test_fogmog_hp_and_ascension():
    # Fogmog.cs:23 — MinHp==MaxHp == 74 (A8 78).
    assert Fogmog.spawn(random.Random(1)).hp == 74
    assert Fogmog.spawn(random.Random(1), ascension=8).hp == 78


def test_fogmog_first_move_is_illusion_then_swipe():
    # State machine starts at ILLUSION_MOVE -> SWIPE_MOVE.
    f = Fogmog.spawn(random.Random(2))
    assert f.next_move is FogmogMove.ILLUSION
    assert f.intent_damage() == 0  # summon, no damage
    p = _player()
    rng = random.Random(2)
    f.take_turn(rng, p)            # ILLUSION
    assert f.next_move is FogmogMove.SWIPE


def test_fogmog_swipe_damage_and_strength_gain():
    # SwipeDamage 8 (A9 9) + self Strength 1 per swipe (Fogmog.cs:62-69).
    f = Fogmog.spawn(random.Random(3))
    f.next_move = FogmogMove.SWIPE
    p = _player()
    ev = f.take_turn(random.Random(3), p)
    assert ev["damage"] == 8
    assert f.get_power("strength").amount == 1
    # A9 swipe is 9.
    fa = Fogmog.spawn(random.Random(3), ascension=9)
    fa.next_move = FogmogMove.SWIPE
    assert fa.take_turn(random.Random(3), _player())["damage"] == 9


def test_fogmog_headbutt_damage():
    # HeadbuttDamage 14 (A9 16) (Fogmog.cs:29,71-77).
    f = Fogmog.spawn(random.Random(4))
    f.next_move = FogmogMove.HEADBUTT
    assert f.intent_damage() == 14
    assert f.take_turn(random.Random(4), _player())["damage"] == 14
    fa = Fogmog.spawn(random.Random(4), ascension=9)
    fa.next_move = FogmogMove.HEADBUTT
    assert fa.take_turn(random.Random(4), _player())["damage"] == 16


def test_fogmog_branch_only_headbutt_or_swipe_random():
    # SWIPE_MOVE -> RandomBranch(SWIPE_RANDOM 0.4, HEADBUTT 0.6), CannotRepeat.
    f = Fogmog.spawn(random.Random(5))
    f.last_move = FogmogMove.SWIPE
    seen = {f.roll_next_move(random.Random(s)) for s in range(40)}
    assert seen <= {FogmogMove.SWIPE_RANDOM, FogmogMove.HEADBUTT}
    # SWIPE_RANDOM -> HEADBUTT -> SWIPE deterministic follow-ups.
    f.last_move = FogmogMove.SWIPE_RANDOM
    assert f.roll_next_move(random.Random(0)) is FogmogMove.HEADBUTT
    f.last_move = FogmogMove.HEADBUTT
    assert f.roll_next_move(random.Random(0)) is FogmogMove.SWIPE


def test_eye_with_teeth_hp_and_illusion_power():
    # EyeWithTeeth.cs:21 — flat 6 HP, gains IllusionPower at spawn.
    e = EyeWithTeeth.spawn(random.Random(0))
    assert e.hp == 6 and e.max_hp == 6
    assert e.get_power("illusion") is not None
    assert EyeWithTeeth.spawn(random.Random(0), ascension=8).hp == 6  # no scaling


def test_eye_with_teeth_distract_queues_3_dazed():
    # DISTRACT_MOVE: 3 Dazed -> discard, no damage (EyeWithTeeth.cs:44-50).
    e = EyeWithTeeth.spawn(random.Random(0))
    p = _player()
    ev = e.take_turn(random.Random(0), p)
    assert ev["damage"] == 0
    pending = getattr(e, "pending_status_cards", [])
    dazed = [c for c, pile in pending if c.id == "dazed" and pile == "discard"]
    assert len(dazed) == 3


def test_fogmog_summons_eye_into_live_combat():
    # In real combat, Fogmog's ILLUSION_MOVE adds an EyeWithTeeth to the field.
    cs = CombatState.new_combat(seed=11,
                                monsters_factory=lambda r: spawn_fogmog_normal(r))
    assert [m.name for m in cs.monsters] == ["Fogmog"]
    cs.start_player_turn()
    cs.end_player_turn()  # -> monster_turn -> Fogmog ILLUSION summons Eye
    assert any(isinstance(m, EyeWithTeeth) for m in cs.monsters)


# ---------------------------------------------------------------------------
# PhrogParasite (PhrogParasite.cs) + Wriggler (Wriggler.cs) + Infested power.
# ---------------------------------------------------------------------------

def test_phrog_hp_range_and_ascension():
    # PhrogParasite.cs:25-27 — HP 61-64 (A8 66-68).
    for s in range(40):
        assert 61 <= PhrogParasite.spawn(random.Random(s)).hp <= 64
        assert 66 <= PhrogParasite.spawn(random.Random(s), ascension=8).hp <= 68


def test_phrog_has_infested_power_at_spawn():
    # AfterAddedToRoom: InfestedPower 4 (PhrogParasite.cs:33-37).
    p = PhrogParasite.spawn(random.Random(0))
    inf = p.get_power("infested")
    assert inf is not None and inf.amount == 4


def test_phrog_first_move_infect_then_lash():
    # Start INFECT_MOVE; INFECT <-> LASH alternation.
    p = PhrogParasite.spawn(random.Random(0))
    assert p.next_move is PhrogMove.INFECT
    assert p.intent_damage() == 0  # status add, no damage
    target = _player()
    p.take_turn(random.Random(0), target)
    assert p.next_move is PhrogMove.LASH
    # INFECT queues 3 Infection -> discard.
    p2 = PhrogParasite.spawn(random.Random(0))
    p2.take_turn(random.Random(0), _player())
    inf_cards = [c for c, pile in getattr(p2, "pending_status_cards", [])
                 if c.id == "infection" and pile == "discard"]
    assert len(inf_cards) == 3


def test_phrog_lash_damage_4x4_and_ascension():
    # LASH: Lash 4 (A9 5) x4 hits (PhrogParasite.cs:21,29,55-63).
    p = PhrogParasite.spawn(random.Random(0))
    p.next_move = PhrogMove.LASH
    assert p.intent_damage() == 4 * 4
    ev = p.take_turn(random.Random(0), _player())
    assert ev["damage"] == 16
    pa = PhrogParasite.spawn(random.Random(0), ascension=9)
    pa.next_move = PhrogMove.LASH
    assert pa.intent_damage() == 5 * 4
    assert pa.take_turn(random.Random(0), _player())["damage"] == 20


def test_phrog_spawns_4_stunned_wrigglers_on_death():
    # InfestedPower.cs:19-35 — on the Phrog's death, spawn 4 Wrigglers
    # (StartStunned). Combat keeps running until the Wrigglers are slain.
    cs = CombatState.new_combat(
        seed=21, monsters_factory=lambda r: spawn_phrog_parasite_elite(r))
    phrog = cs.monsters[0]
    cs.start_player_turn()
    deal_damage(999, cs.player, phrog)
    cs._fire_power_hook(phrog, "on_self_death", cs, phrog)
    cs._drain_pending_spawns()
    wrigglers = [m for m in cs.monsters if isinstance(m, Wriggler)]
    assert len(wrigglers) == 4
    # All alive (combat not over) and each starts STUNNED (no-op first turn).
    assert len(cs.alive_monsters()) == 4
    for w in wrigglers:
        assert w.next_move == WrigglerMove.SPAWNED
        assert w.intent_damage() == 0


def test_wriggler_hp_range_and_ascension():
    # Wriggler.cs:28-30 — HP 17-21 (A8 18-22).
    for s in range(40):
        assert 17 <= Wriggler.spawn(random.Random(s)).hp <= 21
        assert 18 <= Wriggler.spawn(random.Random(s), ascension=8).hp <= 22


def test_wriggler_stunned_then_bite_then_wriggle_cycle():
    # SPAWNED (stun no-op) -> INIT (slot-keyed) -> Bite <-> Wriggle.
    w = Wriggler.spawn(random.Random(0))
    w._slot_kind = "bite"
    w.next_move = WrigglerMove.SPAWNED
    p = _player()
    ev = w.take_turn(random.Random(0), p)       # stunned: no damage
    assert ev["damage"] == 0
    assert w.next_move == WrigglerMove.BITE      # INIT for odd slot
    ev = w.take_turn(random.Random(0), p)        # Bite 6
    assert ev["damage"] == 6
    assert w.next_move == WrigglerMove.WRIGGLE


def test_wriggler_bite_damage_ascension():
    # BiteDamage 6 (A9 7).
    w = Wriggler.spawn(random.Random(0))
    w.next_move = WrigglerMove.BITE
    assert w.take_turn(random.Random(0), _player())["damage"] == 6
    wa = Wriggler.spawn(random.Random(0), ascension=9)
    wa.next_move = WrigglerMove.BITE
    assert wa.take_turn(random.Random(0), _player())["damage"] == 7


def test_wriggler_wriggle_grants_strength_and_infection():
    # WriggleMove: 1 Infection -> discard + self Strength 2 (Wriggler.cs:85-99).
    w = Wriggler.spawn(random.Random(0))
    w.next_move = WrigglerMove.WRIGGLE
    w.take_turn(random.Random(0), _player())
    assert w.get_power("strength").amount == 2
    inf = [c for c, pile in getattr(w, "pending_status_cards", [])
           if c.id == "infection"]
    assert len(inf) == 1


# ---------------------------------------------------------------------------
# TurretOperator (TurretOperator.cs) + LivingShield (LivingShield.cs) + Rampart.
# ---------------------------------------------------------------------------

def test_turret_hp_and_ascension():
    # TurretOperator.cs:26 — MinHp==MaxHp == 41 (A8 51).
    assert TurretOperator.spawn(random.Random(0)).hp == 41
    assert TurretOperator.spawn(random.Random(0), ascension=8).hp == 51


def test_turret_unload_unload_reload_cycle():
    # UNLOAD_1 -> UNLOAD_2 -> RELOAD(+1 Str) -> UNLOAD_1 (TurretOperator.cs:34-47).
    t = TurretOperator.spawn(random.Random(0))
    p = _player()
    assert t.next_move is TurretMove.UNLOAD_1
    # Fire 3 (A9 4) x5 = 15 base.
    assert t.intent_damage() == 3 * 5
    ev = t.take_turn(random.Random(0), p)
    assert ev["damage"] == 15
    assert t.next_move is TurretMove.UNLOAD_2
    ev = t.take_turn(random.Random(0), p)
    assert ev["damage"] == 15
    assert t.next_move is TurretMove.RELOAD
    ev = t.take_turn(random.Random(0), p)        # RELOAD: +1 Strength, no dmg
    assert ev["damage"] == 0
    assert t.get_power("strength").amount == 1
    assert t.next_move is TurretMove.UNLOAD_1


def test_turret_fire_damage_ascension():
    ta = TurretOperator.spawn(random.Random(0), ascension=9)
    ta.next_move = TurretMove.UNLOAD_1
    assert ta.intent_damage() == 4 * 5
    assert ta.take_turn(random.Random(0), _player())["damage"] == 20


def test_living_shield_hp_and_rampart():
    # LivingShield.cs:17 — HP 55 (A8 65). RampartPower 25 at spawn.
    s = LivingShield.spawn(random.Random(0))
    assert s.hp == 55
    assert LivingShield.spawn(random.Random(0), ascension=8).hp == 65
    r = s.get_power("rampart")
    assert r is not None and r.amount == 25


def test_living_shield_shield_slam_while_allies():
    # ShieldSlam 6 (flat, no ascension) while it still has allies.
    cs = CombatState.new_combat(
        seed=31, monsters_factory=lambda r: spawn_turret_operator_weak(r))
    shield = cs.monsters[0]
    assert shield.next_move is LivingShieldMove.SHIELD_SLAM
    assert shield.intent_damage() == 6
    ev = shield.take_turn(cs.rng, cs.player)
    assert ev["damage"] == 6
    assert shield.next_move is LivingShieldMove.SHIELD_SLAM  # still has ally


def test_living_shield_switches_to_smash_when_alone():
    # Once the Turret Operator dies, the shield switches to Smash 16 (A9 18) +
    # Strength 3, and Smash self-loops thereafter (LivingShield.cs:41-51).
    cs = CombatState.new_combat(
        seed=33, monsters_factory=lambda r: spawn_turret_operator_weak(r))
    shield, turret = cs.monsters
    deal_damage(999, cs.player, turret)
    assert not turret.alive
    shield.last_move = shield.next_move
    nxt = shield.roll_next_move(cs.rng)
    assert nxt is LivingShieldMove.SMASH
    shield.next_move = LivingShieldMove.SMASH
    ev = shield.take_turn(cs.rng, cs.player)
    assert ev["damage"] == 16
    assert shield.get_power("strength").amount == 3
    assert shield.next_move is LivingShieldMove.SMASH  # self-loop


def test_living_shield_smash_ascension():
    s = LivingShield.spawn(random.Random(0), ascension=9)
    s.next_move = LivingShieldMove.SMASH
    assert s.take_turn(random.Random(0), _player())["damage"] == 18


def test_rampart_armors_turret_each_player_turn():
    # RampartPower.cs (AfterSideTurnStart side==Player): the Living Shield grants
    # the Turret Operator 25 Block at the start of every player turn.
    cs = CombatState.new_combat(
        seed=35, monsters_factory=lambda r: spawn_turret_operator_weak(r))
    turret = cs.monsters[1]
    assert turret.block == 0
    cs.start_player_turn()
    assert turret.block == 25
