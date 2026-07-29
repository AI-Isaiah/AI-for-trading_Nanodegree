# FX leverage study — constant-notional drawdown scaling

QuantStats tearsheets for two FX daily NAV series under a static leverage policy
and a dynamic "hold notional through the drawdown" policy, at base leverages of
**30x** and **35x**, with a **50x** hard cap.

| Dataset | Period | Days | Start equity | Unlevered result |
|---|---|---|---|---|
| `uc244_jul2026` | 2026-01-01 → 2026-07-20 | 143 | $10,000,000 | +5.86% |
| `fx_dec2025_backtest` | 2021-01-01 → 2025-12-31 | 1,304 | $750,000 | +89.44% (13.1% CAGR) |

## The policy

Run at `base` leverage, and when the book goes into drawdown **don't cut
notional** — let leverage float up (capped at 50x) so gross exposure stays flat.
On the way back, return to `base` by *growing equity into the notional*, not by
selling down.

That is a **notional ratchet**:

```
peak_t      = max(peak_{t-1}, equity_t)            # never falls
target_N_t  = base x peak_t                        # steps up only at a new equity high
lev_{t+1}   = min(50, target_N_t / equity_t)       # >= base by construction
```

1. **In a drawdown**, `target_N` is frozen at its high-water value while equity
   falls, so `lev = target_N / equity` rises automatically — exposure held
   constant in dollars, rising leverage is the arithmetic consequence.
2. **On recovery**, nothing is sold: leverage decays back to `base` on its own
   because the numerator is pinned and equity is growing. It touches exactly
   `base` the day the old high is recovered.
3. **At a new high** the ratchet steps notional up — the only time exposure ever
   increases, and it is always equity-financed.

Leverage for day *t+1* is set at the close of day *t*; no look-ahead. The 50x cap
binds at a drawdown of `1 - base/50` — **40% for base 30x, 30% for base 35x**.
Past that point notional *is* cut, and the constant-notional promise breaks.

## Results

### UC244 (143 days)

| | Unlevered | Static 30x | Dynamic 30→50x | Static 35x | Dynamic 35→50x |
|---|---|---|---|---|---|
| Final equity | $10.59m | $43.40m | **$49.70m** | $52.96m | **$63.69m** |
| Total return | 5.86% | 333.97% | 396.98% | 429.61% | 536.85% |
| Volatility (ann.) | 3.18% | 95.5% | 100.6% | 111.4% | 118.7% |
| Sharpe (rf=0) | 3.17 | 3.17 | **3.30** | 3.17 | **3.32** |
| Sortino | 6.35 | 6.35 | 6.74 | 6.35 | 6.82 |
| Max drawdown | -0.85% | -23.67% | -25.67% | -27.23% | -29.95% |
| Calmar | 12.4 | 51.9 | 61.8 | 65.6 | 83.9 |
| Longest drawdown | — | 65d | **52d** | 66d | **52d** |
| Avg / max leverage | 1x | 30x | 32.4x / 40.4x | 35x | 38.3x / **50.0x** |
| Days at 50x cap | — | — | 0 | — | 0 |

The cap is never reached at either base — at 35x it grazes 49.97x at the trough
of the May drawdown but notional is still held exactly flat throughout.

### FX Dec2025 backtest (1,304 days)

| | Unlevered | Static 30x | Dynamic 30→50x | Static 35x | Dynamic 35→50x |
|---|---|---|---|---|---|
| Total return | 89.44% | 3.5 x10⁹ % | 1.2 x10¹⁰ % | 4.5 x10¹⁰ % | 2.2 x10¹¹ % |
| Volatility (ann.) | 2.74% | 82.2% | 89.2% | 95.9% | 105.3% |
| Sharpe (rf=0) | 4.52 | 4.52 | **4.50** | 4.52 | **4.50** |
| Sortino | 7.82 | 7.82 | 7.79 | 7.82 | 7.75 |
| Max drawdown | -1.55% | -41.30% | -46.38% | -47.01% | -51.36% |
| Longest drawdown | 93d | 110d | **93d** | 110d | **96d** |
| Avg / max leverage | 1x | 30x | 32.4x / 50.0x | 35x | 38.2x / 50.0x |
| Days at 50x cap | — | — | **49** | — | **107** |
| Worst day | -0.57% | -16.95% | -18.73% | -19.77% | -22.24% |

