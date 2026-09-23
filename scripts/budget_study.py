"""How many measurements does it take to find a phase boundary under noise?

    python3 scripts/budget_study.py

Four strategies choose where to measure, under a fixed budget of pings, on the
same stages the game uses. Each ping returns the two correlators with real shot
noise. From those pings alone a boundary is reconstructed, and the reconstructed
ordered/chaotic map is scored against the stage's own ground truth.

Strategies
  random     uniform random points
  grid       an even lattice, the obvious thing to do
  bisect     per-column binary search in h - what the in-game agent plays
  adaptive   a coarse sweep, then every remaining ping next to the current
             boundary estimate, where the answer is still in doubt
"""
from __future__ import annotations

import json
import pathlib
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FERRO, PARA, ANTI, FLOAT = 0, 1, 2, 3
ORDER_THRESHOLD = 0.46          # calibrated once on the clean stage, then frozen
SHOTS = 100
BUDGETS = [6, 10, 16, 24, 36, 50]
SEEDS = 200
TEAL, ORANGE, PURPLE, BLUE, NAVY = "#007F7A", "#D4742B", "#7356A6", "#377CA8", "#152638"
COLORS = {"random": "#8FA6BA", "grid": BLUE, "bisect": ORANGE, "adaptive": TEAL}


class Stage:
    def __init__(self, data, stage):
        self.kappas = np.array(data["kappas"]); self.hs = np.array(data["hs"])
        self.zz1 = np.array(stage["zz1"]); self.zz2 = np.array(stage["zz2"])
        self.sd1 = np.array(stage["sd1"]); self.sd2 = np.array(stage["sd2"])
        self.truth = np.array(stage["truth"]); self.reference = np.array(data["reference"])
        self.scored = self.reference != FLOAT
        self.is_ordered = np.isin(self.truth, [FERRO, ANTI])
        self.name = stage["name"]; self.p = stage["p"]

    def ping(self, a, b, rng):
        zz1 = self.zz1[a, b] + self.sd1[a, b] / np.sqrt(SHOTS) * rng.normal()
        zz2 = self.zz2[a, b] + self.sd2[a, b] / np.sqrt(SHOTS) * rng.normal()
        return max(zz1, -zz2) > ORDER_THRESHOLD


def reconstruct(stage, points, verdicts):
    """Label every cell by the nearest measurements (3-nearest majority)."""
    if not points:
        return np.zeros_like(stage.is_ordered)
    grid_a, grid_b = np.meshgrid(np.arange(len(stage.hs)), np.arange(len(stage.kappas)), indexing="ij")
    pa = np.array([p[0] for p in points])[:, None, None]
    pb = np.array([p[1] for p in points])[:, None, None]
    votes = np.array(verdicts, dtype=float)[:, None, None]
    distance = np.hypot(grid_a[None] - pa, grid_b[None] - pb) + 1e-9
    order = np.argsort(distance, axis=0)[:3]                     # three nearest pings
    weights = 1.0 / np.take_along_axis(distance, order, axis=0)
    picked = np.take_along_axis(np.broadcast_to(votes, distance.shape), order, axis=0)
    return (picked * weights).sum(axis=0) / weights.sum(axis=0) > 0.5


