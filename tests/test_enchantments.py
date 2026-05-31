"""Phase 8B.11 — per-card enchantment system tests.

Covers: the enchant layer (cost/damage/block/keyword modification at the right
pipeline point), each of the 8 enchant relics, the CLONE rest option, the
card/potion/event enchant de-approximations, and the card-affliction status
powers (Hex/Hunger/Dampen/Tangled). Real numbers from the decompile.
"""
from __future__ import annotations

import random
from dataclasses import replace

from sim.cards import (STRIKE_IRONCLAD, DEFEND_IRONCLAD, BASH, upgrade_card)
from sim.combat import CombatState
from sim.creatures import Player, Monster
from sim.dsl import CardType
from sim.enchantments import (
    Enchantment, Affliction, enchant_card, can_enchant, card_keywords,
    clone_card_instance,
    SHARP, NIMBLE, ADROIT, SWIFT, SOWN, MOMENTUM, CORRUPTED, INSTINCT,
    VIGOROUS, GLAM, STEADY, ROYALLY_APPROVED, GOOPY, CLONE, SPIRAL,
    ETHEREAL_ENCHANT, KW_RETAIN, KW_INNATE, KW_EXHAUST, KW_ETHEREAL,
)
from sim.game_state import RunState
from sim.powers import make_power


def _player():
    return Player(name="Ironclad", hp=80, max_hp=80, energy=3, max_energy=3)


class _DummyMonster(Monster):
    def take_turn(self, rng, player) -> dict:
        # No-op turn: lets end_player_turn() run without a real monster AI.
        return {"move": "idle", "damage": 0, "blocked": 0, "hp_loss": 0}


def _dummy_monster(hp: int = 200):
    return _DummyMonster(name="Dummy", hp=hp, max_hp=hp)


def _combat(hand=None, draw=None):
    """Build a standalone CombatState with a beefy dummy monster and a
    controllable hand / draw pile (no relics; run_state=None)."""
    p = _player()
    m = _dummy_monster()
    cs = CombatState(player=p, monster=m, monsters=[m],
                     draw_pile=list(draw or []), hand=list(hand or []),
                     rng=random.Random(0))
    return cs


# ===========================================================================
# Enchant layer — cost / damage / block / keyword modification.
# ===========================================================================
def test_enchant_card_returns_distinct_instance():
    base = STRIKE_IRONCLAD
    e = enchant_card(base, SHARP, 3)
    assert e is not base
    assert e.enchantment is not None and e.enchantment.id == SHARP
    assert e.enchantment.amount == 3
    assert base.enchantment is None  # canonical pool entry untouched
    assert e.id == base.id  # same logical card


def test_sharp_adds_amount_to_powered_attack_damage():
    # Sharp.cs: +Amount damage on a powered attack. Strike base 6 + Sharp 3 = 9.
    card = enchant_card(STRIKE_IRONCLAD, SHARP, 3)
    cs = _combat(hand=[card])
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert hp0 - cs.monster.hp == 9


def test_instinct_doubles_powered_attack_damage():
    # Instinct.cs: ×2 on a powered attack. Strike 6 -> 12.
    card = enchant_card(STRIKE_IRONCLAD, INSTINCT, 0)
    cs = _combat(hand=[card])
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert hp0 - cs.monster.hp == 12


def test_corrupted_multiplies_and_self_damages():
    # Corrupted.cs: powered attack ×1.5, plus 2 unblockable self-damage on play.
    card = enchant_card(STRIKE_IRONCLAD, CORRUPTED, 0)
    cs = _combat(hand=[card])
    hp0 = cs.monster.hp
    php0 = cs.player.hp
    cs.play_card(0)
    assert hp0 - cs.monster.hp == 9   # 6 × 1.5
    assert php0 - cs.player.hp == 2   # self-damage


def test_nimble_adds_block_to_card_block_gain():
    # Nimble.cs: +Amount block on the card's powered block gain. Defend 5 + 2 = 7.
    card = enchant_card(DEFEND_IRONCLAD, NIMBLE, 2)
    cs = _combat(hand=[card])
    cs.play_card(0)
    assert cs.player.block == 7