Calendar-year returns (base 30x):

| Year | Unlevered | Static 30x | Dynamic 30→50x |
|---|---|---|---|
| 2021 | 17.4% | 8,296% | 10,544% |
| 2022 | 16.0% | 5,936% | 7,384% |
| 2023 | 17.4% | 7,992% | 10,390% |
| 2024 | 9.6% | 999% | 1,350% |
| 2025 | 8.2% | 686% | 899% |

## Three findings that matter more than the headline numbers

**1. The 5-year absolute numbers are not investable — they are a compounding
artefact.** Daily rebalancing to 30x on a 13%-CAGR, 2.7%-vol return stream
multiplies equity ~80x *per year*. Over five years that runs $750k to $26.6
trillion of equity against $799bn of gross notional (and $2.7tn for the dynamic
policy). No FX market absorbs that. Read the 5-year sheets as *ratios and
year-by-year behaviour*, not as terminal wealth. If the intent is a realistic
5-year path, the run needs a profit sweep, a notional ceiling, or a fixed capital
base — say the word and I'll add it.

**2. On the long sample the dynamic policy earns no risk-adjusted premium.**
Sharpe goes 4.52 → 4.50 and Sortino 7.82 → 7.79; it is marginally *negative*. All
the extra return is bought with extra risk — the policy simply runs 32.4x average
instead of 30x. The apparent Sharpe improvement on the 143-day UC244 sample
(3.17 → 3.30) does **not** survive 1,304 days and 20+ drawdown cycles. What the
policy does reliably deliver on both samples is a **shorter time under water**
(110d → 93d at 30x, 110d → 96d at 35x) at the cost of a **deeper trough**
(-41.3% → -46.4%, -47.0% → -51.4%).

**3. At 35x the cap does real work, and the constant-notional promise breaks.**
Base 35x puts the cap threshold at a 30% drawdown, which the long backtest
crosses repeatedly: 107 days at the 50x cap, and at the worst point notional is
forced down to **69.5%** of target (89.4% for base 30x). So at 35x the policy is
*not* holding notional constant through the deep drawdowns — it is a 30x-style
policy that gives up and deleverages exactly when the drawdown is worst. If the
constant-notional property is the point, base 35x needs either a higher cap
(≥ 35/(1-maxDD)) or the acceptance that it degrades below -30%.

## Files

```
leverage_analysis/
├── leverage_engine.py                     # policy implementation + stats
├── run_report.py                          # CLI: --csv / --dataset / --all
├── data/
│   ├── UC244_FXDaily_2026-07-20.csv
│   └── FX_DailyDec2025_Backtest.csv
└── output/<dataset>/<base>x/
    ├── tearsheet_static_<b>x.html         # QuantStats: static vs unlevered 1x
    ├── tearsheet_dynamic_<b>_50x.html     # QuantStats: dynamic vs static base
    ├── leverage_diagnostics.png           # equity / leverage / notional / drawdown
    ├── daily_path.csv                     # day-by-day audit trail
    └── summary.csv                        # side-by-side stats
```

```bash
pip install quantstats
python run_report.py --all                                   # both datasets x {30x, 35x}
python run_report.py --dataset fx_dec2025_backtest --base-lev 35
python run_report.py --csv path/to/other.csv --base-lev 30 --max-lev 50
```

## Assumptions

- **Each CSV's NAV series is treated as the unlevered (1x) return stream.**
  Applying Nx means multiplying each daily return by the applied leverage. If a
  file already embeds leverage, set `LEV_IN_DATA` in `leverage_engine.py`.
- Starting equity is recovered exactly from the first row as
  `NAV_0 - DailyP&L_0` ($10,000,000 and $750,000 respectively).
- Returns compound daily; leverage is rebalanced at each close, frictionlessly.
- **No financing, funding or transaction costs**, and no market-impact or
  capacity limit. At these notionals both are decisive, not second-order.
- No margin call, stop-out, or broker leverage limit is modelled beyond the 50x
  cap — the policy is assumed able to hold its target notional at any equity
  level down to that cap.
- 252 trading days per year, rf = 0. Sharpe/Sortino are arithmetic (matching
  QuantStats); Calmar and CAGR are geometric and inflate severely on the 5-year
  compounded runs.
