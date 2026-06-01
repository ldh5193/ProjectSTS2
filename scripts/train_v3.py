"""V3 training pipeline — fixes the RL hygiene gaps identified after Phase 6g.

What changed vs train_v2.py:

  1. ent_coef defaults to 0.02 (was 0.0). PPO mode collapse — observed in
     g01 where 84/100 evals returned bit-identical outputs after 400K
     steps — is the predicted failure mode of ent_coef=0 with masked
     Discrete(300) action space. Standard practice is 0.01-0.05.

  2. SubprocVecEnv / DummyVecEnv with n_envs > 1. Single-env PPO bottlenecks
     on rollout diversity. 8 parallel envs gives the PPO update an actual
     distribution of trajectories per batch.

  3. Bigger rollouts (n_steps=2048, batch_size=256) so PPO's GAE estimate
     spans real episode lengths (200-1500 steps) instead of being chopped
     at 512.

  4. Linear LR schedule 3e-4 -> 1e-5. Flat lr lets late updates overshoot
     when the policy converges; the schedule lets the trained-loss
     gradient settle without forgetting.

  5. Rotating eval seeds. evaluate() in v2 used seed_base + ep -> the same
     50 seeds every eval, so once the policy locked in, every eval returned
     identical numbers and save_best was fishing noise. v3 rotates the
     seed offset with eval_count to widen the measurement.

  6. Linear ascension curriculum. The mixed {A0:.2, A5:.3, A10:.5}
     subjected PPO to 50% A10 from step 0, with no easy wins to anchor.
     v3 ramps A0 -> A10 over training. Same env, mutated mid-flight.

Old run reproducibility is preserved at train_v2.py.
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
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv

from sim.env_run import REWARD_PRESETS, RewardConfig, RunEnv


def _mask_fn(env):
    return env.action_masks()


def parse_ascension_mix(s: str | None) -> dict[int, float] | None:
    if not s:
        return None
    out: dict[int, float] = {}
    for part in s.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        lvl_s, w_s = part.split(":", 1)
        out[int(lvl_s)] = float(w_s)
    return out or None


def resolve_device(name: str) -> str:
    name = (name or "auto").lower()
    if name == "cpu":
        return "cpu"
    if name == "cuda":
        return "cuda"
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


# ---------------------------------------------------------------------------
# Warm-start obs-dim padding (Phase 9.0: obs v4.4 504 -> v5 560).
# ---------------------------------------------------------------------------
#
# A v4.4 Ironclad checkpoint has a policy whose first linear layer expects a
# 504-dim input. The v5 env emits 560 dims (the new char/orb/star/osty/poison
# tail is APPENDED, so dims [0..504) are unchanged). To reuse such a
# checkpoint we zero-pad every first-layer weight matrix whose in_features ==
# old_obs_dim out to new_obs_dim, leaving the rest of the network untouched.
# Because the new tail dims are 0 for Ironclad and the padded weights are 0,
# the warm-started policy produces bit-identical logits on Ironclad obs at
# step 0 — it then learns to use the new dims. Non-matching layers are left
# alone (idempotent + safe on an already-560 checkpoint).

def pad_state_dict_for_obs_change(state_dict, old_obs_dim: int, new_obs_dim: int):
    """Return a copy of `state_dict` with every 2-D weight whose trailing
    dimension == old_obs_dim zero-padded (on the right) to new_obs_dim.

    This targets the policy/value MLP's first linear layer (in_features ==
    obs_dim) without needing to know SB3's exact key names. No-op if
    new_obs_dim <= old_obs_dim or nothing matches (so re-running is safe)."""
    import torch  # local import: training-only dependency

    if new_obs_dim <= old_obs_dim:
        return dict(state_dict)
    out = {}
    pad = new_obs_dim - old_obs_dim
    for k, v in state_dict.items():
        if hasattr(v, "ndim") and v.ndim == 2 and v.shape[1] == old_obs_dim:
            zeros = torch.zeros(v.shape[0], pad, dtype=v.dtype, device=v.device)
            out[k] = torch.cat([v, zeros], dim=1)
        else:
            out[k] = v
    return out


def warm_start_load(init_from, env, *, old_obs_dim: int, new_obs_dim: int,
                    **ppo_kwargs):
    """Load a MaskablePPO checkpoint into a (possibly larger-obs) `env`,
    zero-padding the input layer if the checkpoint's obs dim differs.

    Tries a plain `MaskablePPO.load` first (works when obs dims match). On the
    shape-mismatch path it builds a fresh model on `env`, then copies the old
    parameters in with the first layer zero-padded out to new_obs_dim."""
    # net_arch is only meaningful for the fresh-model fallback; MaskablePPO.load
    # rebuilds the net from the checkpoint and rejects net_arch as a kwarg.
    net_arch = ppo_kwargs.pop("net_arch", None)
    try:
        return MaskablePPO.load(init_from, env=env, **ppo_kwargs)
    except (ValueError, RuntimeError, AssertionError) as exc:
        # Shape mismatch on the input layer — pad and graft.
        print(f"warm_start: direct load failed ({type(exc).__name__}: {exc}); "
              f"zero-padding obs {old_obs_dim}->{new_obs_dim}", flush=True)
        old = MaskablePPO.load(init_from, device=ppo_kwargs.get("device", "auto"))
        old_sd = old.policy.state_dict()
        padded = pad_state_dict_for_obs_change(old_sd, old_obs_dim, new_obs_dim)
        # Build a fresh model whose policy matches the NEW obs space, then load
        # the padded weights (strict=False tolerates any head re-init).
        policy_kwargs = {"net_arch": net_arch} if net_arch else {}
        model = MaskablePPO(
            "MlpPolicy", env, policy_kwargs=policy_kwargs, **ppo_kwargs,
        )
        model.policy.load_state_dict(padded, strict=False)
        return model


def make_env(ascension: int = 10,
             ascension_mix: dict[int, float] | None = None,
             reward_config: RewardConfig | None = None,
             character=None) -> ActionMasker:
    # character: a sim.game_state.Character (or None -> RunEnv default Ironclad).
    # Phase 9.0 wires the per-character env; multi-character per-episode
    # sampling (a --characters set) is P9.7. For now a single character is
    # fixed per env.
    from sim.game_state import Character
    kwargs = {}
    if character is not None:
        kwargs["character"] = character
    env = RunEnv(ascension=ascension, ascension_mixture=ascension_mix,
                 reward_config=reward_config, **kwargs)
    return ActionMasker(env, _mask_fn)


def parse_characters(s: str | None):
    """Parse a --characters CSV (e.g. 'ironclad,silent') into a list of
    Character enums. Empty/None -> [Ironclad]. Phase 9.0 only USES the first
    one (single fixed character per run); the full set is reserved for the
    P9.7 character-conditioned curriculum."""
    from sim.game_state import Character
    if not s:
        return [Character.IRONCLAD]
    out = []
    for part in s.split(","):
        part = part.strip().lower()
        if not part:
            continue
        try:
            out.append(Character(part))
        except ValueError:
            raise SystemExit(f"unknown character in --characters: {part!r}")
    return out or [Character.IRONCLAD]


def make_vec_env(n_envs: int,
                 ascension: int,
                 ascension_mix: dict[int, float] | None,
                 reward_config: RewardConfig,
                 use_subproc: bool = False,
                 character=None):
    """Build a (Subproc|Dummy)VecEnv of n_envs ActionMasker-wrapped RunEnv.

    DummyVecEnv runs envs in-process sequentially but still gives PPO
    n_envs distinct trajectories per rollout. SubprocVecEnv adds true
    parallelism — requires the env+state graph to be picklable.
    """
    def _factory():
        return make_env(ascension=ascension, ascension_mix=ascension_mix,
                        reward_config=reward_config, character=character)
    fns = [_factory for _ in range(n_envs)]
    if use_subproc and n_envs > 1:
        return SubprocVecEnv(fns)
    return DummyVecEnv(fns)


# ---------------------------------------------------------------------------
# Curriculum
# ---------------------------------------------------------------------------

CURRICULUM_STAGES = [
    # (progress_at_or_below, mix dict). Linear interp between adjacent stages.
    (0.00, {0: 1.0}),
    (0.20, {0: 0.7, 5: 0.3}),
    (0.40, {0: 0.4, 5: 0.4, 10: 0.2}),
    (0.60, {0: 0.2, 5: 0.4, 10: 0.4}),
    (0.80, {5: 0.3, 10: 0.7}),
    (1.00, {10: 1.0}),
]


def curriculum_mix(progress: float) -> dict[int, float]:
    """progress in [0,1]. Return interpolated ascension mix.

    Picks the two adjacent stages and lerps weights. Levels appearing
    in only one stage are zero-padded for the lerp.
    """
    progress = max(0.0, min(1.0, progress))
    lo, hi = CURRICULUM_STAGES[0], CURRICULUM_STAGES[0]
    for stage in CURRICULUM_STAGES:
        if stage[0] <= progress:
            lo = stage
        if hi[0] < progress and stage[0] >= progress:
            hi = stage
            break
    else:
        hi = CURRICULUM_STAGES[-1]
    if lo is hi or hi[0] == lo[0]:
        return dict(lo[1])
    t = (progress - lo[0]) / (hi[0] - lo[0])
    keys = set(lo[1]) | set(hi[1])
    out = {}
    for k in sorted(keys):
        w = (1 - t) * lo[1].get(k, 0.0) + t * hi[1].get(k, 0.0)
        if w > 1e-6:
            out[k] = w
    return out


class CurriculumCallback(BaseCallback):
    """Update each sub-env's _ascension_mixture as training progresses."""

    def __init__(self, total_timesteps: int, update_every: int = 25_000):
        super().__init__()
        self.total = total_timesteps
        self.update_every = update_every
        self._next = update_every

    def _on_step(self) -> bool:
        if self.num_timesteps < self._next:
            return True
        self._next += self.update_every
        progress = self.num_timesteps / self.total
        new_mix = curriculum_mix(progress)
        # Mutate each underlying RunEnv (via ActionMasker.env) in the VecEnv.
        self.training_env.set_attr("_ascension_mixture",
                                   new_mix, indices=None)
        # set_attr on ActionMasker doesn't reach the inner env; do it via env_method.
        try:
            self.training_env.env_method("__setattr__",
                                         "_ascension_mixture", new_mix)
        except Exception:
            pass
        # Log curriculum state via tensorboard.
        for lvl, w in new_mix.items():
            self.logger.record(f"curriculum/A{lvl}_weight", w)
        return True


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------

