# Phase 7 — Simulator ↔ Real-Game Validation Framework

Goal: prove (or refute, then fix) that `sim/` reproduces the real game's
combat state at the JSON-field level for every action sequence we feed it.
This is the precondition for trusting any policy trained on the simulator.

The channel is the locally-installed STS2_MCP mod (REST on `localhost:15526`).
See `notes/06_mcp_api.md` for the endpoint reference.

---

## 1. Validation Layers (cheap → expensive)

| Layer | Question | Cost | Blocks on |
| :--- | :--- | :--- | :--- |
| **L0 — Schema** | Does the mod's JSON match what `sim/observation.py` expects? | 1 GET request | Game running, mod enabled |
| **L1 — Initial state** | New combat: simulator's player & monster fields match the real game's, given the same seed? | 1 run-start + 1 GET | Same as L0 |
| **L2 — Single action** | Playing a Strike at index 0 produces the same HP delta on the real monster? | 1 POST + 1 GET, with snapshot before | L1 passed |
| **L3 — Full turn** | After EndTurn, monster's intent + applied debuffs match? | 1 POST + 1 GET | L2 passed |
| **L4 — Full combat** | Identical action sequence yields identical terminal state? | N actions/episode | L3 passed |
| **L5 — Statistical** | 30 random policies → same distribution of outcomes? | Slow, batch | L4 passed |
| **L6 — PRNG bit-exact** | Counter-aligned RNG categories produce identical samples? | Needs RNG dump hook | L5 passed; may require Harmony patch |

Cap each layer at "pass = green" before opening the next. A failure at L_n means the simulator deviates somewhere in the implementation; do not paper over it by relaxing the test — debug the underlying assumption first.

---

## 2. Reproducible Run Setup

### 2.1 Seeded run via the mod

Per `notes/06_mcp_api.md` §5, character select supports a `seed` param:

```http
POST /api/v1/singleplayer
{"action": "menu_select", "option": "ironclad", "seed": "0xDEADBEEF"}
POST /api/v1/singleplayer
{"action": "menu_select", "option": "confirm"}
```

The first combat encountered is then a deterministic function of that seed
(modulo any free-text events). Pick a seed whose first combat is the chosen
MVP encounter (`SludgeSpinnerWeak`). If the seed-search is impractical,
instead navigate the map manually to the first standard combat.

### 2.2 Mirror in simulator

Convert the seed via `sim.rng.get_deterministic_hash_code` and feed it into
`CombatState.new_combat(seed=...)`. Currently `sim/` uses `random.Random`, so
**bit-exact RNG match is out of reach until Phase 4 finishes the xoshiro256\*\* port** (notes/04_prng.md §5). Until then, validation focuses on
deterministic-given-actions fields (HP, block, energy, intents) and treats
HP-roll/RNG mismatch as known divergence.

---

## 3. Diff Schema

Validator pulls these fields from both sources and compares:

| Field | Real (MCP JSON path) | Sim (`CombatState` access) |
| :--- | :--- | :--- |
| `player.hp` | `state.player.hp` | `cs.player.hp` |
| `player.max_hp` | `state.player.max_hp` | `cs.player.max_hp` |
| `player.block` | `state.player.block` | `cs.player.block` |
| `player.energy` | `state.player.energy` | `cs.player.energy` |
| `player.weak` | sum of `weak` in `state.player.powers` | `cs.player.get_power("weak").amount` |
| `monster.hp` | `state.battle.enemies[0].hp` | `cs.monster.hp` |
| `monster.block` | `state.battle.enemies[0].block` | `cs.monster.block` |
| `monster.intent_type` | `state.battle.enemies[0].intents[0].type` | derived from `cs.monster.next_move` |
| `monster.intent_amount` | `state.battle.enemies[0].intents[0].amount` | derived from `cs.monster.next_move` damage |
| `monster.vulnerable` | sum of `vulnerable` stacks | `cs.monster.get_power("vulnerable").amount` |
| `monster.strength` | same | `cs.monster.get_power("strength").amount` |
| `hand_size` | `len(state.player.hand)` | `len(cs.hand)` |
| `hand[i].id` | `state.player.hand[i].id` | `cs.hand[i].id` |
| `draw_pile_count` | `state.player.draw_pile_count` | `len(cs.draw_pile)` |
| `discard_pile_count` | `state.player.discard_pile_count` | `len(cs.discard_pile)` |
| `turn_number` | `state.battle.round` | `cs.turn_number` |

Two-tier diff:

- **Hard fields** (must match): `monster.hp`, `monster.block`, `player.hp`, `player.block`, intent type. Fail loudly.
- **Soft fields** (warn, may diverge due to known RNG mismatch in MVP): hand contents, draw/discard ordering, intent amount when buffed by `strength`.

---

## 4. Test Scenarios

Each scenario is a Python list of `(action, target?)` tuples replayed against
both engines. Compare diffs after every step.

