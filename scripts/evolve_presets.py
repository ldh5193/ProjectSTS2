"""Evolutionary preset search for reward shaping.

Maintains a population of N RewardConfigs. Each generation:

  1. Train each preset for `--steps` (short budget — typically 20K-30K).
  2. Rank by composite score: max(win_det, win_stoch)*100 +
     0.05*max(floor_det, floor_stoch) + 0.5*mean_bosses
     (matches PeriodicEvalCallback's best-save metric).
  3. Top `survive_frac` carry their out_dir + best.zip forward (warm-start).
  4. `mutate_frac` are gaussian-perturbed children of survivors; child
     inherits parent's best.zip + final.zip + arch tag so PPO warm-starts.
  5. `fresh_frac` are uniform Latin-hypercube samples over RANGES.

State persists to models/evolve/state.json so the loop resumes after
interrupt (Ctrl-C, process kill, machine restart).

Usage:
    .\\.venv\\Scripts\\python.exe -u scripts\\evolve_presets.py \\
        --population 80 --steps 20000 --ascension 10
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.generate_presets import RANGES, sample_preset  # noqa: E402


EVOLVE_ROOT = ROOT / "models" / "evolve"
STATE_FILE = EVOLVE_ROOT / "state.json"
LOG_FILE = EVOLVE_ROOT / "log.txt"
GENPRESETS_FILE = ROOT / "models" / "generated_presets.json"

# Hall of Fame — top-K presets ever observed across all generations.
# Re-injected into each new generation's parent pool so a single bad
# gen can't lose a proven preset.
HOF_FILE = EVOLVE_ROOT / "hall_of_fame.json"
HOF_SIZE = 5
HOF_INJECT_COUNT = 3  # how many HoF entries to force into next gen as survivors

# Auto-deploy state — last preset exported to mods/policy.onnx.
# Used to gate the per-recalibration export+commit+push so we only
# push when fitness strictly improves.
LAST_DEPLOY_FILE = EVOLVE_ROOT / "last_deploy.json"
DEPLOYED_ONNX = ROOT / "tools" / "STS2MCP-bin" / "policy.onnx"
EXPORT_SCRIPT = ROOT / "scripts" / "export_onnx.py"
GAME_MODS_DIR = Path("D:/Games/Steam/steamapps/common/Slay the Spire 2/mods")


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def composite_score(eval_row: dict) -> float:
    """Same metric as scripts/train_parallel.py PeriodicEvalCallback uses
    for save-best — keeps fitness ranking aligned with mid-train peak."""
    win = max(eval_row.get("win_rate", 0.0), eval_row.get("win_rate_stoch", 0.0))
    floor = max(eval_row.get("mean_floor", 0.0), eval_row.get("floor_stoch", 0.0))
    boss = eval_row.get("mean_bosses", 0.0)
    return win * 100.0 + 0.05 * floor + 0.5 * boss


def fitness_from_history(history_path: Path) -> float:
    if not history_path.exists():
        return -1e9
    try:
        history = json.loads(history_path.read_text())
        if not history:
            return -1e9
        return max(composite_score(row) for row in history)
    except Exception:
        return -1e9


def random_preset_cfg(rng: random.Random, idx: int, n_total: int) -> dict:
    return sample_preset(rng, idx, n_total)


def mutate(rng: random.Random, parent: dict, sigma: float) -> dict:
    """Per-field mutation with prob 0.5. Multiplicative gaussian for
    non-zero fields; additive fraction-of-range for fields near zero so
    they can escape 0."""
    out = dict(parent)
    for field, (lo, hi) in RANGES.items():
        if field not in out or rng.random() >= 0.5:
            continue
        cur = float(out[field])
        if abs(cur) < 1e-5:
            noise = rng.uniform(-1.0, 1.0) * sigma * (hi - lo)
            new = noise
        else:
            new = cur * rng.gauss(1.0, sigma)
        out[field] = round(max(lo, min(hi, new)), 5)
    return out


def crossover(rng: random.Random, p1: dict, p2: dict) -> dict:
    out = {}
    for field in RANGES:
        src = p1 if rng.random() < 0.5 else p2
        out[field] = round(float(src.get(field, 0.0)), 5)
    return out


def inherit_checkpoint(parent_out_dir: Path, child_out_dir: Path) -> None:
    """Copy best.zip + final.zip + arch tag from parent to child so PPO
    warm-starts from the parent's weights. Silently skips anything that
    isn't there yet (e.g. parent never saved a best.zip)."""
    if not parent_out_dir.exists():
        return
    child_out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("best.zip", "final.zip"):
        src = parent_out_dir / name
        if src.exists():
            shutil.copy2(src, child_out_dir / name)
    # Arch tag file: matches whatever obs/net the training pipeline uses.
    for tag in parent_out_dir.glob(".arch_obs*"):
        shutil.copy2(tag, child_out_dir / tag.name)


