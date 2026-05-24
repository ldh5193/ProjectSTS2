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
        # The live mod emits `rest_site` (see McpMod.StateBuilder.cs); the
        # legacy `rest` value is kept for back-compat with older tests.
        state_types=("rest", "rest_site"),
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
        # Empty state_types tuple = always considered eligible. The
        # _misc_mask predicate is what decides if proceed/advance-dialogue
        # is actually legal in the current state.
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


# Precomputed idx → ActionRange map. find_range() is called once per env step
# (and many times per episode), so the linear scan over 16 ranges is replaced
# with an O(1) lookup. The list spans the full Discrete(300) space; an entry
# is None for the "reserved" tail so callers still see the same None result.
_RANGE_BY_INDEX: tuple[ActionRange | None, ...] = tuple(
    next((r for r in RANGES if r.contains(i)), None)
    for i in range(N_ACTIONS)
)


def find_range(idx: int) -> ActionRange | None:
    if 0 <= idx < N_ACTIONS:
        return _RANGE_BY_INDEX[idx]
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


def _event_mask(state: dict, r: ActionRange) -> Iterable[int]:
    """Event mask: mod exposes options inside `event.options` (not top-level)."""
    event = state.get("event") or {}
    opts = event.get("options") or state.get("event") or []
    return range(min(len(opts), r.size))


def _rewards_mask(state: dict, r: ActionRange) -> Iterable[int]:
    """Multi-reward screen: mod nests `items` under `rewards` dict and
    flips `can_proceed` when nothing left to claim. We expose the
    claim slots here; the proceed-after-empty case is handled by
    _misc_mask."""
    rewards = state.get("rewards")
    if isinstance(rewards, dict):
        items = rewards.get("items") or []
    elif isinstance(rewards, list):
        items = rewards
    else:
        items = []
    return range(min(len(items), r.size))


def _misc_mask(state: dict, r: ActionRange) -> Iterable[int]:
    """Misc range covers proceed/advance-dialogue/etc. We activate
    `proceed` (local 0) whenever the live mod state has stalled with
    an explicit can_proceed flag (rewards screen with empty items,
    event in_dialogue, etc.)."""
    st = state.get("state_type")
    # Fast path: in the overwhelming majority of frames (combat/map/menu/...)
    # neither sub-predicate fires. Short-circuit before the dict lookups so
    # build_mask spends no time on misc unless misc could matter.
    if st not in ("rewards", "event"):
        return ()
    if st == "rewards":
        rewards = state.get("rewards")
        if isinstance(rewards, dict) \
                and rewards.get("can_proceed") and not (rewards.get("items") or []):
            return (0,)  # proceed
        return ()
    # st == "event"
    event = state.get("event") or {}
    if event.get("in_dialogue"):
        return (1,)  # advance_dialogue
    return ()


def _card_reward_mask(state: dict, r: ActionRange) -> Iterable[int]:
    """Card-reward mask: mod nests cards under `card_reward.cards`.
    Also allow the `card_select` top-level list shape as a fallback.
    Index r.size - 1 is the skip slot (covered by predicate only if
    can_skip=true).
    """
    reward = state.get("card_reward") or {}
    cards = reward.get("cards") if isinstance(reward, dict) else None
    if not cards:
        cards = state.get("card_select") or []
    picks = list(range(min(len(cards), r.size - 1)))
    # Skip slot is at local index 5 in our 6-wide range; mod only allows
    # skipping when can_skip is true.
    if isinstance(reward, dict) and reward.get("can_skip"):
        picks.append(r.size - 1)
    return picks


def _hand_select_mask(state: dict, r: ActionRange) -> Iterable[int]:
    """hand_select fires when a card/relic effect prompts the player to pick
    N cards from the current hand (Headbutt, Burn, Discovery, etc). Without
    a predicate the mask is empty and the agent stalls on the overlay
    forever — observed in-game with `[STS2 MCP][AUTO] idle: hand_select:
    0 legal actions in mask`. Each hand slot is a toggle; the last slot
    (local r.size - 1 == 10) is confirm_selection.
    """
    hand = ((state.get("player") or {}).get("hand")) or []
    picks = list(range(min(len(hand), r.size - 1)))
    picks.append(r.size - 1)  # combat_confirm_selection is always available
    return picks


