"""Phase 7F+G tests for the per-item SHOP observation block.

The 5-dim shop summary only exposed coarse affordable-item COUNTS, so a
learned shop bought near-blindly. This block exposes per-item detail
(card features, prices, affordability) so the agent can decide WHAT to
buy. These tests pin:

  - obs length == new OBS_DIM (504)
  - in a stocked shop the shop-card block is non-zero and reflects an
    offered card's features
  - non-shop states leave the whole shop block zero
"""
from __future__ import annotations

import numpy as np

from sim.card_catalog import CARD_FEATURE_DIM, card_features
from sim.env_run import OBS_DIM, OBS_DIM_V4_4, RunEnv
from sim.game_state import Character, MapNode, RunState, StateType
from sim.run_engine import _enter_room


# Block geometry must match sim/env_run.py _obs().
_SHOP_CARD_SLOTS = 6
_SHOP_RELIC_SLOTS = 4
_SHOP_POTION_SLOTS = 2
_SHOP_CARD_DIM = CARD_FEATURE_DIM + 3        # 15
_SHOP_RELIC_DIM = 6
_SHOP_POTION_DIM = 2
_SHOP_PAD = 5
_SHOP_BLOCK = (_SHOP_CARD_SLOTS * _SHOP_CARD_DIM
               + _SHOP_RELIC_SLOTS * _SHOP_RELIC_DIM
               + _SHOP_POTION_SLOTS * _SHOP_POTION_DIM
               + _SHOP_PAD)                  # + pad
# The shop block ends at the v4.4 prefix length (504), not OBS_DIM. Phase 9.0
# appended the obs v5 char/orb/star tail AFTER 504, leaving the shop block at
# the same absolute indices.
_CARD_BASE = OBS_DIM_V4_4 - _SHOP_BLOCK      # 504 - 123 = 381
_RELIC_BASE = _CARD_BASE + _SHOP_CARD_SLOTS * _SHOP_CARD_DIM   # 471
_POTION_BASE = _RELIC_BASE + _SHOP_RELIC_SLOTS * _SHOP_RELIC_DIM  # 495


def _env_in_shop(gold: int = 1000, seed: int = 42) -> RunEnv:
    env = RunEnv(ascension=0)
    env.reset(seed=seed)
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=seed)
    rs.gold = gold
    rs.act = 1
    rs.floor = 5
    node = MapNode(floor=5, x=0, room_type=StateType.SHOP)
    _enter_room(rs, node)
    env.rs = rs
    env._invalidate_caches()
    return env


def test_obs_dim_is_504():
    # Phase 9.0: OBS_DIM is now 560 (obs v5); the v4.4 prefix is 504.
    assert OBS_DIM == 560
    assert OBS_DIM_V4_4 == 504
    env = RunEnv(ascension=0)
    obs, _ = env.reset(seed=1)
    assert obs.shape == (560,)


def test_shop_card_block_nonzero_and_matches_offer():
    env = _env_in_shop(gold=1000)
    assert env.rs.state_type is StateType.SHOP
    obs = env._obs()
    assert obs.shape == (OBS_DIM,)

    # The shop block as a whole must carry signal in a stocked shop.
    block = obs[_CARD_BASE:]
    assert np.any(block != 0.0), "shop block all-zero in a stocked shop"

    # Slot 0 must mirror the first offered card's features + price/afford.
    items = env.rs.pending_shop["items"]
    first_card = next(it for it in items if it["category"] == "card")
    feats = card_features(first_card["card_id"])
    base = _CARD_BASE
    # First 12 dims == card_features (clipped to [0,1] like the obs).
    expected = np.clip(np.asarray(feats, dtype=np.float32), 0.0, 1.0)
    np.testing.assert_allclose(obs[base:base + CARD_FEATURE_DIM], expected,
                               rtol=0, atol=1e-6)
    # price/200, can_afford, is_stocked
    assert obs[base + CARD_FEATURE_DIM + 0] == min(1.0, first_card["price"] / 200.0)
    assert obs[base + CARD_FEATURE_DIM + 1] == (1.0 if first_card["can_afford"] else 0.0)
    assert obs[base + CARD_FEATURE_DIM + 2] == 1.0  # freshly stocked


def test_shop_relic_and_potion_blocks_populated():
    env = _env_in_shop(gold=1000)
    obs = env._obs()
    items = env.rs.pending_shop["items"]

    relics = [it for it in items if it["category"] == "relic"]
    if relics:
        base = _RELIC_BASE
        # is_stocked flag (last of the 6) of slot 0 must be set.
        assert obs[base + 5] == 1.0
        # rarity rank in [0,1].
        assert 0.0 <= obs[base + 2] <= 1.0

    potions = [it for it in items if it["category"] == "potion"]
    if potions:
        base = _POTION_BASE
        assert obs[base + 0] == 1.0  # present


def test_non_shop_state_leaves_shop_block_zero():
    # Fresh reset lands on a map/combat-ish state, never SHOP.
    env = RunEnv(ascension=0)
    obs, _ = env.reset(seed=7)
    assert env.rs.state_type is not StateType.SHOP
    # Bound the slice to the v4.4 prefix (504): the obs v5 tail past 504 holds
    # the character one-hot, which is legitimately nonzero (Ironclad bit set).
    block = obs[_CARD_BASE:OBS_DIM_V4_4]
    assert np.count_nonzero(block) == 0, "shop block nonzero outside a shop"
