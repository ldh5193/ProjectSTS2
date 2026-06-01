"""Phase 9.4 — Regent card pool, signature cards, relics (decompile-exact).

Card .cs refs in sim/cards.py inline comments; relic refs in sim/relics.py.
"""
import random

from sim.combat import CombatState
from sim.cards import (FALLING_STAR, VENERATE, STRIKE_REGENT, DEFEND_REGENT,
                       SOLAR_STRIKE, GUIDING_STAR, COMET, SEVEN_STARS, DYING_STAR,
                       GAMMA_BLAST, ASTRAL_PULSE, CLOAK_OF_STARS, GATHER_LIGHT,
                       GLOW, KNOCKOUT_BLOW, SHINING_STRIKE, CELESTIAL_MIGHT,
                       HIDDEN_CACHE, CHILD_OF_THE_STARS, METEOR_SHOWER,
                       upgrade_card)
from sim.game_state import Character, RunState


def _combat(seed=1):
    return CombatState.new_combat(seed=seed)


# ---- start deck (Regent.cs:38-50) ------------------------------------------

def test_start_deck_exact():
    deck = RunState.new_run(seed=1, character=Character.REGENT, ascension=0).deck
    ids = sorted(c.id for c in deck)
    assert ids == sorted(
        ["strike_regent"] * 4 + ["defend_regent"] * 4
        + ["falling_star", "venerate"])
    assert len(deck) == 10


def test_strike_defend_values():
    # StrikeRegent 6 (upg +3); DefendRegent 5 (upg +3).
    assert STRIKE_REGENT.effects[0].amount == 6
    assert DEFEND_REGENT.effects[0].amount == 5
    assert upgrade_card(STRIKE_REGENT).effects[0].amount == 9
    assert upgrade_card(DEFEND_REGENT).effects[0].amount == 8


# ---- signature: FallingStar / Venerate -------------------------------------

def test_falling_star_cost_damage_debuffs():
    # FallingStar.cs: 0 energy / star 2, 8 dmg + 1 Weak + 1 Vulnerable (upg +4).
    assert FALLING_STAR.cost == 0
    assert FALLING_STAR.star_cost == 2
    assert FALLING_STAR.effects[0].amount == 8
    pids = {e.power_id for e in FALLING_STAR.effects if e.power_id}
    assert pids == {"weak", "vulnerable"}
    assert upgrade_card(FALLING_STAR).effects[0].amount == 12


def test_falling_star_applies_debuffs_on_play():
    cs = _combat()
    cs.player.energy = 3
    cs.gain_stars(2)
    cs.hand = [FALLING_STAR]
    m = cs.monster
    mh0 = m.hp
    cs.play_card(0)
    assert mh0 - m.hp == 8
    assert m.get_power("weak") is not None
    assert m.get_power("vulnerable") is not None


def test_venerate_gains_two_upgrade_three():
    assert VENERATE.effects[0].amount == 2
    assert upgrade_card(VENERATE).effects[0].amount == 3


# ---- signature star cards ---------------------------------------------------

def test_solar_strike_damage_and_star():
    assert SOLAR_STRIKE.effects[0].amount == 9
    assert any(e.op.value == "gain_stars" and e.amount == 1
               for e in SOLAR_STRIKE.effects)


def test_guiding_star_star_cost_two():
    assert GUIDING_STAR.cost == 1
    assert GUIDING_STAR.star_cost == 2
    assert GUIDING_STAR.effects[0].amount == 12


def test_comet_values():
    # Comet.cs: 0 energy / star 5, 33 dmg + 3 Vuln + 3 Weak (upg +11).
    assert COMET.cost == 0 and COMET.star_cost == 5
    assert COMET.effects[0].amount == 33
    assert upgrade_card(COMET).effects[0].amount == 44


def test_seven_stars_seven_hits_star_seven():
    # SevenStars.cs: 2 energy / star 7 AoE, 7 dmg ×7.
    assert SEVEN_STARS.cost == 2 and SEVEN_STARS.star_cost == 7
    assert SEVEN_STARS.effects[0].amount == 7
    assert SEVEN_STARS.effects[0].hit_count == 7


def test_dying_star_aoe_star_three():
    assert DYING_STAR.cost == 1 and DYING_STAR.star_cost == 3
    assert DYING_STAR.effects[0].target.value == "all_enemies"
    assert DYING_STAR.effects[0].amount == 9


def test_gamma_blast_star_three_debuffs():
    assert GAMMA_BLAST.cost == 0 and GAMMA_BLAST.star_cost == 3
    assert GAMMA_BLAST.effects[0].amount == 13
    pids = {e.power_id for e in GAMMA_BLAST.effects if e.power_id}
    assert pids == {"vulnerable", "weak"}


def test_astral_pulse_aoe_star_three():
    assert ASTRAL_PULSE.cost == 0 and ASTRAL_PULSE.star_cost == 3
    assert ASTRAL_PULSE.effects[0].amount == 14
    assert ASTRAL_PULSE.effects[0].target.value == "all_enemies"


def test_knockout_blow_damage_and_star_gain():
    assert KNOCKOUT_BLOW.cost == 3
    assert KNOCKOUT_BLOW.effects[0].amount == 30
    assert any(e.op.value == "gain_stars" and e.amount == 5
               for e in KNOCKOUT_BLOW.effects)


def test_shining_strike_gains_two_stars():
    assert SHINING_STRIKE.effects[0].amount == 8
    assert any(e.op.value == "gain_stars" and e.amount == 2
               for e in SHINING_STRIKE.effects)


