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
from .cards import upgrade_card
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
    current node's `children` list is consulted. children store
    (floor, x) pairs where x is the map-grid column, NOT a python list
    index — so we search the next floor's nodes by `.x` rather than
    indexing by position. This is important because narrow floors
    (treasure / boss) collapse to a single node at col 3.
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
    floor_nodes = rmap.floors[floor - 1]
    cur = next((n for n in floor_nodes if n.x == x), None)
    if cur is None:
        return []
    out: list[MapNode] = []
    for (f, nx) in cur.children:
        if not (1 <= f <= rmap.boss_floor):
            continue
        for n in rmap.floors[f - 1]:
            if n.x == nx:
                out.append(n)
                break
    return out


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
    # action_space.decode emits the mod-API field name `index`. The old
    # `node_index` key was an internal sim convention that pre-dated the
    # mod-side alignment; reading `node_index` here meant every legal map
    # pick decoded to "invalid", deterministic eval policies couldn't
    # escape floor 0, and reward collapsed to -living_cost * 1500 = -150.
    idx = body.get("index", body.get("node_index"))
    if idx is None or idx < 0 or idx >= len(options):
        res.invalid_action = True
        res.reason = f"map index {idx} out of range (have {len(options)})"
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
        # Real choice point — see notes/18_training_gaps.md. Auto-resolving
        # this room meant the policy never trained on the rest/smith
        # trade-off (heal HP now vs upgrade a card forever). Expose the
        # standard two options; smith only enabled when there is an
        # unupgraded card in the deck. The agent picks via
        # choose_rest_option(index); _step_rest applies the effect and
        # returns to map.
        rs.state_type = StateType.REST
        trigger_after_room_entered(rs, rs.state_type)
        has_upgradable = any(
            not (c.id.endswith("+") if isinstance(c.id, str) else False)
            for c in rs.deck
            if c.cost is not None and c.cost >= 0  # exclude curses
        )
        rs.pending_rest_options = [
            {"id": "rest", "is_enabled": True},
            {"id": "smith", "is_enabled": bool(has_upgradable)},
        ]
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
        # L1 shop: only card removal is offered. Real card/relic/potion
        # buying is Phase 2 (needs full shop pool sampling). Card removal
        # cost mirrors STS1's 75g base; STS2 may inflate it later.
        rs.state_type = StateType.SHOP
        trigger_after_room_entered(rs, rs.state_type)
        # Filter to removable cards (no curses).
        removable_idxs = [
            i for i, c in enumerate(rs.deck)
            if c.id != "ascenders_bane"
        ]
        # A6 Inflation raises card-removal base 75 -> 100 (decompiled
        # MerchantCardRemovalEntry.cs:17, AscensionHelper Inflation).
        _removal_cost = 100 if int(rs.ascension) >= 6 else 75
        rs.pending_shop = {
            "card_removal_cost": _removal_cost,
            "removable_card_indices": removable_idxs,
            "removal_used": False,
        }
        return
    elif rt is StateType.EVENT:
        # L1 events: dispatch through sim/events.py registry.
        rs.state_type = StateType.EVENT
        trigger_after_room_entered(rs, rs.state_type)
        from .events import pick_event
        evt = pick_event(rs)
        if evt is None:
            # No eligible event — small heal as a courtesy and return.
            rs.heal(2)
            rs.state_type = StateType.MAP
            return
        rs.pending_event = {
            "event_id": evt.id,
            "options": [
                {"id": o.id, "label": o.label, "enabled": o.enabled, "tag": o.tag}
                for o in evt.generate_options(rs)
            ],
        }
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
    from .encounter import build_monsters_for
    combat_rng = Rng(rs.run_seed, f"combat_{rs.act}_{rs.floor}")
    monsters = build_monsters_for(encounter_id, combat_rng, ascension=int(rs.ascension))
    # Construct a CombatState that mirrors the player's current persistent state.
    from .combat import CombatState, HAND_SIZE as _HS
    cs = CombatState.new_combat(seed=rs.run_seed ^ (rs.floor * 17),
                                monsters_factory=lambda _r: monsters)
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
        # Multi-enemy targeting: action_space encodes the target enemy slot
        # in `target` (combat_id == alive-enemy index). Set target_index
        # before resolving the card so SELECTED_ENEMY hits the right enemy.
        tgt = body.get("target")
        if isinstance(tgt, int):
            alive = cs.alive_monsters()
            if 0 <= tgt < len(alive):
                cs.target_index = tgt
        cs.play_card(idx)
    elif action == "use_potion":
        # L1 potion effects — applied in-combat. Per-floor diagnostic
        # showed 0 potion usage across 30 episodes because the action
        # had no handler. Sim now drops potions from combat (40-100%)
        # so the policy has something to use.
        slot = body.get("slot", -1)
        if not (0 <= slot < len(rs.potions)) or rs.potions[slot] is None:
            res.invalid_action = True
            res.reason = f"no potion in slot {slot}"
            return res
        pid = rs.potions[slot].id
        if pid == "FIRE_POTION":
            # 20 damage to selected enemy (or first alive).
            alive = cs.alive_monsters()
            if alive:
                tgt = body.get("target")
                t_idx = tgt if isinstance(tgt, int) and 0 <= tgt < len(alive) else 0
                alive[t_idx].take_damage(20, source="potion")
        elif pid == "BLOCK_POTION":
            cs.player.block = getattr(cs.player, "block", 0) + 12
        elif pid == "ENERGY_POTION":
            cs.player.energy = getattr(cs.player, "energy", 0) + 2
        else:
            # Unknown potion id — consume harmlessly. (Defensive: future
            # potion pool expansion lands here.)
            pass
        rs.potions[slot] = None
    elif action == "discard_potion":
        slot = body.get("slot", -1)
        if not (0 <= slot < len(rs.potions)) or rs.potions[slot] is None:
            res.invalid_action = True
            res.reason = f"no potion in slot {slot}"
            return res
        rs.potions[slot] = None
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
        # STS2 potion drop: 40% on regular monsters, 100% on elite/boss
        # (decompiled MegaCrit.Sts2.Core.Models.PotionPools — base rate
        # is RNG-driven, dropping from the active pool). L1 simplifies
        # to fixed rates per room_type with a placeholder potion id.
        # Per-floor diagnostic on e01_best showed 0 potions across 30
        # episodes — sim had no drop source besides Wellspring event.
        _pdrop_rate = {
            StateType.MONSTER: 0.40,
            StateType.ELITE: 1.00,
            StateType.BOSS: 1.00,
        }.get(rs.state_type, 0.0)
        if _pdrop_rate > 0:
            _rng = _encounter_rng(rs)
            roll = _rng.next_double()
            if roll < _pdrop_rate:
                # L1 potion pool — three common potions. Index by RNG.
                _potion_pool = ["FIRE_POTION", "BLOCK_POTION", "ENERGY_POTION"]
                pidx = _rng.next_int(0, len(_potion_pool))
                rs.add_potion(_potion_pool[pidx])
        # Combat gold reward (decompiled EncounterModel.cs:42-78): monster
        # 10-20, elite 35-45, boss 100. A3 Poverty cuts combat gold x0.75
        # (AscensionHelper). Previously the sim granted ZERO combat gold,
        # starving the shop/card-removal economy entirely.
        _grng = _encounter_rng(rs)
        if rs.state_type is StateType.MONSTER:
            _gold = _grng.next_int(10, 21)
        elif rs.state_type is StateType.ELITE:
            _gold = _grng.next_int(35, 46)
        elif rs.state_type is StateType.BOSS:
            _gold = 100
        else:
            _gold = 0
        if _gold > 0:
            if int(rs.ascension) >= 3:  # Poverty
                _gold = int(_gold * 0.75)
            rs.gain_gold(_gold)
        # Open reward.
        room_for_source = {
            StateType.MONSTER: "regular",
            StateType.ELITE: "elite",
            StateType.BOSS: "boss",
        }
        source = room_for_source.get(rs.state_type, "regular")
        rs.pending_card_reward = [
            (upgrade_card(CARDS[ch.card_id]) if ch.upgraded else CARDS[ch.card_id])
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
        # Index-based dispatch: action_space.decode emits the mod-API
        # field name `index`. Map back to the option id using the
        # pending list set in _enter_room (or fall back to the legacy
        # `option=<name>` body shape for older tests/fixtures).
        opts = rs.pending_rest_options or []
        idx = body.get("index")
        option = body.get("option")
        if idx is not None and 0 <= idx < len(opts):
            option = opts[idx].get("id")
        if option == "rest":
            rs.heal(int(rs.max_hp * 0.30))
        elif option == "smith":
            upgradables = [c for c in rs.deck
                           if c.cost is not None and c.cost >= 0
                           and not c.id.endswith("+")]
            if upgradables:
                target = upgradables[0]
                deck_idx = rs.deck.index(target)
                rs.deck[deck_idx] = upgrade_card(target)
        rs.pending_rest_options = None
        rs.state_type = StateType.MAP
        return res
    if action == "proceed":
        rs.pending_rest_options = None
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
    """Dispatch event option through sim.events.EVENT_REGISTRY.

    Body shapes accepted:
      - {"action": "choose_event_option", "index": N} — apply option N
      - {"action": "advance_dialogue"} — multi-page placeholder, just proceed
      - {"action": "proceed"} — leave event, return to map
    """
    action = body.get("action")
    if action == "proceed" or action == "advance_dialogue":
        rs.pending_event = None
        rs.state_type = StateType.MAP
        return res
    if action == "choose_event_option":
        from .events import apply_option
        if rs.pending_event is None:
            res.invalid_action = True
            res.reason = "no pending event"
            return res
        event_id = rs.pending_event.get("event_id")
        idx = body.get("index")
        if idx is None or not isinstance(idx, int):
            res.invalid_action = True
            res.reason = "choose_event_option missing index"
            return res
        ok = apply_option(rs, event_id, idx)
        if not ok:
            res.invalid_action = True
            res.reason = f"event option {idx} invalid or disabled"
            return res
        rs.pending_event = None
        # Death by event (e.g., TabletOfTruth decipher → max_hp=0) means
        # we've already transitioned to GAME_OVER inside apply_option.
        if rs.is_dead:
            return res
        rs.state_type = StateType.MAP
        return res
    res.invalid_action = True
    res.reason = f"unsupported event action {action!r}"
    return res


def _step_shop(rs: RunState, body: dict, res: StepResult) -> StepResult:
    """L1 shop: card removal at fixed cost. Real card/relic buying is Phase 2.

    Body shapes:
      - {"action": "shop_purchase_removal", "index": deck_idx} — pay
        cost, remove the card. Disabled if removal already used this
        visit (one per shop).
      - {"action": "proceed"} — leave the shop.
    """
    action = body.get("action")
    if action == "proceed":
        rs.pending_shop = None
        rs.state_type = StateType.MAP
        return res
    if action == "shop_purchase_removal":
        if rs.pending_shop is None:
            res.invalid_action = True
            res.reason = "no pending shop"
            return res
        if rs.pending_shop.get("removal_used"):
            res.invalid_action = True
            res.reason = "card removal already used at this shop"
            return res
        cost = int(rs.pending_shop.get("card_removal_cost", 75))
        if rs.gold < cost:
            res.invalid_action = True
            res.reason = "not enough gold for card removal"
            return res
        idx = body.get("index")
        if idx is None or not isinstance(idx, int):
            res.invalid_action = True
            res.reason = "shop_purchase_removal missing index"
            return res
        if idx < 0 or idx >= len(rs.deck):
            res.invalid_action = True
            res.reason = f"deck index {idx} out of range"
            return res
        if rs.deck[idx].id == "ascenders_bane":
            res.invalid_action = True
            res.reason = "ascenders_bane cannot be removed via shop"
            return res
        rs.gain_gold(-cost)
        del rs.deck[idx]
        rs.pending_shop["removal_used"] = True
        # Refresh removable indices since deck mutated.
        rs.pending_shop["removable_card_indices"] = [
            i for i, c in enumerate(rs.deck)
            if c.id != "ascenders_bane"
        ]
        return res
    # Backward compat: old generic "shop_purchase" still proceeds.
    if action == "shop_purchase":
        rs.pending_shop = None
        rs.state_type = StateType.MAP
        return res
    res.invalid_action = True
    res.reason = f"unsupported shop action {action!r}"
    return res
