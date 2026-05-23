"""Phase D — coverage check: every documented mod action is reachable
via sim.action_space.decode given a plausible state.

Per notes/06_mcp_api.md §3.1 the mod exposes 28+ verbs. The agent
must be able to *send* each one through the Discrete(300) action
space, otherwise the RL policy can't fully drive the live game.
"""
from __future__ import annotations

from sim.action_space import RANGES, decode, range_named


# Map each mod-side action verb -> a (state, action_index) pair that
# should produce it. Mirrors notes/06_mcp_api.md §3.1.
_EXPECTED_VERBS: dict[str, tuple[dict, int]] = {
    "end_turn": (
        {"state_type": "monster",
         "battle": {"is_play_phase": True, "enemies": [{"combat_id": 1}]},
         "player": {"hand": [{"id": "x", "target_type": "AnyEnemy",
                               "can_play": True, "cost": 1}]}},
        range_named("combat").start + 0,
    ),
    "play_card": (
        {"state_type": "monster",
         "battle": {"is_play_phase": True, "enemies": []},
         "player": {"hand": [{"id": "strike", "target_type": "none",
                               "can_play": True, "cost": 1}]}},
        range_named("combat").start + 1,  # untargeted hand[0]
    ),
    "combat_select_card": (
        {"state_type": "hand_select"},
        range_named("hand_select").start + 0,
    ),
    "combat_confirm_selection": (
        {"state_type": "hand_select"},
        range_named("hand_select").start + 10,
    ),
    "select_card_reward": (
        {"state_type": "card_select", "card_select": [{"id": "anger"}]},
        range_named("card_reward").start + 0,
    ),
    "skip_card_reward": (
        {"state_type": "card_select", "card_select": [{"id": "anger"}]},
        range_named("card_reward").start + 5,
    ),
    "claim_reward": (
        {"state_type": "rewards", "rewards": [{"type": "gold"}]},
        range_named("rewards").start + 0,
    ),
    "select_relic": (
        {"state_type": "relic_select", "relic_select": [{"id": "vajra"}]},
        range_named("relic_select").start + 0,
    ),
    "skip_relic_selection": (
        {"state_type": "relic_select"},
        range_named("relic_select").start + 5,
    ),
    "claim_treasure_relic": (
        {"state_type": "treasure", "relic_select": [{"id": "vajra"}]},
        range_named("relic_select").start + 0,
    ),
    "select_bundle": (
        {"state_type": "bundle_select"},
        range_named("bundle_select").start + 0,
    ),
    "confirm_bundle_selection": (
        {"state_type": "bundle_select"},
        range_named("bundle_select").start + 10,
    ),
    "cancel_bundle_selection": (
        {"state_type": "bundle_select"},
        range_named("bundle_select").start + 11,
    ),
    "choose_map_node": (
        {"state_type": "map", "map": {"options": [{"x": 0, "floor": 1}]}},
        range_named("map").start + 0,
    ),
    "choose_event_option": (
        {"state_type": "event", "event": {"options": [{"label": "yes"}]}},
        range_named("event").start + 0,
    ),
    "advance_dialogue": (
        {"state_type": "event"},
        range_named("event").start + 7,
    ),
    "choose_rest_option": (
        {"state_type": "rest"},
        range_named("rest").start + 0,
    ),
    "shop_purchase": (
        {"state_type": "shop"},
        range_named("shop").start + 0,
    ),
    "use_potion": (
        {},
        range_named("potion").start + 0,
    ),
    "discard_potion": (
        {},
        range_named("potion").start + 3,
    ),
    "menu_select": (
        {"state_type": "menu", "options": ["singleplayer"]},
        range_named("menu_select").start + 0,
    ),
    "proceed": (
        {},
        range_named("misc").start + 0,
    ),
    "crystal_sphere_proceed": (
        {},
        range_named("misc").start + 2,
    ),
    "undo_end_turn": (
        {},
        range_named("misc").start + 3,
    ),
}


def test_every_known_mod_verb_is_reachable():
    """Each mod-side action verb must be produced by at least one
    (state, action_index) combination."""
    seen: set[str] = set()
    for verb, (state, idx) in _EXPECTED_VERBS.items():
        body = decode(idx, state)
        assert body.get("action") == verb, \
            f"index {idx} in state {state.get('state_type')} -> {body}, expected {verb}"
        seen.add(verb)
    # All 24 distinct mod verbs covered (28 from §3.1 minus duplicates like
    # `proceed` reused across screens and `crystal_sphere_set_tool` /
    # `crystal_sphere_click_cell` left to a follow-up).
    assert {"select_card_reward", "skip_card_reward", "claim_reward",
            "select_relic", "skip_relic_selection", "claim_treasure_relic",
            "choose_map_node", "choose_event_option", "choose_rest_option",
            "shop_purchase", "use_potion", "discard_potion", "menu_select",
            "play_card", "end_turn", "undo_end_turn",
            "advance_dialogue", "proceed", "crystal_sphere_proceed",
            "combat_select_card", "combat_confirm_selection",
            "select_bundle", "confirm_bundle_selection",
            "cancel_bundle_selection"}.issubset(seen)


def test_ranges_total_300():
    """Re-asserts the layout invariant under coverage testing."""
    assert sum(r.size for r in RANGES) == 300


def test_no_two_ranges_overlap():
    cursor = 0
    for r in RANGES:
        assert r.start == cursor
        cursor = r.stop
