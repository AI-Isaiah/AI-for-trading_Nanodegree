"""
Build QuantStats tearsheets + leverage diagnostics for a NAV file and a base
leverage.

    python run_report.py --csv data/FX_DailyDec2025_Backtest.csv --base-lev 30
    python run_report.py --csv data/FX_DailyDec2025_Backtest.csv --base-lev 35
    python run_report.py --all          # every dataset x {30x, 35x}

Outputs land in output/<dataset>/<base>x/:
    tearsheet_static_<b>x.html        static base leverage, benchmarked vs 1x
    tearsheet_dynamic_<b>_<c>x.html   dynamic policy, benchmarked vs static base
    leverage_diagnostics.png          equity / leverage / notional / drawdown
    daily_path.csv                    day-by-day audit trail
    summary.csv                       side-by-side headline stats
"""

from __future__ import annotations

import argparse
import os
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import numpy as np
import quantstats as qs

from leverage_engine import (
    DATA_DIR,
    MAX_LEV,
    OUT_DIR,
    load_returns,
    run_dynamic,
    run_static,
    summarise,
)

warnings.filterwarnings("ignore")

DATASETS = {
    "uc244_jul2026": "UC244_FXDaily_2026-07-20.csv",
    "fx_dec2025_backtest": "FX_DailyDec2025_Backtest.csv",
}


def build_tearsheets(unlev, static, dynamic, out_dir, base, cap, label):
    b, c = f"{base:g}", f"{cap:g}"
    qs.reports.html(
        static.returns.rename(f"Static {b}x"),
        benchmark=unlev.rename("Unlevered 1x"),
        benchmark_title="Unlevered 1x",
        title=f"{label} — Static {b}x Leverage",
        output=os.path.join(out_dir, f"tearsheet_static_{b}x.html"),
        periods_per_year=252,
        rf=0.0,
    )
    qs.reports.html(
        dynamic.returns.rename(f"Dynamic {b}-{c}x"),
        benchmark=static.returns.rename(f"Static {b}x"),
        benchmark_title=f"Static {b}x",
        title=(f"{label} — Dynamic Leverage ({b}x base, {c}x cap, "
               "constant notional in drawdown)"),
        output=os.path.join(out_dir, f"tearsheet_dynamic_{b}_{c}x.html"),
        periods_per_year=252,
        rf=0.0,
    )


def plot_diagnostics(static, dynamic, out_dir, base, cap, label):
    b, c = f"{base:g}", f"{cap:g}"
    scale, unit = (1e6, "$m")
    fig, ax = plt.subplots(4, 1, figsize=(13, 15), sharex=True,
                           gridspec_kw={"height_ratios": [2.2, 1.3, 1.3, 1.4]})
    fig.suptitle(f"{label} — base {b}x, cap {c}x", y=0.997, fontsize=13)

    ax[0].plot(static.equity.index, static.equity / scale, label=f"Static {b}x", lw=1.2)
    ax[0].plot(dynamic.equity.index, dynamic.equity / scale,
               label=f"Dynamic {b}→{c}x", lw=1.2)
    ax[0].set_yscale("log")
    ax[0].axhline(static.start_equity / scale, color="grey", lw=0.7, ls="--")
    ax[0].set_ylabel(f"Equity ({unit}, log)")
    ax[0].set_title("Equity curve")
    ax[0].legend()
    ax[0].grid(alpha=0.3, which="both")

    ax[1].plot(dynamic.leverage.index, dynamic.leverage, color="darkorange", lw=1.0,
               label="Applied leverage")
    ax[1].axhline(base, color="grey", ls="--", lw=0.8, label=f"{b}x base")
    ax[1].axhline(cap, color="red", ls="--", lw=0.8, label=f"{c}x cap")
    ax[1].set_ylabel("Leverage (x)")
    ax[1].set_title("Applied gross leverage — dynamic policy")
    ax[1].legend()
    ax[1].grid(alpha=0.3)

    ax[2].plot(dynamic.target_notional.index, dynamic.target_notional / scale,
               color="black", lw=1.0, ls="--", label="Target notional (ratchet)")
    ax[2].plot(dynamic.notional.index, dynamic.notional / scale, color="tab:green",
               lw=1.1, label="Dynamic notional held")
    ax[2].plot(static.notional.index, static.notional / scale, color="tab:blue",
               lw=1.0, label=f"Static {b}x notional held")
    ax[2].set_yscale("log")
    ax[2].set_ylabel(f"Gross notional ({unit}, log)")
    ax[2].set_title("Notional exposure — flat through drawdowns, steps up only on new highs")
    ax[2].legend()
    ax[2].grid(alpha=0.3, which="both")

    for path, lbl in ((static, f"Static {b}x"), (dynamic, f"Dynamic {b}→{c}x")):
        dd = path.equity / path.equity.cummax() - 1.0
        ax[3].plot(dd.index, dd * 100, lw=1.1, label=lbl)
    ax[3].set_ylabel("Drawdown (%)")
    ax[3].set_title("Drawdown")
    ax[3].legend()
    ax[3].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "leverage_diagnostics.png"), dpi=130)
    plt.close(fig)