def write_population_json(population: dict[str, dict]) -> None:
    """Overwrite models/generated_presets.json with the current pop so
    train_parallel.load_all_presets picks them up by name."""
    GENPRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GENPRESETS_FILE.write_text(json.dumps(population, indent=2))


def recalibrate_top_k(population: dict[str, dict], raw_fitness: dict[str, float],
                      gen_dir: Path, ascension: int, k: int,
                      n_episodes: int) -> dict[str, float]:
    """Denoising pass — load best.zip for top-K presets and re-evaluate
    with `n_episodes` det + `n_episodes` stoch to replace the noisy
    single-pass mid-eval composite. Presets outside top-K keep their raw
    fitness (they're already losers; no need to spend compute on them).

    Returns a new fitness map: top-K replaced with calibrated score,
    others untouched."""
    from sb3_contrib import MaskablePPO  # local import: skip cost when k=0
    from sim.env_run import RewardConfig
    from scripts.train_parallel import evaluate_solo

    if k <= 0:
        return dict(raw_fitness)

    ranked = sorted(raw_fitness.items(), key=lambda kv: kv[1], reverse=True)
    top_k = ranked[:k]
    log(f"recalibrating top {k} with {n_episodes} det + {n_episodes} stoch episodes")

    calibrated = dict(raw_fitness)
    for i, (name, raw) in enumerate(top_k):
        best_zip = gen_dir / name / "best.zip"
        if not best_zip.exists():
            log(f"  [{i+1}/{k}] {name}  skip (no best.zip)")
            continue
        try:
            cfg = RewardConfig(**population[name])
            # Eval on CPU — model load + inference is dominated by env step
            # which is sequential Python anyway. Avoids contending with any
            # parallel training process on GPU.
            model = MaskablePPO.load(best_zip, device="cpu")
            det = evaluate_solo(model, ascension, cfg, n_episodes,
                                seed_base=500_000, deterministic=True)
            stoch = evaluate_solo(model, ascension, cfg, n_episodes,
                                  seed_base=500_000, deterministic=False)
            row = {
                "win_rate": det["win_rate"],
                "win_rate_stoch": stoch["win_rate"],
                "mean_floor": det["mean_floor"],
                "floor_stoch": stoch["mean_floor"],
                "mean_bosses": det["mean_bosses"],
            }
            new_fit = composite_score(row)
            calibrated[name] = new_fit
            log(f"  [{i+1}/{k}] {name}  raw={raw:.2f} -> cal={new_fit:.2f} "
                f"(win {det['win_rate']:.0%}/{stoch['win_rate']:.0%}, "
                f"floor {det['mean_floor']:.1f}/{stoch['mean_floor']:.1f}, "
                f"boss {det['mean_bosses']:.2f})")
        except Exception as e:
            log(f"  [{i+1}/{k}] {name}  ERR {type(e).__name__}: {e}")
    return calibrated


def train_one_subprocess(preset_name: str, ascension: int, steps: int,
                         eval_episodes: int, seed: int,
                         out_root: Path, history_root: Path,
                         log_path: Path) -> bool:
    """Spawn train_parallel.py for one preset; tee output to log_path.
    Returns True on exit-0."""
    eval_every = max(steps // 3, 5000)
    cmd = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"), "-u",
        str(ROOT / "scripts" / "train_parallel.py"),
        "--preset", preset_name, "--workers", "1",
        "--ascension", str(ascension),
        "--steps", str(steps),
        "--eval-every", str(eval_every),
        "--eval-episodes", str(eval_episodes),
        "--seed", str(seed),
        "--out-root", str(out_root),
        "--history-root", str(history_root),
    ]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                              text=True, cwd=str(ROOT), env=env)
    return proc.returncode == 0


def init_population(rng: random.Random, n: int) -> dict[str, dict]:
    return {f"g000_f{i:03d}": random_preset_cfg(rng, i, n) for i in range(n)}


