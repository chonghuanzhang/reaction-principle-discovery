#!/usr/bin/env python3
"""Branch-wise BO replay on the recorded SH/NH/OH screening plates.

This script never changes the source workbook.  It treats recorded responses
as an oracle and evaluates a prospective policy on the finite measured pool:
an initial outcome-blind batch is selected, a Bayesian linear surrogate is
fitted, and UCB selects subsequent batches.  The result is a replay/benchmark,
not evidence that the historical plates were selected prospectively by BO.
"""
from __future__ import annotations

import csv
import json
import math
import random
import re
import statistics
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BOOK = ROOT / "raw/summary_workbook.xlsx"
OUT = ROOT / "results/branchwise"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

N_REP = 100
N_INIT = 12
BATCH = 12
KAPPA = 1.96

ROUTES = {
    "SH": {
        "sheet": "亲核试剂(SH)-条件筛选", "metric": "AG", "initial": "PL33",
        "grids": ["PL39", "PL40"],
        "condition_cols": {"cat": "D", "ligand": "I", "base": "L", "solvent": "N"},
        "final": {"cat": "Cu9", "ligand": "PPh3", "base": "CsOH/2", "solvent": "DCE"},
        "followup_catalysts": ["Ag6", "Cu9"],
    },
    "NH": {
        "sheet": "亲核试剂(NH)-条件筛选", "metric": "AJ", "initial": "PL35",
        "grids": ["PL36"],
        "condition_cols": {"cat": "D", "ligand": "J", "base": "N", "solvent": "Q"},
        "final": {"cat": "Ag13", "ligand": "PPh3", "base": "NaH", "solvent": "DCE"},
        "followup_catalysts": ["Ag13"],
    },
    "OH": {
        "sheet": "亲核试剂(OH)-条件筛选", "metric": "AJ", "initial": "PL34",
        "grids": ["PL37", "PL38"],
        "condition_cols": {"cat": "D", "ligand": "I", "base": "L", "solvent": "O"},
        "final": {"cat": "Ni203", "ligand": "", "base": "DIPEA", "solvent": "DCE"},
        "followup_catalysts": ["Cu66", "Ni203"],
    },
}


def fnum(value):
    try:
        return float(value)
    except Exception:
        return None


def clean(value):
    return str(value or "").strip()


def plate(value):
    match = re.search(r"(PL\d+)", clean(value))
    return match.group(1) if match else ""


