"""Run engine — drives RunState transitions in response to decoded actions.

This module ties together combat, map traversal, rewards, and room
overlays into a single `step(rs, action_body)` entry point used by the
Gymnasium env wrapper (sim/env_run.py).

Scope of first slice:
- Single character (Ironclad), single act path (Overgrowth).
- Combat rooms only enter sim.combat for modeled encounters; placeholder
  ones auto-resolve.
- Card reward overlay after each combat.
- Map navigation: agent picks one of the reachable next-floor nodes.
- Event/shop/rest/treasure rooms collapse to minimal effects so the run
  loop reaches the boss. They become richer in follow-up commits.
- A0..A10 supported by the data model; only AscensionManager's
  start-of-run effects + the per-monster damage tweaks the decompile
  already gates are applied.

For action shapes, see notes/06_mcp_api.md §3 + sim/action_space.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .card_catalog import CARDS
from .combat import CombatState, HAND_SIZE
from .dsl import CardDef
from .encounter import EncounterPools, build_monster_for, generate_pools
from .game_state import MapNode, RunMap, RunState, StateType
from .map_gen import generate_act_map
from .relics import (
    trigger_after_combat_victory,
    trigger_after_room_entered,
    trigger_on_combat_start,
    trigger_on_player_turn_start,
)
from .rewards import RarityRoller, generate_card_reward


@dataclass
class StepResult:
    """Per-step bookkeeping for reward shaping in env_run."""
    floor_advanced: bool = False
    combat_won: bool = False
    combat_lost: bool = False
    boss_killed: bool = False
    act_completed: bool = False
    run_completed: bool = False
    invalid_action: bool = False
    reason: str = ""


_ACT_ORDER = ("overgrowth", "hive", "glory")  # Single-path run (Underdocks variant ignored).


def start_run(rs: RunState) -> None:
    """After RunState.new_run, advance from MENU into the first map.
    Auto-skips character-select and ancient because those aren't part
    of the first-slice action space yet — RL focuses on map+combat first.
    """
    if rs.state_type is not StateType.MENU:
        return
    _generate_act(rs, _ACT_ORDER[0])
    rs.state_type = StateType.MAP
    rs.floor = 0
    rs.current_node = (0, 0)


def _generate_act(rs: RunState, act_key: str) -> None:
    """Build encounter pools + map for the act and store them on the
    RunState. RunState exposes rs.maps[act-1] for the env's observation."""
    map_rng = _act_rng(rs, act_key)
    encounter_rng = _encounter_rng(rs)
    is_final_act = (act_key == _ACT_ORDER[-1])
    pools = generate_pools(act_key, encounter_rng,
                           ascension=int(rs.ascension),
                           is_final_act=is_final_act)
    rmap = generate_act_map(act_key, map_rng, ascension=int(rs.ascension))
    rs.maps[_act_index(act_key) - 1] = rmap
    rs.act = _act_index(act_key)
    # Stash pools on the RunState via a sidecar attribute (avoid changing
    # the dataclass surface for now).
    setattr(rs, "_pools", pools)


def _act_rng(rs: RunState, act_key: str):
    """Per-act isolated map RNG, mirroring StandardActMap.cs:95."""
    from .rng import Rng, get_deterministic_hash_code
    return Rng(rs.run_seed, f"act_{_act_index(act_key)}_map")


def _encounter_rng(rs: RunState):
    """Run's main Rng used for the encounter GrabBag."""
    from .rng import Rng
    return Rng(rs.run_seed, f"act_{rs.act or 1}_encounters")


def _act_index(act_key: str) -> int:
    return _ACT_ORDER.index(act_key) + 1


def reachable_map_nodes(rs: RunState) -> list[MapNode]:
    """Return the list of map nodes the agent can transition into.

    Floor 0 (pre-map) allows entering any floor-1 node; otherwise the
    current node's `children` list is consulted.
    """
    rmap = rs.maps[rs.act - 1]
    if rmap is None:
        return []
    if rs.floor == 0:
        return list(rmap.floors[0])
    floor, x = rs.current_node
    if floor < 1 or floor > rmap.boss_floor:
        return []
    if floor == rmap.boss_floor:
        return []
    node = rmap.floors[floor - 1][x] if x < len(rmap.floors[floor - 1]) else None
    if node is None:
        return []
    return [rmap.floors[f - 1][nx] for (f, nx) in node.children
            if f - 1 < len(rmap.floors) and nx < len(rmap.floors[f - 1])]


