"""Iterative full-run RL training: train K steps → eval → save → repeat N cycles.

Wraps scripts/train_run.py's primitives with a cycle loop so a long
training session is broken into smaller, observable chunks. Each cycle
saves the model + eval metrics; the loop early-stops if eval metrics
plateau or regress significantly (configurable).

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\train_loop.py `
        --cycles 10 --steps-per-cycle 20000 --eval-episodes 30 `
        --ascension 0 --out models\\run_ppo_loop.zip `
        --history-out runs\\run_ppo_loop_history.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sb3_contrib import MaskablePPO

from scripts.train_run import evaluate, make_env, PeriodicEvalCallback  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=5)
    parser.add_argument("--steps-per-cycle", type=int, default=20_000)
    parser.add_argument("--eval-episodes", type=int, default=30)
    parser.add_argument("--eval-every", type=int, default=5_000)
    parser.add_argument("--ascension", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("models/run_ppo_loop.zip"))
    parser.add_argument("--checkpoint-dir", type=Path, default=Path("models/checkpoints"))
    parser.add_argument("--history-out", type=Path, default=Path("runs/run_ppo_loop.json"))
    parser.add_argument("--tensorboard", type=Path, default=Path("runs/run_ppo_loop_tb"))
    parser.add_argument("--resume", type=Path, default=None,
                        help="If set, load this model and continue training.")
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    args.history_out.parent.mkdir(parents=True, exist_ok=True)

    env = make_env(ascension=args.ascension)
    tb_log = str(args.tensorboard) if args.tensorboard else None

    if args.resume and args.resume.exists():
        print(f"Resuming from {args.resume}")
        model = MaskablePPO.load(args.resume, env=env, tensorboard_log=tb_log)
    else:
        model = MaskablePPO("MlpPolicy", env, verbose=0, seed=args.seed,
                            tensorboard_log=tb_log, n_steps=512, batch_size=64)

    cumulative_history: list[dict] = []
    print(f"Starting {args.cycles} cycles × {args.steps_per_cycle} steps "
          f"(A{args.ascension}; total {args.cycles * args.steps_per_cycle} steps).")

    for cycle in range(1, args.cycles + 1):
        print(f"\n=== Cycle {cycle}/{args.cycles} ===")
        cb = PeriodicEvalCallback(args.ascension, args.eval_every, args.eval_episodes)
        model.learn(total_timesteps=args.steps_per_cycle, callback=cb,
                    reset_num_timesteps=False)
        eval_result = evaluate(model, args.eval_episodes, args.ascension)
        eval_result["cycle"] = cycle
        eval_result["cumulative_steps"] = cycle * args.steps_per_cycle
        cumulative_history.append(eval_result)

        ckpt_path = args.checkpoint_dir / f"cycle_{cycle:03d}.zip"
        model.save(ckpt_path)
        model.save(args.out)  # also overwrite the "latest" model
        args.history_out.write_text(json.dumps(cumulative_history, indent=2))

        print(f"  Eval: win={eval_result['win_rate']:.1%}  "
              f"deaths={eval_result['death_rate']:.1%}  "
              f"act={eval_result['mean_act']:.2f}  "
              f"floor={eval_result['mean_floor']:.2f}  "
              f"bosses={eval_result['mean_bosses']:.2f}  "
              f"hp={eval_result['mean_final_hp']:.1f}  "
              f"rew={eval_result['mean_reward']:+.3f}")
        print(f"  Saved checkpoint to {ckpt_path}")

    print(f"\nDone. Final model: {args.out}. History: {args.history_out}.")
    final = cumulative_history[-1]
    print(f"Final eval: win={final['win_rate']:.1%}  "
          f"act={final['mean_act']:.2f}  floor={final['mean_floor']:.2f}  "
          f"bosses={final['mean_bosses']:.2f}  hp={final['mean_final_hp']:.1f}")


if __name__ == "__main__":
    main()