| ID | Goal | Sequence |
| :--- | :--- | :--- |
| **V01** | Initial state | reset + read state, no actions |
| **V02** | Single Strike | play Strike → expect monster.hp -= 6 |
| **V03** | Single Defend | play Defend → expect player.block += 5 |
| **V04** | End turn alone | end_turn → expect player.hp -= OIL_SPRAY damage, weak applied |
| **V05** | Bash combo | play Bash → expect vulnerable=2; play Strike → expect monster.hp -= 9 |
| **V06** | Vulnerable durability | Bash + end_turn × 2 → expect vulnerable amount ticks at end of monster turn |
| **V07** | Weak effect on player | take Weak from monster, play Strike next turn → expect 6 × 0.75 = 4 dmg |
| **V08** | Strength stack | survive RAGE → next monster attack deals base + 3 |
| **V09** | Full combat clear | scripted "always play biggest attack" policy → both engines terminate same turn with same HP |
| **V10** | Random policy ×30 | identical RNG seed, compare distributions; statistical pass = ≥95% of episodes diverge by ≤2 HP at any turn |

V01–V05 are smoke; V06–V08 catch the Phase 5 §F open questions (power timing).
V09–V10 catch accumulated drift.

---

## 5. Validator Implementation Sketch

```python
# scripts/validate.py — to be implemented after smoke test passes
import requests
from sim.env import SludgeSpinnerEnv
from sim.combat import CombatState

BASE = "http://localhost:15526"

def get_real_state():
    return requests.get(f"{BASE}/api/v1/singleplayer", timeout=3).json()

def post_action(body: dict):
    r = requests.post(f"{BASE}/api/v1/singleplayer", json=body, timeout=3)
    r.raise_for_status()
    return r.json()

def project_real(state: dict) -> dict:
    """Pull hard-diff fields from MCP JSON into a flat dict."""
    p, b = state["player"], state["battle"]
    e = b["enemies"][0]
    return {
        "player_hp": p["hp"],
        "player_block": p["block"],
        "player_energy": p.get("energy", 0),
        "monster_hp": e["hp"],
        "monster_block": e["block"],
        "monster_intent": e["intents"][0]["type"],
        "turn": b["round"],
    }

def project_sim(cs: CombatState) -> dict:
    return {
        "player_hp": cs.player.hp,
        "player_block": cs.player.block,
        "player_energy": cs.player.energy,
        "monster_hp": cs.monster.hp,
        "monster_block": cs.monster.block,
        "monster_intent": _intent_of(cs.monster.next_move),
        "turn": cs.turn_number,
    }

def diff(a: dict, b: dict) -> list[tuple[str, object, object]]:
    return [(k, a[k], b[k]) for k in a if a[k] != b[k]]
```

Hard-diff fields produce a list of `(field, real, sim)` mismatches. Validator
prints the first mismatch per scenario and exits non-zero on any.

---

## 6. Known Caveats Going In

1. **RNG mismatch is expected (MVP)**: `sim/rng.py` is a placeholder. Initial monster HP, draw order, and any RNG-using monster move will differ between real and sim. Validator must whitelist these as known-divergent until Phase 4's xoshiro256\*\* port is finished and seeded identically.

2. **Power tick timing**: notes/05_mvp_combat_spec.md §F flagged this as open. Simulator currently uses "owner-turn-end" rule (notes/07 §3 above). V06/V07/V08 will tell us whether the real game agrees. **Expect V06 or V07 to be the first failing scenario.** That failure is the most valuable result of Phase 7 — it pins down the rule we guessed.

3. **Floating-point determinism risk**: `notes/04_prng.md` §6 flagged `NextUnsignedInt` as FP-sensitive. Monster HP roll is the easiest place to observe this — if hp-roll-with-same-seed differs between Python `random.Random` and the real .NET stream, that's a known-divergent field.

4. **Mod-side latency**: POST returns when the action is queued, not when it's resolved (notes/06_mcp_api.md §3.4). Validator must poll state until `is_play_phase` reflects the expected post-action condition before reading. Suggested: poll every 50 ms with a 2 s timeout.

5. **Hand contents**: even with identical seed, the simulator may shuffle differently. Treat hand contents as soft-diff in MVP, hard-diff only after PRNG port.

---

## 7. Acceptance Criteria

Phase 7 closes when:

- V01–V05: hard-diff fields match in **100% of trials**.
- V06–V08: hard-diff fields match in **100% of trials**. Any divergence here means the simulator's power-tick rule is wrong — fix `sim/combat.py::_tick_powers` and re-run.
- V09: end-of-combat `monster.hp / player.hp / turn_number` match within ±0 (hard-diff) given an identical action sequence and same starting state (HP roll mismatch tolerated as soft-diff).
- V10: ≥95% of 30 random-policy episodes show no hard-diff at any step (statistical test).

PRNG bit-exact (L6) is **out of scope** until Phase 4 finishes the xoshiro256** port; reaching it requires extracting test vectors via either a Harmony hook on `Rng.NextInt` or by instrumenting `TestRngInjector`.

---

## 8. Order of Operations

1. User starts the game, accepts the consent dialog, enables STS2_MCP.
2. Run `scripts/smoke_test_mcp.py`. All probes PASS → proceed.
3. Write `scripts/validate.py` with V01.
4. Manually navigate (or `menu_select` with seed) until the active fight is `SludgeSpinnerWeak`.
5. Run V01. Iterate on field-mapping mismatches until clean.
6. Add V02–V05, run incrementally.
7. Run V06–V08. **This is where bugs are likely found.** Fix `sim/` to match real-game behavior.
8. Run V09, then V10.
9. Document findings in `notes/07_validation_results.md` (one paragraph per V).