def step(rs: RunState, body: dict) -> StepResult:
    """Apply one decoded action to the RunState. Returns a StepResult
    so the env can shape rewards. Idempotent for invalid actions —
    callers should mask before invoking.
    """
    res = StepResult()
    action = body.get("action")

    if rs.is_terminal():
        res.invalid_action = True
        res.reason = "run already terminal"
        return res

    if rs.state_type is StateType.MAP:
        return _step_map(rs, body, res)
    if rs.in_combat():
        return _step_combat(rs, body, res)
    if rs.state_type in (StateType.CARD_REWARD, StateType.CARD_SELECT):
        return _step_card_reward(rs, body, res)
    if rs.state_type is StateType.REST:
        return _step_rest(rs, body, res)
    if rs.state_type is StateType.TREASURE:
        return _step_treasure(rs, body, res)
    if rs.state_type is StateType.EVENT:
        return _step_event(rs, body, res)
    if rs.state_type is StateType.SHOP:
        return _step_shop(rs, body, res)

    res.invalid_action = True
    res.reason = f"unhandled state_type {rs.state_type.value}"
    return res


# --- per-state dispatch -----------------------------------------------------


def _step_map(rs: RunState, body: dict, res: StepResult) -> StepResult:
    if body.get("action") != "choose_map_node":
        res.invalid_action = True
        res.reason = "expected choose_map_node"
        return res
    options = reachable_map_nodes(rs)
    idx = body.get("node_index")
    if idx is None or idx < 0 or idx >= len(options):
        res.invalid_action = True
        res.reason = f"node_index {idx} out of range (have {len(options)})"
        return res
    node = options[idx]
    rs.floor = node.floor
    rs.current_node = (node.floor, node.x)
    _enter_room(rs, node)
    res.floor_advanced = True
    return res


def _enter_room(rs: RunState, node: MapNode) -> None:
    """Translate a node's room_type into the corresponding StateType and
    initialize any room-specific overlay payload."""
    rt = node.room_type
    if rt is StateType.MONSTER:
        rs.state_type = StateType.MONSTER
        eid = rs._pools.next_normal()
        _start_combat(rs, eid)
    elif rt is StateType.ELITE:
        rs.state_type = StateType.ELITE
        eid = rs._pools.next_elite()
        _start_combat(rs, eid)
    elif rt is StateType.BOSS:
        rs.state_type = StateType.BOSS
        eid = rs._pools.next_boss()
        _start_combat(rs, eid)
    elif rt is StateType.REST:
        # Stub: auto-rest (30% max HP heal) and bounce back to MAP so the
        # agent doesn't get stuck on the rest screen. Full rest UI lands
        # once smith/upgrade flows are real.
        rs.state_type = StateType.REST
        trigger_after_room_entered(rs, rs.state_type)
        rs.heal(int(rs.max_hp * 0.30))
        rs.state_type = StateType.MAP
        return
    elif rt is StateType.TREASURE:
        # Stub: auto-grant a placeholder treasure relic, return to MAP.
        from .game_state import RelicInstance
        rs.state_type = StateType.TREASURE
        trigger_after_room_entered(rs, rs.state_type)
        rs.relics.append(RelicInstance(id="UNKNOWN_TREASURE_RELIC"))
        rs.state_type = StateType.MAP
        return
    elif rt is StateType.SHOP:
        # Stub: skip shop until shop content + pricing is real.
        rs.state_type = StateType.SHOP
        trigger_after_room_entered(rs, rs.state_type)
        rs.state_type = StateType.MAP
        return
    elif rt is StateType.EVENT:
        # Stub: events have no real options yet; auto-skip with small heal
        # so the agent has a non-zero reason to choose ?-rooms (gold/HP
        # tradeoffs land once events are real).
        rs.state_type = StateType.EVENT
        trigger_after_room_entered(rs, rs.state_type)
        rs.heal(2)
        rs.state_type = StateType.MAP
        return
    else:
        # Ancient / unknown fallthrough: treat as proceed.
        rs.state_type = StateType.MAP
    # After the state_type is finalized, fire relic on-room-entered hooks
    # (MealTicket on rest, Pantograph on boss, ...).
    trigger_after_room_entered(rs, rs.state_type)


