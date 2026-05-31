"""Phase 8B.5 POTION fidelity tests.

For every newly-implemented (5 omitted) and de-approximated potion, assert the
exact effect against the decompiled ground truth (state before/after
apply_potion), the correct rarity, and any A-level/upgrade/duration interaction.

Ground truth: decompiled/MegaCrit.Sts2.Core.Models.Potions/* and the matching
Models.Powers/* (RetainHandPower, DuplicationPower, GigantificationPower,
ClarityPower, DoomPower, DemisePower, ShrinkPower, BlockNextTurnPower, etc.).
"""
from __future__ import annotations

from dataclasses import replace

from sim import potions as P
from sim.combat import CombatState
from sim.dsl import CardType
from sim.card_catalog import CARDS


def _fresh_combat(seed: int = 1) -> CombatState:
    cs = CombatState.new_combat(seed=seed)
    cs.start_player_turn()
    return cs


def _strike():
    return CARDS["strike_ironclad"]


def _defend():
    return CARDS["defend_ironclad"]


# ===========================================================================
# The 5 OMITTED potions, now implemented.
# ===========================================================================


def test_stable_serum_retains_hand_for_two_turns():
    # StableSerum.cs -> RetainHandPower (RepeatVar 2). Uncommon.
    assert P.potion_rarity("STABLE_SERUM") is P.PotionRarity.UNCOMMON
    cs = _fresh_combat()
    P.apply_potion(None, cs, "STABLE_SERUM", 0)
    rh = cs.player.get_power("retain_hand")
    assert rh is not None and rh.amount == 2
    # Seed a 3-card hand; RetainHand keeps up to 2 (the two highest-cost),
    # discarding the rest. Plenty of filler so the redraw never reaches "lo".
    cs.hand = [
        replace(_strike(), cost=2, id="hi"),
        replace(_strike(), cost=1, id="mid"),
        replace(_strike(), cost=0, id="lo"),
    ]
    cs.draw_pile = [replace(_strike(), id=f"f{i}") for i in range(20)]
    cs.discard_pile = []
    cs.end_player_turn()
    ids = {c.id for c in cs.hand}
    # The two highest-cost cards retained; the lowest-cost discarded.
    assert "hi" in ids and "mid" in ids
    assert "lo" not in ids
    # Retain counter decremented to 1 (lasts one more turn).
    rh = cs.player.get_power("retain_hand")
    assert rh is not None and rh.amount == 1


def test_blessing_of_the_forge_upgrades_hand():
    # BlessingOfTheForge.cs: upgrade every upgradable card in hand. Uncommon.
    assert P.potion_rarity("BLESSING_OF_THE_FORGE") is P.PotionRarity.UNCOMMON
    cs = _fresh_combat()
    cs.hand = [_strike(), _defend()]
    P.apply_potion(None, cs, "BLESSING_OF_THE_FORGE", 0)
    assert all(c.id.endswith("+") for c in cs.hand)


def test_duplicator_next_card_plays_twice():
    # Duplicator.cs -> DuplicationPower 1. Uncommon.
    assert P.potion_rarity("DUPLICATOR") is P.PotionRarity.UNCOMMON
    cs = _fresh_combat()
    P.apply_potion(None, cs, "DUPLICATOR", 0)
    dup = cs.player.get_power("duplication")
    assert dup is not None and dup.amount == 1
    # Play Strike (6 dmg) -> should hit twice == 12 damage to the enemy.
    cs.hand = [_strike()]
    cs.player.energy = 3
    enemy = cs.alive_monsters()[0]
    enemy.hp = 100
    enemy.block = 0
    hp0 = enemy.hp
    cs.target_index = 0
    cs.play_card(0)
    assert hp0 - enemy.hp == 12
    # Stack consumed.
    assert cs.player.get_power("duplication") is None


