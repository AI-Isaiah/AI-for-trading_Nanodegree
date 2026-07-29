"""
Head-to-head between two arbitrary leverage policies on the same return stream.

Default matchup: static 35x versus dynamic 30->60x.  Those two run at a similar
*average* leverage, so the comparison isolates the shape of the policy (flat vs
constant-notional-in-drawdown) from the leverage level.

    python compare_policies.py --dataset fx_dec2025_backtest --start 2025-01-01
    python compare_policies.py --dataset fx_dec2025_backtest          # full period
    python compare_policies.py --dataset uc244_jul2026

Writes to output/<dataset>/<tag>/:
    tearsheet_dyn30_60_vs_static35.html   QuantStats, dynamic as strategy
    comparison.png                        equity / leverage / notional / drawdown
    comparison_summary.csv                full KPI table
    daily_path.csv                        day-by-day audit trail
"""

from __future__ import annotations

import argparse
import os
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import quantstats as qs

from leverage_engine import (
    DATA_DIR,
    OUT_DIR,
    load_returns,
    run_dynamic,
    run_static,
    summarise,
)
from run_report import DATASETS, _fmt

warnings.filterwarnings("ignore")


def compare(csv_path, dataset, static_lev, dyn_base, dyn_cap, start, end,
            start_equity_override, tag):
    unlev, start_equity = load_returns(csv_path)
    if start or end:
        unlev = unlev.loc[start or None:end or None]
    if start_equity_override is not None:
        start_equity = start_equity_override

    window = f"{unlev.index[0].date()} → {unlev.index[-1].date()}"
    label = f"{dataset.replace('_', ' ').upper()} [{window}]"
    tag = tag or f"cmp_static{static_lev:g}_vs_dyn{dyn_base:g}_{dyn_cap:g}"
    out_dir = os.path.join(OUT_DIR, dataset, tag)
    os.makedirs(out_dir, exist_ok=True)

    static = run_static(unlev, start_equity, static_lev)
    dynamic = run_dynamic(unlev, start_equity, dyn_base, dyn_cap)
    # Reference points: the flat policy at the dynamic policy's realised average
    # leverage, and the flat policy at the dynamic base.
    matched_lev = float(dynamic.leverage.mean())
    matched = run_static(unlev, start_equity, matched_lev)
    base_static = run_static(unlev, start_equity, dyn_base)

    s_name = f"Static {static_lev:g}x"
    d_name = f"Dynamic {dyn_base:g}→{dyn_cap:g}x"
    summary = pd.DataFrame(
        [
            summarise(run_static(unlev, start_equity, 1.0), "Unlevered 1x"),
            summarise(base_static, f"Static {dyn_base:g}x"),
            summarise(static, s_name),
            summarise(matched, f"Static {matched_lev:.2f}x (avg-matched)"),
            summarise(dynamic, d_name),
        ]
    ).set_index("policy")
    summary.to_csv(os.path.join(out_dir, "comparison_summary.csv"))

    pd.DataFrame(
        {
            "unlevered_ret": unlev,
            "static35_ret": static.returns,
            "static35_equity": static.equity,
            "static35_notional": static.notional,
            "dyn_leverage": dynamic.leverage,
            "dyn_ret": dynamic.returns,
            "dyn_equity": dynamic.equity,
            "dyn_peak_equity": dynamic.peak_equity,
            "dyn_target_notional": dynamic.target_notional,
            "dyn_notional_held": dynamic.notional,
            "dyn_notional_capped": dynamic.capped,
            "static35_drawdown": static.equity / static.equity.cummax() - 1.0,
            "dyn_drawdown": dynamic.equity / dynamic.equity.cummax() - 1.0,
        }
    ).to_csv(os.path.join(out_dir, "daily_path.csv"))

    qs.reports.html(
        dynamic.returns.rename(d_name),
        benchmark=static.returns.rename(s_name),
        benchmark_title=s_name,
        title=f"{label} — {d_name} vs {s_name}",
        output=os.path.join(
            out_dir,
            f"tearsheet_dyn{dyn_base:g}_{dyn_cap:g}_vs_static{static_lev:g}.html"),
        periods_per_year=252,
        rf=0.0,
    )
    plot(static, dynamic, out_dir, s_name, d_name, dyn_base, dyn_cap, label)

    print(f"\n=== {label} | {len(unlev)} days | start ${start_equity:,.0f} ===")
    print(f"{d_name} realised average leverage: {matched_lev:.2f}x "
          f"(vs {static_lev:g}x flat) | days at cap: {int(dynamic.capped.sum())} "
          f"| max leverage {dynamic.leverage.max():.2f}x")
    print(_fmt(summary).T.to_string())
    return summary


