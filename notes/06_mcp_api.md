# STS2_MCP v0.4.0 — Complete Endpoint Reference for RL Integration

Source code reference: `/Users/dhlee/workspace/STS2/tools/STS2MCP-src/`
Key files: `McpMod.cs` (dispatch), `McpMod.Actions.cs` (handlers), `McpMod.StateBuilder.cs` (state JSON schema), `McpMod.MultiplayerState.cs`, `McpMod.Profile.cs`, `McpMod.Compendium.cs`, `McpMod.Wiki.cs`.

## 1. HTTP Route Dispatch Table

All requests are handled in `McpMod.cs:175` (`HandleRequest`). CORS is enabled for all origins.

| HTTP Method | Path | Dispatcher | File:Line | Notes | Query Params |
| :--- | :--- | :--- | :--- | :--- | :--- |
| GET | `/` | (root) | McpMod.cs:196 | Health check; returns `{message: "Hello...", status: "ok"}` | — |
| GET | `/api/v1/singleplayer` | `HandleGetState` | McpMod.cs:209 | Full SP game state | `format=json\|markdown` |
| POST | `/api/v1/singleplayer` | `HandlePostAction` | McpMod.cs:212 | Execute SP action | — |
| GET | `/api/v1/multiplayer` | `HandleGetMultiplayerState` | McpMod.cs:226 | Full MP game state + votes | `format=json\|markdown` |
| POST | `/api/v1/multiplayer` | `HandlePostMultiplayerAction` | McpMod.cs:229 | Execute MP action (sync-safe) | — |
| GET | `/api/v1/profiles` | `HandleGetProfiles` | McpMod.cs:235 | Summary of all 3 profiles | — |
| POST | `/api/v1/profiles` | `HandlePostProfiles` | McpMod.cs:238 | Switch or delete profile | — |
| GET | `/api/v1/profile` | `HandleGetProfile` | McpMod.cs:245 | Current profile stats | — |
| GET | `/api/v1/compendium` | `HandleGetCompendium` | McpMod.cs:252 | Full compendium (card stats, bestiary, run history) | — |
| GET | `/api/v1/wiki` | `HandleGetWiki` | McpMod.cs:259 | Fuzzy search across discovered cards/relics | `query=<str>, type=all\|card\|relic, limit=1..50` |

**Guard conditions** (`McpMod.cs:198–232`):

- `/api/v1/singleplayer` rejects if `IsMultiplayerRun()` is true (409 Conflict).
- `/api/v1/multiplayer` rejects if NOT multiplayer (409 Conflict).
- Both POST endpoints check for blocking FTUE/tutorial popups; 500 if a popup is visible.

---

## 2. Game State Endpoints — JSON Response Structure

### 2.1 GET /api/v1/singleplayer

The top-level `state_type` field indicates the current context. Branches mostly in `StateBuilder.cs:61–536`.

| `state_type` | When Active | Key Response Fields |
| :--- | :--- | :--- |
| `"menu"` | No run in progress | `menu_screen` ∈ {singleplayer, character_select, main, profile_select, timeline}, `options[]`, `message` |
| `"monster"` / `"elite"` / `"boss"` | In combat (play phase) | `battle`, `player` (see "Battle JSON" below) |
| `"hand_select"` | Card-selection overlay during combat | `hand_select`, `battle` |
| `"card_select"` | Post-combat card reward screen | `card_select[]` (id, title, rarity, description, can_upgrade) |
| `"card_reward"` | Single card reward (pre-pick) | `card_reward` |
| `"rewards"` | Multi-reward screen (relic/gold/potion) | `rewards[]` |
| `"relic_select"` | Treasure room choice | `relic_select[]` |
| `"bundle_select"` | Bundle selection | `bundle_select` |
| `"crystal_sphere"` | Crystal Sphere minigame | `crystal_sphere` (grid + tools) |
| `"map"` | On run map | `map` (node coords, floor metadata) |
| `"event"` | Event room | `event` (options, dialogue) |
| `"fake_merchant"` | Merchant event overlay | `fake_merchant` |
| `"game_over"` | Run ended | `game_over` (victory/defeat, score) |
| `"overlay"` | Unrecognized blocking overlay | `overlay.screen_type`, `overlay.message` |
| `"unknown"` | Error state | `error` / `message` |

### 2.2 Battle JSON (`StateBuilder.cs:1062–1089`)

```json
{
  "battle": {
    "round": 1,
    "turn": "player",           // or "enemy"
    "is_play_phase": true,      // false during enemy turn / mid-animation
    "enemies": [
      {
        "combat_id": "gremlin_0",
        "name": "Gremlin",
        "hp": 10,
        "max_hp": 15,
        "block": 0,
        "intents": [{"type": "attack", "amount": 3}]
      }
    ]
  },
  "player": {
    "character": "IronClad",
    "hp": 75,
    "max_hp": 80,
    "block": 5,
    "energy": 3,                // set only if CombatManager.IsInProgress
    "max_energy": 3,
    "hand": [
      {
        "id": "strike",
        "index": 0,
        "title": "Strike",
        "cost": 1,
        "type": "attack",
        "rarity": "common",
        "description": "Deal 6 damage",
        "can_play": true,
        "target_type": "none",  // or "any_enemy"
        "upgraded": false,
        "upgrade_preview": null
      }
    ],
    "draw_pile_count": 10,
    "discard_pile_count": 2,
    "exhaust_pile_count": 1,
    "draw_pile": [],
    "discard_pile": [],
    "exhaust_pile": [],
    "orbs": [],
    "potions": [
      {"slot": 0, "id": "fire_potion", "name": "Fire Potion", "description": "Deal 20 damage", "can_use": true}
    ],
    "relics": []
  }
}
```