def build_next_generation(rng: random.Random, current_pop: dict[str, dict],
                          fitness: dict[str, float], gen_dir_prev: Path,
                          gen_dir_next: Path,
                          n_survive: int, n_mutate: int, n_fresh: int,
                          sigma: float, hof: list[dict] | None = None) -> dict[str, dict]:
    """Returns the new population dict (name -> cfg) and copies inherited
    checkpoints into gen_dir_next/<new_name>/.

    Survivor pool composition:
      - top (n_survive - hof_inject) by current-gen fitness
      - top hof_inject from Hall of Fame (dedupe vs current survivors)
        — guarantees historically-strong presets aren't lost when a
        single bad gen happens to rank them low.

    Mutate budget is split: ~2/3 pure mutation + ~1/3 crossover (uniform
    per-field mixing of two random survivors)."""
    next_gen_idx = int(gen_dir_next.name.split('_')[1])
    hof = hof or []
    new_pop: dict[str, dict] = {}

    # ---- 1. Survivor pool: current top + HoF injects ----
    ranked = sorted(fitness.items(), key=lambda kv: kv[1], reverse=True)
    hof_inject = min(HOF_INJECT_COUNT, len(hof), n_survive)
    n_current_survive = max(1, n_survive - hof_inject)
    current_survivor_names = [name for name, _ in ranked[:n_current_survive]]

    survivor_cfgs: list[tuple[str, dict, Path | None]] = []  # (new_name, cfg, parent_dir)
    for i, parent_name in enumerate(current_survivor_names):
        child_name = f"g{next_gen_idx:03d}_s{i:03d}"
        survivor_cfgs.append((child_name, dict(current_pop[parent_name]),
                              gen_dir_prev / parent_name))

    # Append HoF entries that aren't already represented by current survivors.
    survivor_cfg_keys = {tuple(sorted((k, round(float(v), 5)) for k, v in c.items()))
                         for _, c, _ in survivor_cfgs}
    hof_added = 0
    for h in hof:
        if hof_added >= hof_inject:
            break
        key = tuple(sorted((k, round(float(v), 5)) for k, v in h["cfg"].items()))
        if key in survivor_cfg_keys:
            continue
        child_name = f"g{next_gen_idx:03d}_h{hof_added:03d}"
        # HoF parent lives in its original gen folder.
        parent_dir = EVOLVE_ROOT / f"gen_{h['gen']:03d}" / h["name"]
        survivor_cfgs.append((child_name, dict(h["cfg"]), parent_dir))
        survivor_cfg_keys.add(key)
        hof_added += 1

    for child_name, cfg, parent_dir in survivor_cfgs:
        new_pop[child_name] = cfg
        if parent_dir is not None:
            inherit_checkpoint(parent_dir, gen_dir_next / child_name)

    # Parents for variation = all survivors (current + HoF).
    parents = [(name, cfg, parent_dir) for name, cfg, parent_dir in survivor_cfgs]

    # ---- 2. Variation: ~2/3 mutation + ~1/3 crossover ----
    n_crossover = n_mutate // 3
    n_pure_mut = n_mutate - n_crossover

    for i in range(n_pure_mut):
        parent = rng.choice(parents)
        child_name = f"g{next_gen_idx:03d}_m{i:03d}"
        new_pop[child_name] = mutate(rng, parent[1], sigma)
        if parent[2] is not None:
            inherit_checkpoint(parent[2], gen_dir_next / child_name)

    if len(parents) >= 2:
        for i in range(n_crossover):
            p1, p2 = rng.sample(parents, 2)
            child_name = f"g{next_gen_idx:03d}_x{i:03d}"
            # Crossover then a touch of mutation so children aren't pure
            # parent combinations — keeps drift moving.
            child_cfg = crossover(rng, p1[1], p2[1])
            child_cfg = mutate(rng, child_cfg, sigma * 0.5)
            new_pop[child_name] = child_cfg
            # Inherit from the higher-ranked parent (p1) — its weights are
            # more likely to fit the merged reward shape.
            if p1[2] is not None:
                inherit_checkpoint(p1[2], gen_dir_next / child_name)
    else:
        # Edge case: only one survivor — top up with pure mutation.
        for i in range(n_crossover):
            parent = parents[0]
            child_name = f"g{next_gen_idx:03d}_x{i:03d}"
            new_pop[child_name] = mutate(rng, parent[1], sigma)
            if parent[2] is not None:
                inherit_checkpoint(parent[2], gen_dir_next / child_name)

    # ---- 3. Fresh random presets — no inheritance ----
    for i in range(n_fresh):
        child_name = f"g{next_gen_idx:03d}_f{i:03d}"
        new_pop[child_name] = random_preset_cfg(rng, i, max(n_fresh, 1))

    return new_pop


