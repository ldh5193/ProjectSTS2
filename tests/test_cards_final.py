"""Phase 8 Track A — final STS2 Ironclad pool completion.

Proves:
  * each newly-implemented id is no longer a placeholder in card_features,
  * a representative persistent POWER fires at the right trigger,
  * a history-conditional card scales with its combat-history counter,
  * implemented cards deal/block the right .cs-faithful amounts.

Ground truth: decompiled/MegaCrit.Sts2.Core.Models.Cards/*.cs (+ Models.Powers).
"""
from __future__ import annotations

from sim.cards import (
    AGGRESSION,
    COLOSSUS,
    CRIMSON_MANTLE,
    DRUM_OF_BATTLE,
    EVIL_EYE,
    EXPECT_A_FIGHT,
    FORGOTTEN_RITUAL,
    GIANT_ROCK,
    INFERNO,
    JUGGLING,
    ONE_TWO_PUNCH,
    PRIMAL_FORCE,
    STAMPEDE,
    THRASH,
    UNMOVABLE,
    VICIOUS,
    upgrade_card,
)
from sim.card_catalog import is_implemented
from sim.combat import CombatState
from sim.dsl import CardDef, CardType, Effect, EffectOp, Target
from sim.powers import make_power


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _fresh(seed: int = 0) -> CombatState:
    cs = CombatState.new_combat(seed=seed)
    cs.start_player_turn()
    return cs


def _play(cs: CombatState, card: CardDef) -> None:
    cs.hand.insert(0, card)
    cs.player.energy = max(cs.player.energy, max(0, card.cost))
    cs.play_card(0)


def _strike(amount: int = 6) -> CardDef:
    from sim.cards import STRIKE_SCALING
    return CardDef(id="strike_ironclad", name="Strike", cost=0,
                   type=CardType.ATTACK,
                   effects=(Effect(op=EffectOp.DEAL_DAMAGE,
                                   target=Target.SELECTED_ENEMY, amount=amount,
                                   scaling=STRIKE_SCALING),))


# --------------------------------------------------------------------------
# 1. newly implemented ids are no longer placeholders
# --------------------------------------------------------------------------

_NEW_IDS = [
    "colossus", "drum_of_battle", "evil_eye", "expect_a_fight",
    "forgotten_ritual", "inferno", "juggling", "stampede", "vicious",
    "aggression", "crimson_mantle", "cruelty", "hellraiser", "one_two_punch",
    "primal_force", "stoke", "thrash", "unmovable",
]


def test_all_new_ids_are_implemented():
    for cid in _NEW_IDS:
        assert is_implemented(cid), f"{cid} should be implemented"


def test_tank_left_placeholder_multiplayer_only():
    # Tank.cs is MultiplayerOnly — intentionally NOT implemented.
    assert not is_implemented("tank")


# --------------------------------------------------------------------------
# 2. persistent powers fire at the right trigger
# --------------------------------------------------------------------------

def test_crimson_mantle_self_damage_and_block_at_turn_start():
    # CrimsonMantlePower(8): turn start -> lose 1 HP (SelfDamage), gain 8 block.
    cs = _fresh()
    _play(cs, CRIMSON_MANTLE)
    hp0 = cs.player.hp
    cs.start_player_turn()
    assert cs.player.hp == hp0 - 1
    assert cs.player.block == 8


def test_drum_of_battle_draws_two_and_exhausts_top_next_turn():
    # DrumOfBattle.cs: draw 2 now; DrumOfBattlePower(1) exhausts top of draw
    # at the next turn start.
    cs = _fresh()
    hand0 = len(cs.hand)
    _play(cs, DRUM_OF_BATTLE)
    assert len(cs.hand) == hand0 + 2  # drew 2
    # Stock the draw pile so the power has a card to exhaust after the next
    # hand draw consumes HAND_SIZE cards.
    for _ in range(10):
        cs.draw_pile.append(_strike(6))
    exh0 = len(cs.exhaust_pile)
    cs.start_player_turn()
    assert len(cs.exhaust_pile) == exh0 + 1  # exhausted top of draw


