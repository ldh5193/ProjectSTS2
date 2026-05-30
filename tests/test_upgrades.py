"""Tests for the real card-upgrade system (Phase 7B).

Verifies that upgrade_card() produces stat-upgraded CardDefs (not just a
renamed id), that combat resolves the upgraded numbers, that the feature
vector reflects the improvements, and that the reward / Smith paths wire
through the real upgrade.
"""
from __future__ import annotations

from sim.cards import (
    BASH,
    BLUDGEON,
    DEFEND_IRONCLAD,
    DEMON_FORM,
    INFLAME,
    POMMEL_STRIKE,
    STRIKE_IRONCLAD,
    upgrade_card,
)
import random

from sim.card_catalog import CARDS, card_features
from sim.combat import CombatState
from sim.creatures import Player
from sim.dsl import EffectOp
from sim.monsters import SludgeSpinnerWeak


def _dmg_of(card) -> int:
    return sum(e.amount for e in card.effects if e.op is EffectOp.DEAL_DAMAGE)


def _block_of(card) -> int:
    return sum(e.amount for e in card.effects if e.op is EffectOp.GAIN_BLOCK)


def _power_amt(card, pid: str) -> int:
    return sum(e.amount for e in card.effects
               if e.op is EffectOp.APPLY_POWER and e.power_id == pid)


# --- Stat deltas (decompiled-verified) -------------------------------------

def test_strike_plus_is_9_damage():
    up = upgrade_card(STRIKE_IRONCLAD)
    assert up.id == "strike_ironclad+"
    assert up.name == "Strike+"
    assert _dmg_of(STRIKE_IRONCLAD) == 6
    assert _dmg_of(up) == 9


def test_defend_plus_is_8_block():
    up = upgrade_card(DEFEND_IRONCLAD)
    assert _block_of(DEFEND_IRONCLAD) == 5
    assert _block_of(up) == 8


def test_bash_plus_is_10_dmg_and_3_vuln():
    up = upgrade_card(BASH)
    assert _dmg_of(up) == 10
    assert _power_amt(up, "vulnerable") == 3


def test_bludgeon_plus_is_42():
    assert _dmg_of(upgrade_card(BLUDGEON)) == 42


def test_pommel_strike_plus_draws_two():
    up = upgrade_card(POMMEL_STRIKE)
    assert _dmg_of(up) == 10
    draw = sum(e.amount for e in up.effects if e.op is EffectOp.DRAW_CARD)
    assert draw == 2


def test_power_card_plus_applies_higher_amount():
    # Demon Form: 2 -> 3 Strength/turn.
    up = upgrade_card(DEMON_FORM)
    assert _power_amt(up, "demon_form") == 3
    # Inflame: 2 -> 3 Strength.
    assert _power_amt(upgrade_card(INFLAME), "strength") == 3


# --- Idempotence ------------------------------------------------------------

def test_upgrade_is_idempotent():
    once = upgrade_card(STRIKE_IRONCLAD)
    twice = upgrade_card(once)
    assert once is twice
    assert _dmg_of(twice) == 9
    assert twice.id == "strike_ironclad+"  # not "++"


# --- Combat actually resolves the upgraded numbers --------------------------

def _fresh_combat() -> CombatState:
    player = Player(name="IC", hp=80, max_hp=80, energy=3, max_energy=3)
    monster = SludgeSpinnerWeak(name="A", hp=100, max_hp=100)
    cs = CombatState(player=player, monster=monster, monsters=[monster],
                     draw_pile=[], rng=random.Random(0))
    return cs


def test_combat_resolves_strike_plus_damage():
    cs = _fresh_combat()
    cs.target_index = 0
    before = cs.monster.hp
    cs._resolve_effects(upgrade_card(STRIKE_IRONCLAD))
    assert before - cs.monster.hp == 9


def test_combat_resolves_defend_plus_block():
    cs = _fresh_combat()
    cs._resolve_effects(upgrade_card(DEFEND_IRONCLAD))
    assert cs.player.block == 8


# --- Feature vector reflects upgrade ----------------------------------------

def test_card_features_show_upgraded_and_higher_damage():
    base = card_features("strike_ironclad")
    up = card_features("strike_ironclad+")
    # feats[11] is the upgraded flag.
    assert base[11] == 0.0
    assert up[11] == 1.0
    # feats[4] is damage_total / 30. Upgraded must be strictly higher.
    assert up[4] > base[4]


# --- Reward path ------------------------------------------------------------

def test_reward_upgrade_path_produces_stat_upgraded_card():
    from sim.run_engine import upgrade_card as ru
    from sim.rewards import CardRewardChoice
    # Simulate the reward mapping done in run_engine for an upgraded choice.
    ch = CardRewardChoice(card_id="strike_ironclad", rarity=None, upgraded=True)
    card = ru(CARDS[ch.card_id]) if ch.upgraded else CARDS[ch.card_id]
    assert card.id.endswith("+")
    assert _dmg_of(card) == 9


# --- Smith path (rest site) -------------------------------------------------

def test_smith_upgrades_a_deck_card_with_real_stats():
    from sim.run_engine import RunState, StepResult, _step_rest

    rs = RunState()
    # Put a fresh deck containing a basic Strike.
    rs.deck = [STRIKE_IRONCLAD]
    rs.max_hp = 80
    rs.hp = 80
    rs.pending_rest_options = [{"id": "smith"}]
    _step_rest(rs, {"action": "choose_rest_option", "index": 0}, StepResult())
    upgraded = rs.deck[0]
    assert upgraded.id == "strike_ironclad+"
    assert _dmg_of(upgraded) == 9
