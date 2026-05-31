"""Phase 8B.8 — POWER tranche fidelity tests.

Each newly-implemented power's trigger fires with the exact .cs effect:
state before/after, correct stacking/decay, and damage/block modification
direction + magnitude (real numbers from the decompile).

Cites: decompiled/MegaCrit.Sts2.Core.Models.Powers/{NoxiousFumes,Mayhem,
Burst,Accuracy,Territorial,PaperCuts,Tracking,Knockdown,Guarded,Covered,
NoBlock,Demesne,Tyranny,MindRot,WasteAway,Strangle,Slippery,HardToKill,
DarkShackles,PiercingWail,FeedingFrenzy}Power.cs and the monster classes
{Byrdonis,Exoskeleton,ScrollOfBiting,Vantom,Inklet}.cs.
"""
from __future__ import annotations

import random

from sim.combat import CombatState, HAND_SIZE
from sim.creatures import Monster, Player
from sim.damage import compute_modified_damage, deal_damage, gain_block
from sim.dsl import CardDef, CardType, Effect, EffectOp, Target
from sim.monsters import Byrdonis, Exoskeleton, Inklet, ScrollOfBiting, Vantom
from sim.powers import POWER_REGISTRY, make_power

_NEW = (
    "noxious_fumes", "mayhem", "burst", "accuracy", "territorial",
    "paper_cuts", "tracking", "knockdown", "guarded", "covered", "no_block",
    "demesne", "tyranny", "mind_rot", "waste_away", "strangle", "slippery",
    "hard_to_kill", "dark_shackles", "piercing_wail", "feeding_frenzy",
)


def _player(hp=80):
    return Player(name="P", hp=hp, max_hp=hp, energy=3, max_energy=3)


def _monster(hp=50):
    return Monster(name="M", hp=hp, max_hp=hp)


# --------------------------------------------------------------------------
# Breadth + constructibility.
# --------------------------------------------------------------------------

def test_registry_grew_and_constructible():
    print(f"\nPOWER_REGISTRY: {len(POWER_REGISTRY)}/262")
    assert len(POWER_REGISTRY) >= 101
    dummy = _monster()
    for pid in _NEW:
        assert pid in POWER_REGISTRY, pid
        assert make_power(pid, 1, dummy).id == pid


# --------------------------------------------------------------------------
# NoxiousFumes — turn start: apply Poison=amount to ALL enemies.
# --------------------------------------------------------------------------

def test_noxious_fumes_poisons_all_at_turn_start():
    cs = CombatState.new_combat(seed=1)
    cs.player.add_or_stack_power(make_power("noxious_fumes", 3, cs.player))
    for m in cs.alive_monsters():
        assert m.get_power("poison") is None
    cs.start_player_turn()
    for m in cs.alive_monsters():
        assert m.get_power("poison").amount == 3


# --------------------------------------------------------------------------
# Mayhem — turn start: auto-play top `amount` cards of the draw pile.
# --------------------------------------------------------------------------

def test_mayhem_autoplays_top_of_draw():
    cs = CombatState.new_combat(seed=2)
    cs.start_player_turn()              # do the hand-draw first
    m = cs.monster
    # A 6-damage attack on top of the (post-draw) draw pile.
    atk = CardDef(id="t_strike", name="T", cost=0, type=CardType.ATTACK,
                  effects=[Effect(op=EffectOp.DEAL_DAMAGE,
                                  target=Target.SELECTED_ENEMY, amount=6)])
    cs.draw_pile.append(atk)            # top of pile
    mayhem = make_power("mayhem", 1, cs.player)
    cs.player.add_or_stack_power(mayhem)
    hp_before = m.hp
    mayhem.on_turn_start(cs, cs.player)  # AfterPlayerTurnStart: auto-play top
    assert m.hp == hp_before - 6        # the top card was auto-played
    assert atk in cs.discard_pile       # it went to discard


# --------------------------------------------------------------------------
# Burst — the next Skill plays one extra time; consumed; removed at turn end.
# --------------------------------------------------------------------------