### 2.3 RL Observation Mapping (initial proposal)

- Current floor: from `map.floor_number` or inferred from `map.current_node_id`
- Hand: `hand[i].index` maps to `card_index` for play_card
- Targetable enemies: `battle.enemies[i].combat_id`
- Energy: `player.energy` / `player.max_energy`
- HP: `player.hp` / `player.max_hp`

### 2.4 GET /api/v1/multiplayer

Identical to SP **plus**:

- `"game_mode": "multiplayer"`, `"net_type": "..."` (e.g. `"HostGame"`), `"player_count": N`
- In combat: `battle.all_players_ready: bool` (`McpMod.MultiplayerState.cs:273`)
- In map: `map.votes[]` `{player, is_local, voted, vote_col, vote_row}` (`MultiplayerState.cs:288–323`)
- In shared event: `event.votes[]` `{player, is_local, voted, vote_option}` (`MultiplayerState.cs:326–355`)

### 2.5 GET /api/v1/profile

```json
{
  "profile_id": 1,
  "characters": [
    {"id": "ironclad", "max_ascension": 15, "preferred_ascension": 10,
     "total_wins": 42, "total_losses": 58, "playtime": 3600000}
  ],
  "discovered_cards": ["strike", "defend"],
  "discovered_relics": ["burning_blood"],
  "discovered_potions": ["fire_potion"]
}
```

### 2.6 GET /api/v1/compendium

```json
{
  "profile_id": 1,
  "sections": {
    "card_library": {
      "discovered_ids": [],
      "stats": [{"id": "strike", "times_picked": 100, "times_skipped": 5, "times_won": 50, "times_lost": 20}]
    },
    "character_stats": {
      "characters": [],
      "global": {"total_playtime": 3600000, "total_wins": 150, "total_losses": 200, "best_win_streak": 7}
    },
    "run_history": {
      "entries": [{"timestamp": "2024-01-15T10:30:00Z", "run_duration": 1800, "character": "ironclad", "outcome": "victory"}]
    }
  }
}
```

---

## 3. Action Endpoints — POST /api/v1/singleplayer and /multiplayer

Both accept JSON body with required `"action"` field. Response shape:

```json
{"status": "ok", "message": "Action description", "error": null}
```

### 3.1 Action Types (`McpMod.Actions.cs:47–92`)

| Action | Required Params | Constraints | Target | Blocks Until |
| :--- | :--- | :--- | :--- | :--- |
| `play_card` | `card_index` | In combat, play phase, energy ≥ cost | `target` if `card.target_type == AnyEnemy` | Animation start |
| `end_turn` (SP) | — | Play phase, hand not mid-play | — | Turn animation start |
| `end_turn` / `undo_end_turn` (MP) | — | Play phase; queues `EndPlayerTurnAction` | — | Immediate; other players gate progression |
| `use_potion` | `slot` | Potion exists, not queued, `UsabilityCheck` passes | — | Potion animation |
| `discard_potion` | `slot` | Same | — | Immediate |
| `choose_map_node` | `node_id` or `coord: {col,row}` | On map, node visible | — | Map transition |
| `choose_event_option` | `option` (0-indexed) | In event, option enabled | — | Event dialogue |
| `advance_dialogue` | — | Dialogue/event overlay active | — | Immediate |
| `choose_rest_option` | `option` (e.g. `rest`,`shop`,`upgrade`) | At rest site | — | Rest animation |
| `shop_purchase` | `item_index` or `item_id` | Merchant, funds OK | — | Shop animation |
| `claim_reward` | `reward_index` | Rewards visible | — | Claim animation |
| `select_card_reward` | `card_index` | Card reward screen | — | Immediate |
| `skip_card_reward` | — | Card reward, skip enabled | — | Immediate |
| `proceed` | — | Generic confirm button | — | Overlay dismissal |
| `select_card` | `option_index` | Card-select grid | — | Highlight only |
| `confirm_selection` / `cancel_selection` | — | Grid selection active | — | Selection confirms |
| `select_bundle` / `confirm_bundle_selection` / `cancel_bundle_selection` | `bundle_index` | Bundle-select grid | — | Same pattern as cards |
| `combat_select_card` / `combat_confirm_selection` | `card_index` | Hand-select overlay | — | Same pattern |
| `select_relic` / `skip_relic_selection` | `relic_index` | Relic-select (treasure) | — | Highlight / immediate |
| `claim_treasure_relic` | `relic_index` | Treasure rewards | — | Claim animation |
| `crystal_sphere_set_tool` | `tool` (id) | Sphere active | — | Immediate |
| `crystal_sphere_click_cell` | `coord:{row,col}` | Sphere cell valid | — | Cell animation |
| `crystal_sphere_proceed` | — | Sphere complete | — | Overlay dismissal |
| `menu_select` | `option` (string) | Menu / FTUE overlay active | — | Menu transition |