def test_adroit_on_play_gains_block():
    # Adroit.cs OnPlay: gain Amount block. Defend(5) + Adroit(3) OnPlay = 8.
    card = enchant_card(DEFEND_IRONCLAD, ADROIT, 3)
    cs = _combat(hand=[card])
    cs.play_card(0)
    assert cs.player.block == 8  # 5 (Defend) + 3 (Adroit OnPlay)


def test_swift_draws_once_then_disabled():
    # Swift.cs OnPlay (once): draw Amount, then Disabled.
    card = enchant_card(STRIKE_IRONCLAD, SWIFT, 2)
    extra = [STRIKE_IRONCLAD, DEFEND_IRONCLAD]
    cs = _combat(hand=[card], draw=extra)
    cs.play_card(0)
    assert len(cs.hand) == 2  # drew 2
    assert card.enchantment.status == "disabled"


def test_sown_gains_energy_once():
    # Sown.cs OnPlay (once): gain Amount energy.
    card = enchant_card(STRIKE_IRONCLAD, SOWN, 2)
    cs = _combat(hand=[card])
    cs.player.energy = 3
    cs.play_card(0)  # costs 1
    assert cs.player.energy == 3 - 1 + 2
    assert card.enchantment.status == "disabled"


def test_momentum_accumulates_extra_damage():
    # Momentum.cs: OnPlay adds Amount to ExtraDamage; later plays read it.
    card = enchant_card(STRIKE_IRONCLAD, MOMENTUM, 5)
    cs = _combat(hand=[card, card])
    hp0 = cs.monster.hp
    cs.player.energy = 9
    cs.play_card(0)            # first play: ExtraDamage 0 -> deals 6, then +5
    first = hp0 - cs.monster.hp
    hp1 = cs.monster.hp
    cs.play_card(0)            # second play: ExtraDamage 5 -> deals 11
    second = hp1 - cs.monster.hp
    assert first == 6
    assert second == 11


def test_vigorous_adds_once_then_disabled():
    # Vigorous.cs: +Amount damage on the FIRST play only, then Disabled.
    card = enchant_card(STRIKE_IRONCLAD, VIGOROUS, 4)
    cs = _combat(hand=[card, card])
    cs.player.energy = 9
    hp0 = cs.monster.hp
    cs.play_card(0)
    first = hp0 - cs.monster.hp
    hp1 = cs.monster.hp
    cs.play_card(0)
    second = hp1 - cs.monster.hp
    assert first == 10   # 6 + 4
    assert second == 6   # disabled


def test_glam_replays_once_then_disabled():
    # Glam.cs: first play replays +Times (default 1), then disabled.
    card = enchant_card(STRIKE_IRONCLAD, GLAM, 0)
    cs = _combat(hand=[card, card])
    cs.player.energy = 9
    hp0 = cs.monster.hp
    cs.play_card(0)             # plays twice -> 12
    assert hp0 - cs.monster.hp == 12
    assert card.enchantment.used_this_combat is True
    hp1 = cs.monster.hp
    cs.play_card(0)             # disabled -> plays once -> 6
    assert hp1 - cs.monster.hp == 6


def test_steady_adds_retain_keyword():
    card = enchant_card(DEFEND_IRONCLAD, STEADY, 0)
    assert KW_RETAIN in card_keywords(card)


def test_royally_approved_adds_innate_and_retain():
    card = enchant_card(DEFEND_IRONCLAD, ROYALLY_APPROVED, 0)
    kws = card_keywords(card)
    assert KW_INNATE in kws and KW_RETAIN in kws


def test_goopy_adds_exhaust_and_grows_block():
    # Goopy.cs: Exhaust keyword; +block == Amount-1, Amount++ each play.
    card = enchant_card(DEFEND_IRONCLAD, GOOPY, 1)
    assert card.exhaust is True
    assert KW_EXHAUST in card_keywords(card)
    cs = _combat(hand=[card])
    cs.play_card(0)
    # first play: block_additive = Amount-1 = 0 -> Defend 5; then Amount -> 2.
    assert cs.player.block == 5
    assert card.enchantment.amount == 2
    assert card in cs.exhaust_pile


