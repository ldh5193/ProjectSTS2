"""V2 training pipeline — Tiered terminal score + ascension mixture + device flag.

This replaces train_run.py for the V2 architecture (see notes/ARCHITECTURE_V2.md).
The key differences:

  - Fitness metric is `compute_terminal_score()` (Tiered) — Layer A of
    the reward design. Floor depth × act_completions × victory bonus,
    not the noisy `win_rate × 100 + 2.0 × floor + 20.0 × boss`
    composite_score that V1's evolver used.

  - Ascension is sampled per-episode from a mixture, e.g.
    `--ascension-mix '0:0.2,5:0.3,10:0.5'`. The same policy learns
    all ascensions; A10 is the deploy target but cross-difficulty
    data gives gradient signal even when A10 alone would die in act 1.

  - `--device {cpu,cuda,auto}` picks PPO compute device explicitly.
    `auto` selects cuda if available else cpu. Small policy nets can
    saturate CPU more efficiently than GPU; large nets benefit from
    GPU. The user toggles via this flag rather than env var.

Usage:
  .\\.venv\\Scripts\\python.exe scripts\\train_v2.py \\
      --steps 200_000 \\
      --ascension-mix '0:0.2,5:0.3,10:0.5' \\
      --device auto \\
      --out models/v2/run.zip \\
      --history-out models/v2/history.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from sb3_contrib import MaskablePPO
from sb3_contrib.common.wrappers import ActionMasker
from stable_baselines3.common.callbacks import BaseCallback

from sim.env_run import REWARD_PRESETS, RewardConfig, RunEnv


def _mask_fn(env):
    return env.action_masks()


def parse_ascension_mix(s: str | None) -> dict[int, float] | None:
    """Parse 'lvl:w,lvl:w,...' into {lvl: weight}. Returns None if input
    is empty/None — the env then falls back to a fixed ascension."""
    if not s:
        return None
    out: dict[int, float] = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"malformed ascension-mix entry {part!r} — expected 'lvl:weight'")
        lvl_s, w_s = part.split(":", 1)
        lvl = int(lvl_s)
        w = float(w_s)
        if not 0 <= lvl <= 20:
            raise ValueError(f"ascension level {lvl} out of [0, 20]")
        if w < 0:
            raise ValueError(f"ascension weight {w} must be >= 0")
        out[lvl] = w
    if not out:
        return None
    return out


def resolve_device(name: str) -> str:
    """Map --device flag to a PPO-friendly device string.
       cpu  -> 'cpu'
       cuda -> 'cuda'
       auto -> 'cuda' if available else 'cpu'
    """
    name = (name or "auto").lower()
    if name == "cpu":
        return "cpu"
    if name == "cuda":
        return "cuda"
    if name == "auto":
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
    raise ValueError(f"unknown device {name!r}; expected cpu/cuda/auto")


def make_env(ascension: int = 10,
             ascension_mix: dict[int, float] | None = None,
             reward_config: RewardConfig | None = None) -> ActionMasker:
    """RunEnv wrapped in ActionMasker. When ascension_mix is set, the
    fixed `ascension` argument is ignored."""
    env = RunEnv(ascension=ascension, ascension_mixture=ascension_mix,
                 reward_config=reward_config)
    return ActionMasker(env, _mask_fn)


def evaluate(model, n_episodes: int, ascension: int,
             seed_base: int = 100_000,
             max_steps_per_episode: int = 1500,
             deterministic: bool = True) -> dict:
    """Eval at a fixed ascension. Returns Tiered terminal score
    aggregates (the new Layer A metric) alongside legacy win/floor."""
    env = make_env(ascension=ascension)
    wins = 0
    deaths = 0
    final_acts: list[int] = []
    final_floors: list[int] = []
    final_hps: list[int] = []
    rewards: list[float] = []
    bosses_killed: list[int] = []
    lengths: list[int] = []
    terminal_scores: list[float] = []

    for ep in range(n_episodes):
        obs, info = env.reset(seed=seed_base + ep)
        ep_reward = 0.0
        ep_bosses = 0
        steps = 0
        while True:
            mask = env.action_masks()
            if not mask.any():
                break
            action, _ = model.predict(obs, action_masks=mask,
                                      deterministic=deterministic)
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
        bosses_killed.append(ep_bosses)
        rewards.append(ep_reward)
        lengths.append(steps)
        terminal_scores.append(env.unwrapped.compute_terminal_score())

    return {
        "episodes": n_episodes,
        "ascension": ascension,
        "win_rate": wins / n_episodes,
        "death_rate": deaths / n_episodes,
        "mean_act": float(np.mean(final_acts)),
        "mean_floor": float(np.mean(final_floors)),
        "mean_final_hp": float(np.mean(final_hps)),
        "mean_reward": float(np.mean(rewards)),
        "mean_bosses": float(np.mean(bosses_killed)),
        "mean_length": float(np.mean(lengths)),
        # New primary metric — Tiered terminal score (Layer A).
        "mean_terminal_score": float(np.mean(terminal_scores)),
        "median_terminal_score": float(np.median(terminal_scores)),
        "p90_terminal_score": float(np.percentile(terminal_scores, 90)),
    }


class PeriodicEvalCallback(BaseCallback):
    """Eval at a fixed ascension (deploy target) every N steps. Saves
    the model whenever the eval metric improves over the running best —
    PPO can oscillate badly, and without this the 300K final-checkpoint
    is often worse than a 100K intermediate peak (50K run hit p90=65
    at 30K and regressed to p90=41 at 50K)."""

    def __init__(self, eval_ascension: int, eval_every: int, eval_episodes: int,
                 best_metric: str = "mean_terminal_score",
                 best_out: Path | None = None):
        super().__init__()
        self.eval_ascension = eval_ascension
        self.eval_every = eval_every
        self.eval_episodes = eval_episodes
        self.history: list[dict] = []
        self._next = eval_every
        self.best_metric = best_metric
        self.best_out = best_out
        self.best_value: float = float("-inf")
        self.best_step: int = 0

    def _on_step(self) -> bool:
        if self.num_timesteps < self._next:
            return True
        self._next += self.eval_every
        res = evaluate(self.model, self.eval_episodes, self.eval_ascension)
        res["timesteps"] = self.num_timesteps
        self.history.append(res)
        for k, v in res.items():
            if isinstance(v, (int, float)) and k not in ("episodes", "timesteps", "ascension"):
                self.logger.record(f"eval/{k}", v)
        # Save-best-eval: track the highest `best_metric` and persist.
        val = float(res.get(self.best_metric, float("-inf")))
        if self.best_out is not None and val > self.best_value:
            self.best_value = val
            self.best_step = self.num_timesteps
            self.model.save(self.best_out)
            print(f"  [save_best] new peak {self.best_metric}={val:.2f} "
                  f"at step {self.num_timesteps:,} -> {self.best_out.name}",
                  flush=True)
        return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=200_000)
    parser.add_argument("--ascension", type=int, default=10,
                        help="Fixed ascension when --ascension-mix is empty.")
    parser.add_argument("--ascension-mix", type=str, default="0:0.2,5:0.3,10:0.5",
                        help="Per-episode ascension mixture. Format: 'lvl:weight,...'. "
                             "Empty string disables mixture.")
    parser.add_argument("--eval-ascension", type=int, default=10,
                        help="Ascension used for periodic eval (the deploy target).")
    parser.add_argument("--eval-episodes", type=int, default=50)
    parser.add_argument("--eval-every", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", type=str, default="auto",
                        choices=["cpu", "cuda", "auto"],
                        help="PPO compute device. 'auto' picks cuda if available.")
    parser.add_argument("--n-steps", type=int, default=512,
                        help="PPO rollout buffer size per env.")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--net-arch", type=str, default="64,64",
                        help="MlpPolicy hidden layer sizes, comma-separated. "
                             "Default '64,64' (sb3 default). For deeper nets: "
                             "'256,256,128' (~250K params). The same arch is "
                             "used for both pi and value heads.")
    parser.add_argument("--init-from", type=Path, default=None,
                        help="Optional path to a checkpoint to warm-start from. "
                             "Used for finetuning passes (iter 3 pattern).")
    parser.add_argument("--reward-preset", type=str, default="default",
                        help=f"RewardConfig preset name from REWARD_PRESETS. "
                             f"Available: {sorted(REWARD_PRESETS.keys())[:8]}...")
    parser.add_argument("--out", type=Path, default=Path("models/v2/run.zip"))
    parser.add_argument("--best-out", type=Path, default=None,
                        help="If set, save the best-eval checkpoint here. "
                             "Defaults to <out>_best.zip when --out is given.")
    parser.add_argument("--best-metric", type=str, default="mean_terminal_score",
                        choices=["mean_terminal_score", "median_terminal_score",
                                 "p90_terminal_score", "mean_floor", "win_rate"],
                        help="Eval metric to maximize for best checkpoint.")
    parser.add_argument("--tensorboard", type=Path, default=None)
    parser.add_argument("--history-out", type=Path, default=None)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.best_out is None:
        args.best_out = args.out.with_name(args.out.stem + "_best.zip")

    # Parse --net-arch into a list of ints.
    try:
        net_arch = [int(x.strip()) for x in args.net_arch.split(",")
                    if x.strip()]
    except ValueError as e:
        raise SystemExit(f"--net-arch parse error: {e!r}")
    if not net_arch:
        raise SystemExit("--net-arch must have at least one layer")

    mix = parse_ascension_mix(args.ascension_mix)
    device = resolve_device(args.device)
    if args.reward_preset not in REWARD_PRESETS:
        raise SystemExit(f"unknown --reward-preset {args.reward_preset!r}. "
                         f"Available: {sorted(REWARD_PRESETS.keys())}")
    reward_cfg = REWARD_PRESETS[args.reward_preset]
    env = make_env(ascension=args.ascension, ascension_mix=mix,
                   reward_config=reward_cfg)

    tb = str(args.tensorboard) if args.tensorboard else None
    if args.init_from is not None:
        model = MaskablePPO.load(args.init_from, env=env, device=device)
        model.tensorboard_log = tb
        print(f"warm-started from {args.init_from}", flush=True)
    else:
        model = MaskablePPO(
            "MlpPolicy", env, verbose=0, seed=args.seed,
            tensorboard_log=tb, n_steps=args.n_steps,
            batch_size=args.batch_size, device=device,
            policy_kwargs={"net_arch": net_arch},
        )

    print(f"=== V2 training ===", flush=True)
    print(f"device: {device}", flush=True)
    print(f"net_arch: {net_arch}", flush=True)
    print(f"reward_preset: {args.reward_preset}", flush=True)
    print(f"ascension mix: {mix or f'fixed A{args.ascension}'}", flush=True)
    print(f"steps: {args.steps:,}", flush=True)
    print(f"eval: A{args.eval_ascension}, every {args.eval_every:,} steps, "
          f"{args.eval_episodes} eps", flush=True)
    print(f"output: {args.out}  (best -> {args.best_out})", flush=True)

    callback = PeriodicEvalCallback(
        eval_ascension=args.eval_ascension,
        eval_every=args.eval_every,
        eval_episodes=args.eval_episodes,
        best_metric=args.best_metric,
        best_out=args.best_out,
    )
    model.learn(total_timesteps=args.steps, callback=callback)
    model.save(args.out)
    print(f"\nSaved model to {args.out}")

    if args.history_out is not None:
        args.history_out.parent.mkdir(parents=True, exist_ok=True)
        args.history_out.write_text(json.dumps(callback.history, indent=2))
        print(f"Saved eval history to {args.history_out} "
              f"({len(callback.history)} points)")

    final = evaluate(model, args.eval_episodes, args.eval_ascension)
    print(f"\nFinal eval (A{final['ascension']}, {final['episodes']} eps):")
    print(f"  Terminal score: {final['mean_terminal_score']:.1f} "
          f"(median {final['median_terminal_score']:.1f}, "
          f"p90 {final['p90_terminal_score']:.1f})")
    print(f"  Win rate:       {final['win_rate']:.1%}")
    print(f"  Mean floor:     {final['mean_floor']:.2f}")
    print(f"  Mean bosses:    {final['mean_bosses']:.2f}")
    print(f"  Mean act:       {final['mean_act']:.2f}")
    print(f"  Mean final HP:  {final['mean_final_hp']:.2f}")
    print(f"\nBest checkpoint ({args.best_metric}={callback.best_value:.2f} "
          f"@ step {callback.best_step:,}):")
    print(f"  -> {args.best_out}")


if __name__ == "__main__":
    main()