def test_gamblers_brew_discards_and_redraws_same_count():
    # GamblersBrew.cs: discard any number, draw that many. Uncommon.
    assert P.potion_rarity("GAMBLERS_BREW") is P.PotionRarity.UNCOMMON
    cs = _fresh_combat()
    cs.hand = [replace(_strike(), id=f"h{i}") for i in range(4)]
    cs.draw_pile = [replace(_strike(), id=f"d{i}") for i in range(6)]
    cs.discard_pile = []
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "GAMBLERS_BREW", 0)
    # Whole hand discarded, same count redrawn.
    assert len(cs.hand) == n0
    assert all(c.id.startswith("d") for c in cs.hand)
    assert len(cs.discard_pile) == 4


def test_gigantification_triples_next_attack():
    # GigantificationPotion.cs -> GigantificationPower 1 (next powered Attack ×3).
    assert P.potion_rarity("GIGANTIFICATION_POTION") is P.PotionRarity.RARE
    cs = _fresh_combat()
    P.apply_potion(None, cs, "GIGANTIFICATION_POTION", 0)
    gig = cs.player.get_power("gigantification")
    assert gig is not None and gig.amount == 1
    cs.hand = [_strike()]  # Strike = 6 damage
    cs.player.energy = 3
    enemy = cs.alive_monsters()[0]
    enemy.hp = 100
    enemy.block = 0
    cs.target_index = 0
    hp0 = enemy.hp
    cs.play_card(0)
    assert hp0 - enemy.hp == 18  # 6 × 3
    assert cs.player.get_power("gigantification") is None


# ===========================================================================
# De-approximated potions.
# ===========================================================================


def test_flex_potion_is_temporary_strength():
    cs = _fresh_combat()
    P.apply_potion(None, cs, "FLEX_POTION", 0)
    ts = cs.player.get_power("temporary_strength")
    assert ts is not None and ts.amount == 5
    # The Strength is removed at the owner's turn end (FlexPotionPower).
    cs.hand = []
    cs.draw_pile = []
    cs.discard_pile = []
    cs.end_player_turn()
    st = cs.player.get_power("strength")
    # Net Strength back to 0 after the temporary +5/-5.
    assert (st is None) or (st.amount == 0)


def test_speed_potion_is_temporary_dexterity():
    cs = _fresh_combat()
    P.apply_potion(None, cs, "SPEED_POTION", 0)
    td = cs.player.get_power("temporary_dexterity")
    assert td is not None and td.amount == 5


def test_clarity_draws_one_and_grants_clarity_power():
    cs = _fresh_combat()
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "CLARITY", 0)
    assert len(cs.hand) == n0 + 1
    cl = cs.player.get_power("clarity")
    assert cl is not None and cl.amount == 3


def test_powdered_demise_is_delayed_tick_not_burst():
    # DemisePower 9: 9 unblockable damage at the enemy's OWN turn end.
    assert P.potion_rarity("POWDERED_DEMISE") is P.PotionRarity.UNCOMMON
    cs = _fresh_combat()
    enemy = cs.alive_monsters()[0]
    enemy.hp = 50
    hp0 = enemy.hp
    P.apply_potion(None, cs, "POWDERED_DEMISE", 0)
    # No immediate damage; a delayed debuff is applied instead.
    assert enemy.hp == hp0
    d = enemy.get_power("demise")
    assert d is not None and d.amount == 9
    # The tick lands at the enemy's turn end.
    cs.hand = []
    cs.draw_pile = []
    cs.discard_pile = []
    cs.end_player_turn()
    assert enemy.hp == hp0 - 9


def test_potion_of_doom_is_common_threshold_execute():
    # PotionOfDoom.cs Rarity Common; DoomPower 33 (execute at <=33 HP at turn end).
    assert P.potion_rarity("POTION_OF_DOOM") is P.PotionRarity.COMMON
    cs = _fresh_combat()
    enemy = cs.alive_monsters()[0]
    enemy.hp = 30  # below the 33 threshold
    P.apply_potion(None, cs, "POTION_OF_DOOM", 0)
    d = enemy.get_power("doom")
    assert d is not None and d.amount == 33
    assert enemy.alive  # not killed immediately
    cs.hand = []
    cs.draw_pile = []
    cs.discard_pile = []
    cs.end_player_turn()
    assert not enemy.alive  # executed at its turn end