def test_retain_keyword_keeps_card_in_hand_at_turn_end():
    card = enchant_card(DEFEND_IRONCLAD, STEADY, 0)
    cs = _combat(hand=[card])
    cs.end_player_turn()
    # Steady card retained; combat continues so a new turn starts and re-draws,
    # but the retained card is in hand and NOT in discard.
    assert card in cs.hand
    assert card not in cs.discard_pile


def test_ethereal_keyword_exhausts_unplayed_card_at_turn_end():
    card = replace(STRIKE_IRONCLAD, enchantment=Enchantment(id=ETHEREAL_ENCHANT))
    assert KW_ETHEREAL in card_keywords(card)
    cs = _combat(hand=[card])
    cs.end_player_turn()
    assert card in cs.exhaust_pile
    assert card not in cs.discard_pile


def test_can_enchant_gates():
    # Sharp: Attack only.
    assert can_enchant(SHARP, STRIKE_IRONCLAD)
    assert not can_enchant(SHARP, DEFEND_IRONCLAD)
    # RoyallyApproved: Skill/Power only (not Attack).
    assert not can_enchant(ROYALLY_APPROVED, STRIKE_IRONCLAD)
    assert can_enchant(ROYALLY_APPROVED, DEFEND_IRONCLAD)
    # Single non-stackable slot: a card already Sharp rejects Nimble.
    sharp_strike = enchant_card(STRIKE_IRONCLAD, SHARP, 3)
    assert not can_enchant(NIMBLE, sharp_strike)


# ===========================================================================
# The 8 enchant relics.
# ===========================================================================
def _run_with_relic(relic_id):
    rs = RunState.new_run(seed=1)
    rs.deck = [STRIKE_IRONCLAD, STRIKE_IRONCLAD, DEFEND_IRONCLAD,
               DEFEND_IRONCLAD, BASH]
    rs.add_relic(relic_id)
    return rs


def test_gnarled_hammer_enchants_3_with_sharp_3():
    # GnarledHammer.cs: pickup -> Sharp(3) on 3 cards. Only Attacks are eligible.
    rs = _run_with_relic("GNARLED_HAMMER")
    sharped = [c for c in rs.deck
               if c.enchantment is not None and c.enchantment.id == SHARP]
    assert len(sharped) == 3
    assert all(c.type is CardType.ATTACK for c in sharped)
    assert all(c.enchantment.amount == 3 for c in sharped)


def test_kifuda_enchants_3_with_adroit_3():
    rs = _run_with_relic("KIFUDA")
    adroit = [c for c in rs.deck
              if c.enchantment is not None and c.enchantment.id == ADROIT]
    assert len(adroit) == 3
    assert all(c.enchantment.amount == 3 for c in adroit)


def test_punch_dagger_enchants_1_with_momentum_5():
    rs = _run_with_relic("PUNCH_DAGGER")
    mom = [c for c in rs.deck
           if c.enchantment is not None and c.enchantment.id == MOMENTUM]
    assert len(mom) == 1
    assert mom[0].enchantment.amount == 5


def test_royal_stamp_enchants_1_with_royally_approved():
    rs = _run_with_relic("ROYAL_STAMP")
    ra = [c for c in rs.deck
          if c.enchantment is not None and c.enchantment.id == ROYALLY_APPROVED]
    assert len(ra) == 1
    # RoyallyApproved targets Skill/Power -> a Defend got it.
    assert ra[0].type in (CardType.SKILL, CardType.POWER)


def test_fresnel_lens_enchants_added_cards_with_nimble_2():
    rs = RunState.new_run(seed=2)
    rs.deck = []
    rs.add_relic("FRESNEL_LENS")
    rs.add_card_to_deck(DEFEND_IRONCLAD)
    added = rs.deck[-1]
    assert added.enchantment is not None
    assert added.enchantment.id == NIMBLE and added.enchantment.amount == 2


def test_wing_charm_enchants_added_card_with_swift_1():
    rs = RunState.new_run(seed=3)
    rs.deck = []
    rs.add_relic("WING_CHARM")
    rs.add_card_to_deck(STRIKE_IRONCLAD)
    added = rs.deck[-1]
    assert added.enchantment is not None
    assert added.enchantment.id == SWIFT and added.enchantment.amount == 1


