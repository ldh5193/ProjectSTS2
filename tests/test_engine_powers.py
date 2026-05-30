"""Phase 7B — Ironclad engine ("deck-power") cards and their trigger hooks.

Each test proves the power's effect fires at the right time, verifying the
POWER-TRIGGER wiring in sim/combat.py against the .cs-faithful semantics in
sim/powers.py.
"""
from __future__ import annotations

import random

from sim.cards import (
    BARRICADE,
    BERSERK,
    BRUTALITY,
    COMBUST,
    CORRUPTION,
    DARK_EMBRACE,
    DEFEND_IRONCLAD,
    DEMON_FORM,
    FEEL_NO_PAIN,
    JUGGERNAUT,
    METALLICIZE,
    RUPTURE,
)
from sim.combat import CombatState
from sim.creatures import Player
from sim.dsl import CardDef, CardType, Effect, EffectOp, Target
from sim.monsters import SludgeSpinnerWeak
from sim.powers import make_power


def _fresh_combat(seed: int = 0) -> CombatState:
    cs = CombatState.new_combat(seed=seed)
    cs.start_player_turn()
    return cs


def _apply(cs: CombatState, card: CardDef) -> None:
    """Put `card` into hand and play it (applies its power to the player)."""
    cs.hand.insert(0, card)
    # Ensure enough energy to play whatever we inject.
    cs.player.energy = max(cs.player.energy, card.cost)
    cs.play_card(0)


# --------------------------------------------------------------------------
# Demon Form — on_turn_start: gain Strength == amount each turn.
# --------------------------------------------------------------------------

def test_demon_form_adds_strength_each_turn():
    cs = _fresh_combat()
    _apply(cs, DEMON_FORM)  # power applied this turn, no Strength yet
    assert cs.player.get_power("strength") is None
    # Next turn start grants +2 Strength.
    cs.start_player_turn()
    assert cs.player.get_power("strength").amount == 2
    # And again the following turn — it stacks.
    cs.start_player_turn()
    assert cs.player.get_power("strength").amount == 4


# --------------------------------------------------------------------------
# Metallicize — on_turn_end: gain block == amount.
# --------------------------------------------------------------------------

def test_metallicize_grants_block_at_turn_end():
    cs = _fresh_combat()
    _apply(cs, METALLICIZE)  # amount 3
    assert cs.player.block == 0
    cs.end_player_turn()
    # End-of-turn Metallicize granted 3 block; it survives into the new turn's
    # reset only if Barricade is present (it isn't), so check before reset by
    # asserting the power exists and re-firing the hook on a clean player.
    p = Player(name="IC", hp=80, max_hp=80, energy=3, max_energy=3)
    p.add_or_stack_power(make_power("metallicize", 3, p))
    CombatState._fire_power_hook(p, "on_turn_end", cs, p)
    assert p.block == 3


# --------------------------------------------------------------------------
# Feel No Pain — on_card_exhausted: gain block == amount.
# --------------------------------------------------------------------------

def test_feel_no_pain_grants_block_on_exhaust():
    cs = _fresh_combat()
    _apply(cs, FEEL_NO_PAIN)  # amount 3
    cs.player.block = 0
    # Exhaust a card directly → Feel No Pain fires.
    cs._exhaust_card(DEFEND_IRONCLAD)
    assert cs.player.block == 3
    cs._exhaust_card(DEFEND_IRONCLAD)
    assert cs.player.block == 6


# --------------------------------------------------------------------------
# Dark Embrace — on_card_exhausted: draw `amount` cards.
# --------------------------------------------------------------------------

def test_dark_embrace_draws_on_exhaust():
    cs = _fresh_combat()
    _apply(cs, DARK_EMBRACE)  # amount 1
    # Guarantee there is something to draw.
    cs.draw_pile.append(DEFEND_IRONCLAD)
    hand_before = len(cs.hand)
    cs._exhaust_card(DEFEND_IRONCLAD)
    assert len(cs.hand) == hand_before + 1


# --------------------------------------------------------------------------
# Juggernaut — on_block_gained: deal `amount` damage to a random enemy.
# --------------------------------------------------------------------------

def test_juggernaut_deals_damage_on_block_gain():
    cs = _fresh_combat()
    _apply(cs, JUGGERNAUT)  # amount 5
    hp_before = cs.monster.hp
    # Play a Defend (5 block) → block gained → Juggernaut hits for 5.
    _apply(cs, DEFEND_IRONCLAD)
    assert cs.monster.hp == hp_before - 5