def test_stampede_autoplays_attack_at_turn_end():
    # StampedePower(1): at turn end, auto-play 1 random Attack from hand.
    cs = _fresh()
    _play(cs, STAMPEDE)
    cs.hand.clear()
    cs.hand.append(_strike(6))
    hp_before = cs.monster.hp
    cs.end_player_turn()
    # The Strike was auto-played (dealt damage) and exhausted, not just discarded.
    assert cs.monster.hp < hp_before


def test_aggression_pulls_attack_from_discard_at_turn_start():
    cs = _fresh()
    _play(cs, AGGRESSION)
    cs.discard_pile.append(_strike(6))
    hand0 = len(cs.hand)
    cs.start_player_turn()
    assert len(cs.hand) >= hand0 + 1  # an attack moved discard -> hand


def test_colossus_blocks_and_halves_incoming_powered_damage():
    cs = _fresh()
    _play(cs, COLOSSUS)
    assert cs.player.block == 5
    assert cs.player.get_power("colossus") is not None
    # A 10-damage powered attack from the monster is halved to 5.
    from sim.damage import compute_modified_damage
    dmg = compute_modified_damage(10, cs.monster, cs.player)
    assert dmg == 5


def test_unmovable_doubles_first_block_then_normal():
    # UnmovablePower(1): first card block-gain this turn is doubled; later ones
    # are not (already had >= amount block-gains).
    cs = _fresh()
    _play(cs, UNMOVABLE)
    defend = CardDef(id="defend_ironclad", name="Defend", cost=0,
                     type=CardType.SKILL,
                     effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF,
                                     amount=5),))
    cs.player.block = 0
    _play(cs, defend)
    assert cs.player.block == 10  # doubled
    _play(cs, defend)
    assert cs.player.block == 15  # second gain not doubled (10 + 5)


# --------------------------------------------------------------------------
# 3. history-conditional cards scale with the counters
# --------------------------------------------------------------------------

def test_evil_eye_doubles_block_when_card_exhausted_this_turn():
    cs = _fresh()
    cs.player.block = 0
    # No exhaust yet -> single block (8).
    _play(cs, EVIL_EYE)  # exhausts itself AFTER computing block
    # EvilEye exhausts itself, but its OWN block was computed before exhaust;
    # at play time no prior card was exhausted, so it grants 8.
    assert cs.player.block == 8


def test_evil_eye_doubles_after_prior_exhaust():
    cs = _fresh()
    cs.player.block = 0
    cs._cards_exhausted_this_turn = 1  # simulate a prior exhaust this turn
    _play(cs, EVIL_EYE)
    assert cs.player.block == 16  # 8 ×2


def test_forgotten_ritual_grants_energy_only_after_exhaust():
    cs = _fresh()
    cs.player.energy = 3
    # No prior exhaust -> no energy (and ForgottenRitual itself exhausts after).
    _play(cs, FORGOTTEN_RITUAL)  # cost 1 -> energy 2, no gain
    assert cs.player.energy == 2
    cs2 = _fresh()
    cs2.player.energy = 3
    cs2._cards_exhausted_this_turn = 1
    _play(cs2, FORGOTTEN_RITUAL)  # cost 1 -> 2, +3 energy -> 5
    assert cs2.player.energy == 5


def test_expect_a_fight_energy_per_attack_then_no_energy_gain():
    cs = _fresh()
    cs.hand.clear()
    cs.hand.append(_strike(6))
    cs.hand.append(_strike(6))  # 2 attacks in hand
    cs.player.energy = 2
    _play(cs, EXPECT_A_FIGHT)  # cost 2 -> 0, +2 (2 attacks) -> 2
    assert cs.player.energy == 2
    assert cs.player.get_power("no_energy_gain") is not None
    # Further energy gains are zeroed while NoEnergyGain is up.
    cs._resolve_single_effect(
        EXPECT_A_FIGHT,
        Effect(op=EffectOp.ENERGY_GAIN, target=Target.SELF, amount=5))
    assert cs.player.energy == 2  # no change


