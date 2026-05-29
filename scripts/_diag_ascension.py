"""Localize the floor-17 wall: eval one checkpoint across ascensions.
If it wins at A0 but not A10 -> wall is A10 difficulty.
If it can't win even A0 -> wall is deckbuilding/combat policy (ascension-independent)."""
import sys
from pathlib import Path
from sb3_contrib import MaskablePPO
from scripts.train_v3 import evaluate, resolve_device

ckpt = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("models/v3/arch_h09b_shapetank_best.zip")
n_eps = int(sys.argv[2]) if len(sys.argv) > 2 else 60
device = resolve_device("auto")
model = MaskablePPO.load(ckpt, device=device)
print(f"diag: {ckpt.name}  n_eps={n_eps}  device={device}", flush=True)
print(f"{'asc':>4} {'win':>6} {'mean_act':>9} {'mean_floor':>11} {'mean_hp':>8} {'mean_boss':>10} {'score':>8}")
for asc in (0, 5, 10):
    r = evaluate(model, n_episodes=n_eps, ascension=asc, seed_offset=0)
    print(f"{asc:>4} {r['win_rate']:>6.0%} {r['mean_act']:>9.2f} {r['mean_floor']:>11.2f} "
          f"{r['mean_final_hp']:>8.2f} {r['mean_bosses']:>10.2f} {r['mean_terminal_score']:>8.1f}", flush=True)