def save_state(gen: int, population: dict[str, dict],
               last_fitness: dict[str, float]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        "gen": gen,
        "population": population,
        "last_fitness": last_fitness,
    }, indent=2))


# -- Hall of Fame ------------------------------------------------------------


def load_hof() -> list[dict]:
    if HOF_FILE.exists():
        try:
            return json.loads(HOF_FILE.read_text())
        except Exception:
            return []
    return []


def save_hof(hof: list[dict]) -> None:
    HOF_FILE.parent.mkdir(parents=True, exist_ok=True)
    HOF_FILE.write_text(json.dumps(hof, indent=2))


def update_hof(hof: list[dict], candidates: list[dict]) -> list[dict]:
    """Merge new candidates into HoF; dedupe by cfg; keep top HOF_SIZE."""
    combined = list(hof) + list(candidates)
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for e in sorted(combined, key=lambda x: x["fitness"], reverse=True):
        key = tuple(sorted((k, round(float(v), 5)) for k, v in e["cfg"].items()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    return deduped[:HOF_SIZE]


# -- Auto-deploy (export ONNX + copy + commit + push) ------------------------


def load_last_deploy() -> dict:
    if LAST_DEPLOY_FILE.exists():
        try:
            return json.loads(LAST_DEPLOY_FILE.read_text())
        except Exception:
            pass
    return {"fitness": -1e9, "gen": -1, "name": ""}


def save_last_deploy(rec: dict) -> None:
    LAST_DEPLOY_FILE.write_text(json.dumps(rec, indent=2))


def _git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True,
                          cwd=str(ROOT), check=check)


def auto_deploy(name: str, cfg: dict, fitness: float, gen: int,
                gen_dir: Path) -> bool:
    """Export top preset's best.zip to ONNX, copy into mods/, commit, push.

    Returns True iff every step succeeded. Failures (export, push) are
    logged but never crash the evolver — training continues even if the
    deploy pipeline is offline."""
    best_zip = gen_dir / name / "best.zip"
    if not best_zip.exists():
        log(f"  auto-deploy: no best.zip at {best_zip} — skip")
        return False

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # 1. Export ONNX (overwrites tools/STS2MCP-bin/policy.onnx)
    cmd = [
        str(ROOT / ".venv" / "Scripts" / "python.exe"),
        str(EXPORT_SCRIPT),
        "--model", str(best_zip),
        "--out", str(DEPLOYED_ONNX),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        log(f"  auto-deploy: export_onnx failed (rc={proc.returncode})")
        log(f"    stderr: {proc.stderr[-400:]}")
        return False
    onnx_size = DEPLOYED_ONNX.stat().st_size
    log(f"  auto-deploy: exported {best_zip.name} -> policy.onnx ({onnx_size} bytes)")

    # 2. Copy to game mods folder (best-effort; game install may not exist
    #    on every machine the evolver runs on).
    if GAME_MODS_DIR.exists():
        try:
            shutil.copy2(DEPLOYED_ONNX, GAME_MODS_DIR / "policy.onnx")
            log(f"  auto-deploy: copied to {GAME_MODS_DIR}")
        except Exception as e:
            log(f"  auto-deploy: copy to mods folder failed: {e!r}")

    # 3. git add + commit + push. `git diff --cached --quiet` returns 1
    #    when there's something staged; we only commit if so.
    _git("add", str(DEPLOYED_ONNX))
    diff_check = _git("diff", "--cached", "--quiet", str(DEPLOYED_ONNX))
    if diff_check.returncode == 0:
        log("  auto-deploy: policy.onnx unchanged after export — skip commit")
        return True

    cfg_pretty = json.dumps(cfg, indent=2)
    msg = (
        f"evolver: deploy gen{gen:03d} top preset ({name}, cal_fit={fitness:.2f})\n"
        f"\n"
        f"Auto-deployed by scripts/evolve_presets.py after recalibration.\n"
        f"\n"
        f"Preset cfg:\n{cfg_pretty}\n"
        f"\n"
        f"Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
    )
    commit = _git("commit", "-m", msg)
    if commit.returncode != 0:
        log(f"  auto-deploy: commit failed (rc={commit.returncode})")
        log(f"    stderr: {commit.stderr[-400:]}")
        return False
    log("  auto-deploy: committed")

    push = _git("push", "origin", "main")
    if push.returncode != 0:
        log(f"  auto-deploy: push failed (rc={push.returncode}); local commit retained")
        log(f"    stderr: {push.stderr[-400:]}")
        return False
    log("  auto-deploy: pushed to origin/main")
    return True


def load_state() -> tuple[int, dict[str, dict], dict[str, float]] | None:
    if not STATE_FILE.exists():
        return None
    try:
        s = json.loads(STATE_FILE.read_text())
        return int(s.get("gen", 0)), dict(s.get("population", {})), dict(s.get("last_fitness", {}))
    except Exception as e:
        log(f"state load failed: {e!r}; starting fresh")
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", type=int, default=80,
                    help="Concurrent population size.")
    ap.add_argument("--steps", type=int, default=20000,
                    help="Train budget per preset per generation.")
    ap.add_argument("--eval-episodes", type=int, default=10,
                    help="Per-eval episode count during training (det + stoch each).")
    ap.add_argument("--survive-frac", type=float, default=0.20)
    ap.add_argument("--mutate-frac", type=float, default=0.60)
    ap.add_argument("--mutation-sigma", type=float, default=0.25)
    ap.add_argument("--ascension", type=int, default=10)
    # Recalibration: denoise fitness via large-N eval on top performers
    # before survivor selection. K=0 disables.
    ap.add_argument("--recal-k", type=int, default=40,
                    help="Re-evaluate top K presets after training; 0 disables.")
    ap.add_argument("--recal-episodes", type=int, default=50,
                    help="Episodes per mode (det+stoch) during recalibration.")
    ap.add_argument("--max-gens", type=int, default=10**9)
    ap.add_argument("--seed", type=int, default=None,
                    help="RNG seed for population init / mutation. Default: time-based.")
    ap.add_argument("--no-resume", action="store_true",
                    help="Ignore state.json and start from gen 0.")
    args = ap.parse_args()

    EVOLVE_ROOT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)

    state = None if args.no_resume else load_state()
    if state is not None:
        gen, population, last_fitness = state
        log(f"resumed: starting gen {gen} with saved pop={len(population)} "
            f"(prev gen top fit: {max(last_fitness.values(), default=-1):.2f})")
    else:
        gen = 0
        population = init_population(rng, args.population)
        last_fitness = {}
        log(f"initialized gen 0: pop={len(population)}")

    n = args.population
    n_survive = max(1, int(n * args.survive_frac))
    n_mutate = max(0, int(n * args.mutate_frac))
    n_fresh = max(0, n - n_survive - n_mutate)
    log(f"gen layout: survive={n_survive}, mutate={n_mutate}, fresh={n_fresh} "
        f"(pop={n}, sigma={args.mutation_sigma}, ascension={args.ascension}, "
        f"steps/preset={args.steps})")

    while gen < args.max_gens:
        gen_dir = EVOLVE_ROOT / f"gen_{gen:03d}"
        runs_dir = EVOLVE_ROOT / f"gen_{gen:03d}_runs"
        gen_dir.mkdir(parents=True, exist_ok=True)
        runs_dir.mkdir(parents=True, exist_ok=True)

        # Snapshot upcoming gen BEFORE training so a crash mid-gen still
        # leaves a recoverable state (resume re-trains this gen rather
        # than losing the population definition).
        save_state(gen, population, last_fitness)

        # Publish population so train_parallel can resolve names.
        write_population_json(population)
        log(f"=== gen {gen} | pop={len(population)} | dir={gen_dir.name} ===")

        # Train each preset sequentially (GPU is the bottleneck — parallel
        # subprocesses don't help when one PPO is already saturating it).
        # Skip already-done presets on resume: a history JSON with at
        # least one mid-eval row means train_parallel completed; redoing
        # it wastes compute and double-counts warm-start.
        t_gen = time.time()
        names = list(population.keys())
        for i, name in enumerate(names):
            hist_path = runs_dir / f"{name}.json"
            if hist_path.exists():
                try:
                    if json.loads(hist_path.read_text()):  # non-empty list
                        f = fitness_from_history(hist_path)
                        log(f"  [{i+1:3d}/{len(names)}] -- {name}  resume-skip  fit={f:.2f}")
                        continue
                except Exception:
                    pass
            t0 = time.time()
            ok = train_one_subprocess(
                preset_name=name,
                ascension=args.ascension,
                steps=args.steps,
                eval_episodes=args.eval_episodes,
                seed=gen * 100_000 + i,
                out_root=gen_dir,
                history_root=runs_dir,
                log_path=runs_dir / f"{name}.log",
            )
            dt = time.time() - t0
            f = fitness_from_history(hist_path)
            tag = "OK " if ok else "ERR"
            log(f"  [{i+1:3d}/{len(names)}] {tag} {name}  {dt:.0f}s  fit={f:.2f}")

        # Raw fitness from training-time mid-evals (noisy: only 10 det +
        # 10 stoch episodes per mid-eval point).
        raw_fitness = {name: fitness_from_history(runs_dir / f"{name}.json")
                       for name in names}
        raw_ranked = sorted(raw_fitness.items(), key=lambda kv: kv[1], reverse=True)
        log(f"gen {gen} training done in {time.time() - t_gen:.0f}s. raw top 5:")
        for name, f in raw_ranked[:5]:
            log(f"  {name}  raw={f:.2f}")

        # Recalibrate top-K with larger N to denoise the survivor pick.
        # Bottom presets keep raw fitness — they're already eliminated.
        t_recal = time.time()
        fitness = recalibrate_top_k(
            population=population,
            raw_fitness=raw_fitness,
            gen_dir=gen_dir,
            ascension=args.ascension,
            k=args.recal_k,
            n_episodes=args.recal_episodes,
        )
        ranked = sorted(fitness.items(), key=lambda kv: kv[1], reverse=True)
        log(f"recalibration done in {time.time() - t_recal:.0f}s. calibrated top 10:")
        for name, f in ranked[:10]:
            raw = raw_fitness.get(name, 0)
            arrow = "->" if raw != f else " ="
            log(f"  {name}  raw={raw:.2f} {arrow} cal={f:.2f}")
        log(f"  median cal={ranked[len(ranked)//2][1]:.2f}, bottom={ranked[-1][1]:.2f}")

        # Update Hall of Fame with this gen's top performers (calibrated).
        hof = load_hof()
        candidates = [{"name": n, "cfg": dict(population[n]), "fitness": f, "gen": gen}
                      for n, f in ranked[:HOF_SIZE]]
        hof = update_hof(hof, candidates)
        save_hof(hof)
        log(f"hall of fame ({len(hof)}):")
        for e in hof:
            log(f"  fit={e['fitness']:.2f}  gen{e['gen']:03d}  {e['name']}")

        # Auto-deploy: export top calibrated preset to ONNX + commit + push,
        # gated on strict improvement vs last deploy.
        top_name, top_fit = ranked[0]
        last_deploy = load_last_deploy()
        if top_fit > last_deploy.get("fitness", -1e9):
            log(f"auto-deploy: new best cal={top_fit:.2f} > last={last_deploy.get('fitness', -1e9):.2f}; deploying {top_name}")
            ok = auto_deploy(name=top_name, cfg=population[top_name],
                             fitness=top_fit, gen=gen, gen_dir=gen_dir)
            if ok:
                save_last_deploy({"fitness": top_fit, "gen": gen,
                                  "name": top_name, "ts": time.time()})
        else:
            log(f"auto-deploy: no improvement (top cal={top_fit:.2f} <= last={last_deploy.get('fitness', -1e9):.2f}); skip")

        # Build next gen — inherits checkpoints + injects HoF survivors.
        next_gen_dir = EVOLVE_ROOT / f"gen_{gen+1:03d}"
        next_gen_dir.mkdir(parents=True, exist_ok=True)
        new_pop = build_next_generation(
            rng=rng,
            current_pop=population,
            fitness=fitness,
            gen_dir_prev=gen_dir,
            gen_dir_next=next_gen_dir,
            n_survive=n_survive,
            n_mutate=n_mutate,
            n_fresh=n_fresh,
            sigma=args.mutation_sigma,
            hof=hof,
        )
        last_fitness = fitness
        population = new_pop
        gen += 1


if __name__ == "__main__":
    main()
