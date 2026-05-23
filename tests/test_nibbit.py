"""NibbitWeak (solo Nibbit, IsAlone branch) — combat behavior tests.

Cites decompiled/MegaCrit.Sts2.Core.Models.Monsters/Nibbit.cs and
NibbitsWeak.cs. Damage numbers are the non-Ascension column.
"""
from __future__ import annotations

import random

from sim.combat import CombatState
from sim.creatures import Player
from sim.monsters import (
    NIBBIT_HP_MAX,
    NIBBIT_HP_MIN,
    NibbitMove,
    NibbitWeak,
)


def _ironclad():
    return Player(name="Ironclad", hp=80, max_hp=80, energy=3, max_energy=3)


def test_nibbit_hp_in_range():
    for seed in range(50):
        n = NibbitWeak.spawn(random.Random(seed))
        assert NIBBIT_HP_MIN <= n.hp <= NIBBIT_HP_MAX
        assert n.max_hp == n.hp


def test_nibbit_alone_opens_with_butt():
    n = NibbitWeak.spawn(random.Random(0))
    assert n.next_move is NibbitMove.BUTT


def test_nibbit_cycle_butt_slice_hiss():
    """Solo Nibbit cycles BUTT (12) -> SLICE (6 + 5 block) -> HISS (+2 Str)
    -> BUTT again, deterministically (no RNG branching when IsAlone)."""
    p = _ironclad()
    n = NibbitWeak.spawn(random.Random(0))
    rng = random.Random(0)

    e1 = n.take_turn(rng, p)
    assert e1["move"] is NibbitMove.BUTT
    assert e1["damage"] == 12

    e2 = n.take_turn(rng, p)
    assert e2["move"] is NibbitMove.SLICE
    assert e2["damage"] == 6
    assert n.block == 5

    e3 = n.take_turn(rng, p)
    assert e3["move"] is NibbitMove.HISS
    assert e3["damage"] == 0
    strength = n.get_power("strength")
    assert strength is not None and strength.amount == 2

    e4 = n.take_turn(rng, p)
    assert e4["move"] is NibbitMove.BUTT
    # Now buffed by Strength 2, so BUTT does 12 + 2 = 14.
    assert e4["damage"] == 12  # base damage stored in event; actual hp loss reflects Strength
    # The player took the modified attack via deal_damage, so verify via the player.
    # Initial 80, hits: turn1 BUTT 12 (no block) -> 68, turn2 SLICE 6 -> 62,
    # turn3 HISS 0 -> 62 (also gains +2 Str), turn4 BUTT 12+2=14 -> 48.
    assert p.hp == 48


def test_combat_with_nibbit_factory():
    """CombatState can be built with NibbitWeak.spawn as the encounter."""
    cs = CombatState.new_combat(seed=7, monster_factory=NibbitWeak.spawn)
    assert isinstance(cs.monster, NibbitWeak)
    assert cs.monster.next_move is NibbitMove.BUTT
    cs.start_player_turn()
    assert len(cs.hand) == 5
