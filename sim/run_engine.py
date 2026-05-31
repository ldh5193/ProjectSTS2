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

from .card_catalog import CARDS, CardRarity
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
from .rewards import (
    _POOL_BY_RARITY,
    _rarity_table,
    RarityRoller,
    generate_card_reward,
)


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


# Default 3-act sequence (ActModel.GetDefaultList): Overgrowth -> Hive -> Glory.
# Act 1 is replaced by Underdocks on a per-run coin flip (see _act_order).
_ACT_ORDER = ("overgrowth", "hive", "glory")


def _act_order(rs: RunState) -> tuple[str, ...]:
    """Per-run act sequence, deterministic from rs.run_seed.

    Mirrors ActModel.GetRandomList (ActModel.cs:414-424): the default list
    is [Overgrowth, Hive, Glory]; once the Underdocks epoch is revealed,
    list[0] becomes Underdocks if first-discovery OR rng.NextBool(). We
    model a normal *endgame* run where Underdocks is unlocked and already
    discovered, so the swap is a pure coin flip on a dedicated run-seed
    stream. Acts 2-3 (Hive, Glory) are unchanged.

    The choice is cached on the RunState so every consumer (act index,
    map/encounter generation, boss-floor logic) sees a single stable
    sequence for the whole run.
    """
    cached = getattr(rs, "_act_order_cache", None)
    if cached is not None:
        return cached
    from .rng import Rng
    # Dedicated stream so the coin flip never perturbs map/encounter RNG and
    # stays reproducible for eval seeds.
    act_rng = Rng(rs.run_seed, "act_selection")
    order = list(_ACT_ORDER)
    if act_rng.next_bool():  # GetRandomList: list[0] = Underdocks on heads.
        order[0] = "underdocks"
    order_t = tuple(order)
    setattr(rs, "_act_order_cache", order_t)
    return order_t


def start_run(rs: RunState) -> None:
    """After RunState.new_run, advance from MENU into the first map.
    Auto-skips character-select and ancient because those aren't part
    of the first-slice action space yet — RL focuses on map+combat first.
    """
    if rs.state_type is not StateType.MENU:
        return
    _generate_act(rs, _act_order(rs)[0])
    rs.state_type = StateType.MAP
    rs.floor = 0
    rs.current_node = (0, 0)


def _generate_act(rs: RunState, act_key: str) -> None:
    """Build encounter pools + map for the act and store them on the
    RunState. RunState exposes rs.maps[act-1] for the env's observation."""
    map_rng = _act_rng(rs, act_key)
    encounter_rng = _encounter_rng(rs)
    is_final_act = (act_key == _act_order(rs)[-1])
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


def _relic_rng(rs: RunState):
    """Per-(act,floor) isolated Rng for relic reward sampling. Keyed on
    floor so successive grants (treasure then a later elite) don't collide,
    while staying deterministic on the run seed."""
    from .rng import Rng
    return Rng(rs.run_seed, f"relic_{rs.act}_{rs.floor}")


def _shop_rng(rs: RunState):
    """Per-(act,floor) isolated Rng for shop stocking. Keyed on floor so
    each shop visit is deterministic on the run seed but distinct from
    the relic/encounter streams (mirrors PlayerRng.Shops in
    MerchantInventory.cs)."""
    from .rng import Rng
    return Rng(rs.run_seed, f"shop_{rs.act}_{rs.floor}")


def _act_index(act_key: str) -> int:
    # Overgrowth and Underdocks are both Act 1; Hive=2, Glory=3. This holds
    # regardless of which Act-1 variant the run rolled, so a static map is
    # both correct and independent of the per-run order.
    return {"overgrowth": 1, "underdocks": 1, "hive": 2, "glory": 3}[act_key]


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


# ---------------------------------------------------------------------------
# Shop stocking (decompiled MerchantInventory.CreateForNormalMerchant).
#
# Inventory: 5 colored cards + 2 colorless cards + 3 relics + 3 potions + 1
# card-removal. The sim has no colorless pool, so colorless slots are
# sampled from the Ironclad pool too (Uncommon + Rare per
# _colorlessCardRarities), and priced with the +15% colorless surcharge
# from MerchantCardEntry.GetCost so the price ranges still match.
#
# Pricing (decompiled, exact):
#   card:   rare 150, uncommon 75, common 50; colorless x1.15;
#           x NextFloat(0.95, 1.05) jitter  (MerchantCardEntry.GetCost/CalcCost)
#   relic:  Model.MerchantCost x NextFloat(0.85, 1.15)  (MerchantRelicEntry)
#   potion: rare 100, uncommon 75, common 50; x NextFloat(0.95, 1.05)
#           (MerchantPotionEntry.GetCost/CalcCost)
#   removal: 75 base (100 at A6 Inflation) + 25 (50 at A6) per prior removal
#           (MerchantCardRemovalEntry)
# ---------------------------------------------------------------------------