def read_workbook(path: Path):
    with zipfile.ZipFile(path) as z:
        shared_root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.findall(".//m:t", NS)) for si in shared_root.findall("m:si", NS)]
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rel = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {x.attrib["Id"]: x.attrib["Target"] for x in rel}
        sheets = {}
        for sh in wb.find("m:sheets", NS):
            name = sh.attrib["name"]
            target = relmap[sh.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
            target = target.lstrip("/") if target.startswith("/") else ("xl/" + target if not target.startswith("xl/") else target)
            root = ET.fromstring(z.read(target))
            rows = []
            for row in root.findall(".//m:sheetData/m:row", NS):
                vals = {}
                for c in row.findall("m:c", NS):
                    ref = c.attrib["r"]
                    col = re.match(r"[A-Z]+", ref).group()
                    typ = c.attrib.get("t")
                    v = c.find("m:v", NS)
                    value = v.text if v is not None else ""
                    if typ == "s" and value:
                        value = shared[int(value)]
                    elif typ == "inlineStr":
                        value = "".join(t.text or "" for t in c.findall(".//m:t", NS))
                    vals[col] = value
                if vals.get("A") and vals.get("A") != "Name":
                    rows.append(vals)
            sheets[name] = rows
        return sheets


def condition(r, route):
    return {k: clean(r.get(col)) for k, col in ROUTES[route]["condition_cols"].items()}


def normalize_condition(c):
    out = dict(c)
    if out.get("base") == "CsOH":
        out["base"] = "CsOH/2"
    if out.get("solvent", "").upper() in {"DIO", "DIOXANE", "1,4-DIOXANE"}:
        out["solvent"] = "1,4-dioxane"
    return out


def response_rows(rows, metric):
    out = []
    for r in rows:
        y = fnum(r.get(metric))
        if y is not None:
            out.append({"well": clean(r.get("A")), "response": y, "row": r})
    return out


def family(code):
    m = re.match(r"([A-Za-z]+)", clean(code))
    return m.group(1).lower() if m else "unknown"


def smiles_features(smiles):
    """Small, dependency-free descriptors for catalyst-panel replay."""
    s = clean(smiles)
    elements = ["cl", "br", "si", "na", "mg", "ca", "li", "al", "fe", "co", "ni", "cu", "ag", "pd", "pt", "rh", "ru", "ir", "au", "zn", "b", "c", "n", "o", "f", "p", "s", "i"]
    feats = []
    low = s.lower()
    for el in elements:
        feats.append(float(len(re.findall(r"(?<![a-z])" + re.escape(el) + r"(?![a-z])", low))))
    feats.extend([
        math.log1p(len(s)), float(s.count(".")), float(s.count("[")),
        float(s.count("+")), float(s.count("-")), float(sum(ch.islower() for ch in s)),
        float(sum(ch.isdigit() for ch in s)),
    ])
    return feats


def categorical_matrix(records, keys):
    levels = {k: sorted({clean(r.get(k)) for r in records}) for k in keys}
    names = [("intercept", "1")]
    for k in keys:
        names.extend((k, v) for v in levels[k])
    if "base" in keys and "solvent" in keys:
        names.extend(("base×solvent", f"{b}|{s}") for b in levels["base"] for s in levels["solvent"])

    def row(rec):
        x = [1.0]
        for k, v in names[1:]:
            if k == "base×solvent":
                x.append(float(f"{clean(rec.get('base'))}|{clean(rec.get('solvent'))}" == v))
            else:
                x.append(float(clean(rec.get(k)) == v))
        return x

    return np.asarray([row(r) for r in records], dtype=float), names


def catalyst_matrix(records):
    families = sorted({family(r.get("catalyst")) for r in records})
    mats = []
    for r in records:
        one = [float(family(r.get("catalyst")) == f) for f in families]
        one += smiles_features(r.get("smiles", ""))
        mats.append(one)
    return np.asarray(mats, dtype=float), [("family", f) for f in families] + [("smiles", str(i)) for i in range(len(mats[0]) - len(families))]


def posterior_ucb(X, selected, y):
    """Bayesian ridge posterior and UCB for finite-candidate BO."""
    p = X.shape[1]
    if not selected:
        beta = np.zeros(p)
        cov = np.eye(p)
        sigma2 = 1.0
    else:
        xs = X[selected]
        ys = np.asarray([y[i] for i in selected], dtype=float)
        prior = np.eye(p)
        prior[0, 0] = 0.1
        A = xs.T @ xs + prior
        cov = np.linalg.pinv(A)
        beta = cov @ xs.T @ ys
        resid = ys - xs @ beta
        sigma2 = max(float(np.var(resid)), 1e-4 * max(float(np.var(ys)), 1e-4))
    mu = X @ beta
    variance = sigma2 * np.maximum(1.0 + np.einsum("ij,jk,ik->i", X, cov, X), 1e-12)
    return mu, np.sqrt(variance), mu + KAPPA * np.sqrt(variance)


def diverse_initial(X, n, rng):
    """Outcome-blind max-min design with a random first point."""
    if n >= len(X):
        return list(range(len(X)))
    scale = np.std(X, axis=0)
    scale[scale == 0] = 1.0
    Z = (X - np.mean(X, axis=0)) / scale
    selected = [int(rng.randrange(len(X)))]
    min_dist = np.linalg.norm(Z - Z[selected[0]], axis=1)
    for _ in range(1, n):
        available = [i for i in range(len(X)) if i not in selected]
        pick = max(available, key=lambda i: (float(min_dist[i]), -i))
        selected.append(pick)
        min_dist = np.minimum(min_dist, np.linalg.norm(Z - Z[pick], axis=1))
    return selected


def run_policy(records, X, strategy, seed, n_init=N_INIT, batch=BATCH):
    rng = random.Random(seed)
    y = [float(r["response"]) for r in records]
    initial = diverse_initial(X, n_init, rng)
    selected = list(initial)
    rounds = [{"round": 1, "selected_indices": list(initial), "selection_mode": "outcome_blind_diverse"}]
    while len(selected) < len(records):
        if strategy == "random":
            remaining = [i for i in range(len(records)) if i not in set(selected)]
            rng.shuffle(remaining)
            pick = remaining[: min(batch, len(remaining))]
            mode = "random"
        else:
            _, _, ucb = posterior_ucb(X, selected, y)
            remaining = [i for i in range(len(records)) if i not in set(selected)]
            pick = sorted(remaining, key=lambda i: (-float(ucb[i]), i))[: min(batch, len(remaining))]
            mode = "ucb"
        if not pick:
            break
        selected.extend(pick)
        rounds.append({"round": len(rounds) + 1, "selected_indices": list(pick), "selection_mode": mode})
    best = []
    running = -float("inf")
    for n, idx in enumerate(selected, 1):
        running = max(running, y[idx])
        best.append(running)
    return {"seed": seed, "strategy": strategy, "selected": selected, "rounds": rounds, "best_by_budget": best, "initial": initial}


def first_selected_budget(run, target_indices):
    target = set(target_indices)
    budget = 0
    for batch in run["rounds"]:
        budget += len(batch["selected_indices"])
        if target.intersection(batch["selected_indices"]):
            return budget
    return None


def summarize_target_reach(runs, target_indices, n_records):
    budgets = [first_selected_budget(run, target_indices) for run in runs]
    values = [x if x is not None else n_records + 1 for x in budgets]
    return {
        "n_target_rows": len(target_indices),
        "median_budget": float(statistics.median(values)),
        "mean_budget": float(statistics.mean(values)),
        "reach_fraction": float(sum(x is not None for x in budgets) / len(budgets)),
    }


def summarize_runs(records, runs):
    y = np.asarray([r["response"] for r in records], dtype=float)
    max_y = float(np.max(y))
    threshold = float(np.min([max_y, np.quantile(y, 0.95)]))
    # The useful threshold is 95% of the observed best, not the 95th percentile.
    threshold = 0.95 * max_y
    budgets = sorted({len(r["selected"]) for r in runs})
    hit = []
    exact_hit = []
    for r in runs:
        first = None
        exact = None
        for i, value in enumerate(r["best_by_budget"], 1):
            if value >= threshold:
                first = i
            if exact is None and value >= max_y - 1e-12:
                exact = i
            if first is not None and exact is not None:
                break
        hit.append(first if first is not None else len(records) + 1)
        exact_hit.append(exact if exact is not None else len(records) + 1)
    by_budget = {}
    for b in range(BATCH, len(records) + 1, BATCH):
        vals = [r["best_by_budget"][min(b, len(records)) - 1] for r in runs]
        by_budget[str(b)] = {"mean_best": float(statistics.mean(vals)), "median_best": float(statistics.median(vals)), "hit_fraction_95pct": float(sum(v >= threshold for v in vals) / len(vals))}
    return {
        "n_records": len(records), "observed_max": max_y, "threshold_95pct_of_max": threshold,
        "median_budget_to_95pct": float(statistics.median(hit)),
        "mean_budget_to_95pct": float(statistics.mean(hit)),
        "median_budget_to_exact_best": float(statistics.median(exact_hit)),
        "mean_budget_to_exact_best": float(statistics.mean(exact_hit)),
        "best_by_budget": by_budget,
    }


def actual_rank(records, target):
    vals = sorted(records, key=lambda r: (-r["response"], r["well"]))
    keys = ["cat", "ligand", "base", "solvent"]
    matches = [i + 1 for i, r in enumerate(vals) if normalize_condition({k: r.get(k, "") for k in keys}) == normalize_condition(target)]
    return matches[0] if matches else None


def route_data(sheets, route):
    cfg = ROUTES[route]
    all_rows = sheets[cfg["sheet"]]
    initial_raw = [r for r in all_rows if plate(r.get("A")) == cfg["initial"]]
    initial = []
    for x in response_rows(initial_raw, cfg["metric"]):
        r = x["row"]
        initial.append({"well": x["well"], "response": x["response"], "catalyst": clean(r.get("D")), "smiles": clean(r.get("G")), "condition": condition(r, route)})
    grids = {}
    for p in cfg["grids"]:
        grid = []
        for x in response_rows([r for r in all_rows if plate(r.get("A")) == p], cfg["metric"]):
            r = x["row"]
            grid.append({"well": x["well"], "response": x["response"], "catalyst": clean(r.get("D")), "smiles": clean(r.get("G")), **condition(r, route)})
        grids[p] = grid
    return initial, grids


def jsonable(obj):
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, dict):
        return {k: jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [jsonable(v) for v in obj]
    return obj


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = read_workbook(BOOK)
    results = {
        "source_workbook": str(BOOK),
        "analysis_type": "prospective_policy_replay_on_recorded_outcomes",
        "n_replicates": N_REP, "n_init": N_INIT, "batch_size": BATCH, "kappa": KAPPA,
        "note": "Responses are revealed only after a policy selects a row; no source workbook cells are changed.",
        "routes": {},
    }
    round_rows = []
    for route in ["SH", "NH", "OH"]:
        initial, grids = route_data(sheets, route)
        X1, _ = catalyst_matrix(initial)
        stage1 = {}
        for strategy in ["BO-UCB", "random"]:
            runs = [run_policy(initial, X1, strategy, seed=1000 + i) for i in range(N_REP)]
            target_indices = [i for i, r in enumerate(initial) if r["catalyst"] in set(ROUTES[route]["followup_catalysts"])]
            stage1[strategy] = {"summary": summarize_runs(initial, runs), "actual_followup_catalyst_reach": summarize_target_reach(runs, target_indices, len(initial)), "runs": runs}
        init_sorted = sorted(initial, key=lambda r: (-r["response"], r["well"]))
        init_rank = {r["catalyst"]: i + 1 for i, r in enumerate(init_sorted)}
        grid_results = {}
        for p, grid in grids.items():
            X2, _ = categorical_matrix(grid, ["base", "solvent"])
            grid_out = {}
            for strategy in ["BO-UCB", "random"]:
                route_seed = {"SH": 1, "NH": 2, "OH": 3}[route]
                plate_seed = int(re.sub(r"\D", "", p) or 0)
                strategy_seed = 100 if strategy == "BO-UCB" else 200
                runs = [run_policy(grid, X2, strategy, seed=200000 + route_seed * 10000 + plate_seed * 100 + strategy_seed + i) for i in range(N_REP)]
                grid_out[strategy] = {"summary": summarize_runs(grid, runs), "runs": runs}
            grid_best = max(grid, key=lambda r: r["response"])
            target = ROUTES[route]["final"]
            final_matches = [r for r in grid if normalize_condition({k: r.get(k, "") for k in ["cat", "ligand", "base", "solvent"]}) == normalize_condition(target)]
            final_indices = [i for i, r in enumerate(grid) if normalize_condition({k: r.get(k, "") for k in ["cat", "ligand", "base", "solvent"]}) == normalize_condition(target)]
            for strategy in ["BO-UCB", "random"]:
                grid_out[strategy]["actual_final_condition_reach"] = summarize_target_reach(grid_out[strategy]["runs"], final_indices, len(grid))
            grid_results[p] = {
                "n_records": len(grid), "observed_best": grid_best,
                "final_condition_matches": final_matches,
                "final_condition_rank": actual_rank(grid, target),
                "replay": grid_out,
            }
            for strategy in ["BO-UCB", "random"]:
                summary = grid_out[strategy]["summary"]
                for budget, val in summary["best_by_budget"].items():
                    round_rows.append({"route": route, "stage": "condition_grid", "plate": p, "strategy": strategy, "budget": budget, **val})
        results["routes"][route] = {
            "initial_panel": {"n_records": len(initial), "top5": init_sorted[:5], "actual_followup_catalysts": [{"catalyst": c, "initial_rank": init_rank.get(c)} for c in ROUTES[route]["followup_catalysts"]], "replay": stage1},
            "condition_grids": grid_results,
            "final_condition": ROUTES[route]["final"],
        }
        for strategy in ["BO-UCB", "random"]:
            summary = stage1[strategy]["summary"]
            for budget, val in summary["best_by_budget"].items():
                round_rows.append({"route": route, "stage": "catalyst_panel", "plate": ROUTES[route]["initial"], "strategy": strategy, "budget": budget, **val})

    (OUT / "branchwise_bo_results.json").write_text(json.dumps(jsonable(results), ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "branchwise_bo_round_metrics.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["route", "stage", "plate", "strategy", "budget", "mean_best", "median_best", "hit_fraction_95pct"]
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(round_rows)

    lines = [
        "# SH/NH/OH 分支 BO 逐轮回放",
        "",
        "本报告把记录中的实验响应作为有限候选池的 oracle，模拟 outcome-blind 初始设计 → Bayesian ridge surrogate → UCB 批次选择 → 揭示响应 → 更新模型。它是基于已完成实验的策略回放，不是原始实验历史日志。",
        "",
        f"参数：每次运行初始批次 {N_INIT} 个，之后每批 {BATCH} 个；每个板运行 {N_REP} 个随机初始设计；BO 使用 UCB = posterior mean + {KAPPA} × posterior standard deviation。",
        "",
    ]
    for route in ["SH", "NH", "OH"]:
        rr = results["routes"][route]
        lines += [f"## {route}", "", f"初始催化剂板：{ROUTES[route]['initial']}，{rr['initial_panel']['n_records']} 条数值记录。"]
        lines.append(f"实际进入后续筛选的催化剂及初始面板名次：{rr['initial_panel']['actual_followup_catalysts']}。")
        for strategy in ["BO-UCB", "random"]:
            s = rr["initial_panel"]["replay"][strategy]["summary"]
            lines.append(f"催化剂面板 {strategy}：达到观测最高值 95% 的中位预算 {s['median_budget_to_95pct']:.1f}，精确命中最高点的中位预算 {s['median_budget_to_exact_best']:.1f}。")
        for p, g in rr["condition_grids"].items():
            lines += ["", f"{p}：{g['n_records']} 点条件网格；观测最高点 {g['observed_best']}；最终条件名次 {g['final_condition_rank']}。"]
            for strategy in ["BO-UCB", "random"]:
                s = g["replay"][strategy]["summary"]
                lines.append(f"{strategy}：达到该网格最高值 95% 的中位预算 {s['median_budget_to_95pct']:.1f}，精确命中最高点的中位预算 {s['median_budget_to_exact_best']:.1f}。")
        lines.append("")
    lines += [
        "## 解读规则",
        "",
        "只有当 BO-UCB 的预算分布优于相同初始设计的随机基线，并且实际采用条件在模型给出的高 acquisition 候选中出现，才能说数据与 BO-guided selection 一致。否则应报告为条件空间 HTE 筛选，而不能把最终最高响应倒推成 BO 推荐。",
        "",
        "对于 96 点网格，本回放把每 12 个候选作为一个虚拟批次；如果原始记录没有这些批次的时间戳，这些虚拟批次是评价策略的计算分组，不是历史实验批次。",
    ]
    (OUT / "branchwise_bo_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
