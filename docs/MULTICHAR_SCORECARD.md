# Multi-Character Fidelity Scorecard

Date: 2026-06-01
Status: **Phase 9.0 (SCAFFOLD) complete** — multi-character foundation +
obs v5 (504 -> 560). No character CONTENT (cards/relics/powers/primitives)
is implemented yet beyond Ironclad; the four new characters are scaffold-only.

See `docs/MULTICHAR_FIDELITY_PLAN.md` for the authoritative plan (roster,
obs v5 layout, primitives, batch order) and `docs/FIDELITY_AUDIT.md` for the
Ironclad critical-path audit.

---

## Per-character status

| Character   | Start setup | Card pool | Relics | Primitive | Critical-path fidelity | Batch |
|-------------|:-----------:|:---------:|:------:|:---------:|:----------------------:|:-----:|
| Ironclad    | done | done (87) | done | n/a | **100%** (Ironclad audit) | shipped |
| Silent      | scaffold | TODO (88) | TODO (8) | poison/shiv/discard TODO | scaffold-only | P9.1 |
| Defect      | scaffold | TODO (88) | TODO (8) | **orbs** TODO | scaffold-only | P9.2 |
| Necrobinder | scaffold | TODO (88) | TODO (8) | **osty** TODO | scaffold-only | P9.3 |
| Regent      | scaffold | TODO (88) | TODO (8) | **stars** TODO | scaffold-only | P9.4 |
| Deprived    | fixture | fallback | fallback | n/a | debug fixture (not a target) | n/a |

"scaffold" = the character can be constructed, reset, masked, and stepped at
A0 (its starting HP / gold / relic / deck / energy / orb-slot count are
faithful), but its signature cards/relics/powers are TODO stubs with no real
effect.

---

## What P9.0 (scaffold) delivered

### obs v5 (504 -> 560), additive tail
The v4.4 layout `[0..504)` is **byte-identical** for Ironclad (verified by
`tests/test_multichar_scaffold.py` + the existing shop-obs tests, which now
anchor on `OBS_DIM_V4_4 = 504`). The new tail `[504..560)`:

| Indices | Dims | Field | Filled by |
|---------|-----:|-------|-----------|
| `[504..510)` | 6 | character one-hot (ironclad/silent/defect/necrobinder/regent + pad) | **P9.0 (live)** |
| `[510..511)` | 1 | star resource / 10 | P9.4 |
| `[511..521)` | 10 | orb-queue slot type-ids / 5 | P9.2 |
| `[521..531)` | 10 | orb-queue evoke values / 30 | P9.2 |
| `[531..532)` | 1 | orb capacity / 10 | P9.2 |
| `[532..533)` | 1 | focus / 10 | P9.2 |
| `[533..537)` | 4 | osty present / hp / block / pad | P9.3 |
| `[537..541)` | 4 | per-enemy poison / 20 | P9.1 |
| `[541..560)` | 19 | pad to a clean 560 | — |

Only the character one-hot carries a value in P9.0; every mechanic slot is 0
until its batch lands. Ironclad's whole tail is 0 except the `[504]` bit.

### Per-character starting setup (`sim/game_state.py`)
StartHP (Ironclad 80 / Silent 70 / Defect 75 / Necrobinder 66 / Regent 75),
StartGold 99, base energy 3, orb-slot count (Defect 3, else 0), starting relic,
and starting deck are now dispatched off the `Character` enum. Non-Ironclad
signature starter cards/relics are faithful-shaped **TODO stubs** (no
fabricated effects) so `new_run` never crashes.

### Per-character pools (`sim/card_catalog.py`, `sim/relics.py`, `sim/rewards.py`)
`CHARACTER_CARD_POOLS` (card-reward pool) and `_CHARACTER_RELIC_POOL_IDS`
(character-exclusive relics) are keyed by character. Ironclad is fully
populated; the other four are empty and **fall back to the Ironclad pool**
during scaffold training so the card-reward path never produces an empty /
crashing reward. `generate_card_reward(..., character=...)` selects the pool.

### Warm-start padding (`scripts/train_v3.py`)
`pad_state_dict_for_obs_change` zero-pads any first-layer weight whose
in_features == 504 out to 560; `warm_start_load` tries a plain
`MaskablePPO.load` and falls back to the padded graft on shape mismatch. A
504-dim Ironclad checkpoint (h21b/h24) warm-starts into the 560-dim v5 obs
with bit-identical Ironclad logits at step 0. `--characters` CSV flag added
(P9.0 uses the first; full per-episode sampling is P9.7).

---

## Known TODOs flagged in code (next batches)

- `TODO(P9.1)` Silent: Neutralize/Survivor real effects, RingOfTheSnake,
  PoisonPower, Shiv token, Accuracy, discard hooks, 88 cards, 8 relics.
- `TODO(P9.2)` Defect: orb primitive (`sim/orbs.py`), Zap/Dualcast, CrackedCore,
  FocusPower, 88 cards, 8 relics, obs orb/focus slots.
- `TODO(P9.3)` Necrobinder: Osty minion primitive, Bodyguard/Unleash,
  BoundPhylactery, MinionPower, 88 cards, 8 relics, obs osty slots.
- `TODO(P9.4)` Regent: Star resource primitive, FallingStar/Venerate,
  DivineRight, star powers, 88 cards, 8 relics, obs star slot.

---

## Mod parity (BLOCKED — user Unity/Godot build)

The OBS_DIM change 504 -> 560 means `tools/STS2MCP-src/McpMod.ObsBuilder.cs`
(the C# obs mirror) is now **out of parity** with the sim. The mod must emit
the v5 tail (character id + orb/star/osty/poison) identically before any
multi-character model can be deployed live. This requires a Unity/Godot mod
rebuild + ONNX re-export (P9.6) and is a **user task** — the C#/Steam folder
was intentionally NOT edited in this batch. Multi-character models can be
trained and evaluated **in-sim** in the meantime.