# Card base prices by rarity (MerchantCardEntry.GetCost).
_CARD_BASE_COST = {
    CardRarity.RARE: 150,
    CardRarity.UNCOMMON: 75,
    CardRarity.COMMON: 50,
    CardRarity.BASIC: 50,
    CardRarity.ANCIENT: 150,
}
# Potion prices/pool now live in sim/potions.py (POTION_SHOP_BASE_COST by
# rarity + the rarity-weighted roll_potion draw). The old fixed FIRE/BLOCK/
# ENERGY proxy pool and flat base cost were removed when the real potion
# system landed.

# Default relic merchant cost when a registry entry has merchant_cost=0
# (boss/event relics aren't normally shop-stocked; keep them buyable but
# expensive so the price stays sane if one ever lands in a slot).
_RELIC_DEFAULT_COST = 200


def _stock_shop(rs: RunState) -> dict:
    """Build the full shop inventory deterministically via _shop_rng.

    Returns the pending_shop dict the action-space contract expects:
      {"items": [<item dict>...], "can_proceed": True,
       "card_removal_cost": int, "removable_card_indices": [...],
       "removal_used": False}

    Each item dict carries the action-space keys
    {index, category, price, can_afford, is_stocked} PLUS a grant payload
    (card_id / upgraded / relic_id / potion_id) the purchase handler reads.
    """
    from .relics import RELIC_REGISTRY, sample_relic_from_pool

    rng = _shop_rng(rs)
    asc = int(rs.ascension)
    items: list[dict] = []
    idx = 0

    # ---- Cards: 5 colored + 2 colorless (sim has only Ironclad pool) ----
    # Colored cards roll rarity by the shop odds table; colorless slots are
    # fixed Uncommon/Rare (decompiled _colorlessCardRarities). Upgrade chance
    # follows the same act scaling as card rewards.
    table = _rarity_table("shop", asc)
    roller = RarityRoller(ascension=asc)
    upgrade_scale = 0.125 if asc >= 7 else 0.25
    upgrade_chance = (rs.act - 1) * upgrade_scale
    seen_cards: set[str] = set()

    def _add_card(rarity, colorless: bool) -> None:
        nonlocal idx
        pool = [c for c in _POOL_BY_RARITY.get(rarity, []) if c not in seen_cards]
        if not pool:
            for fb in (CardRarity.COMMON, CardRarity.UNCOMMON, CardRarity.RARE):
                pool = [c for c in _POOL_BY_RARITY.get(fb, []) if c not in seen_cards]
                if pool:
                    rarity = fb
                    break
        if not pool:
            return
        card_id = rng.next_item(pool)
        seen_cards.add(card_id)
        upgraded = False
        if rarity is not CardRarity.RARE and upgrade_chance > 0:
            if rng.next_float() <= upgrade_chance:
                upgraded = True
        base = _CARD_BASE_COST.get(rarity, 50)
        if colorless:
            base = round(base * 1.15)
        price = int(round(base * rng.next_float(0.95, 1.05)))
        items.append({
            "index": idx,
            "category": "card",
            "price": price,
            "can_afford": rs.gold >= price,
            "is_stocked": True,
            "card_id": card_id,
            "upgraded": upgraded,
        })
        idx += 1

    for _ in range(5):
        _add_card(roller.roll(rng, table), colorless=False)
    for rar in (CardRarity.UNCOMMON, CardRarity.RARE):
        _add_card(rar, colorless=True)

    # ---- Relics: 3, de-duped vs owned (MerchantInventory.PopulateRelicEntries) ----
    owned = {r.id for r in rs.relics}
    for slot in range(3):
        rid = sample_relic_from_pool(rng, owned, boss=False)
        if rid is None:
            break
        owned.add(rid)  # avoid duplicates within the same shop
        rd = RELIC_REGISTRY.get(rid)
        base = (rd.merchant_cost if rd and rd.merchant_cost > 0
                else _RELIC_DEFAULT_COST)
        price = int(round(base * rng.next_float(0.85, 1.15)))
        items.append({
            "index": idx,
            "category": "relic",
            "price": price,
            "can_afford": rs.gold >= price,
            "is_stocked": True,
            "relic_id": rid,
        })
        idx += 1

    # ---- Potions: 2 real pooled potions (MerchantInventory.PopulatePotionEntries
    # draws via PotionFactory; price = MerchantPotionEntry.GetCost by rarity
    # rare 100 / uncommon 75 / common 50, × NextFloat(0.95, 1.05) jitter). ----
    from .potions import roll_potion, potion_rarity, POTION_SHOP_BASE_COST
    seen_potions: set[str] = set()
    for _ in range(2):
        pid = roll_potion(rng)
        # De-dupe within a single shop (best-effort; small pool tolerance).
        for _retry in range(4):
            if pid not in seen_potions:
                break
            pid = roll_potion(rng)
        seen_potions.add(pid)
        base = POTION_SHOP_BASE_COST.get(potion_rarity(pid), 50)
        price = int(round(base * rng.next_float(0.95, 1.05)))
        items.append({
            "index": idx,
            "category": "potion",
            "price": price,
            "can_afford": rs.gold >= price,
            "is_stocked": True,
            "potion_id": pid,
        })
        idx += 1

    # ---- Card removal: 1 slot (MerchantCardRemovalEntry) ----
    removal_cost = 100 if asc >= 6 else 75
    removable_idxs = [
        i for i, c in enumerate(rs.deck) if c.id != "ascenders_bane"
    ]
    items.append({
        "index": idx,
        "category": "card_removal",
        "price": removal_cost,
        "can_afford": rs.gold >= removal_cost,
        "is_stocked": True,
    })
    idx += 1

    return {
        "items": items,
        "can_proceed": True,
        "card_removal_cost": removal_cost,
        "removable_card_indices": removable_idxs,
        "removal_used": False,
    }


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
        rs.pending_rest_options = _generate_rest_options(rs)
        return
    elif rt is StateType.TREASURE:
        # Treasure auto-grants one real relic from the reward pool (replaces
        # the old inert "UNKNOWN_TREASURE_RELIC" placeholder). Deterministic
        # via the run RNG, de-duped against owned relics.
        rs.state_type = StateType.TREASURE
        trigger_after_room_entered(rs, rs.state_type)
        from .relics import grant_relic_reward
        grant_relic_reward(rs, _relic_rng(rs), boss=False)
        rs.state_type = StateType.MAP
        return
    elif rt is StateType.SHOP:
        # Full shop (Phase 7H): stock cards + relics + potions + card
        # removal, mirroring MerchantInventory.CreateForNormalMerchant.
        # The action-space contract (sim/action_space._shop_mask + decode)
        # reads rs.pending_shop["items"] = list of
        # {index, category, price, can_afford, is_stocked, ...}.
        rs.state_type = StateType.SHOP
        trigger_after_room_entered(rs, rs.state_type)
        rs.pending_shop = _stock_shop(rs)
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
    # Reset per-combat enchant state (Swift/Sown re-enabled, Momentum ExtraDamage
    # cleared, Glam un-used). EnchantmentStatus returns to Normal at combat start.
    for c in cs.draw_pile:
        ench = getattr(c, "enchantment", None)
        if ench is not None:
            ench.reset_for_combat()
    cs.hand = []
    cs.discard_pile = []
    cs.run_state = rs  # enable per-attack/per-card/turn-end relic hooks
    # Reset per-combat relic counters (Kunai/Shuriken/Nunchaku/PenNib/
    # HappyFlower/Pendulum/…). Each is flagged resets_per_combat in the
    # registry (decompiled per-combat counters reset on combat end).
    from .relics import reset_combat_counters
    reset_combat_counters(rs)
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
        # Real POTION effects (sim/potions.py POTION_REGISTRY). Routes the
        # potion through its decompiled effect (block/damage/energy/draw/
        # powers/heal/…) against the chosen enemy slot. Belt slot is freed
        # whether or not the id is recognised.
        from .potions import apply_potion
        slot = body.get("slot", -1)
        if not (0 <= slot < len(rs.potions)) or rs.potions[slot] is None:
            res.invalid_action = True
            res.reason = f"no potion in slot {slot}"
            return res
        pid = rs.potions[slot].id
        tgt = body.get("target")
        t_idx = tgt if isinstance(tgt, int) else 0
        apply_potion(rs, cs, pid, t_idx)
        rs.potions[slot] = None
        # Re-sync combat-side player HP into the run HP after heals
        # (Blood/Fairy/Fruit Juice) so the run sees the post-heal value.
        rs.hp = cs.player.hp
        rs.max_hp = cs.player.max_hp
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
        # STS2 potion drop — faithful PotionRewardOdds + PotionFactory draw.
        # (decompiled MegaCrit.Sts2.Core.Odds.PotionRewardOdds + Factories.
        # PotionFactory.CreateRandomPotion). Base odds 0.4, self-adjusting
        # ±0.1 toward 0.5; Elite rooms add eliteBonus*0.5 = 0.125 to the
        # acceptance threshold. The CurrentValue persists across the run.
        # When a drop fires, the potion is a rarity-weighted draw from the
        # SharedPotionPool (Rare<=0.10, Uncommon<=0.35, else Common) — NOT a
        # fixed FIRE/BLOCK/ENERGY proxy. Bosses grant a boss relic (handled
        # below), not a random potion, so they don't roll here.
        if rs.state_type in (StateType.MONSTER, StateType.ELITE):
            from .potions import roll_potion
            _rng = _encounter_rng(rs)
            current = float(getattr(rs, "potion_reward_odds", 0.4))
            num = _rng.next_float()
            # Drift CurrentValue toward the 0.5 target (PotionRewardOdds.Roll).
            if num < current:
                rs.potion_reward_odds = current - 0.1
            else:
                rs.potion_reward_odds = current + 0.1
            elite_bonus = 0.25 if rs.state_type is StateType.ELITE else 0.0
            if num < current + elite_bonus * 0.5:
                rs.add_potion(roll_potion(_rng))
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
        # Relic rewards (auto-added to rs.relics — no selection UI). Real
        # STS: elites ALWAYS drop a relic; bosses drop a boss-pool relic.
        # Grants apply from the NEXT combat (on_combat_start fires then).
        # Deterministic via the per-floor relic RNG; de-duped in
        # grant_relic_reward.
        from .relics import grant_relic_reward
        if rs.state_type is StateType.ELITE:
            grant_relic_reward(rs, _relic_rng(rs), boss=False)
        elif rs.state_type is StateType.BOSS:
            grant_relic_reward(rs, _relic_rng(rs), boss=True)
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
            is_final = (rs.act == len(_act_order(rs)))
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
        rs.add_card_to_deck(rs.pending_card_reward[idx])
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
        order = _act_order(rs)
        next_act_idx = rs.act  # 1-based; rs.act+1 means next
        if next_act_idx < len(order):
            _generate_act(rs, order[next_act_idx])  # next act
            rs.floor = 0
            rs.current_node = (0, 0)
            res.act_completed = True
    return res