def _start_combat(rs: RunState, encounter_id: str) -> None:
    """Build a CombatState and attach it to the RunState."""
    from .rng import Rng
    combat_rng = Rng(rs.run_seed, f"combat_{rs.act}_{rs.floor}")
    monster = build_monster_for(encounter_id, combat_rng)
    # Construct a CombatState that mirrors the player's current persistent state.
    from .combat import CombatState, HAND_SIZE as _HS
    cs = CombatState.new_combat(seed=rs.run_seed ^ (rs.floor * 17),
                                monster_factory=lambda _r: monster)
    # Replace the auto-generated player with one that mirrors RunState HP/deck.
    cs.player.hp = rs.hp
    cs.player.max_hp = rs.max_hp
    cs.draw_pile = [c for c in rs.deck if c.cost >= 0]  # exclude unplayable placeholder curses
    import random as _r
    _r.Random(rs.run_seed).shuffle(cs.draw_pile)
    cs.hand = []
    cs.discard_pile = []
    cs.start_player_turn()
    rs.combat = cs
    # Fire on-combat-start relic hooks now that cs.player/cs.monster are wired up.
    trigger_on_combat_start(rs, cs)
    # And on-player-turn-start for turn-1 hooks (Lantern, BloodVial, …).
    trigger_on_player_turn_start(rs, cs)
    # Re-sync combat-side player HP with the RunState HP after any healing
    # hooks (BloodVial, Bloodletting-style relics) so the combat sees the
    # post-heal value rather than the snapshot taken before hook dispatch.
    cs.player.hp = rs.hp


def _step_combat(rs: RunState, body: dict, res: StepResult) -> StepResult:
    cs = rs.combat
    if cs is None:
        res.invalid_action = True
        res.reason = "combat state missing"
        return res
    action = body.get("action")
    if action == "end_turn":
        cs.end_player_turn()
    elif action == "play_card":
        idx = body.get("card_index", -1)
        if not (0 <= idx < len(cs.hand)) or not cs.can_play(idx):
            res.invalid_action = True
            res.reason = "illegal play_card"
            return res
        cs.play_card(idx)
    else:
        res.invalid_action = True
        res.reason = f"unsupported combat action {action!r}"
        return res

    # Resolve terminal conditions.
    if cs.player_won():
        res.combat_won = True
        rs.hp = cs.player.hp  # carry over post-combat HP
        # Fire relic after-combat-victory hooks (Burning Blood, Black Blood, …).
        trigger_after_combat_victory(rs)
        # Open reward.
        room_for_source = {
            StateType.MONSTER: "regular",
            StateType.ELITE: "elite",
            StateType.BOSS: "boss",
        }
        source = room_for_source.get(rs.state_type, "regular")
        rs.pending_card_reward = [
            CARDS[ch.card_id]
            for ch in generate_card_reward(_encounter_rng(rs), source,
                                           act=rs.act, ascension=int(rs.ascension))
        ]
        was_boss = rs.state_type is StateType.BOSS
        rs.state_type = StateType.CARD_REWARD
        if was_boss:
            res.boss_killed = True
            # On final-act boss with no second-boss queued, the run is won.
            pools = getattr(rs, "_pools", None)
            is_final = (rs.act == len(_ACT_ORDER))
            second_done = pools is None or pools.boss_visited >= 2 or pools.second_boss is None
            if is_final and second_done:
                rs.is_victorious = True
                rs.state_type = StateType.VICTORY
                res.run_completed = True
            elif is_final and not second_done:
                # A10 double boss: queue the second one immediately after reward.
                rs._defer_second_boss = True  # type: ignore[attr-defined]
        rs.combat = None
        return res

    if cs.player_lost():
        res.combat_lost = True
        rs.hp = 0
        rs.is_dead = True
        rs.state_type = StateType.GAME_OVER
        rs.combat = None
        return res

    # Sync HP back to RunState so the env observation tracks it mid-combat too.
    rs.hp = cs.player.hp
    return res


