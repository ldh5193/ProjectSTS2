"""Parallel multi-worker + reward-sweep RL trainer.

Two parallelism axes:

1. Within a single experiment: SubprocVecEnv runs N RunEnv workers in
   parallel processes so PPO collects rollouts much faster.
2. Across experiments: --presets foo,bar,baz launches one process per
   reward preset, each with its own VecEnv. Final checkpoints land in
   models/sweeps/<preset>/, with per-step eval JSON in runs/sweeps/.

Usage (single preset, 8 workers):
    .\\.venv\\Scripts\\python.exe scripts\\train_parallel.py `
        --preset default --workers 8 --steps 200000 --eval-episodes 30

Usage (sweep 4 presets in parallel):
    .\\.venv\\Scripts\\python.exe scripts\\train_parallel.py `
        --presets default,aggressive,defensive,dense_floor `
        --workers 4 --steps 150000
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import SubprocVecEnv, DummyVecEnv

from sim.env_run import REWARD_PRESETS, RewardConfig, RunEnv
from sim.game_state import Character


def _mask_fn(env):
    return env.action_masks()


def make_env_factory(ascension: int, reward_cfg: RewardConfig, seed_offset: int):
    def _f():
        env = ActionMasker(RunEnv(ascension=ascension, reward_config=reward_cfg), _mask_fn)
        return env
    return _f


def evaluate_solo(model, ascension: int, reward_cfg: RewardConfig,
                  n_episodes: int, seed_base: int = 100_000) -> dict:
    """Solo (non-vectorized) eval for clean per-episode aggregates."""
    env = ActionMasker(RunEnv(ascension=ascension, reward_config=reward_cfg), _mask_fn)
    wins = 0
    deaths = 0
    final_acts, final_floors, final_hps, bosses, rewards, lengths = [], [], [], [], [], []
    for ep in range(n_episodes):
        obs, info = env.reset(seed=seed_base + ep)
        ep_reward, ep_bosses, steps = 0.0, 0, 0
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            action, _ = model.predict(obs, action_masks=mask, deterministic=True)
            obs, reward, term, _, info = env.step(int(action))
            ep_reward += reward
            result = info.get("result")
            if result is not None and result.boss_killed:
                ep_bosses += 1
            steps += 1
            if term:
                break
        rs = env.unwrapped.rs
        if rs.is_victorious:
            wins += 1
        if rs.is_dead:
            deaths += 1
        final_acts.append(rs.act)
        final_floors.append(rs.floor)
        final_hps.append(rs.hp)
        bosses.append(ep_bosses)
        rewards.append(ep_reward)
        lengths.append(steps)
    return {
        "episodes": n_episodes,
        "win_rate": wins / n_episodes,
        "death_rate": deaths / n_episodes,
        "mean_act": float(np.mean(final_acts)),
        "mean_floor": float(np.mean(final_floors)),
        "mean_final_hp": float(np.mean(final_hps)),
        "mean_reward": float(np.mean(rewards)),
        "mean_bosses": float(np.mean(bosses)),
        "mean_length": float(np.mean(lengths)),
    }


class PeriodicEvalCallback(BaseCallback):
    def __init__(self, ascension: int, reward_cfg: RewardConfig,
                 eval_every: int, eval_episodes: int, label: str = ""):
        super().__init__()
        self.ascension = ascension
        self.reward_cfg = reward_cfg
        self.eval_every = eval_every
        self.eval_episodes = eval_episodes
        self.label = label
        self.history: list[dict] = []
        self._next = eval_every

    def _on_step(self) -> bool:
        if self.num_timesteps < self._next:
            return True
        self._next += self.eval_every
        res = evaluate_solo(self.model, self.ascension, self.reward_cfg, self.eval_episodes)
        res["timesteps"] = self.num_timesteps
        self.history.append(res)
        for k, v in res.items():
            if k in ("episodes", "timesteps"):
                continue
            self.logger.record(f"eval/{k}", v)
        prefix = f"[{self.label}] " if self.label else ""
        print(f"{prefix}step={self.num_timesteps} "
              f"win={res['win_rate']:.1%} death={res['death_rate']:.1%} "
              f"act={res['mean_act']:.2f} floor={res['mean_floor']:.2f} "
              f"bosses={res['mean_bosses']:.2f} hp={res['mean_final_hp']:.1f} "
              f"rew={res['mean_reward']:+.3f}", flush=True)
        return True


def run_one_experiment(preset: str, ascension: int, workers: int, steps: int,
                       eval_every: int, eval_episodes: int, seed: int,
                       out_dir: Path, history_path: Path, tb_dir: Path | None) -> dict:
    """Train one model for one reward preset. Returns final eval dict."""
    reward_cfg = REWARD_PRESETS[preset]
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if tb_dir:
        tb_dir.mkdir(parents=True, exist_ok=True)

    # SubprocVecEnv is heavier to spawn but actually parallel; fall back
    # to DummyVecEnv when workers == 1.
    factories = [make_env_factory(ascension, reward_cfg, i) for i in range(workers)]
    VecCls = SubprocVecEnv if workers > 1 else DummyVecEnv
    vec_env = VecCls(factories)

    # n_steps 1024 + ent_coef 0.01 set after 3rd sweep; tunable via env vars
    # for cycle-E v5 hyperparameter sweeps without rewriting the script.
    import os
    lr = float(os.getenv("PPO_LR", "3e-4"))
    ent = float(os.getenv("PPO_ENT", "0.01"))
    n_steps = int(os.getenv("PPO_N_STEPS", "1024"))
    batch = int(os.getenv("PPO_BATCH", "128"))
    model = MaskablePPO("MlpPolicy", vec_env, verbose=0, seed=seed,
                        tensorboard_log=str(tb_dir) if tb_dir else None,
                        n_steps=n_steps, batch_size=batch, ent_coef=ent,
                        learning_rate=lr)

    callback = PeriodicEvalCallback(ascension, reward_cfg,
                                    eval_every, eval_episodes, label=preset)
    t0 = time.time()
    model.learn(total_timesteps=steps, callback=callback)
    train_time = time.time() - t0

    model.save(out_dir / "final.zip")
    history_path.write_text(json.dumps(callback.history, indent=2))

    final = evaluate_solo(model, ascension, reward_cfg, eval_episodes)
    final["preset"] = preset
    final["train_seconds"] = train_time
    final["workers"] = workers
    final["steps"] = steps
    print(f"\n[{preset}] DONE in {train_time:.1f}s  win={final['win_rate']:.1%}  "
          f"floor={final['mean_floor']:.2f}  bosses={final['mean_bosses']:.2f}  "
          f"hp={final['mean_final_hp']:.1f}", flush=True)
    return final


def _worker_target(preset: str, ascension: int, workers: int, steps: int,
                   eval_every: int, eval_episodes: int, seed: int,
                   out_dir: str, history_path: str, tb_dir: str | None) -> None:
    """Worker entry-point for the multi-preset sweep."""
    run_one_experiment(preset, ascension, workers, steps, eval_every,
                       eval_episodes, seed, Path(out_dir), Path(history_path),
                       Path(tb_dir) if tb_dir else None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", type=str, default=None,
                        help="Single preset to train (see REWARD_PRESETS).")
    parser.add_argument("--presets", type=str, default=None,
                        help="Comma-separated preset list to sweep in parallel processes.")
    parser.add_argument("--workers", type=int, default=4,
                        help="Per-experiment vectorized env workers.")
    parser.add_argument("--steps", type=int, default=100_000)
    parser.add_argument("--eval-every", type=int, default=20_000)
    parser.add_argument("--eval-episodes", type=int, default=20)
    parser.add_argument("--ascension", type=int, default=0)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out-root", type=Path, default=Path("models/sweeps"))
    parser.add_argument("--history-root", type=Path, default=Path("runs/sweeps"))
    parser.add_argument("--tensorboard", action="store_true")
    args = parser.parse_args()

    if not args.preset and not args.presets:
        args.presets = "default"

    if args.preset:
        run_one_experiment(
            preset=args.preset, ascension=args.ascension, workers=args.workers,
            steps=args.steps, eval_every=args.eval_every,
            eval_episodes=args.eval_episodes, seed=args.seed,
            out_dir=args.out_root / args.preset,
            history_path=args.history_root / f"{args.preset}.json",
            tb_dir=(args.history_root / f"{args.preset}_tb") if args.tensorboard else None,
        )
        return

    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    unknown = [p for p in presets if p not in REWARD_PRESETS]
    if unknown:
        raise SystemExit(f"Unknown presets: {unknown}. Known: {list(REWARD_PRESETS)}")

    print(f"Sweeping {len(presets)} presets in parallel processes, "
          f"each with {args.workers} env workers...")
    procs: list[mp.Process] = []
    for preset in presets:
        out_dir = args.out_root / preset
        history_path = args.history_root / f"{preset}.json"
        tb_dir = (args.history_root / f"{preset}_tb") if args.tensorboard else None
        p = mp.Process(
            target=_worker_target,
            args=(preset, args.ascension, args.workers, args.steps,
                  args.eval_every, args.eval_episodes, args.seed,
                  str(out_dir), str(history_path), str(tb_dir) if tb_dir else None),
        )
        p.start()
        procs.append(p)

    for p in procs:
        p.join()
    print("\nAll sweeps complete.")


if __name__ == "__main__":
    main()
