"""Phase 9.4 — Regent Star resource primitive tests (decompile-exact values).

Refs: PlayerCombatState.cs (Stars / GainStars / LoseStars / HasEnoughResourcesFor
/ SpendResources, lines 70-182, 146-165, 1397-1410 in CardModel.cs),
StarNextTurnPower.cs, ChildOfTheStarsPower.cs (AfterStarsSpent), DivineRight.cs
(GainStars 3 on combat enter), GalacticDust.cs / MiniRegent.cs / LunarPastry.cs.
"""
import numpy as np

from sim.combat import CombatState
from sim.cards import FALLING_STAR, VENERATE, COMET, SOLAR_STRIKE
from sim.dsl import CardDef, CardType, Target, Effect, EffectOp
from sim.game_state import Character, RunState
from sim.powers import make_power


def _combat(seed=1):
    return CombatState.new_combat(seed=seed)


# ---- gain / lose / clamp / persistence -------------------------------------

def test_stars_start_at_zero():
    cs = _combat()
    assert cs.stars == 0


def test_gain_stars_adds():
    cs = _combat()
    cs.gain_stars(3)
    assert cs.stars == 3
    cs.gain_stars(2)
    assert cs.stars == 5


def test_lose_stars_floors_at_zero():
    # LoseStars: Stars = max(Stars - amount, 0) (PlayerCombatState.LoseStars).
    cs = _combat()
    cs.gain_stars(4)
    cs.lose_stars(10)
    assert cs.stars == 0


def test_gain_negative_is_noop():
    cs = _combat()
    cs.gain_stars(-5)
    assert cs.stars == 0


def test_stars_persist_across_turns():
    # Stars are NOT reset per turn (no per-turn reset in PlayerCombatState).
    cs = _combat()
    cs.gain_stars(5)
    cs.end_player_turn()
    cs.start_player_turn()
    assert cs.stars == 5


# ---- star-cost playability + spend (HasEnoughResourcesFor / SpendResources) -

def test_star_card_unplayable_without_stars():
    cs = _combat()
    cs.player.energy = 3
    cs.stars = 0
    cs.hand = [FALLING_STAR]          # 0 energy / 2 stars
    assert cs.can_play(0) is False    # StarCostTooHigh


def test_star_card_playable_with_enough_stars():
    cs = _combat()
    cs.player.energy = 3
    cs.gain_stars(2)
    cs.hand = [FALLING_STAR]
    assert cs.can_play(0) is True


def test_playing_star_card_spends_stars():
    cs = _combat()
    cs.player.energy = 3
    cs.gain_stars(2)
    cs.hand = [FALLING_STAR]
    cs.play_card(0)
    assert cs.stars == 0              # 2 stars spent
    # FallingStar is 0-energy, so energy is unchanged.
    assert cs.player.energy == 3


def test_comet_needs_five_stars():
    cs = _combat()
    cs.player.energy = 3
    cs.gain_stars(4)
    cs.hand = [COMET]                 # 0 energy / 5 stars
    assert cs.can_play(0) is False
    cs.gain_stars(1)
    assert cs.can_play(0) is True


def test_venerate_gains_two_stars():
    # Venerate.cs: GainStars(2). Played for 1 energy, no star cost.
    cs = _combat()
    cs.player.energy = 3
    cs.hand = [VENERATE]
    cs.play_card(0)
    assert cs.stars == 2
    assert cs.player.energy == 2


def test_solar_strike_gains_one_star():
    cs = _combat()
    cs.player.energy = 3
    cs.hand = [SOLAR_STRIKE]
    cs.play_card(0)
    assert cs.stars == 1


# ---- excess-energy-paid-with-stars (2 stars per missing energy) -------------

from dataclasses import dataclass, field  # noqa: E402
from sim.powers import Power  # noqa: E402


@dataclass
class _ExcessPower(Power):
    """A test power that grants ShouldPayExcessEnergyCostWithStars."""
    id: str = field(default="excess_star_pay", init=False)

    def should_pay_excess_energy_with_stars(self):
        return True


