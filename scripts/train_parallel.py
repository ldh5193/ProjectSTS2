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


def load_all_presets() -> dict[str, RewardConfig]:
    """Merge hand-tuned REWARD_PRESETS with anything in
    models/generated_presets.json (written by scripts/generate_presets.py).
    Generated names always take precedence on name collision."""
    out = dict(REWARD_PRESETS)
    gen_path = Path(__file__).resolve().parent.parent / "models" / "generated_presets.json"
    if gen_path.exists():
        try:
            import json
            gen = json.loads(gen_path.read_text())
            for name, cfg_dict in gen.items():
                try:
                    out[name] = RewardConfig(**cfg_dict)
                except Exception as e:
                    print(f"[load_presets] skip {name}: {e}", flush=True)
        except Exception as e:
            print(f"[load_presets] failed to read {gen_path}: {e}", flush=True)
    return out


def _mask_fn(env):
    return env.action_masks()


def make_env_factory(ascension: int, reward_cfg: RewardConfig, seed_offset: int):
    def _f():
        env = ActionMasker(RunEnv(ascension=ascension, reward_config=reward_cfg), _mask_fn)
        return env
    return _f


def evaluate_solo(model, ascension: int, reward_cfg: RewardConfig,
                  n_episodes: int, seed_base: int = 100_000,
                  max_steps_per_episode: int = 1500,
                  deterministic: bool = True) -> dict:
    """Solo (non-vectorized) eval for clean per-episode aggregates.

    `max_steps_per_episode` is a watchdog: a deterministic policy can occa-
    sionally land in an unsolvable RunState (currently possible while the
    multi-monster combat refactor is in progress) and the env loop would
    otherwise spin forever, stalling the entire sweep with no log output.
    The cap is generous enough that healthy episodes are never truncated.

    `deterministic=True`: argmax — matches how the mod runs the policy.
    `deterministic=False`: stochastic sampling — matches training, exposes
    the policy's full multi-modal capability when argmax happens to pick
    a worse mode.
    """
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
            action, _ = model.predict(obs, action_masks=mask, deterministic=deterministic)
            obs, reward, term, _, info = env.step(int(action))
            ep_reward += reward
            result = info.get("result")
            if result is not None and result.boss_killed:
                ep_bosses += 1
            steps += 1
            if term or steps >= max_steps_per_episode:
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
        # Rotate seed each eval so the policy can't overfit to a fixed
        # 30-seed evaluation pool. Without this an early-trained policy
        # could appear to plateau because the same seeds keep failing.
        seed_base = 100_000 + (self.num_timesteps // 1000)
        # Deterministic = how the mod plays. Stochastic = full training
        # capability. We track both because mid-train action sampling
        # often beats argmax when the policy is multi-modal.
        res = evaluate_solo(self.model, self.ascension, self.reward_cfg,
                            self.eval_episodes, seed_base=seed_base,
                            deterministic=True)
        res_stoch = evaluate_solo(self.model, self.ascension, self.reward_cfg,
                                  self.eval_episodes, seed_base=seed_base,
                                  deterministic=False)
        res["timesteps"] = self.num_timesteps
        res["win_rate_stoch"] = res_stoch["win_rate"]
        res["floor_stoch"] = res_stoch["mean_floor"]
        self.history.append(res)
        for k, v in res.items():
            if k in ("episodes", "timesteps"):
                continue
            self.logger.record(f"eval/{k}", v)
        prefix = f"[{self.label}] " if self.label else ""
        print(f"{prefix}step={self.num_timesteps} "
              f"win={res['win_rate']:.1%}(s={res_stoch['win_rate']:.1%}) "
              f"death={res['death_rate']:.1%} "
              f"act={res['mean_act']:.2f} floor={res['mean_floor']:.2f}(s={res_stoch['mean_floor']:.2f}) "
              f"bosses={res['mean_bosses']:.2f} hp={res['mean_final_hp']:.1f} "
              f"rew={res['mean_reward']:+.3f}", flush=True)
        return True


def run_one_experiment(preset: str, ascension: int, workers: int, steps: int,
                       eval_every: int, eval_episodes: int, seed: int,
                       out_dir: Path, history_path: Path, tb_dir: Path | None) -> dict:
    """Train one model for one reward preset. Returns final eval dict."""
    all_presets = load_all_presets()
    if preset not in all_presets:
        raise SystemExit(f"Unknown preset '{preset}'. Known: {sorted(all_presets)}")
    reward_cfg = all_presets[preset]
    out_dir.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)
    if tb_dir:
        tb_dir.mkdir(parents=True, exist_ok=True)

    # SubprocVecEnv is heavier to spawn but actually parallel; fall back
    # to DummyVecEnv when workers == 1.
    factories = [make_env_factory(ascension, reward_cfg, i) for i in range(workers)]
    VecCls = SubprocVecEnv if workers > 1 else DummyVecEnv
    vec_env = VecCls(factories)

    # v3 (2026-05-25): exploration + capacity bump after 30 cycles
    # plateaued at ~10% win across all reward presets. ent_coef tripled,
    # n_steps doubled, and the policy net widened 64→256 (×6 params).
    # Auto-switch to GPU when the net is large enough that math beats
    # transfer overhead. Env vars still override.
    import os
    lr = float(os.getenv("PPO_LR", "3e-4"))
    ent = float(os.getenv("PPO_ENT", "0.03"))     # was 0.01 — boost exploration
    n_steps = int(os.getenv("PPO_N_STEPS", "2048"))  # was 1024
    batch = int(os.getenv("PPO_BATCH", "256"))    # was 128 (matches new n_steps)
    # net_arch via env var "PPO_NET" = comma-separated hidden sizes.
    # Default 256,256,128 = ~170K params (was 64,64,64 = ~25K).
    net_str = os.getenv("PPO_NET", "256,256,128")
    net_arch = [int(x) for x in net_str.split(",") if x.strip()]
    n_params_est = 128 * net_arch[0] + sum(net_arch[i-1]*net_arch[i] for i in range(1,len(net_arch))) + net_arch[-1]*300
    # GPU pays off above ~100K params; below that the host↔device
    # transfer per minibatch dominates. Override with PPO_DEVICE.
    if os.getenv("PPO_DEVICE"):
        device = os.environ["PPO_DEVICE"]
    else:
        device = "cuda" if n_params_est > 100_000 else "cpu"
    from sb3_contrib.common.maskable.policies import MaskableActorCriticPolicy
    policy_kwargs = dict(net_arch=net_arch)
    # Warm-start from the previous sweep checkpoint if one exists.
    # NOTE: warm-start ONLY works if net_arch matches. We tag the
    # checkpoint with the arch in its parent dir to avoid silent mismatches.
    prev_ckpt = out_dir / "final.zip"
    arch_tag = out_dir / f".arch_{net_str.replace(',','x')}"
    arch_compatible = arch_tag.exists()
    if prev_ckpt.exists() and arch_compatible and os.getenv("PPO_WARM_START", "1") != "0":
        try:
            model = MaskablePPO.load(prev_ckpt, env=vec_env, device=device,
                                     custom_objects={"learning_rate": lr,
                                                     "ent_coef": ent})
            print(f"[{preset}] PPO device={device} net={net_arch} warm-start from {prev_ckpt.name}", flush=True)
        except Exception as e:
            print(f"[{preset}] warm-start failed ({e}); fresh init", flush=True)
            model = MaskablePPO("MlpPolicy", vec_env, verbose=0, seed=seed,
                                tensorboard_log=str(tb_dir) if tb_dir else None,
                                n_steps=n_steps, batch_size=batch, ent_coef=ent,
                                learning_rate=lr, device=device,
                                policy_kwargs=policy_kwargs)
    else:
        if prev_ckpt.exists() and not arch_compatible:
            print(f"[{preset}] ARCH MISMATCH (no .arch_{net_str.replace(',','x')} tag) - fresh init", flush=True)
        model = MaskablePPO("MlpPolicy", vec_env, verbose=0, seed=seed,
                            tensorboard_log=str(tb_dir) if tb_dir else None,
                            n_steps=n_steps, batch_size=batch, ent_coef=ent,
                            learning_rate=lr, device=device,
                            policy_kwargs=policy_kwargs)
        print(f"[{preset}] PPO device={device} net={net_arch} (~{n_params_est//1000}K params) fresh init", flush=True)
    # Drop a marker so the next cycle knows the arch — prevents loading
    # a checkpoint trained on a different net_arch.
    arch_tag.parent.mkdir(parents=True, exist_ok=True)
    arch_tag.touch(exist_ok=True)

    callback = PeriodicEvalCallback(ascension, reward_cfg,
                                    eval_every, eval_episodes, label=preset)
    t0 = time.time()
    model.learn(total_timesteps=steps, callback=callback)
    train_time = time.time() - t0

    model.save(out_dir / "final.zip")
    history_path.write_text(json.dumps(callback.history, indent=2))

    # Final eval: bigger N (3× train-time eval) for tight CI, and report
    # both deterministic (mod-style argmax) and stochastic (training
    # capability) to spot multi-modal policies the argmax is hiding.
    final_n = max(eval_episodes * 3, 100)
    final = evaluate_solo(model, ascension, reward_cfg, final_n,
                          deterministic=True, seed_base=900_000)
    final_stoch = evaluate_solo(model, ascension, reward_cfg, final_n,
                                deterministic=False, seed_base=900_000)
    final["preset"] = preset
    final["train_seconds"] = train_time
    final["workers"] = workers
    final["steps"] = steps
    final["win_rate_stoch"] = final_stoch["win_rate"]
    final["mean_floor_stoch"] = final_stoch["mean_floor"]
    final["mean_bosses_stoch"] = final_stoch["mean_bosses"]
    print(f"\n[{preset}] DONE in {train_time:.1f}s  "
          f"win={final['win_rate']:.1%}(s={final_stoch['win_rate']:.1%}) "
          f"floor={final['mean_floor']:.2f}(s={final_stoch['mean_floor']:.2f}) "
          f"bosses={final['mean_bosses']:.2f} hp={final['mean_final_hp']:.1f} "
          f"n={final_n}", flush=True)
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
    all_presets = load_all_presets()
    unknown = [p for p in presets if p not in all_presets]
    if unknown:
        raise SystemExit(f"Unknown presets: {unknown}. Known: {sorted(all_presets)}")

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
