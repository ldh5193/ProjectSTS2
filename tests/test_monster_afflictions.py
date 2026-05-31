"""Phase 8B.12 — monster card-affliction wiring tests.

Proves that the four monsters that apply a *card-affliction* status power in
the decompiled game now apply the REAL power (with the right amount, on the
right move) in the sim — replacing the previous Weak/Frail approximations —
and that the affliction then has its real effect on the player's cards.

Also covers the two event enchants closed this batch (SoulsPower exhaust
removal, PerfectFit shuffle-to-top) now that the enchantment layer + combat
shuffle hook exist.

Real numbers straight from:
  decompiled/MegaCrit.Sts2.Core.Models.Monsters/{SpectralKnight,MagiKnight,
    VineShambler,Doormaker}.cs
  decompiled/MegaCrit.Sts2.Core.Models.Powers/{HexPower,DampenPower,
    TangledPower,HungerPower}.cs
  decompiled/MegaCrit.Sts2.Core.Models.Enchantments/{SoulsPower,PerfectFit}.cs
"""
from __future__ import annotations

import random
from dataclasses import replace

from sim.cards import STRIKE_IRONCLAD, DEFEND_IRONCLAD, upgrade_card
from sim.combat import CombatState
from sim.creatures import Player
from sim.dsl import CardType
from sim.enchantments import (
    enchant_card, can_enchant, card_keywords, SOULS, PERFECT_FIT, KW_EXHAUST,
)
from sim.monsters import (
    SpectralKnight, MagiKnight, VineShambler, Doormaker, DoormakerMove,
)


def _player(hp: int = 200) -> Player:
    return Player(name="Ironclad", hp=hp, max_hp=hp, energy=3, max_energy=3)


def _combat(monster, hand=None, draw=None) -> CombatState:
    """Standalone combat with `monster` and a controllable hand/draw, with the
    combat back-reference attached (so monster affliction moves can mutate the
    player's cards via the AfterApplied hook)."""
    cs = CombatState(player=_player(), monster=monster, monsters=[monster],
                     draw_pile=list(draw or []), hand=list(hand or []),
                     rng=random.Random(0))
    cs._attach_combat_refs()
    return cs


def _run_move(cs, monster, move) -> None:
    """Force `monster` to perform `move` this monster turn."""
    monster.next_move = move
    cs.monster_turn()


# ===========================================================================
# SpectralKnight — HEX applies HexPower 2 (SpectralKnight.cs:66).
# ===========================================================================
def test_spectral_knight_hex_applies_hex_power_2():
    m = SpectralKnight.spawn(random.Random(0), ascension=0)
    hand = [STRIKE_IRONCLAD, DEFEND_IRONCLAD]
    cs = _combat(m, hand=hand)
    _run_move(cs, m, "HEX")
    hex_power = cs.player.get_power("hex")
    assert hex_power is not None
    assert hex_power.amount == 2  # PowerCmd.Apply<HexPower>(target, 2m)
    # HexPower.AfterApplied: every card gets Hexed + Ethereal.
    for c in cs.hand:
        assert c.affliction is not None and c.affliction.id == "hexed"
        assert "ethereal" in card_keywords(c)


def test_spectral_knight_opens_on_hex_then_soul_slash():
    # SpectralKnight.cs move machine: HEX -> SOUL_SLASH -> RAND.
    m = SpectralKnight.spawn(random.Random(0), ascension=0)
    assert m.next_move == "HEX"
    cs = _combat(m, hand=[STRIKE_IRONCLAD])
    cs.monster_turn()             # HEX
    assert m.last_move == "HEX"
    assert m.next_move == "SOUL_SLASH"


# ===========================================================================
# MagiKnight — DAMPEN applies DampenPower 1 (MagiKnight.cs:89).
# ===========================================================================
def test_magi_knight_dampen_applies_dampen_power_1_and_downgrades():
    m = MagiKnight.spawn(random.Random(0), ascension=0)
    up_strike = upgrade_card(STRIKE_IRONCLAD)   # id ends with '+'
    cs = _combat(m, hand=[up_strike])
    assert up_strike.id.endswith("+")
    _run_move(cs, m, "DAMPEN")
    dampen = cs.player.get_power("dampen")
    assert dampen is not None and dampen.amount == 1
    # DampenPower.AfterApplied: every UPGRADED card is downgraded.
    assert all(not c.id.endswith("+") for c in cs.hand)
    # AfterRemoved restores the upgrade.
    cs.remove_player_affliction_power("dampen")
    assert any(c.id.endswith("+") for c in cs.hand)


def test_magi_knight_move_cycle_matches_decompile():
    # POWER_SHIELD -> DAMPEN -> SPEAR -> PREP -> MAGIC_BOMB -> SPEAR (loop).
    m = MagiKnight.spawn(random.Random(0), ascension=0)
    seq = []
    cs = _combat(m, hand=[STRIKE_IRONCLAD])
    for _ in range(6):
        seq.append(m.next_move)
        cs.monster_turn()
    assert seq == ["POWER_SHIELD", "DAMPEN", "SPEAR", "PREP", "MAGIC_BOMB",
                   "SPEAR"]


