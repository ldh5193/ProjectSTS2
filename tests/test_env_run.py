"""Full-run env smoke tests."""
from __future__ import annotations

import numpy as np

from sim.action_space import N_ACTIONS, range_named
from sim.env_run import OBS_DIM, RunEnv


def test_reset_returns_obs_and_mask():
    env = RunEnv()
    obs, info = env.reset(seed=0)
    assert obs.shape == (OBS_DIM,)
    assert obs.dtype == np.float32
    assert 0.0 <= obs.min() and obs.max() <= 1.0
    mask = info["action_mask"]
    assert mask.shape == (N_ACTIONS,)
    # At reset the agent is on the map; map options should be available.
    map_r = range_named("map")
    assert any(mask[map_r.start:map_r.stop])


def test_random_policy_terminates_under_500_steps():
    env = RunEnv()
    obs, info = env.reset(seed=1)
    rng = np.random.default_rng(0)
    steps = 0
    while True:
        mask = info["action_mask"]
        legal = np.flatnonzero(mask)
        if len(legal) == 0:
            break
        action = int(rng.choice(legal))
        obs, reward, term, _, info = env.step(action)
        steps += 1
        if term or steps >= 500:
            break
    # The run should end within the cap — either victory or death.
    assert steps < 500 or term


def test_obs_clipped_to_unit_interval():
    env = RunEnv()
    obs, info = env.reset(seed=7)
    assert (obs >= 0.0).all() and (obs <= 1.0).all()
    # Take a few legal random steps and re-check.
    rng = np.random.default_rng(0)
    for _ in range(20):
        mask = info["action_mask"]
        legal = np.flatnonzero(mask)
        if len(legal) == 0:
            break
        obs, reward, term, _, info = env.step(int(rng.choice(legal)))
        assert (obs >= 0.0).all() and (obs <= 1.0).all()
        if term:
            break


def test_invalid_action_penalty_via_reward():
    """Stepping with an explicitly illegal action returns negative reward
    and does not terminate the run abruptly."""
    env = RunEnv()
    env.reset(seed=0)
    # Pick an index that should be masked (combat range while on map).
    map_r = range_named("combat")
    obs, reward, term, _, info = env.step(map_r.start + 1)
    assert reward < 0.0
    assert not term


def test_run_is_deterministic_for_same_seed():
    env = RunEnv()
    obs1, info1 = env.reset(seed=42)
    obs2, info2 = env.reset(seed=42)
    assert np.allclose(obs1, obs2)
    assert (info1["action_mask"] == info2["action_mask"]).all()