# Per-run cap on Girya lifts (decompiled Girya.maxLifts = 3). Once a run has
# lifted 3 times the LiftRestSiteOption is no longer offered (Girya
# .TryModifyRestSiteOptions: returns false when TimesLifted >= 3).
GIRYA_MAX_LIFTS = 3


def _generate_rest_options(rs: RunState) -> list[dict]:
    """Build the rest-site option list, faithful to the decompiled real game.

    Base set (RestSiteOption.Generate): HEAL + SMITH always offered. MEND is
    only added when ``RunState.Players.Count > 1`` (multiplayer) — N/A for the
    single-player sim, so it is never emitted.

    Relic/card-gated options (each relic/card's ``TryModifyRestSiteOptions``):
      * DIG   — owns Shovel       (DigRestSiteOption: pull next relic).
      * COOK  — owns MeatCleaver  (CookRestSiteOption: remove 2 cards, +9 max
                HP; disabled when <2 removable cards).
      * LIFT  — owns Girya AND TimesLifted < 3 (LiftRestSiteOption:
                permanent +Strength; the relic stops adding the option at the
                3-lift cap).
      * HATCH — ByrdonisEgg card in deck (HatchRestSiteOption: obtain Byrdpip).
      * CLONE — owns Pael's Growth (CloneRestSiteOption: duplicate every
                Clone-enchanted card).

    Midas modifier removes the SMITH option entirely (Midas
    .TryModifyRestSiteOptions). The sim does not model the Midas modifier;
    documented here for completeness.

    Slot indices MUST match the action_space "rest" range (6 slots):
        0=rest(HEAL) 1=upgrade(SMITH) 2=clone(CLONE)/hatch(HATCH)
        3=dig(DIG) 4=cook(COOK) 5=lift(LIFT)
    The slot-2 relic-gated options (CLONE, HATCH) are mutually exclusive in
    practice (each needs a distinct, rare relic/card); CLONE takes priority if
    both are somehow present so a single Discrete slot stays unambiguous.
    """
    has_upgradable = any(
        not (c.id.endswith("+") if isinstance(c.id, str) else False)
        for c in rs.deck
        if c.cost is not None and c.cost >= 0  # exclude curses
    )
    removable_count = sum(
        1 for c in rs.deck if getattr(c, "id", None) != "ascenders_bane"
    )

    # SmithRestSiteOption(owner): base.IsEnabled = Deck.UpgradableCardCount != 0.
    opts: list[dict] = [
        {"id": "rest", "index": 0, "is_enabled": True},
        {"id": "smith", "index": 1, "is_enabled": bool(has_upgradable)},
    ]

    # Slot 2: relic/card-gated CLONE (Pael's Growth) or HATCH (Byrdonis Egg).
    if rs.has_relic("PAELS_GROWTH"):
        opts.append({"id": "clone", "index": 2, "is_enabled": True})
    elif any(getattr(c, "id", None) == "byrdonis_egg" for c in rs.deck):
        opts.append({"id": "hatch", "index": 2, "is_enabled": True})

    # Slot 3: DIG only when the run owns Shovel.
    if rs.has_relic("SHOVEL"):
        opts.append({"id": "dig", "index": 3, "is_enabled": True})

    # Slot 4: COOK only when the run owns Meat Cleaver; disabled <2 removable.
    if rs.has_relic("MEAT_CLEAVER"):
        opts.append(
            {"id": "cook", "index": 4, "is_enabled": removable_count >= 2}
        )

    # Slot 5: LIFT only when the run owns Girya AND under the 3-lift cap.
    if rs.has_relic("GIRYA"):
        girya = next((r for r in rs.relics if r.id == "GIRYA"), None)
        lifts = (girya.counter or 0) if girya is not None else 0
        if lifts < GIRYA_MAX_LIFTS:
            opts.append({"id": "lift", "index": 5, "is_enabled": True})

    return opts


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
        # Resolve option id by the option's `index` field (slots are sparse:
        # e.g. cook sits at slot 4, lift at 5), falling back to positional.
        if idx is not None:
            match = next((o for o in opts if int(o.get("index", -1)) == idx), None)
            if match is None and 0 <= idx < len(opts):
                match = opts[idx]
            if match is not None and match.get("is_enabled", True):
                option = match.get("id")
        if option == "rest":
            # HealRestSiteOption: heal 30% of max HP. rs.heal applies the A2
            # WearyTraveler x0.8 multiplier (heal_multiplier).
            rs.heal(int(rs.max_hp * 0.30))
        elif option == "smith":
            # SmithRestSiteOption: upgrade one card.
            upgradables = [c for c in rs.deck
                           if c.cost is not None and c.cost >= 0
                           and not c.id.endswith("+")]
            if upgradables:
                target = upgradables[0]
                deck_idx = rs.deck.index(target)
                rs.deck[deck_idx] = upgrade_card(target)
        elif option == "dig":
            # DigRestSiteOption: pull next relic (random pooled relic).
            from .relics import grant_relic_reward
            grant_relic_reward(rs, _relic_rng(rs), boss=False)
        elif option == "cook":
            # CookRestSiteOption: remove 2 cards, gain 9 max HP.
            for _ in range(2):
                for i, c in enumerate(rs.deck):
                    if getattr(c, "id", None) != "ascenders_bane":
                        del rs.deck[i]
                        break
            rs.gain_max_hp(9)
        elif option == "lift":
            # LiftRestSiteOption: permanent +Strength buff (Girya). The lift
            # count is tracked on the Girya relic instance's counter
            # (decompiled Girya.TimesLifted); Girya's on_combat_start hook
            # reads it to apply that many Strength each combat. Capped at
            # GIRYA_MAX_LIFTS (decompiled Girya.maxLifts = 3); the option is
            # withheld at the cap by _generate_rest_options, but guard here too.
            for r in rs.relics:
                if r.id == "GIRYA":
                    if (r.counter or 0) < GIRYA_MAX_LIFTS:
                        r.counter = (r.counter or 0) + 1
                    break
        elif option == "hatch":
            # HatchRestSiteOption: hatch the Byrdonis Egg into the Byrdpip
            # relic (RelicCmd.Obtain<Byrdpip>). Consume the egg card and grant
            # the relic.
            for i, c in enumerate(rs.deck):
                if getattr(c, "id", None) == "byrdonis_egg":
                    del rs.deck[i]
                    break
            rs.add_relic("BYRDPIP")
        elif option == "clone":
            # CloneRestSiteOption (Pael's Growth): duplicate every Clone-enchanted
            # card in the deck (RunState.CloneCard each, add to Deck). The clone
            # carries its own enchant-state copy so the two stay independent.
            from .enchantments import clone_card_instance
            clones = [clone_card_instance(c) for c in rs.deck
                      if getattr(c, "enchantment", None) is not None
                      and c.enchantment.id == "clone"]
            for c in clones:
                rs.add_card_to_deck(c)
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
            from .relics import grant_relic_reward
            grant_relic_reward(rs, _relic_rng(rs), boss=False)
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