def solve_min_cap(unlev, start_equity, base) -> tuple[float, float]:
    """
    Smallest cap at which the policy is never forced to cut notional.

    Running the policy uncapped is already the fixed point: the highest leverage
    it reaches is exactly the cap that would just never bind (raising the cap
    deepens the drawdown, which raises the leverage required -- the uncapped run
    resolves that circularity in one pass).  Returns (min_cap, uncapped_max_dd).
    """
    free = run_dynamic(unlev, start_equity, base, np.inf)
    max_dd = (free.equity / free.equity.cummax() - 1.0).min()
    return float(free.leverage.max()), float(max_dd)


def run_one(csv_path: str, base: float, cap: float, dataset: str,
            start: str | None = None, end: str | None = None,
            start_equity_override: float | None = None,
            tag: str | None = None) -> pd.DataFrame:
    label = dataset.replace("_", " ").upper()
    out_dir = os.path.join(OUT_DIR, dataset, tag or f"{base:g}x")
    os.makedirs(out_dir, exist_ok=True)

    unlev, start_equity = load_returns(csv_path)
    if start or end:
        unlev = unlev.loc[start or None:end or None]
        label = f"{label} [{unlev.index[0].date()} → {unlev.index[-1].date()}]"
    if start_equity_override is not None:
        start_equity = start_equity_override
    static = run_static(unlev, start_equity, base)
    dynamic = run_dynamic(unlev, start_equity, base, cap)

    pd.DataFrame(
        {
            "unlevered_ret": unlev,
            "static_ret": static.returns,
            "static_equity": static.equity,
            "dyn_leverage": dynamic.leverage,
            "dyn_ret": dynamic.returns,
            "dyn_equity": dynamic.equity,
            "dyn_peak_equity": dynamic.peak_equity,
            "dyn_target_notional": dynamic.target_notional,
            "dyn_notional_held": dynamic.notional,
            "dyn_notional_capped": dynamic.capped,
            "dyn_drawdown": dynamic.equity / dynamic.equity.cummax() - 1.0,
        }
    ).to_csv(os.path.join(out_dir, "daily_path.csv"))

    summary = pd.DataFrame(
        [
            summarise(run_static(unlev, start_equity, 1.0), "Unlevered 1x"),
            summarise(static, f"Static {base:g}x"),
            summarise(dynamic, f"Dynamic {base:g}→{cap:g}x"),
        ]
    ).set_index("policy")
    summary.to_csv(os.path.join(out_dir, "summary.csv"))

    build_tearsheets(unlev, static, dynamic, out_dir, base, cap, label)
    plot_diagnostics(static, dynamic, out_dir, base, cap, label)

    print(f"\n=== {label} | base {base:g}x, cap {cap:g}x | "
          f"{len(unlev)} days {unlev.index[0].date()} → {unlev.index[-1].date()} | "
          f"start ${start_equity:,.0f} ===")
    print(_fmt(summary).T.to_string())
    return summary


def _fmt(summary: pd.DataFrame) -> pd.DataFrame:
    d = summary.copy()
    for c in ["total_return", "cagr", "ann_vol", "max_dd", "avg_dd", "pct_time_in_dd",
              "best_day", "worst_day", "worst_5d", "win_rate"]:
        d[c] = (d[c] * 100).round(2).astype(str) + "%"
    for c in ["final_equity", "min_notional", "max_notional", "final_notional",
              "worst_day_pnl"]:
        d[c] = (d[c] / 1e6).round(3).astype(str) + "m"
    for c in ["sharpe", "sortino", "calmar", "avg_leverage", "max_leverage",
              "profit_factor"]:
        d[c] = d[c].round(2)
    return d


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv")
    p.add_argument("--dataset", choices=list(DATASETS))
    p.add_argument("--base-lev", type=float, default=30.0)
    p.add_argument("--max-lev", type=float, default=MAX_LEV)
    p.add_argument("--all", action="store_true",
                   help="run every dataset at 30x and 35x")
    p.add_argument("--start", help="restrict to dates >= this (YYYY-MM-DD)")
    p.add_argument("--end", help="restrict to dates <= this (YYYY-MM-DD)")
    p.add_argument("--start-equity", type=float,
                   help="override the equity the window starts from")
    p.add_argument("--tag", help="output sub-directory name (default '<base>x')")
    p.add_argument("--solve-cap", action="store_true",
                   help="report the smallest cap that never binds, then use it")
    a = p.parse_args()

    if a.all:
        for ds, fname in DATASETS.items():
            for base in (30.0, 35.0):
                run_one(os.path.join(DATA_DIR, fname), base, a.max_lev, ds)
        return

    if a.dataset:
        csv_path = os.path.join(DATA_DIR, DATASETS[a.dataset])
        dataset = a.dataset
    elif a.csv:
        csv_path = a.csv
        dataset = os.path.splitext(os.path.basename(csv_path))[0].lower()
    else:
        p.error("pass --csv, --dataset or --all")

    cap = a.max_lev
    if a.solve_cap:
        unlev, se = load_returns(csv_path)
        if a.start or a.end:
            unlev = unlev.loc[a.start or None:a.end or None]
        cap, free_dd = solve_min_cap(unlev, a.start_equity or se, a.base_lev)
        print(f"Smallest never-binding cap at base {a.base_lev:g}x: "
              f"{cap:.3f}x  (uncapped max DD {free_dd*100:.2f}%, "
              f"{a.base_lev:g}/(1{free_dd:+.4f}) = {a.base_lev/(1+free_dd):.3f})")

    run_one(csv_path, a.base_lev, cap, dataset, a.start, a.end, a.start_equity, a.tag)


if __name__ == "__main__":
    main()
