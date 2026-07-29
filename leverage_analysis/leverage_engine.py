"""
Constant-notional dynamic leverage engine + QuantStats tearsheets.

Input
-----
UC244 FX daily NAV file (Date, NAV, Daily ROI%, Daily P&L, Drawdown, Log Return).
The NAV series in that file is treated as the *unlevered* (1x) return stream of
the strategy -- see ASSUMPTIONS in README.md.  Change ``LEV_IN_DATA`` if the file
already embeds leverage.

Policies compared
-----------------
1. ``static``  : constant leverage of TARGET_LEV (30x) every day.  Notional is
                 marked to equity daily, so notional *shrinks* in a drawdown.
2. ``dynamic`` : notional ratchet.  Target notional is fixed at
                 TARGET_LEV x (running peak equity) and is never cut while under
                 water, so leverage rises as equity falls -- capped at MAX_LEV
                 (50x).  As equity recovers, leverage decays back toward 30x on
                 its own because the numerator (notional) is held flat while the
                 denominator (equity) grows.  Notional only steps up when a new
                 equity high is made, i.e. it is financed by new equity, never by
                 cutting risk.

Leverage for day t+1 is set from information available at the close of day t
(no look-ahead).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(HERE, "data", "UC244_FXDaily_2026-07-20.csv")
OUT_DIR = os.path.join(HERE, "output")

TARGET_LEV = 30.0   # leverage we run at when flat / at a new equity high
MAX_LEV = 50.0      # hard cap on gross leverage while under water
LEV_IN_DATA = 1.0   # leverage already embedded in the NAV series of the CSV
START_EQUITY = 10_000_000.0
PERIODS_PER_YEAR = 252


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_returns(path: str = CSV_PATH) -> pd.Series:
    """Return the unlevered daily return series implied by the NAV column."""
    raw = pd.read_csv(path, skiprows=1, thousands=",")
    raw = raw.loc[:, ~raw.columns.str.startswith("Unnamed")]
    raw["Date"] = pd.to_datetime(raw["Date"])

    nav = (
        raw["NAV"]
        .astype(str)
        .str.replace(r"[$,]", "", regex=True)
        .astype(float)
    )
    nav.index = raw["Date"]
    nav.index.name = "Date"

    # The file's first row is already a return vs the (unreported) inception NAV,
    # which the Daily ROI% column implies is exactly START_EQUITY.
    nav_full = pd.concat(
        [pd.Series([START_EQUITY], index=[nav.index[0] - pd.Timedelta(days=1)]), nav]
    )
    rets = nav_full.pct_change().dropna()
    return (rets / LEV_IN_DATA).rename("unlevered")


# --------------------------------------------------------------------------- #
# Leverage policies
# --------------------------------------------------------------------------- #
@dataclass
class Path:
    equity: pd.Series
    returns: pd.Series
    leverage: pd.Series       # leverage actually applied to that day's return
    notional: pd.Series       # gross notional held during that day
    target_notional: pd.Series
    peak_equity: pd.Series
    capped: pd.Series         # True when the 50x cap forced notional below target


def run_static(rets: pd.Series, lev: float = TARGET_LEV) -> Path:
    """Constant leverage: notional is re-marked to equity every day."""
    lev_rets = rets * lev
    equity = START_EQUITY * (1 + lev_rets).cumprod()
    prev_equity = equity.shift(1).fillna(START_EQUITY)
    peak = equity.cummax()
    return Path(
        equity=equity,
        returns=lev_rets,
        leverage=pd.Series(lev, index=rets.index),
        notional=prev_equity * lev,
        target_notional=prev_equity * lev,
        peak_equity=peak,
        capped=pd.Series(False, index=rets.index),
    )


def run_dynamic(
    rets: pd.Series,
    target_lev: float = TARGET_LEV,
    max_lev: float = MAX_LEV,
) -> Path:
    """
    Constant-notional-in-drawdown policy.

    At each close:
        peak      = max(peak, equity)                  # ratchet, never falls
        target_N  = target_lev * peak                  # only steps up on new highs
        lev_next  = min(max_lev, target_N / equity)    # >= target_lev by construction
    """
    idx = rets.index
    n = len(idx)
    equity = np.empty(n)
    lev_used = np.empty(n)
    notional = np.empty(n)
    target_n = np.empty(n)
    peak_arr = np.empty(n)
    capped = np.zeros(n, dtype=bool)

    eq = START_EQUITY
    peak = START_EQUITY
    r = rets.to_numpy()

    for i in range(n):
        # --- decided at the previous close, applied to today's return ---------
        tgt_notional = target_lev * peak
        lev = min(max_lev, tgt_notional / eq)
        notional_held = lev * eq

        lev_used[i] = lev
        target_n[i] = tgt_notional
        notional[i] = notional_held
        capped[i] = notional_held < tgt_notional - 1e-6

        # --- today's P&L ------------------------------------------------------
        eq *= 1.0 + lev * r[i]
        equity[i] = eq
        peak = max(peak, eq)          # ratchet the notional base on new highs
        peak_arr[i] = peak

    equity_s = pd.Series(equity, index=idx)
    return Path(
        equity=equity_s,
        returns=pd.Series(lev_used * r, index=idx),
        leverage=pd.Series(lev_used, index=idx),
        notional=pd.Series(notional, index=idx),
        target_notional=pd.Series(target_n, index=idx),
        peak_equity=pd.Series(peak_arr, index=idx),
        capped=pd.Series(capped, index=idx),
    )


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def summarise(path: Path, name: str) -> dict:
    r = path.returns
    eq = path.equity
    dd = eq / eq.cummax() - 1.0
    years = len(r) / PERIODS_PER_YEAR
    total = eq.iloc[-1] / START_EQUITY - 1.0
    cagr = (eq.iloc[-1] / START_EQUITY) ** (1 / years) - 1.0
    vol = r.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)
    downside = r[r < 0].std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)
    return {
        "policy": name,
        "final_equity": eq.iloc[-1],
        "total_return": total,
        "cagr": cagr,
        "ann_vol": vol,
        "sharpe": cagr / vol if vol else np.nan,
        "sortino": cagr / downside if downside else np.nan,
        "max_dd": dd.min(),
        "calmar": cagr / abs(dd.min()) if dd.min() else np.nan,
        "best_day": r.max(),
        "worst_day": r.min(),
        "win_rate": (r > 0).mean(),
        "avg_leverage": path.leverage.mean(),
        "max_leverage": path.leverage.max(),
        "days_above_target": int((path.leverage > TARGET_LEV + 1e-9).sum()),
        "days_at_cap": int(path.capped.sum()),
        "min_notional": path.notional.min(),
        "max_notional": path.notional.max(),
        "final_notional": path.notional.iloc[-1],
    }
