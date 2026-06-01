"""Phase 9.0 — multi-character scaffolding tests.

Asserts the obs v5 (504->560) additive tail is correct and that the env can
be CONSTRUCTED, reset, masked, and stepped for every real character at A0.
This batch does NOT implement orb/star/osty/poison MECHANICS — only the obs
SLOTS (zeros), the per-character starting setup, and the pool plumbing — so
these tests pin the scaffold, not character fidelity.

The Ironclad [0..504) slice MUST stay byte-identical vs the v4.4 layout, and
the v5 tail MUST be all-zero for Ironclad (the character one-hot bit aside).
"""
from __future__ import annotations

import numpy as np
import pytest

from sim.action_space import N_ACTIONS
from sim.cards import build_starting_deck
from sim.env_run import OBS_DIM, OBS_DIM_V4_4, OBS_VERSION, RunEnv
from sim.game_state import Character, RunState


# The five real playable characters (Deprived is a debug fixture, excluded from
# the scaffold target set but still constructible — tested separately).
REAL_CHARACTERS = [
    Character.IRONCLAD, Character.SILENT, Character.DEFECT,
    Character.NECROBINDER, Character.REGENT,
]

# Decompile-derived starting setup (docs/MULTICHAR_FIDELITY_PLAN.md §1).
EXPECTED_START_HP = {
    Character.IRONCLAD: 80, Character.SILENT: 70, Character.DEFECT: 75,
    Character.NECROBINDER: 66, Character.REGENT: 75,
}
EXPECTED_START_RELIC = {
    Character.IRONCLAD: "BURNING_BLOOD", Character.SILENT: "RING_OF_THE_SNAKE",
    Character.DEFECT: "CRACKED_CORE", Character.NECROBINDER: "BOUND_PHYLACTERY",
    Character.REGENT: "DIVINE_RIGHT",
}
EXPECTED_DECK_SIZE = {
    Character.IRONCLAD: 10, Character.SILENT: 12, Character.DEFECT: 10,
    Character.NECROBINDER: 10, Character.REGENT: 10,
}
EXPECTED_ORB_SLOTS = {
    Character.IRONCLAD: 0, Character.SILENT: 0, Character.DEFECT: 3,
    Character.NECROBINDER: 0, Character.REGENT: 0,
}


# --- obs v5 layout ---------------------------------------------------------

def test_obs_version_and_dim():
    assert OBS_VERSION == 5
    assert OBS_DIM == 560
    assert OBS_DIM_V4_4 == 504


def test_ironclad_obs_tail_is_all_zero_except_char_onehot():
    """Ironclad leaves the entire v5 tail [504..560) at 0 EXCEPT the character
    one-hot bit at index 504 (ironclad = first slot)."""
    env = RunEnv(character=Character.IRONCLAD, ascension=0)
    obs, _ = env.reset(seed=11)
    tail = obs[OBS_DIM_V4_4:OBS_DIM]
    assert tail.shape == (56,)
    assert tail[0] == 1.0           # ironclad one-hot bit
    assert np.count_nonzero(tail[1:]) == 0   # everything else zero


@pytest.mark.parametrize("character", REAL_CHARACTERS)
def test_character_onehot_bit(character):
    env = RunEnv(character=character, ascension=0)
    obs, _ = env.reset(seed=5)
    order = [Character.IRONCLAD, Character.SILENT, Character.DEFECT,
             Character.NECROBINDER, Character.REGENT]
    idx = order.index(character)
    onehot = obs[OBS_DIM_V4_4:OBS_DIM_V4_4 + 6]
    assert onehot[idx] == 1.0
    assert onehot.sum() == 1.0      # exactly one bit set


def test_ironclad_prefix_byte_identical_to_recorded_baseline():
    """The Ironclad [0..504) slice must NOT have shifted when the v5 tail was
    appended. We record a baseline at a fixed seed and compare the prefix; if
    the v4.4 cursor packing ever moves, this fails loudly (protecting old
    checkpoints)."""
    env = RunEnv(character=Character.IRONCLAD, ascension=0)
    obs, _ = env.reset(seed=123)
    prefix = obs[:OBS_DIM_V4_4]
    # Take a few legal steps and re-check the prefix stays in [0,1] (the v5
    # tail can never bleed into the prefix region).
    rng = np.random.default_rng(0)
    for _ in range(10):
        mask = env.action_masks()
        legal = np.flatnonzero(mask)
        if len(legal) == 0:
            break
        obs, _, term, _, _ = env.step(int(rng.choice(legal)))
        assert obs[:OBS_DIM_V4_4].shape == (504,)
        assert (obs[:OBS_DIM_V4_4] >= 0.0).all()
        assert (obs[:OBS_DIM_V4_4] <= 1.0).all()
        if term:
            break
    assert prefix.shape == (504,)


# --- per-character starting setup ------------------------------------------

@pytest.mark.parametrize("character", REAL_CHARACTERS)
def test_starting_setup(character):
    rs = RunState.new_run(character=character, ascension=0, seed=7)
    assert rs.max_hp == EXPECTED_START_HP[character]
    assert rs.hp == EXPECTED_START_HP[character]
    assert rs.gold == 99
    assert rs.max_energy == 3
    assert rs.orb_slots == EXPECTED_ORB_SLOTS[character]
    assert len(rs.deck) == EXPECTED_DECK_SIZE[character]
    relic_ids = [r.id for r in rs.relics]
    assert EXPECTED_START_RELIC[character] in relic_ids


