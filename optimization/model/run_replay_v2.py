#!/usr/bin/env python3
"""Validated v2 branch-wise batch BO replay."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import bo_core  # noqa: E402
import run_branchwise_bo_replay as v1  # noqa: E402


OUT = HERE
N_REP = 100
N_INIT = 12
BATCH = 12
PRIMARY_BUDGET = 48
ROUTES = v1.ROUTES


def standardize(X):
    X = np.asarray(X, dtype=float)
    scale = np.std(X, axis=0)
    scale[scale == 0] = 1.0
    return (X - np.mean(X, axis=0)) / scale


def family(code):
    m = re.match(r"([A-Za-z]+)", str(code or ""))
    return m.group(1).lower() if m else "unknown"


def panel_matrix(records):
    families = sorted({family(r.get("catalyst")) for r in records})
    elements = ["Br", "Cl", "Si", "Na", "Mg", "Ca", "Li", "Al", "Fe", "Co", "Ni", "Cu", "Ag", "Pd", "Pt", "Rh", "Ru", "Ir", "Au", "Zn", "B", "C", "N", "O", "P", "S", "F", "I", "b", "c", "n", "o", "p", "s"]
    rows = []
    for r in records:
        counts = bo_core.smiles_counts(r.get("smiles", ""))
        one = [float(family(r.get("catalyst")) == f) for f in families]
        one += [float(counts.get(e, 0)) for e in elements]
        one += [math.log1p(len(str(r.get("smiles", "")))), float(str(r.get("smiles", "")).count(".")), float(str(r.get("smiles", "")).count("+")), float(str(r.get("smiles", "")).count("-"))]
        rows.append(one)
    return standardize(rows)


def grid_matrix(records):
    levels = {k: sorted({str(r.get(k, "")) for r in records}) for k in ["base", "solvent"]}
    names = [("base", x) for x in levels["base"]] + [("solvent", x) for x in levels["solvent"]] + [("pair", f"{b}|{s}") for b in levels["base"] for s in levels["solvent"]]
    rows = []
    for r in records:
        rows.append([float(str(r.get(k, "")) == v if k != "pair" else f"{r.get('base','')}|{r.get('solvent','')}" == v) for k, v in names])
    return standardize(rows)


def key_condition(r):
    return v1.normalize_condition({k: r.get(k, "") for k in ["cat", "ligand", "base", "solvent"]})


def batch_end_budget(run, records, target_indices=None, threshold=None):
    target = set(target_indices or [])
    best = -float("inf")
    exact = None
    near = None
    target_budget = None
    for round_no, batch in enumerate(run["batches"], 1):
        for i in batch:
            best = max(best, float(records[i]["response"]))
        budget = sum(len(x) for x in run["batches"][:round_no])
        if threshold is not None and near is None and best >= threshold:
            near = budget
        if exact is None and best >= max(float(r["response"]) for r in records) - 1e-12:
            exact = budget
        if target and target_budget is None and target.intersection(batch):
            target_budget = budget
    return {"near_budget": near, "exact_budget": exact, "target_budget": target_budget}


def budget_or_sentinel(value, n):
    return int(value) if value is not None else n + 1


def paired_summary(bo_values, random_values, n, primary=PRIMARY_BUDGET):
    bo = np.asarray([budget_or_sentinel(v, n) for v in bo_values], dtype=float)
    rnd = np.asarray([budget_or_sentinel(v, n) for v in random_values], dtype=float)
    d = rnd - bo
    return {
        "bo_median": float(np.median(bo)), "random_median": float(np.median(rnd)),
        "bo_mean": float(np.mean(bo)), "random_mean": float(np.mean(rnd)),
        "median_saving_random_minus_bo": float(np.median(d)),
        "mean_saving_random_minus_bo": float(np.mean(d)),
        "bo_success_by_budget": float(np.mean(bo <= primary)),
        "random_success_by_budget": float(np.mean(rnd <= primary)),
        "paired_bootstrap_95ci_saving": bootstrap_ci(d, seed=42),
    }


def bootstrap_ci(values, seed=42, n_boot=2000):
    rng = np.random.default_rng(seed)
    values = np.asarray(values, dtype=float)
    means = np.mean(rng.choice(values, size=(n_boot, len(values)), replace=True), axis=1)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def summarize_stage(records, K, runs_by_strategy, target_indices=None):
    best = max(float(r["response"]) for r in records)
    near = 0.95 * best
    out = {"n_records": len(records), "observed_best": best, "threshold": near}
    for strategy, runs in runs_by_strategy.items():
        near_values, exact_values, target_values = [], [], []
        for run in runs:
            stat = batch_end_budget(run, records, target_indices, near)
            near_values.append(stat["near_budget"])
            exact_values.append(stat["exact_budget"])
            target_values.append(stat["target_budget"])
        out[strategy] = {
            "near_budget": {"median": float(np.median([budget_or_sentinel(x, len(records)) for x in near_values])), "mean": float(np.mean([budget_or_sentinel(x, len(records)) for x in near_values]))},
            "exact_budget": {"median": float(np.median([budget_or_sentinel(x, len(records)) for x in exact_values])), "mean": float(np.mean([budget_or_sentinel(x, len(records)) for x in exact_values]))},
            "target_budget": {"median": float(np.median([budget_or_sentinel(x, len(records)) for x in target_values])) if target_indices else None, "mean": float(np.mean([budget_or_sentinel(x, len(records)) for x in target_values])) if target_indices else None, "reach_fraction": float(np.mean([x is not None for x in target_values])) if target_indices else None},
        }
    for metric in ["near_budget", "exact_budget", "target_budget"]:
        if metric == "target_budget" and not target_indices:
            continue
        bo_vals = [batch_end_budget(r, records, target_indices, near)[metric] for r in runs_by_strategy["BO-UCB"]]
        random_vals = [batch_end_budget(r, records, target_indices, near)[metric] for r in runs_by_strategy["random"]]
        out["paired_" + metric] = paired_summary(bo_vals, random_vals, len(records))
    return out


def run_stage(records, K, target_indices, seed_base):
    runs = {"BO-UCB": [], "random": []}
    for i in range(N_REP):
        # Same seed means the two policies receive the same outcome-blind initial batch.
        runs["BO-UCB"].append(bo_core.run_campaign(K, np.asarray([r["response"] for r in records]), seed_base + i, "BO-UCB", N_INIT, BATCH))
        runs["random"].append(bo_core.run_campaign(K, np.asarray([r["response"] for r in records]), seed_base + i, "random", N_INIT, BATCH))
    return runs, summarize_stage(records, K, runs, target_indices)


def reference_log(route, stage, plate, records, runs, output_rows):
    for strategy, run in runs.items():
        ref = run[0]
        for round_no, (batch, score) in enumerate(zip(ref["batches"], ref["scores"]), 1):
            score_by_idx = {idx: (score["mean"][j], score["std"][j], score["acquisition"][j]) for j, idx in enumerate(score["indices"]) if j < len(score["mean"])}
            budget = sum(len(x) for x in ref["batches"][:round_no])
            for idx in batch:
                mean, std, acq = score_by_idx.get(idx, ("", "", ""))
                output_rows.append({"route": route, "stage": stage, "plate": plate, "strategy": strategy, "seed": 0, "round": round_no, "budget": budget, "well": records[idx]["well"], "response": records[idx]["response"], "selected": 1, "posterior_mean": mean, "posterior_std": std, "ucb": acq})


def main():
    sheets = v1.read_workbook(v1.BOOK)
    source_hash = hashlib.sha256(v1.BOOK.read_bytes()).hexdigest()
    results = {
        "source_workbook": str(v1.BOOK), "source_sha256": source_hash,
        "analysis_type": "retrospective_batch_policy_benchmark",
        "algorithm": "conjugate Bayesian linear regression in kernel form + batch UCB",
        "n_replicates": N_REP, "n_init": N_INIT, "batch_size": BATCH, "primary_budget": PRIMARY_BUDGET,
        "paired_initial_design": True, "historical_order_claim": False,
        "routes": {},
    }
    log_rows = []
    for route in ["SH", "NH", "OH"]:
        initial, grids = v1.route_data(sheets, route)
        K1x = panel_matrix(initial); K1 = K1x @ K1x.T
        target_cat_idx = [i for i, r in enumerate(initial) if r["catalyst"] in set(ROUTES[route]["followup_catalysts"])]
        s1_runs, s1_summary = run_stage(initial, K1, target_cat_idx, {"SH": 1000, "NH": 2000, "OH": 3000}[route])
        initial_sorted = sorted(initial, key=lambda r: (-r["response"], r["well"]))
        rank = {r["catalyst"]: i + 1 for i, r in enumerate(initial_sorted)}
        grids_out = {}
        reference_log(route, "catalyst_panel", ROUTES[route]["initial"], initial, s1_runs, log_rows)
        for plate, grid in grids.items():
            K2x = grid_matrix(grid); K2 = K2x @ K2x.T
            target = ROUTES[route]["final"]
            target_idx = [i for i, r in enumerate(grid) if key_condition(r) == v1.normalize_condition(target)]
            runs, summary = run_stage(grid, K2, target_idx, {"PL39": 4000, "PL40": 5000, "PL36": 6000, "PL37": 7000, "PL38": 8000}[plate])
            observed_best = max(grid, key=lambda r: r["response"])
            vals = sorted(grid, key=lambda r: (-r["response"], r["well"]))
            final_rank = next((i + 1 for i, r in enumerate(vals) if key_condition(r) == v1.normalize_condition(target)), None)
            grids_out[plate] = {"summary": summary, "observed_best": observed_best, "final_condition_rank": final_rank, "final_condition_rows": [grid[i] for i in target_idx]}
            reference_log(route, "condition_grid", plate, grid, runs, log_rows)
        results["routes"][route] = {
            "initial_panel": {"plate": ROUTES[route]["initial"], "n_records": len(initial), "actual_followup_catalyst_ranks": [{"catalyst": c, "rank": rank.get(c)} for c in ROUTES[route]["followup_catalysts"]], "summary": s1_summary},
            "condition_grids": grids_out, "final_condition": ROUTES[route]["final"],
        }

    (OUT / "bo_v2_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "bo_v2_reference_round_log.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["route", "stage", "plate", "strategy", "seed", "round", "budget", "well", "response", "selected", "posterior_mean", "posterior_std", "ucb"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(log_rows)

    lines = [
        "# SH/NH/OH 批量 BO 验证 v2", "",
        "这是在已完成实验响应上的策略回放。模型每轮只能读取此前已选批次的响应；原始实验记录没有被修改，也不据此声称历史实验当时由 BO 实时控制。", "",
        f"固定参数：100 组配对运行；初始批次 {N_INIT} 点，后续每批 {BATCH} 点；相同 seed 下 BO 与随机基线使用完全相同的初始批次；主要预算为 {PRIMARY_BUDGET} 点。", "",
    ]
    for route in ["SH", "NH", "OH"]:
        rr = results["routes"][route]
        lines += [f"## {route}", "", f"催化剂面板 {rr['initial_panel']['plate']}：{rr['initial_panel']['n_records']} 条记录；实际后续催化剂初始排名 {rr['initial_panel']['actual_followup_catalyst_ranks']}。"]
        for s in ["BO-UCB", "random"]:
            q = rr["initial_panel"]["summary"][s]
            lines.append(f"{s}：95% 最高响应中位预算 {q['near_budget']['median']:.1f}，精确最高点中位预算 {q['exact_budget']['median']:.1f}，实际后续催化剂命中中位预算 {q['target_budget']['median']:.1f}。")
        lines.append(f"催化剂面板 BO 相对随机的 95% 命中预算节省（random − BO）中位数：{rr['initial_panel']['summary']['paired_near_budget']['median_saving_random_minus_bo']:.1f}，bootstrap 95% CI {rr['initial_panel']['summary']['paired_near_budget']['paired_bootstrap_95ci_saving']}。")
        for plate, gg in rr["condition_grids"].items():
            lines += ["", f"{plate} 条件网格：{gg['observed_best']['well']} 为观测最高点；主条件在该网格排名 {gg['final_condition_rank']}。"]
            for s in ["BO-UCB", "random"]:
                q = gg["summary"][s]
                lines.append(f"{s}：95% 最高响应中位预算 {q['near_budget']['median']:.1f}，精确最高点中位预算 {q['exact_budget']['median']:.1f}，实际主条件命中中位预算 {q['target_budget']['median'] if q['target_budget']['median'] is not None else 'n/a'}。")
            lines.append(f"该网格 95% 命中预算节省（random − BO）中位数：{gg['summary']['paired_near_budget']['median_saving_random_minus_bo']:.1f}，bootstrap 95% CI {gg['summary']['paired_near_budget']['paired_bootstrap_95ci_saving']}。")
        lines.append("")
    lines += ["## 解释边界", "", "催化剂面板和条件网格必须分别报告。只有当 BO 的配对预算分布优于随机基线、bootstrap 区间支持方向稳定，并且实际采用条件在 BO 轨迹中按预先定义的 target 指标被提前选中时，才可称为与 BO-guided selection 一致。这个分析不把最终全池最优值传入模型，也不把虚拟批次称为历史实验批次。"]
    (OUT / "bo_v2_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