def test_excess_energy_paid_with_stars_two_per_energy():
    # PlayerCombatState.HasEnoughResourcesFor / CardModel.SpendResources:
    # if energy < energy_cost and the hook is on, the missing energy is paid
    # at 2 stars each. A 2-energy card with 0 energy + 4 stars -> 4 stars spent.
    cs = _combat()
    cs.player.energy = 0
    cs.gain_stars(4)
    cs.player.powers.append(_ExcessPower())
    card = CardDef(id="t2", name="T2", cost=2, type=CardType.SKILL,
                   effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF,
                                   amount=1),))
    assert cs.star_cost_of(card) == 4   # (2 - 0) * 2
    cs.hand = [card]
    assert cs.can_play(0) is True
    cs.play_card(0)
    assert cs.stars == 0


def test_excess_energy_partial_payment():
    cs = _combat()
    cs.player.energy = 1                # 1 short of a 2-cost card
    cs.gain_stars(2)
    cs.player.powers.append(_ExcessPower())
    card = CardDef(id="t2b", name="T2b", cost=2, type=CardType.SKILL,
                   effects=(Effect(op=EffectOp.GAIN_BLOCK, target=Target.SELF,
                                   amount=1),))
    assert cs.star_cost_of(card) == 2   # (2 - 1) * 2


# ---- star powers ------------------------------------------------------------

def test_star_next_turn_power_gains_then_removes():
    # StarNextTurnPower.cs (AfterEnergyReset): GainStars(amount), then Remove.
    cs = _combat()
    cs.player.add_or_stack_power(make_power("star_next_turn", 3, cs.player))
    cs.end_player_turn()
    cs.start_player_turn()
    assert cs.stars == 3
    assert cs.player.get_power("star_next_turn") is None


def test_child_of_the_stars_block_per_star_spent():
    # ChildOfTheStarsPower.cs (AfterStarsSpent): +Amount block per star spent.
    cs = _combat()
    cs.player.block = 0
    cs.player.add_or_stack_power(make_power("child_of_the_stars", 1, cs.player))
    cs.gain_stars(2)
    cs.lose_stars(2)                    # spend 2 -> 2*1 = 2 block
    assert cs.player.block == 2


def test_child_of_the_stars_scales_with_amount():
    cs = _combat()
    cs.player.block = 0
    cs.player.add_or_stack_power(make_power("child_of_the_stars", 2, cs.player))
    cs.gain_stars(3)
    cs.lose_stars(3)                    # 3 spent * 2 = 6 block
    assert cs.player.block == 6


def test_void_form_zeroes_first_card_energy_and_stars():
    # VoidFormPower.cs: first `amount` cards each turn cost 0 energy AND 0 stars.
    cs = _combat()
    cs.player.energy = 0
    cs.stars = 0
    cs.player.add_or_stack_power(make_power("void_form", 1, cs.player))
    cs.player._void_init = True
    # Trigger the per-turn reset so the counter is 0.
    for p in cs.player.powers:
        if getattr(p, "id", None) == "void_form":
            p._played_this_turn = 0
    cs.hand = [FALLING_STAR]            # would need 2 stars normally
    assert cs.effective_cost(FALLING_STAR) == 0
    assert cs.star_cost_of(FALLING_STAR) == 0
    assert cs.can_play(0) is True


# ---- DivineRight starter + obs ---------------------------------------------

def test_divine_right_grants_3_stars_on_combat_start():
    from sim.relics import trigger_on_combat_start
    rs = RunState.new_run(seed=1, character=Character.REGENT, ascension=0)
    cs = _combat()
    cs.run_state = rs
    # DivineRight is the Regent starter relic.
    assert any(r.id == "DIVINE_RIGHT" for r in rs.relics)
    trigger_on_combat_start(rs, cs)
    assert cs.stars >= 3


def test_obs_star_slot_populated_for_regent():
    from sim.env_run import RunEnv
    env = RunEnv(ascension=0, character=Character.REGENT)
    env.reset(seed=3)
    # Step with random legal actions until a combat exists, then set stars and
    # read the obs slot [510] = stars / 10.
    found = False
    for _ in range(400):
        if env.rs.in_combat() and env.rs.combat is not None:
            env.rs.combat.stars = 5
            obs = env._obs()
            assert abs(obs[510] - 0.5) < 1e-6   # 5 / 10
            found = True
            break
        mask = env.action_masks()
        legal = [i for i, m in enumerate(mask) if m]
        if not legal:
            break
        env.step(legal[0])
        if env.rs.is_terminal():
            env.reset(seed=3)
    assert found


def test_obs_star_slot_zero_for_ironclad():
    from sim.env_run import RunEnv
    env = RunEnv(ascension=0, character=Character.IRONCLAD)
    obs, _ = env.reset(seed=3)
    assert obs[510] == 0.0