def play(stage, strategy, budget, rng):
    n_h, n_k = stage.zz1.shape
    points, verdicts = [], []

    def take(a, b):
        a = int(np.clip(a, 0, n_h - 1)); b = int(np.clip(b, 0, n_k - 1))
        points.append((a, b)); verdicts.append(stage.ping(a, b, rng))
        return verdicts[-1]

    if strategy == "random":
        for _ in range(budget):
            take(rng.integers(n_h), rng.integers(n_k))

    elif strategy == "grid":
        side = max(2, int(round(np.sqrt(budget))))
        spots = [(a, b) for a in np.linspace(0, n_h - 1, side) for b in np.linspace(0, n_k - 1, side)]
        for a, b in spots[:budget]:
            take(a, b)

    elif strategy == "bisect":
        columns = max(2, budget // 3)
        per = max(1, budget // columns)
        for b in np.linspace(0, n_k - 1, columns):
            low, high = 0, n_h - 1
            for _ in range(per):
                if len(points) >= budget:
                    break
                mid = (low + high) // 2
                if take(mid, b):
                    low = mid
                else:
                    high = mid

    elif strategy == "adaptive":
        seed_count = max(4, budget // 3)
        for a, b in [(a, b) for a in np.linspace(0, n_h - 1, 2) for b in np.linspace(0, n_k - 1, max(2, seed_count // 2))]:
            if len(points) < seed_count:
                take(a, b)
        while len(points) < budget:
            belief = reconstruct(stage, points, verdicts)
            edge = np.zeros_like(belief, dtype=float)
            edge[:-1, :] += belief[:-1, :] != belief[1:, :]      # cells straddling the current guess
            edge[1:, :] += belief[:-1, :] != belief[1:, :]
            edge[:, :-1] += belief[:, :-1] != belief[:, 1:]
            edge[:, 1:] += belief[:, :-1] != belief[:, 1:]
            for a, b in points:                                   # do not re-measure what we know
                edge[max(0, a - 1):a + 2, max(0, b - 1):b + 2] = 0
            if edge.max() <= 0:
                take(rng.integers(n_h), rng.integers(n_k))
            else:
                candidates = np.argwhere(edge > 0)
                take(*candidates[rng.integers(len(candidates))])

    predicted = reconstruct(stage, points, verdicts)
    return float((predicted[stage.scored] == stage.is_ordered[stage.scored]).mean())


def main() -> None:
    data = json.loads((ROOT / "game/dataset.json").read_text())
    stages = {s["id"]: Stage(data, s) for s in data["stages"]}
    chosen = ["clean8", "noise01", "noise05"]
    results, report = {}, {}

    for key in chosen:
        stage = stages[key]
        results[key] = {}
        for strategy in ("random", "grid", "bisect", "adaptive"):
            rows = []
            for budget in BUDGETS:
                scores = [play(stage, strategy, budget, np.random.default_rng(1000 * seed + budget))
                          for seed in range(SEEDS)]
                rows.append((budget, float(np.mean(scores)), float(np.std(scores))))
            results[key][strategy] = rows
            report.setdefault(stage.name, {})[strategy] = {
                str(b): {"mean": round(m, 4), "sd": round(s, 4)} for b, m, s in rows}
        print(f"{stage.name:12} " + "  ".join(
            f"{st}:{results[key][st][2][1]:.1%}@16" for st in ("random", "grid", "bisect", "adaptive")))

    # Pings needed to reach 90%. The budget ladder is coarse, so a crossing whose mean
    # sits within two standard errors of the line could land one rung either way on a
    # different machine. Those are flagged rather than quoted as if they were exact.
    needed, borderline = {}, []
    for key in chosen:
        needed[stages[key].name] = {}
        for strategy, rows in results[key].items():
            hit = next((b for b, m, _ in rows if m >= 0.90), None)
            needed[stages[key].name][strategy] = hit
            for budget, mean, sd in rows:
                if budget == hit or (hit is not None and budget == max(
                        (b for b, _, _ in rows if b < hit), default=None)):
                    error = sd / np.sqrt(SEEDS)
                    if abs(mean - 0.90) < 2 * error:
                        borderline.append({"stage": stages[key].name, "strategy": strategy,
                                           "budget": budget, "mean": round(mean, 4),
                                           "standard_error": round(error, 4)})
    report["pings_to_reach_90pct"] = needed
    report["borderline_crossings"] = borderline
    report["seeds"] = SEEDS
    (ROOT / "data/budget_study.json").write_text(json.dumps(report, indent=2))
    for row in borderline:
        print(f"  borderline: {row['stage']} / {row['strategy']} at {row['budget']} pings is "
              f"{row['mean']:.3f} +/- {row['standard_error']:.3f} - within noise of the 90% line")

    figure, axes = plt.subplots(1, len(chosen), figsize=(4.4 * len(chosen), 3.6), sharey=True)
    for axis, key in zip(axes, chosen):
        stage = stages[key]
        for strategy, rows in results[key].items():
            budgets = np.array([b for b, _, _ in rows])
            means = np.array([m for _, m, _ in rows]); sds = np.array([s for _, _, s in rows])
            axis.plot(budgets, 100 * means, "o-", color=COLORS[strategy], lw=2, ms=4, label=strategy)
            axis.fill_between(budgets, 100 * (means - sds), 100 * (means + sds),
                              color=COLORS[strategy], alpha=0.13, lw=0)
        axis.axhline(90, color=NAVY, lw=1, ls=":")
        axis.set_xlabel("measurements (pings)")
        axis.set_title(f"{stage.name}  ·  p = {stage.p}", fontsize=10)
        axis.set_ylim(45, 100)
    axes[0].set_ylabel("map labelled correctly (%)")
    axes[0].legend(frameon=False, fontsize=8.5, loc="lower right")
    figure.suptitle(f"Finding a phase boundary on a measurement budget "
                    f"({SEEDS} seeds per point, {SHOTS} shots per ping)", fontsize=10.5)
    figure.tight_layout()
    figure.savefig(ROOT / "figures/budget_study.png", dpi=200)
    print("\npings to reach 90%:", json.dumps(needed))


if __name__ == "__main__":
    main()
