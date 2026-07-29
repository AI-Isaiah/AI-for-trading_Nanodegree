"""
Constant-notional dynamic leverage engine + QuantStats tearsheets.

Input
-----
Any of the FX daily NAV files (Date, NAV, Daily ROI%, Daily P&L, Drawdown,
Log Return).  The NAV series is treated as the *unlevered* (1x) return stream of
the strategy -- see ASSUMPTIONS in README.md.  Change ``LEV_IN_DATA`` if the file
already embeds leverage.  Starting equity is recovered exactly from the first
row as ``NAV_0 - DailyP&L_0``.

Policies compared
-----------------
1. ``static``  : constant leverage of ``base_lev`` every day.  Notional is marked
                 to equity daily, so notional *shrinks* in a drawdown.
2. ``dynamic`` : notional ratchet.  Target notional is fixed at
                 base_lev x (running peak equity) and is never cut while under
                 water, so leverage rises as equity falls -- capped at ``max_lev``.
                 As equity recovers, leverage decays back toward base_lev on its
                 own because the numerator (notional) is held flat while the
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
DATA_DIR = os.path.join(HERE, "data")
OUT_DIR = os.path.join(HERE, "output")

TARGET_LEV = 30.0   # default base leverage
MAX_LEV = 50.0      # hard cap on gross leverage while under water
LEV_IN_DATA = 1.0   # leverage already embedded in the NAV series of the CSV
PERIODS_PER_YEAR = 252


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def _money(col: pd.Series) -> pd.Series:
    return (
        col.astype(str)
        .str.replace(r"[$,]", "", regex=True)
        .str.replace(r"^\((.*)\)$", r"-\1", regex=True)
        .astype(float)
    )


def load_returns(path: str) -> tuple[pd.Series, float]:
    """
    Return ``(unlevered daily returns, starting equity)``.

    Starting equity is inferred exactly from the first row: the file's first NAV
    already includes that day's P&L, so equity_0 = NAV_0 - P&L_0.
    """
    raw = pd.read_csv(path, skiprows=1, thousands=",")
    raw = raw.loc[:, ~raw.columns.str.startswith("Unnamed")]
    raw["Date"] = pd.to_datetime(raw["Date"])

    nav = _money(raw["NAV"])
    pnl = _money(raw["Daily P&L"])
    nav.index = raw["Date"]
    nav.index.name = "Date"

    start_equity = float(nav.iloc[0] - pnl.iloc[0])

    nav_full = pd.concat(
        [pd.Series([start_equity], index=[nav.index[0] - pd.Timedelta(days=1)]), nav]
    )
    rets = nav_full.pct_change().dropna()
    return (rets / LEV_IN_DATA).rename("unlevered"), start_equity


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
    capped: pd.Series         # True when the cap forced notional below target
    base_lev: float
    start_equity: float


def run_static(rets: pd.Series, start_equity: float, lev: float = TARGET_LEV) -> Path:
    """Constant leverage: notional is re-marked to equity every day."""
    lev_rets = rets * lev
    equity = start_equity * (1 + lev_rets).cumprod()
    prev_equity = equity.shift(1).fillna(start_equity)
    return Path(
        equity=equity,
        returns=lev_rets,
        leverage=pd.Series(lev, index=rets.index),
        notional=prev_equity * lev,
        target_notional=prev_equity * lev,
        peak_equity=equity.cummax(),
        capped=pd.Series(False, index=rets.index),
        base_lev=lev,
        start_equity=start_equity,
    )


def run_dynamic(
    rets: pd.Series,
    start_equity: float,
    base_lev: float = TARGET_LEV,
    max_lev: float = MAX_LEV,
) -> Path:
    """
    Constant-notional-in-drawdown policy.

    At each close:
        peak      = max(peak, equity)                  # ratchet, never falls
        target_N  = base_lev * peak                    # only steps up on new highs
        lev_next  = min(max_lev, target_N / equity)    # >= base_lev by construction
    """
    idx = rets.index
    n = len(idx)
    equity = np.empty(n)
    lev_used = np.empty(n)
    notional = np.empty(n)
    target_n = np.empty(n)
    peak_arr = np.empty(n)
    capped = np.zeros(n, dtype=bool)

    eq = start_equity
    peak = start_equity
    r = rets.to_numpy()

    for i in range(n):
        # --- decided at the previous close, applied to today's return ---------
        tgt_notional = base_lev * peak
        lev = min(max_lev, tgt_notional / eq)
        notional_held = lev * eq

        lev_used[i] = lev
        target_n[i] = tgt_notional
        notional[i] = notional_held
        # Relative tolerance: notional reaches 1e12+ on the multi-year compounded
        # runs, where float64 rounding alone is ~1e-4 -- an absolute epsilon here
        # reports phantom cap hits.
        capped[i] = notional_held < tgt_notional * (1.0 - 1e-9)

        # --- today's P&L ------------------------------------------------------
        eq *= 1.0 + lev * r[i]
        equity[i] = eq
        peak = max(peak, eq)          # ratchet the notional base on new highs
        peak_arr[i] = peak

    return Path(
        equity=pd.Series(equity, index=idx),
        returns=pd.Series(lev_used * r, index=idx),
        leverage=pd.Series(lev_used, index=idx),
        notional=pd.Series(notional, index=idx),
        target_notional=pd.Series(target_n, index=idx),
        peak_equity=pd.Series(peak_arr, index=idx),
        capped=pd.Series(capped, index=idx),
        base_lev=base_lev,
        start_equity=start_equity,
    )


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def _dd_spells(dd: pd.Series) -> tuple[int, int]:
    """(longest drawdown spell in observations, days spent under water)."""
    under = dd < -1e-12
    longest = run = 0
    for u in under:
        run = run + 1 if u else 0
        longest = max(longest, run)
    return longest, int(under.sum())


def summarise(path: Path, name: str) -> dict:
    r = path.returns
    eq = path.equity
    dd = eq / eq.cummax() - 1.0
    longest_dd, days_under = _dd_spells(dd)
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    years = len(r) / PERIODS_PER_YEAR
    growth = eq.iloc[-1] / path.start_equity
    cagr = growth ** (1 / years) - 1.0 if growth > 0 else np.nan
    vol = r.std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)
    downside = r[r < 0].std(ddof=1) * np.sqrt(PERIODS_PER_YEAR)
    # Arithmetic (standard, rf=0) Sharpe/Sortino -- matches QuantStats.  Do NOT
    # use cagr/vol here: geometric growth explodes under multi-year compounding
    # at these leverages and would report a wildly inflated ratio.
    ann_mean = r.mean() * PERIODS_PER_YEAR
    return {
        "policy": name,
        "final_equity": eq.iloc[-1],
        "total_return": growth - 1.0,
        "cagr": cagr,
        "ann_vol": vol,
        "sharpe": ann_mean / vol if vol else np.nan,
        "sortino": ann_mean / downside if downside else np.nan,
        "max_dd": dd.min(),
        "max_dd_date": dd.idxmin().date().isoformat(),
        "avg_dd": dd[dd < 0].mean() if (dd < 0).any() else 0.0,
        "longest_dd_days": longest_dd,
        "pct_time_in_dd": days_under / len(dd),
        "calmar": cagr / abs(dd.min()) if dd.min() else np.nan,
        "best_day": r.max(),
        "worst_day": r.min(),
        "worst_day_date": r.idxmin().date().isoformat(),
        "worst_day_pnl": (eq.shift(1).fillna(path.start_equity) * r).min(),
        "worst_5d": r.rolling(5).apply(lambda x: (1 + x).prod() - 1).min(),
        "win_rate": (r > 0).mean(),
        "profit_factor": gains / losses if losses else np.nan,
        "avg_leverage": path.leverage.mean(),
        "max_leverage": path.leverage.max(),
        "days_above_base": int((path.leverage > path.base_lev + 1e-9).sum()),
        "days_at_cap": int(path.capped.sum()),
        "min_notional": path.notional.min(),
        "max_notional": path.notional.max(),
        "final_notional": path.notional.iloc[-1],
    }