### 3.2 `menu_select` options (`McpMod.Actions.cs:1079–1662`)

- Character select: `"character_id"`, `"confirm"`, `"back"`, `"unready"` (MP only); supports `seed` param for seeded runs
- Game over: `"main_menu"`
- Tutorial / FTUE: `"yes"`, `"no"`, `"advance"`, `"proceed"`
- SP mode: `"standard"`, `"daily"`, `"custom"`
- MP mode: `"host"`, `"join"`, `"load"`, `"abandon"`

### 3.3 Error responses

- **400**: missing required field (e.g. `action`, `card_index`)
- **409**: wrong endpoint for current run mode (e.g. POST to `/singleplayer` during MP run)
- **500**: execution failure (card cannot play, target not found, hand locked during animation)

### 3.4 Blocking behavior

Most actions queue to `ActionQueueSynchronizer` (`McpMod.Actions.cs:140`) and resolve on the main thread. Response returns **immediately after queuing**, NOT after animation completes. Clients must poll state to detect completion.

---

## 4. RL Action-Space Mapping: Discrete(61) → API Schema

Project plan's space:

- `0`: end turn
- `1..10`: untargeted card slots
- `11..60`: targeted (10 slots × 5 enemy positions)

Reference Python mapping:

```python
def map_discrete_action(action_idx: int, state: dict) -> dict:
    if action_idx == 0:
        return {"action": "end_turn"}

    if 1 <= action_idx <= 10:
        return {"action": "play_card", "card_index": action_idx - 1}

    if 11 <= action_idx <= 60:
        offset = action_idx - 11
        card_slot, enemy_idx = divmod(offset, 5)
        hand = state["player"]["hand"]
        enemies = state["battle"]["enemies"]
        if card_slot >= len(hand) or enemy_idx >= len(enemies):
            return {"action": "invalid"}
        return {
            "action": "play_card",
            "card_index": card_slot,
            "target": enemies[enemy_idx]["combat_id"],
        }

    return {"action": "invalid"}
```

### 4.1 Out-of-scope for Discrete(61) — extension required

| Class | Example | Notes |
| :--- | :--- | :--- |
| Card rewards | Pick 1 of 3 post-combat | `select_card_reward` + `confirm_selection` |
| Map navigation | Next floor node | `choose_map_node` (dynamic node list) |
| Potion use | Use potion N | `use_potion`; up to 3 slots |
| Event choices | Branch picks | `choose_event_option` (variable count) |
| Rest options | rest / upgrade / shop | `choose_rest_option` (3–4) |
| Relic selection | Treasure room | `select_relic` + confirm |
| Card upgrade | Rest-site upgrade | `select_card` + confirm |
| Crystal Sphere | Tools + cells | Sub-game; not a single discrete action |

**Recommendation**: extend to `Discrete(300)` (or use a structured/factored action space) to cover potion, event, map, relic, card-reward, and rest-site actions with fixed max indices.

---

## 5. Menu / Lobby Control — Programmatic Run Start

SP flow:

1. `GET /api/v1/singleplayer` → `state_type == "menu"` with `menu_screen ∈ {singleplayer, main}`
2. `POST {"action": "menu_select", "option": "standard"}` → character select
3. `GET …` → `menu_screen == "character_select"`
4. `POST {"action": "menu_select", "option": "ironclad", "seed": "abc123"}` → selects character (with optional seed)
5. `POST {"action": "menu_select", "option": "confirm"}` → start run
6. `GET …` → `state_type == "map"` (run started)

MP host flow:

1. `POST {"action": "menu_select", "option": "host"}`
2. `POST {"action": "menu_select", "option": "standard"}`
3. Wait for join screen, then character select (same as SP)

Profile switch (`McpMod.Profile.cs`):

```json
POST /api/v1/profiles
{"action": "switch", "profile_id": 2}
```

Response: `{"status": "ok", "message": "...", "current_profile_id": 2}`

---

## 6. Open Questions for Live API Validation

1. **Action queue latency** — How long does the main thread take to dequeue after POST returns? Safe poll interval (e.g. 50–100 ms)?
2. **Hand index persistence** — After playing card at index 0 of a 5-card hand, does the next GET return shifted indices immediately, or are they only valid after the play animation completes?
3. **Target ID stability** — Confirm `combat_id` (e.g. `"gremlin_0"`) is stable across rounds and never reused for a new spawn.
4. **MP turn sync** — After `end_turn` in MP, when does `battle.is_play_phase` flip to false? Immediately (queued) or after other players also end?
5. **Error reporting** — Invalid action: immediate 400/500 vs. silent queue failure? Document the exact error envelope for each failure mode.