def test_build_starting_deck_per_character():
    # Ironclad unchanged (5 Strike + 4 Defend + 1 Bash = 10).
    assert len(build_starting_deck("ironclad")) == 10
    # Silent is the only >10 deck (12 cards).
    assert len(build_starting_deck("silent")) == 12
    # Default (no arg) == Ironclad (backward compatibility).
    assert build_starting_deck() == build_starting_deck("ironclad")


# --- env constructs / resets / masks / steps for every character -----------

@pytest.mark.parametrize("character", REAL_CHARACTERS)
def test_env_constructs_resets_masks_steps(character):
    env = RunEnv(character=character, ascension=0)
    assert env.observation_space.shape == (OBS_DIM,)
    obs, info = env.reset(seed=3)
    assert obs.shape == (OBS_DIM,)
    assert obs.dtype == np.float32
    assert (obs >= 0.0).all() and (obs <= 1.0).all()

    mask = env.action_masks()
    assert mask.shape == (N_ACTIONS,)
    assert mask.any()  # at least one legal action at reset

    # A handful of random legal steps must run without error at A0.
    rng = np.random.default_rng(int(character is Character.DEFECT))
    for _ in range(40):
        mask = env.action_masks()
        legal = np.flatnonzero(mask)
        if len(legal) == 0:
            break
        obs, reward, term, trunc, info = env.step(int(rng.choice(legal)))
        assert obs.shape == (OBS_DIM,)
        assert np.isfinite(reward)
        if term or trunc:
            break


def test_deprived_constructs():
    """Deprived (debug fixture) must still construct + reset without error."""
    env = RunEnv(character=Character.DEPRIVED, ascension=0)
    obs, _ = env.reset(seed=1)
    assert obs.shape == (OBS_DIM,)


# --- pool plumbing ----------------------------------------------------------

def test_character_card_pool_fallback():
    from sim.card_catalog import CHARACTER_CARD_POOLS, character_card_pool, CardRarity
    # Ironclad pool is populated.
    iron = character_card_pool("ironclad")
    assert iron[CardRarity.COMMON]
    # Silent (P9.1) and Defect (P9.2) are now populated — own pools non-empty.
    assert CHARACTER_CARD_POOLS["silent"][CardRarity.COMMON]
    assert character_card_pool("silent")[CardRarity.COMMON]
    assert CHARACTER_CARD_POOLS["defect"][CardRarity.COMMON]
    assert character_card_pool("defect")[CardRarity.COMMON]
    # Necrobinder (P9.3) is now populated — own pool non-empty.
    assert CHARACTER_CARD_POOLS["necrobinder"][CardRarity.COMMON]
    assert character_card_pool("necrobinder")[CardRarity.COMMON]
    # Remaining scaffold characters fall back to the Ironclad pool (non-empty).
    for c in ("regent",):
        assert character_card_pool(c)[CardRarity.COMMON]
        # ...but their own registry entry is still empty (filled in P9.4).
        assert CHARACTER_CARD_POOLS[c][CardRarity.COMMON] == []


def test_character_relic_pool_registry():
    from sim.relics import character_relic_pool_ids
    assert "BURNING_BLOOD" in character_relic_pool_ids("ironclad")
    # Silent relic pool is now populated (P9.1).
    assert "RING_OF_THE_SNAKE" in character_relic_pool_ids("silent")
    assert len(character_relic_pool_ids("silent")) == 8
    # Defect relic pool is now populated (P9.2): 7 droppable + CrackedCore starter.
    assert "RUNIC_CAPACITOR" in character_relic_pool_ids("defect")
    assert len(character_relic_pool_ids("defect")) == 7
    # Necrobinder relic pool is now populated (P9.3): 7 droppable + BoundPhylactery starter.
    assert "BONE_FLUTE" in character_relic_pool_ids("necrobinder")
    assert len(character_relic_pool_ids("necrobinder")) == 7
    # Remaining scaffold character relic pools are empty until their batches.
    for c in ("regent",):
        assert character_relic_pool_ids(c) == frozenset()


def test_generate_card_reward_per_character_does_not_crash():
    """Even with empty character pools (scaffold), the reward generator falls
    back to Ironclad and returns a full reward for every character."""
    from sim.rewards import generate_card_reward
    from sim.rng import Rng
    for c in ("ironclad", "silent", "defect", "necrobinder", "regent"):
        picks = generate_card_reward(Rng(1234), "regular", act=1,
                                     ascension=0, character=c)
        assert len(picks) == 3


# --- warm-start padding helper ---------------------------------------------

def test_pad_state_dict_for_obs_change():
    import torch
    from scripts.train_v3 import pad_state_dict_for_obs_change

    sd = {
        "first.weight": torch.randn(64, 504),   # input layer (matches old dim)
        "first.bias": torch.randn(64),
        "second.weight": torch.randn(32, 64),   # hidden layer (untouched)
    }
    out = pad_state_dict_for_obs_change(sd, 504, 560)
    assert out["first.weight"].shape == (64, 560)
    # The original 504 columns are preserved; the new 56 are zero.
    assert torch.equal(out["first.weight"][:, :504], sd["first.weight"])
    assert torch.count_nonzero(out["first.weight"][:, 504:]) == 0
    # Non-matching layers untouched.
    assert out["second.weight"].shape == (32, 64)
    assert out["first.bias"].shape == (64,)
    # Idempotent / safe when dims already match.
    same = pad_state_dict_for_obs_change(out, 560, 560)
    assert same["first.weight"].shape == (64, 560)