def evaluate(model, n_episodes: int, ascension: int,
             seed_offset: int = 0,
             seed_base: int = 100_000,
             max_steps_per_episode: int = 1500,
             deterministic: bool = True) -> dict:
    """Eval at fixed ascension. seed_offset rotates the seed window each
    call so successive evals don't return bit-identical numbers when the
    policy converges."""
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
        seed = seed_base + seed_offset * 10_000 + ep
        obs, info = env.reset(seed=seed)
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
        "seed_offset": seed_offset,
        "win_rate": wins / n_episodes,
        "death_rate": deaths / n_episodes,
        "mean_act": float(np.mean(final_acts)),
        "mean_floor": float(np.mean(final_floors)),
        "mean_final_hp": float(np.mean(final_hps)),
        "mean_reward": float(np.mean(rewards)),
        "mean_bosses": float(np.mean(bosses_killed)),
        "mean_length": float(np.mean(lengths)),
        "mean_terminal_score": float(np.mean(terminal_scores)),
        "median_terminal_score": float(np.median(terminal_scores)),
        "p90_terminal_score": float(np.percentile(terminal_scores, 90)),
    }


class RotatingEvalCallback(BaseCallback):
    """Periodic eval with seed rotation + EMA-smoothed best tracker.

    save_best fires on EMA(score) > current_best, not raw score. This
    suppresses the "single 50-ep luck spike -> save_best" fishing pattern
    that v2 showed (e01 peak 61.7 was 6%/50 -> 3 lucky episodes carrying
    the mean from 49 to 61).
    """

    def __init__(self, eval_ascension: int, eval_every: int,
                 eval_episodes: int,
                 best_metric: str = "mean_terminal_score",
                 best_out: Path | None = None,
                 ema_alpha: float = 0.5):
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
        self.ema_value: float | None = None
        self.ema_alpha = ema_alpha
        self._eval_count = 0

    def _on_step(self) -> bool:
        if self.num_timesteps < self._next:
            return True
        self._next += self.eval_every
        res = evaluate(self.model, self.eval_episodes, self.eval_ascension,
                       seed_offset=self._eval_count)
        self._eval_count += 1
        res["timesteps"] = self.num_timesteps
        self.history.append(res)
        for k, v in res.items():
            if isinstance(v, (int, float)) and k not in (
                    "episodes", "timesteps", "ascension", "seed_offset"):
                self.logger.record(f"eval/{k}", v)
        val = float(res.get(self.best_metric, float("-inf")))
        if self.ema_value is None:
            self.ema_value = val
        else:
            self.ema_value = self.ema_alpha * val + (1 - self.ema_alpha) * self.ema_value
        self.logger.record(f"eval/{self.best_metric}_ema", self.ema_value)
        # Heartbeat: always print every eval so progress is observable even
        # when the EMA peak is unchanged (otherwise "no new peak" during the
        # A0 curriculum phase is indistinguishable from a hung process).
        print(f"  [eval] step {self.num_timesteps:,} "
              f"win_rate={res.get('win_rate', 0.0):.3f} "
              f"floor={res.get('mean_floor', 0.0):.1f} "
              f"score={res.get('mean_terminal_score', 0.0):.1f} "
              f"EMA({self.best_metric})={self.ema_value:.3f}",
              flush=True)
        if self.best_out is not None and self.ema_value > self.best_value:
            self.best_value = self.ema_value
            self.best_step = self.num_timesteps
            self.model.save(self.best_out)
            print(f"  [save_best] new peak EMA {self.best_metric}="
                  f"{self.ema_value:.2f} (raw {val:.2f}) "
                  f"at step {self.num_timesteps:,} -> {self.best_out.name}",
                  flush=True)
        return True