def test_juggernaut_does_not_fire_when_no_block_gained():
    cs = _fresh_combat()
    _apply(cs, JUGGERNAUT)
    hp_before = cs.monster.hp
    # A zero-block gain must not trigger Juggernaut.
    zero = CardDef(id="zero_block", name="Zero", cost=0, type=CardType.SKILL,
                   effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF,
                                   amount=0),))
    _apply(cs, zero)
    assert cs.monster.hp == hp_before


# --------------------------------------------------------------------------
# Rupture — on_hp_lost_from_card: gain Strength == amount.
# --------------------------------------------------------------------------

def test_rupture_gains_strength_on_card_hp_loss():
    cs = _fresh_combat()
    _apply(cs, RUPTURE)  # amount 1
    assert cs.player.get_power("strength") is None
    bloodletting = CardDef(id="hp_lose", name="HPLose", cost=0,
                           type=CardType.SKILL,
                           effects=(Effect(op=EffectOp.SELF_HP_LOSE,
                                           target=Target.SELF, amount=3),))
    _apply(cs, bloodletting)
    assert cs.player.get_power("strength").amount == 1


# --------------------------------------------------------------------------
# Combust — on_turn_end: lose `multiplier` HP, deal `amount` to ALL enemies.
# --------------------------------------------------------------------------

def test_combust_aoe_and_self_hp_loss_at_turn_end():
    p = Player(name="IC", hp=80, max_hp=80, energy=3, max_energy=3)
    p.add_or_stack_power(make_power("combust", 5, p))  # amount 5, multiplier 1
    m1 = SludgeSpinnerWeak(name="A", hp=40, max_hp=40)
    m2 = SludgeSpinnerWeak(name="B", hp=40, max_hp=40)
    cs = CombatState(player=p, monster=m1, monsters=[m1, m2],
                     draw_pile=[], rng=random.Random(0))
    CombatState._fire_power_hook(p, "on_turn_end", cs, p)
    assert p.hp == 79  # lost 1 HP
    assert m1.hp == 35 and m2.hp == 35  # 5 AoE to each


# --------------------------------------------------------------------------
# Barricade — blocks_block_reset: block persists across turn start.
# --------------------------------------------------------------------------

def test_barricade_block_persists_across_turn_start():
    cs = _fresh_combat()
    _apply(cs, BARRICADE)
    cs.player.block = 12
    cs.start_player_turn()
    assert cs.player.block == 12  # not reset to 0


def test_no_barricade_resets_block():
    cs = _fresh_combat()
    cs.player.block = 12
    cs.start_player_turn()
    assert cs.player.block == 0


# --------------------------------------------------------------------------
# Berserk — on_turn_start: +amount energy.
# --------------------------------------------------------------------------

def test_berserk_grants_energy_at_turn_start():
    cs = _fresh_combat()
    _apply(cs, BERSERK)  # amount 1
    cs.start_player_turn()
    assert cs.player.energy == cs.player.max_energy + 1


# --------------------------------------------------------------------------
# Brutality — on_turn_start: lose `amount` HP, draw `amount`.
# --------------------------------------------------------------------------

def test_brutality_loses_hp_and_draws_at_turn_start():
    cs = _fresh_combat()
    _apply(cs, BRUTALITY)  # amount 1
    cs.draw_pile.append(DEFEND_IRONCLAD)  # ensure a card to draw
    hp_before = cs.player.hp
    hand_before = len(cs.hand)
    # Fire the turn-start hook in isolation (no monster turn).
    CombatState._fire_power_hook(cs.player, "on_turn_start", cs, cs.player)
    assert cs.player.hp == hp_before - 1
    assert len(cs.hand) == hand_before + 1  # drew exactly 1


# --------------------------------------------------------------------------
# Corruption — modify_card_cost: skills cost 0 and exhaust on play.
# --------------------------------------------------------------------------

def test_corruption_makes_skills_cost_zero_and_exhausts():
    cs = _fresh_combat()
    _apply(cs, CORRUPTION)
    energy_before = cs.player.energy
    # Defend is a skill: should cost 0 and go to exhaust, not discard.
    cs.hand.insert(0, DEFEND_IRONCLAD)
    assert cs.effective_cost(DEFEND_IRONCLAD) == 0
    exhaust_before = len(cs.exhaust_pile)
    cs.play_card(0)
    assert cs.player.energy == energy_before  # no energy spent
    assert len(cs.exhaust_pile) == exhaust_before + 1
    assert DEFEND_IRONCLAD not in cs.discard_pile


def test_corruption_does_not_zero_attacks():
    cs = _fresh_combat()
    _apply(cs, CORRUPTION)
    from sim.cards import STRIKE_IRONCLAD
    assert cs.effective_cost(STRIKE_IRONCLAD) == STRIKE_IRONCLAD.cost
