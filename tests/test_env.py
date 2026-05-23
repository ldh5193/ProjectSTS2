"""Tests for the Gymnasium env wrapper."""
from __future__ import annotations

import numpy as np

from sim.env import ACTION_END_TURN, ACTION_PLAY_OFFSET, N_ACTIONS, SludgeSpinnerEnv
from sim.observation import OBS_DIM


def test_reset_returns_obs_and_mask():
    env = SludgeSpinnerEnv()
    obs, info = env.reset(seed=42)
    assert isinstance(obs, np.ndarray)
    assert obs.shape == (OBS_DIM,)
    assert obs.dtype == np.float32
    mask = info["action_mask"]
    assert mask.shape == (N_ACTIONS,)
    assert mask[ACTION_END_TURN]
    # At least one card should be playable (hand size 5, energy 3, cards cost 1–2).
    assert mask[ACTION_PLAY_OFFSET:].any()


def test_step_end_turn_does_not_terminate_immediately():
    env = SludgeSpinnerEnv()
    env.reset(seed=42)
    obs, reward, term, trunc, info = env.step(ACTION_END_TURN)
    assert not term
    assert not trunc
    assert obs.shape == (OBS_DIM,)
    assert "action_mask" in info


def test_random_policy_terminates_under_300_steps():
    env = SludgeSpinnerEnv()
    rng = np.random.default_rng(0)
    won = lost = 0
    for episode in range(30):
        obs, info = env.reset(seed=episode)
        for _ in range(300):
            mask = info["action_mask"]
            valid = np.flatnonzero(mask)
            assert valid.size > 0, "no valid action under random policy"
            action = int(rng.choice(valid))
            obs, reward, term, trunc, info = env.step(action)
            if term:
                if reward > 0:
                    won += 1
                else:
                    lost += 1
                break
        else:
            raise AssertionError("env did not terminate in 300 steps")
    # Sanity: at least some games end either way (no crashes).
    assert won + lost == 30


def test_obs_values_within_bounds():
    env = SludgeSpinnerEnv()
    obs, info = env.reset(seed=7)
    assert (obs >= 0.0).all() and (obs <= 1.0).all()
    for _ in range(20):
        mask = info["action_mask"]
        action = int(np.flatnonzero(mask)[0])
        obs, _, term, _, info = env.step(action)
        assert (obs >= 0.0).all() and (obs <= 1.0).all()
        if term:
            break
