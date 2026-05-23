"""Discrete(300) full-game action space for RL.

Project plan §3.2's Discrete(61) only covers in-combat play. The mod
exposes 28 actions across menu, map, combat, rewards, events, rest,
treasure, and crystal-sphere overlays (notes/06_mcp_api.md §3.1).
This module pins down a single flat Discrete(300) encoding so the env
wrapper and the validator agree on what each index means.

Layout: a list of contiguous, non-overlapping ranges. Each range owns
one logical sub-space (combat, card-reward pick, map node, etc.).
Outside any range, the action is invalid by construction; the action
mask is derived from `state_type` plus a sub-space-specific predicate
(e.g. how many enemies are alive, how many reward cards are visible).

Why flat rather than gym.spaces.Dict?
- MaskablePPO already handles Discrete + mask cleanly; Dict would
  require a custom policy.
- The mod's POST endpoint is one action at a time, so the env step
  also takes one action at a time. A single discrete index is the
  most direct fit.

The cost is a bigger but mostly-masked output head: the mask is the
critical piece for both training stability and call-site validity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class ActionRange:
    """A contiguous slice of the action space."""
    name: str
    start: int
    size: int
    # state_types this range is *potentially* legal in. Empty = always legal
    # (used for proceed/menu_select-style helpers).
    state_types: tuple[str, ...] = ()
    # Short docstring shown in dump/help.
    doc: str = ""

    @property
    def stop(self) -> int:
        return self.start + self.size

    def contains(self, idx: int) -> bool:
        return self.start <= idx < self.stop

    def offset(self, idx: int) -> int:
        if not self.contains(idx):
            raise IndexError(f"{idx} not in range {self.name} [{self.start}, {self.stop})")
        return idx - self.start


# Layout — keep these in this exact order so consumers can slice by name.
# Total size = 300. If a future endpoint grows past its slot, prefer adding
# a new range at the end rather than reshuffling indices, so trained
# checkpoints stay compatible.

RANGES: tuple[ActionRange, ...] = (
    ActionRange(
        "combat", 0, 61,
        state_types=("monster", "elite", "boss"),
        doc="0=end_turn; 1..10=play_card(idx) untargeted; "
            "11..60=play_card(idx, enemy) for 10 slots * 5 enemies.",
    ),
    ActionRange(
        "hand_select", 61, 11,
        state_types=("hand_select",),
        doc="0..9=combat_select_card(idx); 10=combat_confirm_selection.",
    ),
    ActionRange(
        "card_reward", 72, 6,
        state_types=("card_select", "card_reward"),
        doc="0..4=select_card_reward(idx); 5=skip_card_reward.",
    ),
    ActionRange(
        "rewards", 78, 8,
        state_types=("rewards",),
        doc="0..7=claim_reward(idx). Slot count varies; mask the unused tail.",
    ),
    ActionRange(
        "relic_select", 86, 6,
        state_types=("relic_select",),
        doc="0..4=select_relic(idx) or claim_treasure_relic(idx); "
            "5=skip_relic_selection.",
    ),
    ActionRange(
        "bundle_select", 92, 12,
        state_types=("bundle_select",),
        doc="0..9=select_bundle(idx); 10=confirm_bundle_selection; "
            "11=cancel_bundle_selection.",
    ),
    ActionRange(
        "map", 104, 20,
        state_types=("map",),
        doc="choose_map_node by ordered visible-node index. 20 slots is "
            "well above the act-1 fanout; the mask reflects state.map.options.",
    ),
    ActionRange(
        "event", 124, 8,
        state_types=("event", "fake_merchant"),
        doc="0..6=choose_event_option(idx); 7=advance_dialogue.",
    ),
    ActionRange(
        "rest", 132, 6,
        state_types=("rest",),
        doc="choose_rest_option: 0=rest, 1=upgrade, 2=shop, 3=dig, 4=key, 5=lift.",
    ),
    ActionRange(
        "shop", 138, 16,
        state_types=("shop",),
        doc="0..14=shop_purchase(item_index); 15=leave (proceed).",
    ),
    ActionRange(
        "potion", 154, 8,
        state_types=(),  # potions are usable in combat AND on map; mask via state
        doc="0..2=use_potion(slot); 3..5=discard_potion(slot); "
            "6..7=reserved.",
    ),
    ActionRange(
        "crystal_sphere", 162, 32,
        state_types=("crystal_sphere",),
        doc="0..7=crystal_sphere_set_tool(tool_id); 8..31=crystal_sphere_click_cell "
            "in a 4x6 grid (row-major); crystal_sphere_proceed lives in 'misc'.",
    ),
    ActionRange(
        "select_card", 194, 12,
        state_types=("card_select",),
        doc="0..9=select_card(idx); 10=confirm_selection; 11=cancel_selection.",
    ),
    ActionRange(
        "menu_select", 206, 32,
        state_types=("menu",),
        doc="Menu options (character ids, mode names, confirm/back/yes/no). "
            "The decoder needs the live menu_screen + options[] to map "
            "an index back to a string; reserve enough headroom for FTUE.",
    ),
    ActionRange(
        "misc", 238, 8,
        state_types=(),
        doc="0=proceed; 1=advance_dialogue; 2=crystal_sphere_proceed; "
            "3=undo_end_turn (MP only); 4..7=reserved.",
    ),
    ActionRange(
        "reserved", 246, 54,
        state_types=(),
        doc="Headroom for future endpoints. Always masked off.",
    ),
)


N_ACTIONS = sum(r.size for r in RANGES)
assert N_ACTIONS == 300, f"Discrete(300) layout drift: total={N_ACTIONS}"


_BY_NAME: dict[str, ActionRange] = {r.name: r for r in RANGES}


def range_named(name: str) -> ActionRange:
    return _BY_NAME[name]


def find_range(idx: int) -> ActionRange | None:
    for r in RANGES:
        if r.contains(idx):
            return r
    return None


# ---------------------------------------------------------------------------
# Mask
# ---------------------------------------------------------------------------

# (state_type, range_name) -> predicate(state_json, range) -> Iterable[int] of LOCAL indices
MaskPredicate = Callable[[dict, ActionRange], Iterable[int]]


def _combat_mask(state: dict, r: ActionRange) -> Iterable[int]:
    battle = state.get("battle") or {}
    if not battle.get("is_play_phase"):
        return []
    hand = (state.get("player") or {}).get("hand") or []
    enemies = battle.get("enemies") or []
    yielded: list[int] = [0]  # end_turn
    for i, card in enumerate(hand[:10]):
        if not card.get("can_play"):
            continue
        ttype = (card.get("target_type") or "").lower()
        if ttype in ("none", "self"):
            yielded.append(1 + i)
        else:
            for j, _enemy in enumerate(enemies[:5]):
                yielded.append(11 + i * 5 + j)
    return yielded


def _by_visible_options(key: str) -> MaskPredicate:
    def f(state: dict, r: ActionRange) -> Iterable[int]:
        opts = state.get(key) or []
        return range(min(len(opts), r.size))
    return f


_PREDICATES: dict[str, MaskPredicate] = {
    "combat": _combat_mask,
    "card_reward": _by_visible_options("card_select"),
    "rewards": _by_visible_options("rewards"),
    "relic_select": _by_visible_options("relic_select"),
    "map": lambda state, r: range(min(len((state.get("map") or {}).get("options") or []), r.size)),
    "event": _by_visible_options("event"),
    "menu_select": _by_visible_options("options"),
}


def build_mask(state: dict) -> list[bool]:
    """Return a boolean mask of length N_ACTIONS marking legal actions
    for the given live mod state. Conservative: anything we don't know
    how to enumerate yet stays masked off.
    """
    mask = [False] * N_ACTIONS
    state_type = state.get("state_type")
    for r in RANGES:
        if r.state_types and state_type not in r.state_types:
            continue
        pred = _PREDICATES.get(r.name)
        if pred is None:
            continue
        for local in pred(state, r):
            if 0 <= local < r.size:
                mask[r.start + local] = True
    return mask


# ---------------------------------------------------------------------------
# Decode: index -> mod-API body
# ---------------------------------------------------------------------------


def decode(idx: int, state: dict) -> dict:
    """Map a Discrete(300) index to the JSON body the mod POST expects.

    The state is used for context (enemy ids for targeting, option strings
    for menu_select). Returns ``{"action": "invalid", "reason": "..."}``
    if the index isn't legal in the current state — callers should mask
    before reaching this.
    """
    r = find_range(idx)
    if r is None:
        return {"action": "invalid", "reason": f"index {idx} out of range"}
    local = idx - r.start

    if r.name == "combat":
        if local == 0:
            return {"action": "end_turn"}
        if 1 <= local <= 10:
            return {"action": "play_card", "card_index": local - 1}
        offset = local - 11
        card_slot, enemy_slot = divmod(offset, 5)
        enemies = (state.get("battle") or {}).get("enemies") or []
        if enemy_slot >= len(enemies):
            return {"action": "invalid", "reason": "enemy slot vacant"}
        return {
            "action": "play_card",
            "card_index": card_slot,
            "target": enemies[enemy_slot].get("combat_id") or enemies[enemy_slot].get("entity_id"),
        }

    if r.name == "card_reward":
        if local == 5:
            return {"action": "skip_card_reward"}
        return {"action": "select_card_reward", "card_index": local}

    if r.name == "rewards":
        return {"action": "claim_reward", "reward_index": local}

    if r.name == "relic_select":
        if local == 5:
            return {"action": "skip_relic_selection"}
        # Treasure rooms use claim_treasure_relic; ordinary relic picks use
        # select_relic. Disambiguate by state.relic_select source if needed;
        # default to select_relic.
        return {"action": "select_relic", "relic_index": local}

    if r.name == "map":
        return {"action": "choose_map_node", "node_index": local}

    if r.name == "event":
        if local == 7:
            return {"action": "advance_dialogue"}
        return {"action": "choose_event_option", "option": local}

    if r.name == "rest":
        opts = ["rest", "upgrade", "shop", "dig", "key", "lift"]
        return {"action": "choose_rest_option", "option": opts[local]}

    if r.name == "shop":
        if local == 15:
            return {"action": "proceed"}
        return {"action": "shop_purchase", "item_index": local}

    if r.name == "potion":
        if local < 3:
            return {"action": "use_potion", "slot": local}
        if local < 6:
            return {"action": "discard_potion", "slot": local - 3}
        return {"action": "invalid", "reason": "potion slot reserved"}

    if r.name == "menu_select":
        opts = state.get("options") or []
        if local >= len(opts):
            return {"action": "invalid", "reason": "menu option out of range"}
        return {"action": "menu_select", "option": opts[local]}

    if r.name == "misc":
        misc = ["proceed", "advance_dialogue", "crystal_sphere_proceed",
                "undo_end_turn"]
        if local < len(misc):
            return {"action": misc[local]}
        return {"action": "invalid", "reason": "misc reserved"}

    return {"action": "invalid", "reason": f"range {r.name!r} decode not implemented"}