def test_mystic_lighter_adds_9_to_enchanted_card_attack():
    # MysticLighter.cs: powered attacks from ENCHANTED cards deal +9. A plain
    # (un-enchanted) attack gets no bonus.
    rs = RunState.new_run(seed=4)
    rs.deck = [enchant_card(STRIKE_IRONCLAD, SHARP, 0), STRIKE_IRONCLAD]
    rs.add_relic("MYSTIC_LIGHTER")
    from sim.combat import CombatState
    cs = _combat(hand=[rs.deck[0], rs.deck[1]])
    cs.run_state = rs
    hp0 = cs.monster.hp
    cs.play_card(0)  # enchanted: 6 + 9 = 15
    enchanted_dmg = hp0 - cs.monster.hp
    hp1 = cs.monster.hp
    cs.play_card(0)  # plain: 6
    plain_dmg = hp1 - cs.monster.hp
    assert enchanted_dmg == 15
    assert plain_dmg == 6


def test_ghost_seed_gives_ethereal_to_basic_strike_defend():
    # GhostSeed.cs: basic Strike/Defend gain Ethereal at combat start.
    rs = RunState.new_run(seed=5)
    rs.deck = [STRIKE_IRONCLAD, DEFEND_IRONCLAD, BASH]
    rs.add_relic("GHOST_SEED")
    from sim.relics import _ghost_seed_combat_start
    cs = _combat(draw=list(rs.deck))
    _ghost_seed_combat_start(rs, cs)
    eth = [c for c in cs.draw_pile if KW_ETHEREAL in card_keywords(c)]
    # Strike + Defend get Ethereal; Bash (not basic) does not.
    assert len(eth) == 2
    assert all(c.id in ("strike_ironclad", "defend_ironclad") for c in eth)


# ===========================================================================
# CLONE rest option.
# ===========================================================================
def test_clone_rest_duplicates_clone_enchanted_cards():
    from sim.run_engine import _step_rest, StepResult
    from sim.game_state import StateType
    rs = RunState.new_run(seed=6)
    clone_strike = enchant_card(STRIKE_IRONCLAD, CLONE, 4)
    rs.deck = [clone_strike, DEFEND_IRONCLAD, BASH]
    rs.add_relic("PAELS_GROWTH")  # note: also clone-enchants one card on pickup
    n_clone_before = sum(1 for c in rs.deck
                         if c.enchantment is not None and c.enchantment.id == CLONE)
    rs.state_type = StateType.REST
    rs.pending_rest_options = [{"id": "clone", "index": 2, "is_enabled": True}]
    _step_rest(rs, {"action": "choose_rest_option", "index": 2}, StepResult())
    n_clone_after = sum(1 for c in rs.deck
                        if c.enchantment is not None and c.enchantment.id == CLONE)
    # Each Clone-enchanted card is duplicated -> count doubles.
    assert n_clone_after == 2 * n_clone_before
    assert n_clone_before >= 1


def test_clone_card_instance_is_independent():
    card = enchant_card(STRIKE_IRONCLAD, MOMENTUM, 5)
    card.enchantment.extra_damage = 99
    clone = clone_card_instance(card)
    assert clone is not card
    assert clone.enchantment is not card.enchantment
    assert clone.enchantment.extra_damage == 99
    clone.enchantment.extra_damage = 0
    assert card.enchantment.extra_damage == 99  # independent


# ===========================================================================
# Card-affliction status powers (Hex / Hunger / Tangled / Dampen).
# ===========================================================================
def test_tangled_adds_energy_cost_to_attacks():
    # TangledPower.cs: Attack cards cost +1 energy; cleared at turn end.
    cs = _combat(hand=[STRIKE_IRONCLAD, DEFEND_IRONCLAD])
    cs.apply_player_affliction_power("tangled", 1)
    # Strike (Attack) now costs 1 + 1 = 2; Defend (Skill) unaffected at 1.
    assert cs.effective_cost(cs.hand[0]) == 2
    assert cs.effective_cost(cs.hand[1]) == 1
    # Cleared at the player's turn end.
    cs.end_player_turn()
    assert cs.player.get_power("tangled") is None
    assert all(getattr(c, "affliction", None) is None
               for c in cs.hand + cs.discard_pile)