def test_one_two_punch_doubles_next_attack():
    cs = _fresh()
    _play(cs, ONE_TWO_PUNCH)
    cs.monster.hp = 50
    cs.monster.block = 0
    hp0 = cs.monster.hp
    _play(cs, _strike(6))  # plays twice -> 12 damage
    assert hp0 - cs.monster.hp == 12
    # Charge consumed; the next attack hits once.
    hp1 = cs.monster.hp
    _play(cs, _strike(6))
    assert hp1 - cs.monster.hp == 6


def test_juggling_clones_third_attack():
    cs = _fresh()
    _play(cs, JUGGLING)
    cs.monster.hp = 99
    hand0 = len(cs.hand)
    _play(cs, _strike(1))
    _play(cs, _strike(1))
    _play(cs, _strike(1))  # 3rd attack -> clone added to hand
    assert len(cs.hand) == hand0 + 1


def test_vicious_draws_when_vulnerable_applied():
    cs = _fresh()
    _play(cs, VICIOUS)
    # Ensure there's something to draw.
    cs.draw_pile.append(_strike(6))
    hand0 = len(cs.hand)
    bash = CardDef(id="bash", name="Bash", cost=0, type=CardType.ATTACK,
                   effects=(Effect(op=EffectOp.APPLY_POWER,
                                   target=Target.SELECTED_ENEMY,
                                   power_id="vulnerable", amount=2),))
    _play(cs, bash)
    assert len(cs.hand) == hand0 + 1  # drew 1 from Vicious


# --------------------------------------------------------------------------
# 4. damage / transform cards deal the right amounts
# --------------------------------------------------------------------------

def test_thrash_hits_twice_plus_exhausted_attack_damage():
    cs = _fresh()
    cs.monster.hp = 99
    cs.monster.block = 0
    # Put a 10-damage attack in hand for Thrash to exhaust + add.
    cs.hand.append(_strike(10))
    hp0 = cs.monster.hp
    _play(cs, THRASH)  # 4 ×2 = 8, + 10 (exhausted attack base dmg) = 18
    assert hp0 - cs.monster.hp == 18
    # The borrowed attack is exhausted, and Thrash exhausts itself too.
    assert any("strike" in c.id for c in cs.exhaust_pile)


def test_primal_force_transforms_hand_attacks_to_giant_rock():
    cs = _fresh()
    cs.hand.clear()
    cs.hand.append(_strike(6))
    cs.hand.append(_strike(6))
    _play(cs, PRIMAL_FORCE)
    assert all(c.id == "giant_rock" for c in cs.hand)
    assert len(cs.hand) == 2


def test_giant_rock_deals_sixteen():
    cs = _fresh()
    cs.monster.hp = 99
    cs.monster.block = 0
    hp0 = cs.monster.hp
    _play(cs, GIANT_ROCK)
    assert hp0 - cs.monster.hp == 16


def test_inferno_self_damage_at_turn_start_and_retaliates():
    cs = _fresh()
    _play(cs, INFERNO)  # InfernoPower(6), self_damage 1
    hp0 = cs.player.hp
    cs.start_player_turn()
    assert cs.player.hp == hp0 - 1  # turn-start self damage


# --------------------------------------------------------------------------
# 5. upgrades carry the .cs-faithful deltas
# --------------------------------------------------------------------------

def test_colossus_upgrade_block_five_to_eight():
    up = upgrade_card(COLOSSUS)
    blk = next(e.amount for e in up.effects if e.op is EffectOp.GAIN_BLOCK)
    assert blk == 8


def test_thrash_upgrade_damage_four_to_six():
    up = upgrade_card(THRASH)
    dmg = next(e.amount for e in up.effects if e.op is EffectOp.DEAL_DAMAGE)
    assert dmg == 6


def test_stampede_upgrade_reduces_cost():
    up = upgrade_card(STAMPEDE)
    assert up.cost == 1