def test_burst_doubles_next_skill_only():
    cs = CombatState.new_combat(seed=3)
    cs.start_player_turn()
    cs.player.add_or_stack_power(make_power("burst", 1, cs.player))
    skill = CardDef(id="t_block", name="B", cost=0, type=CardType.SKILL,
                    effects=[Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF,
                                    amount=5)])
    cs.hand.insert(0, skill)
    cs.player.block = 0
    cs.play_card(0)
    assert cs.player.block == 10                 # 5 played twice
    assert cs.player.get_power("burst") is None  # charge consumed


def test_burst_ignores_attacks():
    cs = CombatState.new_combat(seed=4)
    cs.start_player_turn()
    cs.player.add_or_stack_power(make_power("burst", 1, cs.player))
    m = cs.monster
    atk = CardDef(id="t_strike", name="T", cost=0, type=CardType.ATTACK,
                  effects=[Effect(op=EffectOp.DEAL_DAMAGE,
                                  target=Target.SELECTED_ENEMY, amount=6)])
    cs.hand.insert(0, atk)
    hp_before = m.hp
    cs.play_card(0)
    assert m.hp == hp_before - 6                       # only once
    assert cs.player.get_power("burst").amount == 1    # not consumed by Attacks


# --------------------------------------------------------------------------
# Accuracy — +amount additive damage on the owner's Shiv attacks only.
# --------------------------------------------------------------------------

def test_accuracy_buffs_shivs_only():
    cs = CombatState.new_combat(seed=5)
    cs.start_player_turn()
    cs.player.add_or_stack_power(make_power("accuracy", 4, cs.player))
    m = cs.monster
    shiv = CardDef(id="shiv", name="Shiv", cost=0, type=CardType.ATTACK,
                   effects=[Effect(op=EffectOp.DEAL_DAMAGE,
                                   target=Target.SELECTED_ENEMY, amount=4)])
    strike = CardDef(id="t_strike", name="T", cost=0, type=CardType.ATTACK,
                     effects=[Effect(op=EffectOp.DEAL_DAMAGE,
                                     target=Target.SELECTED_ENEMY, amount=4)])
    # Non-shiv: 4 damage, no bonus.
    cs.hand.insert(0, strike)
    hp = m.hp
    cs.play_card(0)
    assert m.hp == hp - 4
    # Shiv: 4 + 4 accuracy = 8 damage.
    cs.hand.insert(0, shiv)
    hp = m.hp
    cs.play_card(0)
    assert m.hp == hp - 8


# --------------------------------------------------------------------------
# Territorial — +Strength at turn end (Byrdonis at spawn).
# --------------------------------------------------------------------------

def test_territorial_gains_strength_at_turn_end():
    m = _monster()
    m.add_or_stack_power(make_power("territorial", 1, m))
    m.get_power("territorial").on_turn_end(None, m)
    assert m.get_power("strength").amount == 1
    m.get_power("territorial").on_turn_end(None, m)
    assert m.get_power("strength").amount == 2


def test_byrdonis_spawns_with_territorial():
    b = Byrdonis.spawn(random.Random(0))
    assert b.get_power("territorial") is not None
    assert b.get_power("territorial").amount == 1


# --------------------------------------------------------------------------
# PaperCuts — landing an unblocked powered hit costs the victim max HP.
# --------------------------------------------------------------------------

def test_paper_cuts_reduces_victim_max_hp():
    p = _player(hp=80)
    m = _monster()
    m.add_or_stack_power(make_power("paper_cuts", 2, m))
    deal_damage(6, m, p)                 # monster lands 6 unblocked on player
    assert p.max_hp == 78                # 80 - 2 max HP
    assert p.hp == 74                    # took 6 dmg


def test_paper_cuts_no_maxhp_loss_if_fully_blocked():
    p = _player(hp=80)
    p.block = 100
    m = _monster()
    m.add_or_stack_power(make_power("paper_cuts", 2, m))
    deal_damage(6, m, p)                 # fully blocked -> no unblocked dmg
    assert p.max_hp == 80