def test_potion_of_doom_does_not_execute_above_threshold():
    cs = _fresh_combat()
    enemy = cs.alive_monsters()[0]
    enemy.hp = 60  # above the 33 threshold
    P.apply_potion(None, cs, "POTION_OF_DOOM", 0)
    cs.hand = []
    cs.draw_pile = []
    cs.discard_pile = []
    cs.end_player_turn()
    assert enemy.alive  # survives — Doom only executes at/below 33


def test_beetle_juice_applies_shrink_30pct_for_4():
    # BeetleJuice.cs -> ShrinkPower (DamageDecrease 30, Repeat 4). Rare.
    assert P.potion_rarity("BEETLE_JUICE") is P.PotionRarity.RARE
    cs = _fresh_combat()
    enemy = cs.alive_monsters()[0]
    P.apply_potion(None, cs, "BEETLE_JUICE", 0)
    sh = enemy.get_power("shrink")
    assert sh is not None and sh.amount == 4
    assert abs(sh.modify_damage_multiplicative(enemy, cs.player, 10) - 0.70) < 1e-9


def test_shackling_potion_minus7_strength_all_enemies():
    # ShacklingPotion.cs -> ShacklingPotionPower (-7 Strength, temporary). Rare.
    assert P.potion_rarity("SHACKLING_POTION") is P.PotionRarity.RARE

    def two_monsters(rng):
        from sim.monsters import SludgeSpinnerWeak
        return [SludgeSpinnerWeak.spawn(rng), SludgeSpinnerWeak.spawn(rng)]

    cs = CombatState.new_combat(seed=2, monsters_factory=two_monsters)
    cs.start_player_turn()
    P.apply_potion(None, cs, "SHACKLING_POTION", 0)
    for m in cs.alive_monsters():
        sd = m.get_power("strength_down")
        assert sd is not None and sd.amount == 7
        # Outgoing damage reduced by 7.
        assert sd.modify_damage_additive(m, cs.player, 10) == -7


def test_lucky_tonic_grants_buffer():
    # LuckyTonic.cs -> BufferPower 1. Rare.
    assert P.potion_rarity("LUCKY_TONIC") is P.PotionRarity.RARE
    cs = _fresh_combat()
    P.apply_potion(None, cs, "LUCKY_TONIC", 0)
    b = cs.player.get_power("buffer")
    assert b is not None and b.amount == 1
    # Buffer prevents the next instance of HP loss entirely.
    assert b.modify_hp_lost(None, cs.player, 12) == 0


def test_mazaleths_gift_grants_ritual():
    # MazalethsGift.cs -> RitualPower 1 (Strength each turn end). Rare.
    assert P.potion_rarity("MAZALETHS_GIFT") is P.PotionRarity.RARE
    cs = _fresh_combat()
    P.apply_potion(None, cs, "MAZALETHS_GIFT", 0)
    r = cs.player.get_power("ritual")
    assert r is not None and r.amount == 1
    cs.hand = []
    cs.draw_pile = []
    cs.discard_pile = []
    cs.end_player_turn()
    st = cs.player.get_power("strength")
    assert st is not None and st.amount == 1


def test_ghost_in_a_jar_grants_intangible():
    cs = _fresh_combat()
    P.apply_potion(None, cs, "GHOST_IN_A_JAR", 0)
    it = cs.player.get_power("intangible")
    assert it is not None and it.amount == 1
    # Intangible reduces all incoming HP loss to at most 1.
    assert it.modify_hp_lost(None, cs.player, 30) == 1


def test_ship_in_a_bottle_block_now_and_next_turn():
    cs = _fresh_combat()
    b0 = cs.player.block
    P.apply_potion(None, cs, "SHIP_IN_A_BOTTLE", 0)
    assert cs.player.block - b0 == 10
    bnt = cs.player.get_power("block_next_turn")
    assert bnt is not None and bnt.amount == 10
    # Next turn start grants the deferred 10 block, then removes the power.
    cs.hand = []
    cs.draw_pile = []
    cs.discard_pile = []
    cs.end_player_turn()  # -> monster_turn -> start_player_turn (block reset to 0)
    assert cs.player.block == 10
    assert cs.player.get_power("block_next_turn") is None


