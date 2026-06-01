"""Phase 2 tests — obs v4 + Tiered terminal score + ascension mixture."""
from __future__ import annotations

import numpy as np
import pytest

from sim.env_run import OBS_DIM, OBS_DIM_V3, RunEnv
from sim.game_state import Character


def test_obs_dim_v4():
    """obs bumped 256 (v3) → 384 (Phase 3) → 504 (Phase 7F+G shop block)
    → 560 (Phase 9.0 v5 multi-character additive tail)."""
    assert OBS_DIM >= 320  # at least Phase 2 worth
    assert OBS_DIM == 560  # current layout (Phase 9.0 obs v5)
    assert OBS_DIM_V3 == 256


def test_observation_space_matches_obs_dim():
    env = RunEnv(ascension=0)
    assert env.observation_space.shape == (OBS_DIM,)


def test_reset_returns_obs_of_correct_shape():
    env = RunEnv(ascension=0)
    obs, _ = env.reset(seed=42)
    assert obs.shape == (OBS_DIM,)
    assert obs.dtype == np.float32


def test_obs_values_in_unit_range():
    env = RunEnv(ascension=0)
    obs, _ = env.reset(seed=42)
    assert (obs >= 0.0).all()
    assert (obs <= 1.0).all()


def test_ascension_mixture_samples_levels():
    env = RunEnv(ascension_mixture={0: 0.5, 10: 0.5})
    seen = set()
    for seed in range(30):
        env.reset(seed=seed)
        seen.add(int(env.rs.ascension))
    # Over 30 seeds, both 0 and 10 should appear (with overwhelming prob).
    assert 0 in seen
    assert 10 in seen


def test_ascension_mixture_respects_weights_roughly():
    env = RunEnv(ascension_mixture={0: 0.9, 10: 0.1})
    n0 = n10 = 0
    for seed in range(200):
        env.reset(seed=seed)
        if int(env.rs.ascension) == 0:
            n0 += 1
        elif int(env.rs.ascension) == 10:
            n10 += 1
    # With 0.9/0.1 weights over 200 samples, ~180/20 expected.
    # Allow wide margin since np_random seeding from env can correlate.
    assert n0 > n10  # qualitative direction must hold


def test_ascension_mixture_rejects_empty():
    with pytest.raises(ValueError):
        RunEnv(ascension_mixture={})


def test_compute_terminal_score_early_death():
    env = RunEnv(ascension=0)
    env.reset(seed=42)
    # Force early-act-1 death by zeroing HP.
    env.rs.hp = 0
    env.rs.is_dead = True
    score = env.compute_terminal_score()
    # acts_completed=0, within = floor/17 ≈ 0 at floor 0/1, no boss dmg
    # → small score, well under 50.
    assert 0 <= score < 50


def test_compute_terminal_score_act_1_complete():
    env = RunEnv(ascension=0)
    env.reset(seed=42)
    env._acts_completed = 1
    env.rs.floor = 17  # at act-1 boss kill, transitioning to act 2
    score = env.compute_terminal_score()
    # 100 (1 act) + 50 (within = 17/17 = 1.0) = 150
    # — but actually within for act 1 with floor 17 = 1.0,
    # for act 2 with floor 17 = 0.0. We're "at" the transition.
    # Score should be at least 100.
    assert score >= 100


def test_compute_terminal_score_victory_dominates():
    env = RunEnv(ascension=0)
    env.reset(seed=42)
    env._acts_completed = 3
    env.rs.act = 3
    env.rs.floor = 51
    env.rs.is_victorious = True
    score = env.compute_terminal_score()
    # 100*3 + 50*1 + 0 + 300 = 650 (within_act_progress for act 3 at f51
    # = (51-34)/17 = 1.0)
    assert score >= 600
    assert score <= 700


def test_compute_terminal_score_monotonic_in_floor():
    """Scores must increase as floor depth increases (same acts_completed)."""
    env = RunEnv(ascension=0)
    env.reset(seed=42)
    env.rs.act = 1
    env.rs.floor = 5
    score_5 = env.compute_terminal_score()
    env.rs.floor = 10
    score_10 = env.compute_terminal_score()
    env.rs.floor = 16
    score_16 = env.compute_terminal_score()
    assert score_5 < score_10 < score_16


def test_compute_terminal_score_act_jumps_dominate_floor():
    """Beating an act > floor depth without it. 100-pt jump per act."""
    env = RunEnv(ascension=0)
    env.reset(seed=42)

    # Scenario A: die floor 16 (just before act 1 boss).
    env._acts_completed = 0
    env.rs.act = 1
    env.rs.floor = 16
    s_die_act1 = env.compute_terminal_score()

    # Scenario B: beat act 1, die floor 18 (just after).
    env._acts_completed = 1
    env.rs.act = 2
    env.rs.floor = 18
    s_beat_act1 = env.compute_terminal_score()

    assert s_beat_act1 > s_die_act1 + 50  # act-completion bonus dominates


def test_compute_terminal_score_boss_damage_partial():
    """30 * within_act_boss_dmg_ratio adds to the score."""
    env = RunEnv(ascension=0)
    env.reset(seed=42)
    env._acts_completed = 0
    env.rs.act = 1
    env.rs.floor = 17
    env._boss_dmg_dealt_ratio = 0.0
    s0 = env.compute_terminal_score()
    env._boss_dmg_dealt_ratio = 1.0
    s_full = env.compute_terminal_score()
    assert s_full - s0 == 30.0