def _recompute_shop_affordability(rs: RunState) -> None:
    """Refresh can_afford on every stocked item after gold changes."""
    if not rs.pending_shop:
        return
    for it in rs.pending_shop.get("items", []):
        it["can_afford"] = it.get("is_stocked", False) and rs.gold >= int(it.get("price", 0))


def _step_shop(rs: RunState, body: dict, res: StepResult) -> StepResult:
    """Full shop: buy cards / relics / potions, remove a card, or leave.

    Body shapes:
      - {"action": "shop_purchase", "index": local_slot} — buy the item in
        that shop slot (card/relic/potion). Deducts gold, grants the item,
        marks the slot unstocked, refreshes affordability.
      - {"action": "shop_purchase_removal", "index": deck_idx} — pay
        cost, remove the card. One per shop visit.
      - {"action": "proceed"} — leave the shop.
    """
    action = body.get("action")
    if action == "proceed":
        rs.pending_shop = None
        rs.state_type = StateType.MAP
        return res
    if action == "shop_purchase":
        if rs.pending_shop is None:
            res.invalid_action = True
            res.reason = "no pending shop"
            return res
        slot = body.get("index")
        if slot is None or not isinstance(slot, int):
            res.invalid_action = True
            res.reason = "shop_purchase missing index"
            return res
        item = next((it for it in rs.pending_shop.get("items", [])
                     if int(it.get("index", -1)) == slot), None)
        if item is None:
            res.invalid_action = True
            res.reason = f"shop slot {slot} not found"
            return res
        # card_removal must come through shop_purchase_removal (decode
        # already dispatches it there); reject it here defensively.
        if item.get("category") == "card_removal":
            res.invalid_action = True
            res.reason = "card_removal must use shop_purchase_removal"
            return res
        if not item.get("is_stocked", False):
            res.invalid_action = True
            res.reason = f"shop slot {slot} already sold"
            return res
        price = int(item.get("price", 0))
        if rs.gold < price:
            res.invalid_action = True
            res.reason = "not enough gold for purchase"
            return res
        category = item.get("category")
        if category == "card":
            cdef = CARDS.get(item.get("card_id"))
            if cdef is None:
                res.invalid_action = True
                res.reason = f"unknown shop card {item.get('card_id')!r}"
                return res
            rs.add_card_to_deck(upgrade_card(cdef) if item.get("upgraded") else cdef)
        elif category == "relic":
            rs.add_relic(item.get("relic_id"))
        elif category == "potion":
            if not rs.add_potion(item.get("potion_id")):
                # Belt full — purchase fails, no gold spent (mirrors the
                # mod's PurchaseStatus.FailureSpace path).
                res.invalid_action = True
                res.reason = "no free potion slot"
                return res
        else:
            res.invalid_action = True
            res.reason = f"unbuyable shop category {category!r}"
            return res
        rs.gain_gold(-price)
        # MawBank.cs: once the owner spends gold at a shop, Maw Bank is used up
        # (stops granting +12 gold per room).
        if price > 0:
            rs.maw_bank_spent = True
        item["is_stocked"] = False
        item["can_afford"] = False
        _recompute_shop_affordability(rs)
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
        # Mark the card_removal item slot unstocked so the mask drops it
        # (mirrors MerchantCardRemovalEntry.IsStocked => !Used).
        for it in rs.pending_shop.get("items", []):
            if it.get("category") == "card_removal":
                it["is_stocked"] = False
                it["can_afford"] = False
        # Refresh removable indices since deck mutated.
        rs.pending_shop["removable_card_indices"] = [
            i for i, c in enumerate(rs.deck)
            if c.id != "ascenders_bane"
        ]
        _recompute_shop_affordability(rs)
        return res
    res.invalid_action = True
    res.reason = f"unsupported shop action {action!r}"
    return res