# ---------------------------------------------------------------------------
# LR schedule
# ---------------------------------------------------------------------------

def make_lr_schedule(initial: float, final: float):
    """SB3 lr takes a callable on progress_remaining in [0,1]
    (1.0 at start, 0.0 at end). Linear from initial -> final."""
    def _schedule(progress_remaining: float) -> float:
        return final + (initial - final) * progress_remaining
    return _schedule


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--steps", type=int, default=2_500_000)
    parser.add_argument("--ascension", type=int, default=10)
    parser.add_argument("--ascension-mix", type=str, default="",
                        help="Static mix. Empty + --curriculum enables ramp.")
    parser.add_argument("--curriculum", action="store_true",
                        help="Use linear A0->A10 ascension ramp.")
    parser.add_argument("--eval-ascension", type=int, default=10)
    parser.add_argument("--eval-episodes", type=int, default=50)
    parser.add_argument("--eval-every", type=int, default=25_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", type=str, default="auto",
                        choices=["cpu", "cuda", "auto"])
    parser.add_argument("--n-envs", type=int, default=8)
    parser.add_argument("--subproc", action="store_true",
                        help="Use SubprocVecEnv (true parallelism). Default DummyVecEnv.")
    parser.add_argument("--n-steps", type=int, default=2048)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--n-epochs", type=int, default=5)
    parser.add_argument("--ent-coef", type=float, default=0.02)
    parser.add_argument("--gae-lambda", type=float, default=0.97)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--lr-init", type=float, default=3e-4)
    parser.add_argument("--lr-final", type=float, default=1e-5)
    parser.add_argument("--net-arch", type=str, default="1024,1024")
    parser.add_argument("--init-from", type=Path, default=None)
    parser.add_argument("--characters", type=str, default="",
                        help="CSV of characters (e.g. ironclad,silent). Phase "
                             "9.0 uses the first; default ironclad.")
    parser.add_argument("--reward-preset", type=str, default="shape_damage")
    parser.add_argument("--out", type=Path, default=Path("models/v3/run.zip"))
    parser.add_argument("--best-out", type=Path, default=None)
    parser.add_argument("--best-metric", type=str, default="mean_terminal_score")
    parser.add_argument("--tensorboard", type=Path, default=None)
    parser.add_argument("--history-out", type=Path, default=None)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.best_out is None:
        args.best_out = args.out.with_name(args.out.stem + "_best.zip")

    try:
        net_arch = [int(x.strip()) for x in args.net_arch.split(",") if x.strip()]
    except ValueError as e:
        raise SystemExit(f"--net-arch parse error: {e!r}")

    if args.reward_preset not in REWARD_PRESETS:
        raise SystemExit(f"unknown --reward-preset {args.reward_preset!r}")
    reward_cfg = REWARD_PRESETS[args.reward_preset]

    if args.curriculum:
        initial_mix = curriculum_mix(0.0)
    else:
        initial_mix = parse_ascension_mix(args.ascension_mix)

    device = resolve_device(args.device)
    characters = parse_characters(args.characters)
    train_character = characters[0]  # P9.0: single fixed character per run
    env = make_vec_env(args.n_envs, args.ascension, initial_mix,
                       reward_cfg, use_subproc=args.subproc,
                       character=train_character)

    tb = str(args.tensorboard) if args.tensorboard else None
    lr = make_lr_schedule(args.lr_init, args.lr_final)

    if args.init_from is not None:
        # Phase 9.0: obs grew 504 (v4.4) -> 560 (v5). warm_start_load tries a
        # plain load (matching dims) and falls back to zero-padding the input
        # layer when a 504-dim Ironclad checkpoint is grafted onto the 560-dim
        # v5 obs (the new tail is 0 for Ironclad, so logits are unchanged at
        # step 0). Pass net_arch so the fresh fallback model matches the CLI.
        from sim.env_run import OBS_DIM, OBS_DIM_V4_4
        model = warm_start_load(
            args.init_from, env,
            old_obs_dim=OBS_DIM_V4_4, new_obs_dim=OBS_DIM,
            device=device, ent_coef=args.ent_coef, n_steps=args.n_steps,
            batch_size=args.batch_size, n_epochs=args.n_epochs,
            gae_lambda=args.gae_lambda, gamma=args.gamma, learning_rate=lr,
            net_arch=net_arch,
        )
        model.tensorboard_log = tb
        print(f"warm-started from {args.init_from}", flush=True)
    else:
        model = MaskablePPO(
            "MlpPolicy", env, verbose=0, seed=args.seed,
            tensorboard_log=tb,
            n_steps=args.n_steps,
            batch_size=args.batch_size,
            n_epochs=args.n_epochs,
            ent_coef=args.ent_coef,
            gae_lambda=args.gae_lambda,
            gamma=args.gamma,
            learning_rate=lr,
            device=device,
            policy_kwargs={"net_arch": net_arch},
        )

    print(f"=== V3 training ===", flush=True)
    print(f"device: {device}", flush=True)
    print(f"net_arch: {net_arch}", flush=True)
    print(f"reward_preset: {args.reward_preset}", flush=True)
    print(f"curriculum: {args.curriculum}", flush=True)
    print(f"initial mix: {initial_mix}", flush=True)
    print(f"n_envs: {args.n_envs}  subproc: {args.subproc}", flush=True)
    print(f"ent_coef: {args.ent_coef}  n_steps: {args.n_steps}  "
          f"batch: {args.batch_size}  epochs: {args.n_epochs}", flush=True)
    print(f"lr: {args.lr_init} -> {args.lr_final} (linear)", flush=True)
    print(f"gae_lambda: {args.gae_lambda}  gamma: {args.gamma}", flush=True)
    print(f"steps: {args.steps:,}", flush=True)
    print(f"eval: A{args.eval_ascension}, every {args.eval_every:,} steps, "
          f"{args.eval_episodes} eps (rotating seeds, EMA best)", flush=True)
    print(f"output: {args.out}  (best -> {args.best_out})", flush=True)

    callbacks = [
        RotatingEvalCallback(
            eval_ascension=args.eval_ascension,
            eval_every=args.eval_every,
            eval_episodes=args.eval_episodes,
            best_metric=args.best_metric,
            best_out=args.best_out,
        )
    ]
    if args.curriculum:
        callbacks.append(CurriculumCallback(total_timesteps=args.steps))
    model.learn(total_timesteps=args.steps, callback=callbacks)
    model.save(args.out)
    print(f"\nSaved model to {args.out}")

    if args.history_out is not None:
        args.history_out.parent.mkdir(parents=True, exist_ok=True)
        eval_cb = callbacks[0]
        args.history_out.write_text(json.dumps(eval_cb.history, indent=2))
        print(f"Saved eval history to {args.history_out} "
              f"({len(eval_cb.history)} points)")

    final = evaluate(model, args.eval_episodes, args.eval_ascension,
                     seed_offset=99999)
    print(f"\nFinal eval (A{final['ascension']}, {final['episodes']} eps):")
    print(f"  Terminal score: {final['mean_terminal_score']:.1f} "
          f"(median {final['median_terminal_score']:.1f}, "
          f"p90 {final['p90_terminal_score']:.1f})")
    print(f"  Win rate:       {final['win_rate']:.1%}")
    print(f"  Mean floor:     {final['mean_floor']:.2f}")
    print(f"  Mean bosses:    {final['mean_bosses']:.2f}")
    print(f"  Mean act:       {final['mean_act']:.2f}")
    print(f"  Mean final HP:  {final['mean_final_hp']:.2f}")
    eval_cb = callbacks[0]
    print(f"\nBest checkpoint (EMA {args.best_metric}={eval_cb.best_value:.2f} "
          f"@ step {eval_cb.best_step:,}):")
    print(f"  -> {args.best_out}")


if __name__ == "__main__":
    main()
