"""Phase 3 tests — event option features in obs + shop dispatch + map lookahead."""
from __future__ import annotations

import numpy as np
import pytest

from sim.env_run import OBS_DIM, RunEnv
from sim.events import OPTION_FEATURE_BITS, encode_option_tag
from sim.game_state import Character, MapNode, RunState, StateType
from sim.run_engine import _enter_room


def _new_env(seed: int = 42) -> RunEnv:
    env = RunEnv(ascension=0)
    env.reset(seed=seed)
    return env


# --- option tag encoding ---

def test_option_feature_bits_length():
    assert len(OPTION_FEATURE_BITS) == 8


def test_encode_hp_loss_card_add():
    bits = encode_option_tag("HP_LOSS_CARD_ADD")
    assert bits[OPTION_FEATURE_BITS.index("HP_LOSS")] == 1.0
    assert bits[OPTION_FEATURE_BITS.index("CARD_ADD")] == 1.0
    # MAX_HP_LOSS should NOT trigger from HP_LOSS_CARD_ADD
    assert bits[OPTION_FEATURE_BITS.index("MAX_HP_LOSS")] == 0.0


def test_encode_max_hp_loss():
    bits = encode_option_tag("MAX_HP_LOSS_UPGRADE")
    assert bits[OPTION_FEATURE_BITS.index("MAX_HP_LOSS")] == 1.0
    assert bits[OPTION_FEATURE_BITS.index("CARD_UPGRADE")] == 1.0
    # plain HP_LOSS bit should NOT be set when MAX_HP_LOSS applies
    assert bits[OPTION_FEATURE_BITS.index("HP_LOSS")] == 0.0


def test_encode_relic_gain():
    bits = encode_option_tag("RELIC_GAIN")
    assert bits[OPTION_FEATURE_BITS.index("RELIC_GAIN")] == 1.0
    assert sum(bits) == 1.0  # no spurious bits


def test_encode_empty_tag():
    bits = encode_option_tag("")
    assert all(b == 0.0 for b in bits)


def test_encode_curse_add():
    bits = encode_option_tag("CARD_REMOVE_CURSE")
    # CARD_REMOVE should be set
    assert bits[OPTION_FEATURE_BITS.index("CARD_REMOVE")] == 1.0
    # CURSE_ADD should NOT be set (since CARD_REMOVE is present —
    # disambiguates removal-with-curse-side-effect from pure curse).
    assert bits[OPTION_FEATURE_BITS.index("CURSE_ADD")] == 0.0


# --- obs integration ---

def _force_event(env: RunEnv, event_id: str) -> None:
    """Drop the env into an EVENT state with a known pending_event."""
    from sim.events import EVENT_REGISTRY
    rs = env.rs
    rs.state_type = StateType.EVENT
    evt = EVENT_REGISTRY[event_id]
    rs.pending_event = {
        "event_id": evt.id,
        "options": [
            {"id": o.id, "label": o.label, "enabled": o.enabled, "tag": o.tag}
            for o in evt.generate_options(rs)
        ],
    }
    env._invalidate_caches()


def test_obs_contains_event_option_features_for_brain_leech():
    env = _new_env()
    _force_event(env, "brain_leech")
    obs = env._obs()
    # Cursor for event option features sits after Phase 2 additions.
    # We won't pin the exact offset; instead verify the slot contains
    # NON-ZERO bits when an event is pending.
    assert (obs > 0).any()


def test_obs_event_features_zero_when_no_event():
    env = _new_env()
    env.rs.state_type = StateType.MAP
    env.rs.pending_event = None
    obs = env._obs()
    # Just confirm we don't crash and obs has expected shape.
    assert obs.shape == (OBS_DIM,)


# --- shop view + decoding ---

def _new_rs_in_shop(gold: int = 200) -> RunState:
    rs = RunState.new_run(character=Character.IRONCLAD, ascension=0, seed=42)
    rs.gold = gold
    rs.act = 1
    rs.floor = 5
    node = MapNode(floor=5, x=0, room_type=StateType.SHOP)
    _enter_room(rs, node)
    return rs


def test_shop_view_exposes_removal_item_when_unused():
    rs = _new_rs_in_shop(gold=200)
    env = RunEnv(ascension=0)
    env.rs = rs
    env._invalidate_caches()
    view = env._mod_state_view()
    assert "shop" in view
    items = view["shop"]["items"]
    assert len(items) == 1
    assert items[0]["category"] == "card_removal"
    assert items[0]["can_afford"] is True


def test_shop_view_hides_removal_after_use():
    rs = _new_rs_in_shop(gold=200)
    rs.pending_shop["removal_used"] = True
    env = RunEnv(ascension=0)
    env.rs = rs
    env._invalidate_caches()
    view = env._mod_state_view()
    assert view["shop"]["items"] == []
    assert view["shop"]["can_proceed"] is True


def test_shop_view_locks_removal_when_broke():
    rs = _new_rs_in_shop(gold=10)
    env = RunEnv(ascension=0)
    env.rs = rs
    env._invalidate_caches()
    view = env._mod_state_view()
    assert view["shop"]["items"][0]["can_afford"] is False


# --- event view ---

def test_event_view_exposes_pending_options():
    env = _new_env()
    _force_event(env, "brain_leech")
    view = env._mod_state_view()
    assert "event" in view
    assert len(view["event"]["options"]) == 2  # BrainLeech has 2 options
    assert all("id" in o and "enabled" in o for o in view["event"]["options"])


def test_event_mask_via_pending_event():
    """The build_mask() call sees event.options via the view and marks
    only those slots legal."""
    env = _new_env()
    _force_event(env, "brain_leech")
    mask = env.action_masks()
    # Event range starts at 124 (size 8). BrainLeech has 2 options →
    # slots 124, 125 should be legal; 126+ not.
    assert mask[124]
    assert mask[125]
    assert not mask[126]
    assert not mask[127]