def test_scroll_of_biting_spawns_with_paper_cuts():
    s = ScrollOfBiting.spawn(random.Random(0))
    assert s.get_power("paper_cuts").amount == 2


# --------------------------------------------------------------------------
# Tracking — ×amount damage vs Weak targets (owner's attacks).
# --------------------------------------------------------------------------

def test_tracking_multiplies_vs_weak():
    p = _player()
    m = _monster()
    p.add_or_stack_power(make_power("tracking", 2, p))
    # No Weak on target -> no bonus.
    assert compute_modified_damage(10, p, m) == 10
    m.add_or_stack_power(make_power("weak", 2, m))
    # Weak target -> ×2 (Tracking returns base.Amount as the multiplier).
    assert compute_modified_damage(10, p, m) == 20


# --------------------------------------------------------------------------
# Knockdown — powered attacks on the owner deal ×amount (debuff on a monster).
# --------------------------------------------------------------------------

def test_knockdown_amplifies_incoming():
    p = _player()
    m = _monster()
    m.add_or_stack_power(make_power("knockdown", 2, m))
    assert compute_modified_damage(10, p, m) == 20   # ×2 onto the owner


# --------------------------------------------------------------------------
# Guarded — powered attacks on the owner halved.
# --------------------------------------------------------------------------

def test_guarded_halves_incoming():
    p = _player()
    m = _monster()
    m.add_or_stack_power(make_power("guarded", 1, m))
    assert compute_modified_damage(10, p, m) == 5


# --------------------------------------------------------------------------
# Covered — powered attacks on the owner fully negated (×0).
# --------------------------------------------------------------------------

def test_covered_negates_incoming():
    p = _player()
    m = _monster()
    m.add_or_stack_power(make_power("covered", 1, m))
    assert compute_modified_damage(20, p, m) == 0


# --------------------------------------------------------------------------
# NoBlock — owner's card block reduced to 0 (Unpowered block unaffected).
# --------------------------------------------------------------------------

def test_no_block_zeroes_card_block():
    p = _player()
    p.add_or_stack_power(make_power("no_block", 1, p))
    p.block = 0
    gain_block(p, 8)                     # routed through block-multiplicative
    assert p.block == 0


# --------------------------------------------------------------------------
# Demesne — +amount hand draw AND +amount max energy.
# --------------------------------------------------------------------------

def test_demesne_adds_draw_and_energy():
    cs = CombatState.new_combat(seed=6)
    cs.player.add_or_stack_power(make_power("demesne", 1, cs.player))
    cs.start_player_turn()
    assert len(cs.hand) == HAND_SIZE + 1
    assert cs.player.energy == cs.player.max_energy + 1


# --------------------------------------------------------------------------
# Tyranny — +amount hand draw, then exhaust `amount` at turn start.
# --------------------------------------------------------------------------

def test_tyranny_draws_more_then_exhausts():
    cs = CombatState.new_combat(seed=7)
    cs.player.add_or_stack_power(make_power("tyranny", 1, cs.player))
    cs.start_player_turn()
    # Drew HAND_SIZE+1, then exhausted 1 -> HAND_SIZE in hand.
    assert len(cs.hand) == HAND_SIZE
    assert len(cs.exhaust_pile) == 1


# --------------------------------------------------------------------------
# MindRot — -amount hand draw (floored at 0).
# --------------------------------------------------------------------------

def test_mind_rot_reduces_draw():
    cs = CombatState.new_combat(seed=8)
    cs.player.add_or_stack_power(make_power("mind_rot", 2, cs.player))
    cs.start_player_turn()
    assert len(cs.hand) == HAND_SIZE - 2


# --------------------------------------------------------------------------
# WasteAway — -amount max energy.
# --------------------------------------------------------------------------

def test_waste_away_reduces_energy():
    cs = CombatState.new_combat(seed=9)
    cs.player.add_or_stack_power(make_power("waste_away", 1, cs.player))
    cs.start_player_turn()
    assert cs.player.energy == cs.player.max_energy - 1