# ===========================================================================
# VineShambler — GRASPING_VINES applies TangledPower 1 (VineShambler.cs:66).
# ===========================================================================
def test_vine_shambler_grasping_vines_applies_tangled_power_1():
    m = VineShambler.spawn(random.Random(0), ascension=0)
    cs = _combat(m, hand=[STRIKE_IRONCLAD])
    hp0 = cs.player.hp
    _run_move(cs, m, "GRASPING_VINES")
    tangled = cs.player.get_power("tangled")
    assert tangled is not None and tangled.amount == 1
    # TangledPower.AfterApplied: Attack cards entangled (+1 energy cost).
    strike = cs.hand[0]
    assert strike.affliction is not None and strike.affliction.id == "entangled"
    assert cs.effective_cost(strike) == STRIKE_IRONCLAD.cost + 1
    # GraspingVines also deals 8 damage (SingleAttackIntent).
    assert hp0 - cs.player.hp == 8


def test_vine_shambler_starts_on_swipe_cycle():
    # Initial state is SWIPE_MOVE: SWIPE -> GRASPING_VINES -> CHOMP -> SWIPE.
    m = VineShambler.spawn(random.Random(0), ascension=0)
    assert m.next_move == "SWIPE"
    cs = _combat(m, hand=[STRIKE_IRONCLAD])
    seq = []
    for _ in range(4):
        seq.append(m.next_move)
        cs.monster_turn()
    assert seq == ["SWIPE", "GRASPING_VINES", "CHOMP", "SWIPE"]


# ===========================================================================
# Doormaker — phase-power rotation; HungerPower modeled (Doormaker.cs:129/164).
# ===========================================================================
def test_doormaker_dramatic_open_applies_hunger_power():
    m = Doormaker.spawn(random.Random(0), ascension=0)
    cs = _combat(m, hand=[STRIKE_IRONCLAD])
    assert m.next_move is DoormakerMove.DRAMATIC_OPEN
    cs.monster_turn()             # DRAMATIC_OPEN -> SwapPhasePower<HungerPower>
    hunger = cs.player.get_power("hunger")
    assert hunger is not None and hunger.amount == 1
    # HungerPower.AfterApplied: Attack/Skill cards get Devoured + Exhaust.
    strike = cs.hand[0]
    assert strike.affliction is not None and strike.affliction.id == "devoured"
    assert KW_EXHAUST in card_keywords(strike)


def test_doormaker_hunger_move_removes_phase_power():
    # HungerMove ends with SwapPhasePower<ScrutinyPower> -> Hunger removed.
    m = Doormaker.spawn(random.Random(0), ascension=0)
    cs = _combat(m, hand=[STRIKE_IRONCLAD])
    cs.monster_turn()             # DRAMATIC_OPEN: apply Hunger
    assert cs.player.get_power("hunger") is not None
    cs.monster_turn()             # HUNGER move: remove Hunger
    assert cs.player.get_power("hunger") is None


def test_doormaker_grasp_reapplies_hunger():
    # GraspMove ends with SwapPhasePower<HungerPower> -> Hunger re-applied.
    m = Doormaker.spawn(random.Random(0), ascension=0)
    cs = _combat(m, hand=[STRIKE_IRONCLAD])
    _run_move(cs, m, DoormakerMove.GRASP)
    assert cs.player.get_power("hunger") is not None


# ===========================================================================
# Event enchants closed this batch (real enchant layer).
# ===========================================================================
def test_souls_enchant_removes_exhaust_keyword():
    # SoulsPower.cs: CanEnchant requires Exhaust; OnEnchant removes it.
    exhaust_card = replace(STRIKE_IRONCLAD, exhaust=True)
    assert can_enchant(SOULS, exhaust_card)
    assert not can_enchant(SOULS, STRIKE_IRONCLAD)  # no Exhaust -> ineligible
    out = enchant_card(exhaust_card, SOULS)
    assert out.exhaust is False
    assert KW_EXHAUST not in card_keywords(out)
    assert out.enchantment is not None and out.enchantment.id == SOULS


def test_perfect_fit_shuffles_card_to_top_of_draw_pile():
    # PerfectFit.ModifyShuffleOrder (non-initial shuffle): card -> drawn first.
    pf_card = enchant_card(replace(STRIKE_IRONCLAD, id="pf_marker"), PERFECT_FIT)
    others = [DEFEND_IRONCLAD for _ in range(4)]
    # Start with an empty draw pile and the PerfectFit card in discard so the
    # next draw triggers a reshuffle (the only place ModifyShuffleOrder fires).
    cs = _combat(VineShambler.spawn(random.Random(1)),
                 draw=[], )
    cs.discard_pile = others + [pf_card]
    cs.draw(1)                    # forces a reshuffle, then pops the top
    assert cs.hand[-1].id == "pf_marker"  # PerfectFit card drawn first
