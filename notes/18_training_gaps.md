# Training pipeline gaps audit — 2026-05-25

## Why this file exists

We hit a wall around 10% win rate on the full-run env. The user noticed three
specific symptoms: potions never used, status effects ignored, card play
order looking random. The systematic audit below confirms those are tips of a
larger iceberg — the observation vector is missing most of the in-combat
semantics that a real Slay-the-Spire policy needs.

## Round-1 fixes (this commit)

| Gap | Old | New |
|---|---|---|
| **Player status effects** invisible | `_obs` had only hp/block/energy | 5 features: strength, vulnerable, weak, dexterity, frail |
| **Monster status effects** invisible | only hp/block/round | 3 features (str, vuln, weak) for first enemy |
| **Enemy intent** invisible | not in obs | `is_attacking_next_turn` flag for first enemy |
| **Card identity in hand** invisible (only `len(hand)`) | n/a | 30 features: per-slot {cost/3, is_attack, can_play} for 10 slots |
| **Multi-monster** invisible past first | only mon1 | mon2 + mon3: hp / block / vuln / is_alive (4 each) |
| **Pile sizes** missing | only `len(draw_pile)` | draw / discard / exhaust pile sizes |
| **Potions never picked** by policy | no mask predicate | new `_potion_mask`: slot legal when occupied + usable in current state |
| **Potion slots** invisible to obs | no | 3 features: is_potion_in_slot[0..2] |

OBS_DIM grows 64 → 128. Existing trained models become incompatible —
intentional, the previous policies were essentially blind. The 35-d trailing
padding leaves headroom for round-2 additions without another break.

## Round-2 (next, deferred)

- Real rest_site choice point (sim/run_engine.py:_enter_room: REST currently
  auto-heals 30% and bounces to MAP, never lets policy pick rest vs smith).
- Real event branching (same pattern; currently auto-+2 HP).
- Real shop with gold cost + purchase decisions.
- Real treasure relic selection (currently grants placeholder).
- Curse + Status card types (sim/dsl.py:CardType has only ATTACK/SKILL/POWER).
- Retain / Innate / Ethereal / Exhaust-on-end keywords in card DSL.
- Power-decay coverage: only Weak/Vulnerable tick today; Frail/Vigor missing.
- Boss-specific mechanics (Hexaghost charging, Slime Boss split, Guardian flip).

## Round-3 — reward shaping (decisions still open)

- Deck-bloat penalty per added card past N=15-20 → encourage skipping bad cards
- Unused-potion-on-death penalty → encourage drinking
- Wasted-energy-at-end-of-turn penalty → encourage filling the turn
- Reduced HP-delta-weight scaling at low HP (preserve HP penalty doesn't crush)

## Verification protocol after round-1

1. `pytest tests/` should pass with new OBS_DIM = 128
2. Smoke train (5K steps × `tank_plus`) — check log shows `PPO device=cpu`,
   step lines emitting, reward not pinned to `-living_cost × max_steps`
3. Full sweep (300K × 4 presets) — expect win rate > 10% if obs v2 helps
4. New ONNX export + mod redeploy at `tools/STS2MCP-bin/policy.onnx` (110-120 KB)
   — verify policy.onnx size grows proportional to first-layer width (64→128 input)