# --------------------------------------------------------------------------
# Strangle — each card played, take amount unblockable; removed at turn end.
# --------------------------------------------------------------------------

def test_strangle_damages_on_each_card_then_clears():
    cs = CombatState.new_combat(seed=10)
    cs.start_player_turn()
    cs.player.add_or_stack_power(make_power("strangle", 3, cs.player))
    hp = cs.player.hp
    skill = CardDef(id="t_block", name="B", cost=0, type=CardType.SKILL,
                    effects=[Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF,
                                    amount=5)])
    cs.hand.insert(0, skill)
    cs.play_card(0)
    assert cs.player.hp == hp - 3        # unblockable strangle damage
    # Removed at the player's own turn end.
    cs.player.get_power("strangle").on_turn_end(cs, cs.player)
    assert cs.player.get_power("strangle") is None


# --------------------------------------------------------------------------
# Slippery — caps each incoming instance to 1, decrements per damage taken.
# --------------------------------------------------------------------------

def test_slippery_caps_damage_and_decays():
    p = _player()
    m = _monster(hp=50)
    m.add_or_stack_power(make_power("slippery", 2, m))
    deal_damage(20, p, m)                # capped to 1
    assert m.hp == 49 and m.get_power("slippery").amount == 1
    deal_damage(20, p, m)                # capped to 1, last charge -> removed
    assert m.hp == 48 and m.get_power("slippery") is None
    deal_damage(20, p, m)                # no cap now: full 20
    assert m.hp == 28


def test_vantom_spawns_with_slippery_9():
    v = Vantom.spawn(random.Random(0))
    assert v.get_power("slippery").amount == 9


def test_inklet_spawns_with_slippery_1():
    ink = Inklet.spawn(random.Random(0))
    assert ink.get_power("slippery").amount == 1


# --------------------------------------------------------------------------
# HardToKill — caps damage the owner takes per instance to `amount`.
# --------------------------------------------------------------------------

def test_hard_to_kill_caps_per_hit():
    p = _player()
    m = _monster(hp=50)
    m.add_or_stack_power(make_power("hard_to_kill", 9, m))
    deal_damage(30, p, m)                # capped to 9
    assert m.hp == 41
    # Small hits pass through unchanged.
    deal_damage(5, p, m)
    assert m.hp == 36


def test_exoskeleton_spawns_with_hard_to_kill_9():
    e = Exoskeleton.spawn(random.Random(0))
    assert e.get_power("hard_to_kill").amount == 9


# --------------------------------------------------------------------------
# DarkShackles / PiercingWail — temporary Strength-down, lifted at turn end.
# --------------------------------------------------------------------------

def test_dark_shackles_reduces_outgoing_then_lifts():
    m = _monster()
    p = _player()
    m.add_or_stack_power(make_power("dark_shackles", 4, m))
    # Monster deals 10 -> 10-4 = 6.
    assert compute_modified_damage(10, m, p) == 6
    # Lifted at the monster's own turn end.
    m.get_power("dark_shackles").on_turn_end(None, m)
    assert m.get_power("dark_shackles") is None
    assert compute_modified_damage(10, m, p) == 10


def test_piercing_wail_reduces_outgoing():
    m = _monster()
    p = _player()
    m.add_or_stack_power(make_power("piercing_wail", 6, m))
    assert compute_modified_damage(10, m, p) == 4


# --------------------------------------------------------------------------
# FeedingFrenzy — temporary +Strength, lifted at turn end.
# --------------------------------------------------------------------------

def test_feeding_frenzy_boosts_then_lifts():
    p = _player()
    m = _monster()
    p.add_or_stack_power(make_power("feeding_frenzy", 3, p))
    assert compute_modified_damage(6, p, m) == 9
    p.get_power("feeding_frenzy").on_turn_end(None, p)
    assert p.get_power("feeding_frenzy") is None
    assert compute_modified_damage(6, p, m) == 6