def plot(static, dynamic, out_dir, s_name, d_name, base, cap, label):
    fig, ax = plt.subplots(4, 1, figsize=(13, 15), sharex=True,
                           gridspec_kw={"height_ratios": [2.2, 1.3, 1.3, 1.4]})
    fig.suptitle(f"{label} — {d_name} vs {s_name}", y=0.997, fontsize=13)
    multi_year = (static.equity.index[-1] - static.equity.index[0]).days > 400

    ax[0].plot(static.equity.index, static.equity / 1e6, label=s_name, lw=1.2)
    ax[0].plot(dynamic.equity.index, dynamic.equity / 1e6, label=d_name, lw=1.2)
    if multi_year:
        ax[0].set_yscale("log")
    ax[0].axhline(static.start_equity / 1e6, color="grey", lw=0.7, ls="--")
    ax[0].set_ylabel("Equity ($m)")
    ax[0].set_title("Equity curve")
    ax[0].legend()
    ax[0].grid(alpha=0.3, which="both")

    ax[1].plot(dynamic.leverage.index, dynamic.leverage, color="darkorange", lw=1.0,
               label=f"{d_name} applied leverage")
    ax[1].axhline(static.base_lev, color="tab:blue", ls="-", lw=1.0, label=s_name)
    ax[1].axhline(dynamic.leverage.mean(), color="green", ls=":", lw=1.2,
                  label=f"Dynamic average {dynamic.leverage.mean():.2f}x")
    ax[1].axhline(base, color="grey", ls="--", lw=0.8, label=f"{base:g}x base")
    ax[1].axhline(cap, color="red", ls="--", lw=0.8, label=f"{cap:g}x cap")
    ax[1].set_ylabel("Leverage (x)")
    ax[1].set_title("Applied gross leverage")
    ax[1].legend(fontsize=8)
    ax[1].grid(alpha=0.3)

    ax[2].plot(dynamic.notional.index, dynamic.notional / 1e6, color="tab:green",
               lw=1.1, label=f"{d_name} notional")
    ax[2].plot(static.notional.index, static.notional / 1e6, color="tab:blue",
               lw=1.0, label=f"{s_name} notional")
    if multi_year:
        ax[2].set_yscale("log")
    ax[2].set_ylabel("Gross notional ($m)")
    ax[2].set_title("Gross notional held")
    ax[2].legend()
    ax[2].grid(alpha=0.3, which="both")

    for path, lbl in ((static, s_name), (dynamic, d_name)):
        dd = path.equity / path.equity.cummax() - 1.0
        ax[3].plot(dd.index, dd * 100, lw=1.1, label=lbl)
    ax[3].set_ylabel("Drawdown (%)")
    ax[3].set_title("Drawdown")
    ax[3].legend()
    ax[3].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, "comparison.png"), dpi=130)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", choices=list(DATASETS), default="fx_dec2025_backtest")
    p.add_argument("--csv")
    p.add_argument("--static-lev", type=float, default=35.0)
    p.add_argument("--dyn-base", type=float, default=30.0)
    p.add_argument("--dyn-cap", type=float, default=60.0)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--start-equity", type=float)
    p.add_argument("--tag")
    a = p.parse_args()

    csv_path = a.csv or os.path.join(DATA_DIR, DATASETS[a.dataset])
    dataset = a.dataset if not a.csv else os.path.splitext(
        os.path.basename(a.csv))[0].lower()
    compare(csv_path, dataset, a.static_lev, a.dyn_base, a.dyn_cap,
            a.start, a.end, a.start_equity, a.tag)


if __name__ == "__main__":
    main()