def test_celestial_might_three_hits():
    assert CELESTIAL_MIGHT.effects[0].amount == 6
    assert CELESTIAL_MIGHT.effects[0].hit_count == 3


def test_cloak_of_stars_block_star_one():
    assert CLOAK_OF_STARS.cost == 0 and CLOAK_OF_STARS.star_cost == 1
    assert CLOAK_OF_STARS.effects[0].amount == 7


def test_gather_light_block_and_star():
    assert GATHER_LIGHT.effects[0].amount == 8
    assert any(e.op.value == "gain_stars" and e.amount == 1
               for e in GATHER_LIGHT.effects)


def test_glow_gains_star_and_draw():
    assert any(e.op.value == "gain_stars" and e.amount == 1 for e in GLOW.effects)
    assert any(e.op.value == "draw_card" for e in GLOW.effects)


def test_hidden_cache_star_next_turn():
    # HiddenCache.cs: GainStars 1 + StarNextTurn 3.
    cs = _combat()
    cs.player.energy = 3
    cs.hand = [HIDDEN_CACHE]
    cs.play_card(0)
    assert cs.stars == 1
    assert cs.player.get_power("star_next_turn") is not None
    cs.end_player_turn()
    cs.start_player_turn()
    assert cs.stars == 4   # 1 + 3 next turn


def test_child_of_the_stars_power_card():
    cs = _combat()
    cs.player.energy = 3
    cs.player.block = 0
    cs.hand = [CHILD_OF_THE_STARS]
    cs.play_card(0)
    assert cs.player.get_power("child_of_the_stars") is not None
    cs.gain_stars(3)
    cs.lose_stars(3)
    assert cs.player.block == 3   # 1 block per star spent


def test_meteor_shower_ancient_excluded_from_reward():
    from sim.card_catalog import REGENT_COMMON, REGENT_UNCOMMON, REGENT_RARE
    assert "meteor_shower" not in REGENT_COMMON + REGENT_UNCOMMON + REGENT_RARE
    assert METEOR_SHOWER.star_cost == 2


# ---- pool + reward keying ---------------------------------------------------

def test_regent_pool_88_cards():
    from sim.card_catalog import _REGENT_META
    assert len(_REGENT_META) == 88


def test_regent_reward_pool_keyed():
    from sim.rewards import generate_card_reward
    from sim.rng import Rng
    picks = generate_card_reward(Rng(99), "regular", act=1, ascension=0,
                                 character="regent")
    assert len(picks) == 3
    # Picks should be Regent cards (in the Regent pool), not Ironclad fallbacks.
    from sim.card_catalog import REGENT_COMMON, REGENT_UNCOMMON, REGENT_RARE
    regent_ids = set(REGENT_COMMON + REGENT_UNCOMMON + REGENT_RARE)
    assert all(p.card_id in regent_ids for p in picks)


# ---- relics (RegentRelicPool.cs) -------------------------------------------

def test_regent_relic_pool_eight():
    from sim.relics import character_relic_pool_ids
    ids = character_relic_pool_ids("regent")
    assert len(ids) == 7   # 7 droppable; DivineRight is the starter
    for rid in ("FENCING_MANUAL", "GALACTIC_DUST", "LUNAR_PASTRY", "MINI_REGENT",
                "ORANGE_DOUGH", "REGALITE", "VITRUVIAN_MINION"):
        assert rid in ids


def test_galactic_dust_block_per_ten_stars():
    from sim.relics import _galactic_dust_stars_spent
    cs = _combat()
    cs.player.block = 0
    _galactic_dust_stars_spent(None, cs, 4)
    assert cs.player.block == 0      # 4 < 10
    _galactic_dust_stars_spent(None, cs, 7)   # total 11 -> cross 10 once
    assert cs.player.block == 10


def test_mini_regent_first_spend_strength():
    from sim.relics import _mini_regent_stars_spent
    cs = _combat()
    cs.turn_number = 1
    _mini_regent_stars_spent(None, cs, 2)
    st = cs.player.get_power("strength")
    assert st is not None and st.amount == 1
    # Second spend same turn -> no extra Strength.
    _mini_regent_stars_spent(None, cs, 1)
    assert cs.player.get_power("strength").amount == 1


def test_lunar_pastry_gains_star_at_turn_end():
    from sim.relics import _lunar_pastry_turn_end
    cs = _combat()
    _lunar_pastry_turn_end(None, cs)
    assert cs.stars == 1


def test_regalite_block_on_card_drawn():
    from sim.relics import _regalite_card_drawn
    cs = _combat()
    cs.player.block = 0
    _regalite_card_drawn(None, cs, None)
    assert cs.player.block == 2


# ---- A0 integration ---------------------------------------------------------

def test_regent_a0_integration_reaches_deep_floors():
    """A random-legal-action Regent run at A0 advances through several floors
    drawing from her star deck without exceptions."""
    from sim.env_run import RunEnv
    env = RunEnv(ascension=0, character=Character.REGENT)
    max_floor = 0
    seed = 777
    env.reset(seed=seed)
    for _ in range(8000):
        mask = env.action_masks()
        legal = [i for i, m in enumerate(mask) if m]
        if not legal:
            seed += 1
            env.reset(seed=seed)
            continue
        a = random.Random(env.rs.floor * 7 + len(legal) + seed).choice(legal)
        env.step(a)
        max_floor = max(max_floor, env.rs.floor)
        if env.rs.is_terminal():
            seed += 1
            env.reset(seed=seed)
    assert max_floor >= 3