def _step_card_reward(rs: RunState, body: dict, res: StepResult) -> StepResult:
    action = body.get("action")
    if action == "select_card_reward":
        idx = body.get("card_index", -1)
        if rs.pending_card_reward is None or not (0 <= idx < len(rs.pending_card_reward)):
            res.invalid_action = True
            res.reason = "card_index out of range"
            return res
        rs.deck.append(rs.pending_card_reward[idx])
    elif action != "skip_card_reward":
        res.invalid_action = True
        res.reason = f"unsupported card reward action {action!r}"
        return res
    rs.pending_card_reward = None
    # If we deferred a second boss, jump straight into it.
    if getattr(rs, "_defer_second_boss", False):
        rs._defer_second_boss = False  # type: ignore[attr-defined]
        rs.state_type = StateType.BOSS
        eid = rs._pools.next_boss()
        _start_combat(rs, eid)
        return res
    rs.state_type = StateType.MAP
    # Advance to next act if we just killed the act boss.
    rmap = rs.maps[rs.act - 1]
    if rmap and rs.current_node == (rmap.boss_floor, 3):
        next_act_idx = rs.act  # 1-based; rs.act+1 means next
        if next_act_idx < len(_ACT_ORDER):
            _generate_act(rs, _ACT_ORDER[next_act_idx])  # next act
            rs.floor = 0
            rs.current_node = (0, 0)
            res.act_completed = True
    return res


def _step_rest(rs: RunState, body: dict, res: StepResult) -> StepResult:
    action = body.get("action")
    if action == "choose_rest_option":
        option = body.get("option")
        if option == "rest":
            rs.heal(int(rs.max_hp * 0.30))
        elif option == "smith":
            upgradables = [c for c in rs.deck if c.cost >= 0]
            if upgradables:
                # Placeholder upgrade: mark via id suffix.
                target = upgradables[0]
                idx = rs.deck.index(target)
                from dataclasses import replace
                rs.deck[idx] = replace(target, id=target.id + "+",
                                       name=target.name + "+")
        rs.state_type = StateType.MAP
        return res
    if action == "proceed":
        rs.state_type = StateType.MAP
        return res
    res.invalid_action = True
    res.reason = f"unsupported rest action {action!r}"
    return res


def _step_treasure(rs: RunState, body: dict, res: StepResult) -> StepResult:
    # Treasure auto-resolves into a free relic; agent only chooses to take/skip
    # via select_relic / skip_relic_selection.
    action = body.get("action")
    if action in ("select_relic", "skip_relic_selection", "proceed"):
        if action == "select_relic":
            from .game_state import RelicInstance
            rs.relics.append(RelicInstance(id="UNKNOWN_TREASURE_RELIC"))
        rs.state_type = StateType.MAP
        return res
    res.invalid_action = True
    res.reason = f"unsupported treasure action {action!r}"
    return res


def _step_event(rs: RunState, body: dict, res: StepResult) -> StepResult:
    """Stub event handler: any `choose_event_option` advances back to map.
    A real event registry lands in sim/events.py later.
    """
    action = body.get("action")
    if action in ("choose_event_option", "advance_dialogue", "proceed"):
        rs.state_type = StateType.MAP
        return res
    res.invalid_action = True
    res.reason = f"unsupported event action {action!r}"
    return res


def _step_shop(rs: RunState, body: dict, res: StepResult) -> StepResult:
    action = body.get("action")
    if action in ("shop_purchase", "proceed"):
        # No purchase logic yet — just leave the shop.
        rs.state_type = StateType.MAP
        return res
    res.invalid_action = True
    res.reason = f"unsupported shop action {action!r}"
    return res
