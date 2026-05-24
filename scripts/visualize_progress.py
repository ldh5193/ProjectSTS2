"""Cross-sweep progress summary - overlays the entire cycle-E trajectory.

Reads runs/sweeps/*.json and runs/sweeps/<preset>_history-like files,
draws a single 2x2 grid showing how win rate / boss kills / floor /
HP evolved as the sim got richer (placeholder -> real bosses -> Tier-1
powers -> Underdocks bosses -> multi-monster).

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\visualize_progress.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np


# Hand-collected cycle E results (the live training output is in
# C:\Users\DHLee\AppData\Local\Temp\... transcripts; collating the final
# numbers here keeps the chart self-contained).
# Each entry: (sweep_label, sim_state_change, {preset: (win, bosses, floor, hp)})
SWEEPS = [
    ("Sweep 3", "first real combat",
     {"sparse": (36.7, 1.57, 10.73, 24.3),
      "aggressive": (36.7, 1.50, 10.77, 25.3),
      "default": (23.3, 1.30, 10.33, 15.8),
      "dense_floor": (20.0, 1.10, 9.77, 13.7)}),
    ("Sweep 4", "+survival preset",
     {"survival": (40.0, 1.60, 9.97, 25.7),
      "sparse": (36.7, 1.57, 10.73, 24.3),
      "aggressive": (36.7, 1.50, 10.77, 25.3),
      "boss_heavy": (33.3, 1.33, 11.47, 18.4)}),
    ("Sweep 5", "+real Act-1 bosses",
     {"sparse": (15.0, 0.62, 12.70, 9.7),
      "boss_heavy": (12.5, 0.50, 13.10, 7.8),
      "survival": (10.0, 0.60, 12.65, 7.2),
      "aggressive": (7.5, 0.35, 13.25, 4.9)}),
    ("Sweep 7", "+working Tier-1 powers",
     {"survival": (17.5, 0.72, 13.18, 13.0),
      "sparse": (15.0, 0.55, 13.65, 8.0),
      "boss_heavy": (10.0, 0.45, 13.60, 5.2),
      "aggressive": (7.5, 0.40, 12.82, 3.6)}),
    ("Sweep 8", "+HP-aware presets",
     {"survival_v2": (15.0, 0.62, 13.95, 9.8),
      "survival": (15.0, 0.57, 13.72, 11.6),
      "tank": (12.5, 0.62, 12.97, 7.8),
      "sparse": (5.0, 0.30, 12.95, 2.8)}),
    ("Sweep 9", "+real Act-2/3 bosses",
     {"survival": (15.0, 0.62, 12.97, 9.7),
      "boss_heavy": (5.0, 0.33, 13.22, 3.5),
      "survival_v2": (5.0, 0.47, 12.95, 3.4),
      "tank": (2.5, 0.47, 13.43, 1.5)}),
    ("Sweep 10", "+700K longer training",
     {"survival": (15.0, 0.68, 13.70, 9.0),
      "sparse": (12.5, 0.60, 13.50, 8.1),
      "boss_heavy": (7.5, 0.38, 13.50, 4.7),
      "survival_v2": (5.0, 0.42, 13.03, 3.8)}),
    ("Sweep 11", "+Underdocks bosses, 800K",
     {"tank": (15.0, 0.65, 13.72, 10.5),
      "sparse": (12.5, 0.60, 13.22, 8.6),
      "survival": (5.0, 0.47, 13.32, 3.4),
      "survival_v2": (5.0, 0.42, 13.35, 3.0)}),
    ("Sweep 13", "1M each",
     {"tank": (12.0, 0.56, 14.28, 7.6),
      "boss_heavy": (12.0, 0.60, 13.36, 6.8),
      "sparse": (8.0, 0.62, 12.58, 6.0),
      "survival": (4.0, 0.40, 12.78, 2.5)}),
    ("Sweep 15", "lower lr 1.5e-4",
     {"sparse": (12.0, 0.66, 12.70, 7.2),
      "balanced": (8.0, 0.44, 12.70, 6.1),
      "tank": (6.0, 0.34, 13.62, 4.4),
      "survival": (2.0, 0.32, 13.52, 1.5)}),
    ("Sweep 16", "higher lr 5e-4",
     {"sparse": (8.0, 0.62, 12.84, 4.5),
      "balanced": (8.0, 0.46, 13.02, 4.3),
      "boss_heavy": (6.0, 0.44, 13.12, 4.2),
      "tank": (6.0, 0.50, 12.84, 3.9)}),
]


def main() -> None:
    sweep_labels = [s[0] for s in SWEEPS]
    sweep_subtitles = [s[1] for s in SWEEPS]

    # Best preset per sweep (highest win, then bosses as tiebreak).
    best_per_sweep = []
    for _, _, results in SWEEPS:
        best_preset = max(results, key=lambda p: (results[p][0], results[p][1]))
        w, b, f, h = results[best_preset]
        best_per_sweep.append((best_preset, w, b, f, h))

    wins = [x[1] for x in best_per_sweep]
    bosses = [x[2] for x in best_per_sweep]
    floors = [x[3] for x in best_per_sweep]
    hps = [x[4] for x in best_per_sweep]
    presets = [x[0] for x in best_per_sweep]

    fig, axes = plt.subplots(2, 2, figsize=(15, 9))
    x = np.arange(len(SWEEPS))
    width = 0.6

    ax = axes[0, 0]
    bars = ax.bar(x, wins, width, color="tab:blue")
    ax.set_title("Best preset win rate per sweep (%)")
    ax.set_xticks(x)
    ax.set_xticklabels(sweep_labels)
    ax.grid(alpha=0.3, axis="y")
    for i, (bar, p) in enumerate(zip(bars, presets)):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.5,
                p, ha="center", va="bottom", fontsize=8, rotation=0)
    ax.set_ylim(0, max(wins) * 1.3)

    ax = axes[0, 1]
    ax.bar(x, bosses, width, color="tab:purple")
    ax.set_title("Best preset mean boss kills per sweep")
    ax.set_xticks(x)
    ax.set_xticklabels(sweep_labels)
    ax.grid(alpha=0.3, axis="y")

    ax = axes[1, 0]
    ax.bar(x, floors, width, color="tab:orange")
    ax.set_title("Best preset mean floor reached")
    ax.set_xticks(x)
    ax.set_xticklabels(sweep_labels)
    ax.set_xlabel("sweep")
    ax.grid(alpha=0.3, axis="y")
    # Reference line for boss floor (16).
    ax.axhline(y=16, color="red", linestyle="--", alpha=0.5, label="boss floor 16")
    ax.legend(loc="lower right", fontsize=8)

    ax = axes[1, 1]
    ax.bar(x, hps, width, color="tab:green")
    ax.set_title("Best preset mean final HP")
    ax.set_xticks(x)
    ax.set_xticklabels(sweep_labels)
    ax.set_xlabel("sweep")
    ax.grid(alpha=0.3, axis="y")

    fig.suptitle("Cycle E - full-run RL training progress across 11 sweeps\n"
                 "(each bar = best preset of that sweep; subtitles below note the sim change)",
                 fontsize=12)
    fig.tight_layout(rect=[0, 0.04, 1, 0.96])
    # subtitles under each bar group
    for i, sub in enumerate(sweep_subtitles):
        fig.text(0.5 / len(SWEEPS) + i / len(SWEEPS) * 0.95 + 0.025,
                 0.01, sub, ha="center", fontsize=7, style="italic",
                 color="dimgray", rotation=0)

    out = Path("runs/cycle_e_summary.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120, bbox_inches="tight")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
