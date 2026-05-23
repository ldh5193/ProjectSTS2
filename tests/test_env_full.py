"""Tests for the Discrete(61) env wrapper."""
from __future__ import annotations

import numpy as np

from sim.env_full import (
    ACTION_END_TURN,
    ACTION_TARGETED_BASE,
    ACTION_UNTARGETED_BASE,
    ENEMY_SLOTS,
    HAND_SLOTS,
    N_ACTIONS,
    SludgeSpinnerEnvFull,
    decode_action,
)


def test_action_count_matches_plan():
    assert N_ACTIONS == 61
    assert HAND_SLOTS == 10
    assert ENEMY_SLOTS == 5


def test_decode_partitions_action_space():
    assert decode_action(0) == ("end", -1, -1)
    assert decode_action(1) == ("untargeted", 0, -1)
    assert decode_action(10) == ("untargeted", 9, -1)
    assert decode_action(11) == ("targeted", 0, 0)
    assert decode_action(15) == ("targeted", 0, 4)
    assert decode_action(16) == ("targeted", 1, 0)
    assert decode_action(60) == ("targeted", 9, 4)


def test_reset_returns_obs_and_mask():
    env = SludgeSpinnerEnvFull()
    obs, info = env.reset(seed=42)
    assert obs.shape == (20,)
    mask = info["action_mask"]
    assert mask.shape == (N_ACTIONS,)
    assert mask[ACTION_END_TURN]


def test_only_single_enemy_slot_is_open():
    env = SludgeSpinnerEnvFull()
    env.reset(seed=42)
    mask = env.action_masks()
    # MVP has 1 enemy, so j>0 columns must all be False.
    for i in range(HAND_SLOTS):
        for j in range(1, ENEMY_SLOTS):
            assert not mask[ACTION_TARGETED_BASE + i * ENEMY_SLOTS + j]


def test_strike_is_in_targeted_slot_defend_in_untargeted():
    env = SludgeSpinnerEnvFull()
    env.reset(seed=42)
    mask = env.action_masks()
    # At least one targeted action (Strike or Bash) and one untargeted (Defend)
    # should typically be playable on opening hand with 3 energy.
    targeted = mask[ACTION_TARGETED_BASE:].any()
    untargeted = mask[ACTION_UNTARGETED_BASE : ACTION_TARGETED_BASE].any()
    assert targeted and untargeted


def test_random_policy_terminates():
    env = SludgeSpinnerEnvFull()
    rng = np.random.default_rng(0)
    obs, info = env.reset(seed=1)
    for _ in range(500):
        valid = np.flatnonzero(info["action_mask"])
        assert valid.size > 0
        action = int(rng.choice(valid))
        obs, reward, term, _, info = env.step(action)
        if term:
            return
    raise AssertionError("env did not terminate")