def test_hex_gives_ethereal_to_all_cards():
    # HexPower.cs: every card gets Hexed + Ethereal.
    cs = _combat(hand=[STRIKE_IRONCLAD], draw=[DEFEND_IRONCLAD])
    cs.apply_player_affliction_power("hex", 1)
    for c in cs.hand + cs.draw_pile:
        assert c.affliction is not None and c.affliction.id == "hexed"
        assert KW_ETHEREAL in card_keywords(c)
    # Removal clears the afflictions.
    cs.remove_player_affliction_power("hex")
    for c in cs.hand + cs.draw_pile:
        assert getattr(c, "affliction", None) is None


def test_hex_afflicts_newly_drawn_card():
    cs = _combat(hand=[], draw=[STRIKE_IRONCLAD])
    cs.apply_player_affliction_power("hex", 1)
    cs.draw(1)
    drawn = cs.hand[-1]
    assert drawn.affliction is not None and drawn.affliction.id == "hexed"
    assert KW_ETHEREAL in card_keywords(drawn)


def test_hunger_gives_exhaust_to_attacks_and_skills():
    # HungerPower.cs: Attack/Skill cards get Devoured + Exhaust.
    cs = _combat(hand=[STRIKE_IRONCLAD, DEFEND_IRONCLAD])
    cs.apply_player_affliction_power("hunger", 1)
    for c in cs.hand:
        assert c.affliction is not None and c.affliction.id == "devoured"
        assert KW_EXHAUST in card_keywords(c)


def test_dampen_downgrades_upgraded_cards_and_restores():
    # DampenPower.cs: downgrade every upgraded card; restore on removal.
    up = upgrade_card(STRIKE_IRONCLAD)  # strike_ironclad+
    cs = _combat(hand=[up, DEFEND_IRONCLAD])
    cs.apply_player_affliction_power("dampen", 1)
    # The upgraded strike was downgraded to base.
    assert not cs.hand[0].id.endswith("+")
    cs.remove_player_affliction_power("dampen")
    assert cs.hand[0].id.endswith("+")


# ===========================================================================
# Event / potion de-approximations enabled by the layer.
# ===========================================================================
def test_sapphire_seed_plant_enchants_sown():
    from sim.events import _sapphire_seed_options
    rs = RunState.new_run(seed=7)
    rs.deck = [STRIKE_IRONCLAD, DEFEND_IRONCLAD]
    opts = {o.id: o for o in _sapphire_seed_options(rs)}
    opts["plant"].apply(rs)
    assert any(c.enchantment is not None and c.enchantment.id == SOWN
               for c in rs.deck)


def test_symbiote_approach_enchants_corrupted():
    from sim.events import _symbiote_options
    rs = RunState.new_run(seed=8)
    rs.deck = [STRIKE_IRONCLAD, BASH]
    opts = {o.id: o for o in _symbiote_options(rs)}
    opts["approach"].apply(rs)
    assert any(c.enchantment is not None and c.enchantment.id == CORRUPTED
               for c in rs.deck)


def test_self_help_book_enchants_by_type():
    from sim.events import _self_help_book_options
    rs = RunState.new_run(seed=9)
    rs.deck = [STRIKE_IRONCLAD, DEFEND_IRONCLAD]
    opts = {o.id: o for o in _self_help_book_options(rs)}
    opts["read_the_back"].apply(rs)   # Sharp(2) on an Attack
    assert any(c.enchantment is not None and c.enchantment.id == SHARP
               and c.type is CardType.ATTACK for c in rs.deck)


def test_soldiers_stew_spiral_on_strikes():
    # Soldier's Stew: +1 replay on all Strike cards -> Spiral enchant.
    from sim.potions import POTION_REGISTRY
    cs = _combat(hand=[STRIKE_IRONCLAD], draw=[STRIKE_IRONCLAD, DEFEND_IRONCLAD])
    eff = POTION_REGISTRY["SOLDIERS_STEW"].apply
    eff(None, cs, cs.player)
    strikes = [c for pile in (cs.hand, cs.draw_pile) for c in pile
               if "strike" in c.id]
    assert all(c.enchantment is not None and c.enchantment.id == SPIRAL
               for c in strikes)
    # A Spiral'd Strike replays once: 6 + 6 = 12.
    hp0 = cs.monster.hp
    cs.play_card(0)
    assert hp0 - cs.monster.hp == 12
