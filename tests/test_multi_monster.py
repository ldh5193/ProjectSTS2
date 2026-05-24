"""Multi-monster combat smoke tests (Cycle F)."""
from __future__ import annotations

from sim.combat import CombatState
from sim.creatures import Player
from sim.dsl import CardDef, CardType, Effect, EffectOp, Target
from sim.encounter import build_monsters_for, is_multi_encounter
from sim.monsters import NibbitMove, NibbitWeak, spawn_nibbits_normal
from sim.rng import Rng


def test_nibbits_normal_spawns_two_nibbits():
    rng = Rng(0)
    monsters = spawn_nibbits_normal(rng)
    assert len(monsters) == 2
    assert all(isinstance(m, NibbitWeak) for m in monsters)
    assert monsters[0].name == "Nibbit (Front)"
    assert monsters[1].name == "Nibbit (Back)"
    # Distinct opening moves per IsFront / IsBack.
    assert monsters[0].next_move is NibbitMove.SLICE
    assert monsters[1].next_move is NibbitMove.HISS


def test_build_monsters_for_routes_multi_when_available():
    rng = Rng(0)
    assert is_multi_encounter("NibbitsNormal")
    monsters = build_monsters_for("NibbitsNormal", rng)
    assert len(monsters) == 2

    # Solo encounters still wrap in a single-element list.
    solo = build_monsters_for("NibbitsWeak", rng)
    assert len(solo) == 1


def test_combat_state_with_multi_monsters_runs_a_turn():
    rng = Rng(42)
    monsters = spawn_nibbits_normal(rng)
    cs = CombatState.new_combat(seed=42, monsters_factory=lambda _r: monsters)
    cs.start_player_turn()
    assert len(cs.alive_monsters()) == 2
    # Player_won False while both alive.
    assert not cs.player_won()
    # Selected enemy defaults to first (target_index=0); attack drops its HP.
    strike = CardDef(id="x", name="x", cost=1, type=CardType.ATTACK,
                     effects=(Effect(op=EffectOp.DEAL_DAMAGE,
                                     target=Target.SELECTED_ENEMY, amount=6),))
    cs.hand = [strike]
    hp_before = cs.monsters[0].hp
    cs.play_card(0)
    assert cs.monsters[0].hp == hp_before - 6
    # The other monster is untouched.
    assert cs.monsters[1].alive


def test_all_enemies_target_hits_every_alive():
    rng = Rng(7)
    monsters = spawn_nibbits_normal(rng)
    cs = CombatState.new_combat(seed=7, monsters_factory=lambda _r: monsters)
    cs.start_player_turn()
    hp_before = [m.hp for m in cs.monsters]
    aoe = CardDef(id="aoe", name="aoe", cost=1, type=CardType.ATTACK,
                  effects=(Effect(op=EffectOp.DEAL_DAMAGE,
                                  target=Target.ALL_ENEMIES, amount=3),))
    cs.hand = [aoe]
    cs.play_card(0)
    for i, m in enumerate(cs.monsters):
        assert m.hp == hp_before[i] - 3


def test_killing_one_monster_does_not_end_combat():
    rng = Rng(0)
    monsters = spawn_nibbits_normal(rng)
    cs = CombatState.new_combat(seed=0, monsters_factory=lambda _r: monsters)
    cs.start_player_turn()
    # Drain front to 1 HP and finish it.
    cs.monsters[0].hp = 1
    kill = CardDef(id="k", name="k", cost=1, type=CardType.ATTACK,
                   effects=(Effect(op=EffectOp.DEAL_DAMAGE,
                                   target=Target.SELECTED_ENEMY, amount=1),))
    cs.hand = [kill]
    cs.play_card(0)
    assert not cs.monsters[0].alive
    assert cs.monsters[1].alive
    assert not cs.player_won()