def test_touch_of_insanity_makes_a_hand_card_free():
    cs = _fresh_combat()
    cs.hand = [replace(_strike(), cost=2, id="big"), replace(_strike(), cost=1, id="small")]
    P.apply_potion(None, cs, "TOUCH_OF_INSANITY", 0)
    # Highest-cost card made free (cost 0).
    big = next(c for c in cs.hand if c.id == "big")
    assert big.cost == 0


def test_snecko_oil_draws_seven():
    cs = _fresh_combat()
    cs.hand = []
    cs.draw_pile = [replace(_strike(), id=f"d{i}") for i in range(10)]
    cs.discard_pile = []
    P.apply_potion(None, cs, "SNECKO_OIL", 0)
    assert len(cs.hand) == 7


def test_attack_potion_adds_free_attack_to_hand():
    cs = _fresh_combat()
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "ATTACK_POTION", 0)
    assert len(cs.hand) == n0 + 1
    added = cs.hand[-1]
    assert added.type is CardType.ATTACK
    assert added.cost == 0  # free this turn


def test_skill_potion_adds_free_skill():
    cs = _fresh_combat()
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "SKILL_POTION", 0)
    assert len(cs.hand) == n0 + 1
    assert cs.hand[-1].type is CardType.SKILL


def test_power_potion_adds_free_power():
    cs = _fresh_combat()
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "POWER_POTION", 0)
    assert len(cs.hand) == n0 + 1
    assert cs.hand[-1].type is CardType.POWER


def test_cosmic_concoction_adds_three_upgraded_cards():
    cs = _fresh_combat()
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "COSMIC_CONCOCTION", 0)
    assert len(cs.hand) == n0 + 3
    for c in cs.hand[-3:]:
        assert c.id.endswith("+")
        assert c.cost == 0


def test_orobic_acid_adds_attack_skill_power():
    cs = _fresh_combat()
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "OROBIC_ACID", 0)
    assert len(cs.hand) == n0 + 3
    types = {c.type for c in cs.hand[-3:]}
    assert CardType.ATTACK in types
    assert CardType.SKILL in types
    assert CardType.POWER in types


def test_pot_of_ghouls_adds_two_cards():
    cs = _fresh_combat()
    n0 = len(cs.hand)
    P.apply_potion(None, cs, "POT_OF_GHOULS", 0)
    assert len(cs.hand) == n0 + 2


def test_kings_courage_upgrades_hand():
    cs = _fresh_combat()
    cs.hand = [_strike(), _defend()]
    P.apply_potion(None, cs, "KINGS_COURAGE", 0)
    assert all(c.id.endswith("+") for c in cs.hand)


# ===========================================================================
# Pool / rarity reconciliation.
# ===========================================================================


def test_omitted_potions_no_longer_noop():
    # The 5 previously-omitted potions now apply a real, observable effect.
    for pid in ("STABLE_SERUM", "BLESSING_OF_THE_FORGE", "DUPLICATOR",
                "GAMBLERS_BREW", "GIGANTIFICATION_POTION"):
        cs = _fresh_combat()
        # Give a hand so hand-dependent effects have material to act on.
        cs.hand = [_strike(), _defend()]
        snapshot_powers = len(cs.player.powers)
        snapshot_hand_ids = [c.id for c in cs.hand]
        P.apply_potion(None, cs, pid, 0)
        changed = (
            len(cs.player.powers) != snapshot_powers
            or [c.id for c in cs.hand] != snapshot_hand_ids
        )
        assert changed, pid


def test_all_pool_potions_resolve_without_error():
    # Every pooled potion fires through apply_potion in a live combat. A real
    # RunState is supplied so the out-of-combat helpers (Fruit Juice's max-HP
    # gain, Entropic Brew's slot fill) have the run object they need.
    from sim.game_state import RunState, Character
    for pid in P._POOL_IDS:
        rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=f"pool{pid}")
        cs = _fresh_combat()
        cs.run_state = rs
        cs.hand = [_strike(), _defend()]
        assert P.apply_potion(rs, cs, pid, 0) is True