def _rest_mask(state: dict, r: ActionRange) -> Iterable[int]:
    """rest_site exposes options[] with per-option `index` and `is_enabled`.
    Smith/dig/key/lift are disabled unless the per-run prereqs are met,
    so the mask must follow `is_enabled` to keep the policy from picking
    a button the game would reject. Mirrors C# MaskBuilder.RestMask."""
    rs = state.get("rest_site") or {}
    opts = rs.get("options") or []
    yielded: list[int] = []
    for o in opts:
        if not isinstance(o, dict):
            continue
        if o.get("is_enabled"):
            idx = int(o.get("index", len(yielded)))
            if 0 <= idx < r.size:
                yielded.append(idx)
    return yielded


_PREDICATES: dict[str, MaskPredicate] = {
    "combat": _combat_mask,
    "hand_select": _hand_select_mask,
    "card_reward": _card_reward_mask,
    "rewards": _rewards_mask,
    "rest": _rest_mask,
    "misc": _misc_mask,
    "relic_select": _by_visible_options("relic_select"),
    "map": lambda state, r: range(min(
        len((state.get("map") or {}).get("next_options")
            or (state.get("map") or {}).get("options") or []),
        r.size)),
    "event": _event_mask,
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
        # Mod expects target as the enemy's *string* entity_id, not the
        # numeric combat_id. Fall back to combat_id only if entity_id
        # is missing (older mod versions / test fixtures).
        enemy = enemies[enemy_slot]
        target = enemy.get("entity_id") or str(enemy.get("combat_id", ""))
        return {
            "action": "play_card",
            "card_index": card_slot,
            "target": target,
        }

    if r.name == "card_reward":
        if local == 5:
            return {"action": "skip_card_reward"}
        return {"action": "select_card_reward", "card_index": local}

    if r.name == "rewards":
        return {"action": "claim_reward", "index": local}

    if r.name == "relic_select":
        if local == 5:
            return {"action": "skip_relic_selection"}
        # Treasure rooms use claim_treasure_relic; ordinary relic picks
        # (event-spawned, boss-relic style) use select_relic.
        if state.get("state_type") == "treasure":
            return {"action": "claim_treasure_relic", "index": local}
        return {"action": "select_relic", "index": local}

    if r.name == "map":
        return {"action": "choose_map_node", "index": local}

    if r.name == "event":
        if local == 7:
            return {"action": "advance_dialogue"}
        return {"action": "choose_event_option", "index": local}

    if r.name == "rest":
        return {"action": "choose_rest_option", "index": local}

    if r.name == "shop":
        if local == 15:
            return {"action": "proceed"}
        return {"action": "shop_purchase", "index": local}

    if r.name == "potion":
        if local < 3:
            return {"action": "use_potion", "slot": local}
        if local < 6:
            return {"action": "discard_potion", "slot": local - 3}
        return {"action": "invalid", "reason": "potion slot reserved"}

    if r.name == "hand_select":
        if local == 10:
            return {"action": "combat_confirm_selection"}
        return {"action": "combat_select_card", "card_index": local}

    if r.name == "bundle_select":
        if local == 10:
            return {"action": "confirm_bundle_selection"}
        if local == 11:
            return {"action": "cancel_bundle_selection"}
        return {"action": "select_bundle", "index": local}

    if r.name == "select_card":
        if local == 10:
            return {"action": "confirm_selection"}
        if local == 11:
            return {"action": "cancel_selection"}
        return {"action": "select_card", "index": local}

    if r.name == "crystal_sphere":
        if local < 8:
            tools = ["red", "orange", "yellow", "green",
                     "blue", "purple", "rainbow", "reset"]
            return {"action": "crystal_sphere_set_tool", "tool": tools[local]}
        cell = local - 8
        return {"action": "crystal_sphere_click_cell",
                "coord": {"row": cell // 6, "col": cell % 6}}

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
