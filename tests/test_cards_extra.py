"""Cards beyond the MVP starting deck (decompile-verified Ironclad library)."""
from __future__ import annotations

from sim.cards import INFLAME, IRON_WAVE, IRONCLAD_LIBRARY, STRIKE_IRONCLAD
from sim.combat import CombatState


def _new_combat(seed: int = 0) -> CombatState:
    cs = CombatState.new_combat(seed=seed)
    cs.start_player_turn()
    return cs


def test_library_includes_starting_deck_plus_extras():
    ids = {c.id for c in IRONCLAD_LIBRARY}
    assert {"strike_ironclad", "defend_ironclad", "bash"}.issubset(ids)
    assert {"iron_wave", "inflame"}.issubset(ids)


def test_iron_wave_grants_block_then_deals_damage():
    """IronWave (decompile: GainBlock(5) -> Attack(5)). Order matters: block
    is applied to the player before damage resolution so a same-turn attack
    can't be reduced by the block IronWave just placed (separate creatures)."""
    cs = _new_combat()
    cs.hand = [IRON_WAVE]
    monster_hp_before = cs.monster.hp
    cs.player.block = 0
    cs.player.energy = 1

    cs.play_card(0)

    assert cs.player.block == 5
    assert cs.monster.hp == monster_hp_before - 5


def test_inflame_stacks_strength_on_self():
    """Inflame applies +2 Strength to the player; the next Strike does 8 dmg
    (6 base + 2 Strength), confirming the additive STRIKE_SCALING path."""
    cs = _new_combat()
    cs.hand = [INFLAME, STRIKE_IRONCLAD]
    cs.player.energy = 2
    monster_hp_before = cs.monster.hp

    cs.play_card(0)  # Inflame -> Strength +2 on player

    strength = cs.player.get_power("strength")
    assert strength is not None and strength.amount == 2

    cs.play_card(0)  # Strike (now at hand[0] because Inflame was popped)
    assert cs.monster.hp == monster_hp_before - 8


def test_inflame_costs_one_energy():
    cs = _new_combat()
    cs.hand = [INFLAME]
    cs.player.energy = 1
    cs.play_card(0)
    assert cs.player.energy == 0
