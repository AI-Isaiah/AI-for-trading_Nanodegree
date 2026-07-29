"""
Build the QuantStats tearsheets and the leverage diagnostics for UC244.

Outputs (leverage_analysis/output/):
    tearsheet_static_30x.html      static 30x, benchmarked against 1x
    tearsheet_dynamic_30_50x.html  dynamic 30->50x, benchmarked against static 30x
    leverage_diagnostics.png       equity / leverage / notional / drawdown panels
    daily_path.csv                 full day-by-day audit trail
    summary.csv                    side-by-side headline stats
"""

from __future__ import annotations

import os
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

import quantstats as qs

from leverage_engine import (
    MAX_LEV,
    OUT_DIR,
    START_EQUITY,
    TARGET_LEV,
    load_returns,
    run_dynamic,
    run_static,
    summarise,
)

warnings.filterwarnings("ignore")
pd.set_option("display.width", 200)


def build_tearsheets(unlev, static, dynamic):
    os.makedirs(OUT_DIR, exist_ok=True)

    qs.reports.html(
        static.returns.rename("Static 30x"),
        benchmark=unlev.rename("Unlevered 1x"),
        benchmark_title="Unlevered 1x",
        title="UC244 FX — Static 30x Leverage",
        output=os.path.join(OUT_DIR, "tearsheet_static_30x.html"),
        periods_per_year=252,
        rf=0.0,
    )

    qs.reports.html(
        dynamic.returns.rename("Dynamic 30-50x"),
        benchmark=static.returns.rename("Static 30x"),
        benchmark_title="Static 30x",
        title="UC244 FX — Dynamic Leverage (30x base, 50x cap, constant notional in drawdown)",
        output=os.path.join(OUT_DIR, "tearsheet_dynamic_30_50x.html"),
        periods_per_year=252,
        rf=0.0,
    )


def plot_diagnostics(static, dynamic):
    fig, ax = plt.subplots(4, 1, figsize=(13, 15), sharex=True,
                           gridspec_kw={"height_ratios": [2.2, 1.3, 1.3, 1.4]})

    ax[0].plot(static.equity.index, static.equity / 1e6, label="Static 30x", lw=1.4)
    ax[0].plot(dynamic.equity.index, dynamic.equity / 1e6, label="Dynamic 30→50x", lw=1.4)
    ax[0].axhline(START_EQUITY / 1e6, color="grey", lw=0.7, ls="--")
    ax[0].set_ylabel("Equity ($m)")
    ax[0].set_title("Equity curve")
    ax[0].legend()
    ax[0].grid(alpha=0.3)

    ax[1].plot(dynamic.leverage.index, dynamic.leverage, color="darkorange", lw=1.3,
               label="Applied leverage")
    ax[1].axhline(TARGET_LEV, color="grey", ls="--", lw=0.8, label=f"{TARGET_LEV:.0f}x target")
    ax[1].axhline(MAX_LEV, color="red", ls="--", lw=0.8, label=f"{MAX_LEV:.0f}x cap")
    ax[1].set_ylabel("Leverage (x)")
    ax[1].set_title("Applied gross leverage — dynamic policy")
    ax[1].legend()
    ax[1].grid(alpha=0.3)

    ax[2].plot(dynamic.target_notional.index, dynamic.target_notional / 1e6,
               color="black", lw=1.1, ls="--", label="Target notional (ratchet)")
    ax[2].plot(dynamic.notional.index, dynamic.notional / 1e6, color="tab:green", lw=1.3,
               label="Dynamic notional held")
    ax[2].plot(static.notional.index, static.notional / 1e6, color="tab:blue", lw=1.1,
               label="Static 30x notional held")
    ax[2].set_ylabel("Gross notional ($m)")
    ax[2].set_title("Notional exposure — flat through drawdowns, steps up only on new highs")
    ax[2].legend()
    ax[2].grid(alpha=0.3)

    for path, lbl in ((static, "Static 30x"), (dynamic, "Dynamic 30→50x")):
        dd = path.equity / path.equity.cummax() - 1.0
        ax[3].plot(dd.index, dd * 100, lw=1.3, label=lbl)
    ax[3].set_ylabel("Drawdown (%)")
    ax[3].set_title("Drawdown")
    ax[3].legend()
    ax[3].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "leverage_diagnostics.png"), dpi=130)
    plt.close(fig)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    unlev = load_returns()
    static = run_static(unlev)
    dynamic = run_dynamic(unlev)

    audit = pd.DataFrame(
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
    )
    audit.to_csv(os.path.join(OUT_DIR, "daily_path.csv"))

    summary = pd.DataFrame(
        [
            summarise(run_static(unlev, 1.0), "Unlevered 1x"),
            summarise(static, "Static 30x"),
            summarise(dynamic, f"Dynamic {TARGET_LEV:.0f}→{MAX_LEV:.0f}x"),
        ]
    ).set_index("policy")
    summary.to_csv(os.path.join(OUT_DIR, "summary.csv"))

    build_tearsheets(unlev, static, dynamic)
    plot_diagnostics(static, dynamic)

    pct = ["total_return", "cagr", "ann_vol", "max_dd", "best_day", "worst_day", "win_rate"]
    disp = summary.copy()
    for c in pct:
        disp[c] = (disp[c] * 100).round(2).astype(str) + "%"
    for c in ["final_equity", "min_notional", "max_notional", "final_notional"]:
        disp[c] = (disp[c] / 1e6).round(2).astype(str) + "m"
    for c in ["sharpe", "sortino", "calmar", "avg_leverage", "max_leverage"]:
        disp[c] = disp[c].round(2)
    print(disp.T.to_string())
    print(f"\nWrote outputs to {OUT_DIR}")


if __name__ == "__main__":
    main()
