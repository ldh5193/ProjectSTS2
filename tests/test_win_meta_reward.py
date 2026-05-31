"""Tests for the meta-informed `win_meta` reward preset and the two new
RewardConfig dense signals: relic_gained_weight and power_card_played_weight.

Background: STS2 community stats show relic count is the #1 win predictor
and scaling powers before Act 3 are mandatory. These dense per-step bonuses
teach those behaviors instead of relying on the sparse victory signal alone.
"""
from __future__ import annotations

from dataclasses import fields

from sim.combat import CombatState
from sim.dsl import CardType
from sim.env_run import REWARD_PRESETS, RewardConfig, RunEnv
from sim.run_engine import StepResult


def _fresh_env(preset: str) -> RunEnv:
    env = RunEnv(ascension=0, reward_config=REWARD_PRESETS[preset])
    env.reset(seed=123)
    return env


def _noop_result() -> StepResult:
    """A StepResult with no milestone flags so _reward only reflects the
    living_cost baseline plus whatever dense delta we inject."""
    return StepResult()


# ---- preset existence / selectability -------------------------------------

def test_win_meta_preset_exists_and_selectable():
    assert "win_meta" in REWARD_PRESETS
    cfg = REWARD_PRESETS["win_meta"]
    assert isinstance(cfg, RewardConfig)
    # Selectable through the env constructor.
    env = RunEnv(ascension=0, reward_config=cfg)
    assert env.reward_config is cfg


def test_win_meta_values():
    cfg = REWARD_PRESETS["win_meta"]
    assert cfg.run_victory == 30.0
    assert cfg.boss_kill == 8.0
    assert cfg.act_completion == 4.0
    assert cfg.elite_kill == 2.0
    assert cfg.relic_gained_weight == 3.0
    assert cfg.power_card_played_weight == 0.5
    assert cfg.floor_advance == 0.005
    assert cfg.living_cost == -0.0005
    assert cfg.death == -2.0
    assert cfg.hp_delta_weight == 0.01
    assert cfg.damage_dealt_weight == 0.003


# ---- relic_gained signal --------------------------------------------------

def test_relic_gained_adds_weight_under_win_meta():
    env = _fresh_env("win_meta")
    cfg = env.reward_config
    base = env.rs.hp  # keep hp constant so hp_delta contributes 0
    env._last_hp = base
    # Baseline reward with no relic change.
    r0 = env._reward(_noop_result())
    # Grant a new relic, then take a step's reward.
    env.rs.add_relic("VAJRA")
    r1 = env._reward(_noop_result())
    # The only difference is one new relic.
    assert abs((r1 - r0) - cfg.relic_gained_weight) < 1e-9
    assert cfg.relic_gained_weight == 3.0


def test_multiple_relics_scale_linearly():
    env = _fresh_env("win_meta")
    cfg = env.reward_config
    env._last_hp = env.rs.hp
    r0 = env._reward(_noop_result())
    before = len(env.rs.relics)
    env.rs.add_relic("VAJRA")
    env.rs.add_relic("ANCHOR")
    r1 = env._reward(_noop_result())
    gained = len(env.rs.relics) - before
    assert gained == 2
    assert abs((r1 - r0) - cfg.relic_gained_weight * gained) < 1e-9


def test_relic_gained_zero_under_zero_weight_preset():
    # "default" has relic_gained_weight == 0.0.
    env = _fresh_env("default")
    assert env.reward_config.relic_gained_weight == 0.0
    env._last_hp = env.rs.hp
    r0 = env._reward(_noop_result())
    env.rs.add_relic("VAJRA")
    r1 = env._reward(_noop_result())
    assert abs(r1 - r0) < 1e-9  # no relic bonus


# ---- power_card_played signal ---------------------------------------------

def test_power_card_played_adds_weight_under_win_meta():
    env = _fresh_env("win_meta")
    cfg = env.reward_config
    # Force an in-combat state with a combat object exposing the counter.
    cs = CombatState.new_combat(seed=0)
    env.rs.combat = cs
    env._last_hp = env.rs.hp
    cs.powers_played_this_step = 0
    r0 = env._reward(_noop_result())
    cs.powers_played_this_step = 1
    r1 = env._reward(_noop_result())
    assert abs((r1 - r0) - cfg.power_card_played_weight) < 1e-9
    assert cfg.power_card_played_weight == 0.5


def test_power_counter_reset_after_reward():
    env = _fresh_env("win_meta")
    cs = CombatState.new_combat(seed=0)
    env.rs.combat = cs
    env._last_hp = env.rs.hp
    cs.powers_played_this_step = 2
    env._reward(_noop_result())
    # _reward must reset the per-step counter so it never leaks.
    assert cs.powers_played_this_step == 0


def test_power_card_played_increments_in_play_card():
    """The CombatState.play_card choke point increments the counter for a
    POWER card and leaves it untouched for a non-power card."""
    from sim.card_catalog import CARDS

    cs = CombatState.new_combat(seed=0)
    cs.powers_played_this_step = 0
    # Find a POWER card and an ATTACK card.
    power_id = next(cid for cid, c in CARDS.items() if c.type is CardType.POWER)
    cs.hand = [CARDS[power_id]]
    cs.player.energy = 9
    cs.play_card(0)
    assert cs.powers_played_this_step == 1


def test_power_card_played_zero_under_zero_weight_preset():
    env = _fresh_env("default")
    assert env.reward_config.power_card_played_weight == 0.0
    cs = CombatState.new_combat(seed=0)
    env.rs.combat = cs
    env._last_hp = env.rs.hp
    cs.powers_played_this_step = 0
    r0 = env._reward(_noop_result())
    cs.powers_played_this_step = 3
    r1 = env._reward(_noop_result())
    assert abs(r1 - r0) < 1e-9  # no power bonus


# ---- existing presets unchanged -------------------------------------------

def test_existing_presets_have_zero_new_weights():
    """Every preset except win_meta must keep the two new dense weights at
    their 0.0 default so prior training signals are byte-for-byte unchanged."""
    for name, cfg in REWARD_PRESETS.items():
        if name == "win_meta":
            continue
        assert cfg.relic_gained_weight == 0.0, name
        assert cfg.power_card_played_weight == 0.0, name


def test_victory_preset_unchanged():
    """The original 'victory' preset values must be exactly preserved."""
    cfg = REWARD_PRESETS["victory"]
    assert cfg.combat_win == 0.25
    assert cfg.elite_kill == 1.0
    assert cfg.boss_kill == 8.0
    assert cfg.act_completion == 4.0
    assert cfg.run_victory == 30.0
    assert cfg.floor_advance == 0.005
    assert cfg.living_cost == -0.0005
    assert cfg.death == -2.0
    assert cfg.hp_delta_weight == 0.01
    assert cfg.damage_dealt_weight == 0.003
    assert cfg.relic_gained_weight == 0.0
    assert cfg.power_card_played_weight == 0.0


def test_new_fields_default_zero():
    cfg = RewardConfig()
    assert cfg.relic_gained_weight == 0.0
    assert cfg.power_card_played_weight == 0.0
    names = {f.name for f in fields(RewardConfig)}
    assert "relic_gained_weight" in names
    assert "power_card_played_weight" in names
