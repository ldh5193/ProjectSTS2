"""Phase 7 validation harness -sim/ ↔ real-game-via-STS2MCP cross-check.

Implements V01–V05 from notes/07_validation.md. V06+ are stubs to be
expanded after the simpler scenarios pass.

Usage (after game running, mod active, in a SludgeSpinnerWeak fight):
  ./.venv/bin/python scripts/validate.py
  ./.venv/bin/python scripts/validate.py --scenario V02

The harness exits non-zero on any hard-diff mismatch.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from sim.combat import CombatState

BASE = "http://localhost:15526"
TIMEOUT = 3.0


# ---------- low-level HTTP wrappers ----------


def _check_reachable() -> bool:
    try:
        r = requests.get(f"{BASE}/", timeout=TIMEOUT)
        return r.status_code == 200
    except requests.exceptions.RequestException:
        return False


def get_state() -> dict:
    r = requests.get(f"{BASE}/api/v1/singleplayer", timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def post_action(body: dict) -> dict:
    r = requests.post(f"{BASE}/api/v1/singleplayer", json=body, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def wait_for_play_phase(max_wait_s: float = 2.0) -> dict:
    """Poll state until is_play_phase becomes true again (action resolved)."""
    deadline = time.monotonic() + max_wait_s
    last = None
    while time.monotonic() < deadline:
        last = get_state()
        battle = last.get("battle")
        if battle and battle.get("is_play_phase"):
            return last
        time.sleep(0.05)
    return last or {}


# ---------- projection: extract hard-diff fields from each engine ----------


def project_real(state: dict) -> dict:
    p = state.get("player", {})
    b = state.get("battle", {}) or {}
    enemies = b.get("enemies") or []
    e = enemies[0] if enemies else {}
    intents = e.get("intents") or []
    intent_type = intents[0].get("type") if intents else None
    powers_p = {pw["id"]: pw.get("amount", 1) for pw in p.get("powers", [])}
    powers_e = {pw["id"]: pw.get("amount", 1) for pw in e.get("powers", [])}
    return {
        "player_hp": p.get("hp"),
        "player_block": p.get("block"),
        "player_energy": p.get("energy"),
        "player_weak": powers_p.get("weak", 0),
        "monster_hp": e.get("hp"),
        "monster_block": e.get("block"),
        "monster_vulnerable": powers_e.get("vulnerable", 0),
        "monster_strength": powers_e.get("strength", 0),
        "monster_intent": intent_type,
        "turn": b.get("round"),
    }


def project_sim(cs: CombatState) -> dict:
    intent = None
    if cs.monster.next_move is not None:
        intent_map = {"oil_spray": "attack", "slam": "attack", "rage": "attack"}
        intent = intent_map.get(cs.monster.next_move.value, cs.monster.next_move.value)
    weak = cs.player.get_power("weak")
    vuln = cs.monster.get_power("vulnerable")
    strg = cs.monster.get_power("strength")
    return {
        "player_hp": cs.player.hp,
        "player_block": cs.player.block,
        "player_energy": cs.player.energy,
        "player_weak": weak.amount if weak else 0,
        "monster_hp": cs.monster.hp,
        "monster_block": cs.monster.block,
        "monster_vulnerable": vuln.amount if vuln else 0,
        "monster_strength": strg.amount if strg else 0,
        "monster_intent": intent,
        "turn": cs.turn_number,
    }


HARD_FIELDS = {
    "player_hp", "player_block", "player_energy", "player_weak",
    "monster_hp", "monster_block", "monster_vulnerable", "monster_strength",
    "monster_intent", "turn",
}


def diff(real: dict, sim: dict) -> list[tuple[str, object, object]]:
    out: list[tuple[str, object, object]] = []
    for k in HARD_FIELDS:
        rv, sv = real.get(k), sim.get(k)
        if rv != sv:
            out.append((k, rv, sv))
    return out


# ---------- scenarios ----------


def v01_initial_state(cs: CombatState) -> list:
    real = project_real(get_state())
    sim = project_sim(cs)
    return diff(real, sim)


def _find_card_index(cs: CombatState, card_id: str) -> int:
    for i, c in enumerate(cs.hand):
        if c.id == card_id:
            return i
    raise RuntimeError(f"{card_id} not in opening hand; reshuffle and retry")


def v02_strike(cs: CombatState) -> list:
    idx = _find_card_index(cs, "strike_ironclad")
    # POST first, then mirror in sim so both engines step.
    post_action({"action": "play_card", "card_index": idx,
                 "target": _enemy_id_or_default()})
    cs.play_card(idx)
    wait_for_play_phase()
    return diff(project_real(get_state()), project_sim(cs))


def v03_defend(cs: CombatState) -> list:
    idx = _find_card_index(cs, "defend_ironclad")
    post_action({"action": "play_card", "card_index": idx})
    cs.play_card(idx)
    wait_for_play_phase()
    return diff(project_real(get_state()), project_sim(cs))


def v04_end_turn(cs: CombatState) -> list:
    post_action({"action": "end_turn"})
    cs.end_player_turn()
    wait_for_play_phase()
    return diff(project_real(get_state()), project_sim(cs))


def v05_bash_combo(cs: CombatState) -> list:
    bash_idx = _find_card_index(cs, "bash")
    post_action({"action": "play_card", "card_index": bash_idx,
                 "target": _enemy_id_or_default()})
    cs.play_card(bash_idx)
    wait_for_play_phase()
    d1 = diff(project_real(get_state()), project_sim(cs))
    if d1:
        return d1
    strike_idx = _find_card_index(cs, "strike_ironclad")
    post_action({"action": "play_card", "card_index": strike_idx,
                 "target": _enemy_id_or_default()})
    cs.play_card(strike_idx)
    wait_for_play_phase()
    return diff(project_real(get_state()), project_sim(cs))


def _enemy_id_or_default() -> str:
    enemies = get_state().get("battle", {}).get("enemies") or []
    return enemies[0]["combat_id"] if enemies else "0"


SCENARIOS = {
    "V01": v01_initial_state,
    "V02": v02_strike,
    "V03": v03_defend,
    "V04": v04_end_turn,
    "V05": v05_bash_combo,
}


# ---------- driver ----------


def _wait_for_combat(timeout_s: float, poll_s: float = 1.0) -> dict | None:
    """Poll state until the game enters a combat encounter (state_type in
    {'monster', 'elite'}) or the timeout elapses. Returns the first combat
    state observed, or None on timeout."""
    deadline = time.monotonic() + timeout_s
    last_kind = None
    while time.monotonic() < deadline:
        state = get_state()
        kind = state.get("state_type")
        if kind in ("monster", "elite"):
            return state
        if kind != last_kind:
            last_kind = kind
            print(f"  waiting for combat... (state={kind})")
        time.sleep(poll_s)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario", choices=sorted(SCENARIOS), default=None,
        help="Run a single scenario; default runs all in order."
    )
    parser.add_argument("--seed", type=int, default=42,
                        help="Simulator seed. NOTE: until we can derive the same "
                             "uint seed the game's RunRngSet was built with, the "
                             "monster HP roll and hand order will diverge from the "
                             "real game -those fields are soft-diff for now.")
    parser.add_argument("--wait", type=float, default=0.0,
                        help="Seconds to wait for the game to enter combat before "
                             "giving up. Default 0 = require combat already active.")
    args = parser.parse_args()

    if not _check_reachable():
        print(f"FAIL: cannot reach {BASE}. Is the game running with STS2_MCP enabled?",
              file=sys.stderr)
        print("Run scripts/smoke_test_mcp.py first.", file=sys.stderr)
        return 2

    real0 = get_state()
    if real0.get("state_type") not in ("monster", "elite"):
        if args.wait <= 0:
            print(f"FAIL: not in a combat state (got state_type={real0.get('state_type')}).",
                  file=sys.stderr)
            print("Navigate to a SludgeSpinner Weak fight, then re-run, or pass "
                  "--wait <seconds> to poll until combat starts.", file=sys.stderr)
            return 2
        print(f"Waiting up to {args.wait}s for combat to start...")
        real0 = _wait_for_combat(args.wait)
        if real0 is None:
            print("FAIL: timeout waiting for combat.", file=sys.stderr)
            return 2

    # Surface the actual encounter we landed in -V01-V05 are written against
    # SludgeSpinnerWeak, so a different encounter means the hard fields will
    # diverge and the failure mode should look obvious.
    enemies = real0.get("battle", {}).get("enemies") or []
    encounter_ids = [e.get("id") or e.get("model_id") or "?" for e in enemies]
    print(f"Real engine reachable, combat in progress: {encounter_ids}.\n")
    if not any("SludgeSpinner" in str(eid) for eid in encounter_ids):
        print(f"WARNING: simulator only models SludgeSpinnerWeak; current encounter "
              f"is {encounter_ids}. Hard-diff failures are expected.\n")

    # Build a sim combat in lockstep. The PRNG core is now bit-exact to .NET's
    # seeded Random (tests/test_rng_oracle.py), but the simulator's combat
    # currently still uses Python's `random.Random` and a Python-side seed; the
    # category/seed plumbing from RunRngSet hasn't been wired in yet. So HP
    # rolls and hand order may still diverge -those are tracked as soft fields.
    cs = CombatState.new_combat(seed=args.seed)
    cs.start_player_turn()

    targets = [args.scenario] if args.scenario else ["V01", "V02", "V03", "V04", "V05"]
    fails = 0
    for name in targets:
        scenario = SCENARIOS[name]
        try:
            mismatches = scenario(cs)
        except Exception as e:
            print(f"[{name}] ERROR: {type(e).__name__}: {e}")
            fails += 1
            continue
        if mismatches:
            print(f"[{name}] FAIL -{len(mismatches)} field(s) diverge:")
            for field, rv, sv in mismatches:
                print(f"    {field:24s}  real={rv!r:20s}  sim={sv!r}")
            fails += 1
        else:
            print(f"[{name}] PASS")

    print()
    print(json.dumps({"scenarios": len(targets), "fails": fails}, indent=2))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
