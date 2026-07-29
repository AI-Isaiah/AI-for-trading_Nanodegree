# UC244 FX — 30x base leverage with constant-notional drawdown scaling

QuantStats tearsheets for the UC244 FX daily NAV series (2026-01-01 → 2026-07-20,
143 trading days) under two leverage policies, plus the engine that produces them.

## The policy

The ask: run 30x, and when we go into a drawdown **don't cut notional** — let
leverage float up (capped at 50x) so gross exposure stays flat. On the way back,
return to 30x by *growing equity into the notional*, not by selling down.

That is a **notional ratchet**:

```
peak_t      = max(peak_{t-1}, equity_t)          # never falls
target_N_t  = 30 x peak_t                        # steps up only at a new equity high
lev_{t+1}   = min(50, target_N_t / equity_t)     # >= 30 by construction
```

Three properties fall out of it:

1. **In a drawdown**, `target_N` is frozen at its last high-water value while
   equity falls, so `lev = target_N / equity` rises automatically — exposure held
   constant in dollars, leverage rises as the arithmetic consequence.
2. **On recovery**, nothing has to be sold. Leverage decays back to 30x on its
   own because the numerator is pinned and the denominator (equity) is growing.
   It touches exactly 30.0x at the moment the old high is recovered.
3. **At a new high**, the ratchet steps notional up to 30x the new equity — the
   only time exposure ever increases.

Leverage for day *t+1* is set from the close of day *t*; there is no look-ahead.
The 50x cap binds at a 40% equity drawdown (30/50 = 0.6); in this sample it was
never reached, so notional was held *exactly* constant through every drawdown.

## Results

| | Unlevered 1x | Static 30x | **Dynamic 30→50x** |
|---|---|---|---|
| Final equity (from $10m) | $10.59m | $43.40m | **$49.70m** |
| Cumulative return | 5.86% | 333.97% | **396.98%** |
| CAGR (annualised from 143d) | 10.56% | 1228.5% | 1587.0% |
| Volatility (ann.) | 3.18% | 95.47% | 100.6% |
| Sharpe (QuantStats, rf=0) | — | 3.17 | **3.30** |
| Sortino | — | 6.47 | 6.77 |
| Max drawdown | -0.85% | -23.67% | **-25.67%** |
| Calmar | 12.4 | 51.9 | **61.8** |
| Longest drawdown | — | 65 days | **52 days** |
| Worst day | -0.40% | -11.99% | -11.99% |
| Best day | +1.02% | +30.58% | +30.58% |
| Win rate | 58.0% | 58.0% | 58.0% |

Leverage actually used by the dynamic policy: **average 32.4x, max 40.4x**,
above 30x on 111 of 143 days, never at the 50x cap. Gross notional ran from
$300m to $1,508m versus $295m–$1,327m for static 30x, ending at $1,508m vs
$1,315m — 14.7% more notional carried on 14.5% more equity, i.e. the extra
exposure is fully equity-financed and the policy still ends at ~30x.

Worked example — the April/May drawdown, the deepest in the sample:

| Date | Equity | Peak | Target notional | Held | Leverage | DD |
|---|---|---|---|---|---|---|
| 2026-04-14 | $43.63m | $43.63m | $1,308.8m | $1,173.0m | 30.00x | 0.0% |
| 2026-04-17 | $37.33m | $43.63m | $1,308.8m | $1,308.8m | 31.85x | -14.4% |
| 2026-04-20 | $33.33m | $43.63m | $1,308.8m | $1,308.8m | 35.06x | -23.6% |
| 2026-05-05 | $32.43m | $43.63m | $1,308.8m | $1,308.8m | 38.55x | -25.7% |
| 2026-05-06 | $38.08m | $43.63m | $1,308.8m | $1,308.8m | 40.36x | -12.7% |
| 2026-06-08 | $43.63m | recovered | $1,308.8m | $1,308.8m | 30.11x | 0.0% |
| 2026-06-09 | new high | ratchets up | $1,308.9m | $1,308.9m | **30.00x** | 0.0% |

Notional never moves off $1,308.8m; only leverage floats.

**What it costs.** The policy is buying exposure into weakness, so it is
risk-additive at exactly the worst moment: max drawdown deepens from -23.67% to
-25.67% and annualised vol from 95% to 101%. The trade paid here because every
drawdown in the sample mean-reverted — the recovery was fought with a bigger
book, which is why the longest drawdown *shortens* from 65 to 52 days. In a
sustained one-way loss it would do the opposite and compound the damage; at 50x,
a 2% adverse move in the underlying return stream is a total loss of equity.

## Files

```
leverage_analysis/
├── leverage_engine.py                 # policy implementation + stats
├── run_report.py                      # builds everything below
├── data/UC244_FXDaily_2026-07-20.csv  # source NAV file
└── output/
    ├── tearsheet_dynamic_30_50x.html  # QuantStats: dynamic vs static 30x benchmark
    ├── tearsheet_static_30x.html      # QuantStats: static 30x vs unlevered benchmark
    ├── leverage_diagnostics.png       # equity / leverage / notional / drawdown
    ├── daily_path.csv                 # day-by-day audit trail
    └── summary.csv                    # side-by-side stats
```

Run with `pip install quantstats && python run_report.py`.

## Assumptions

- **The CSV's NAV series is treated as the unlevered (1x) return stream.** Applying
  30x means multiplying each daily return by the applied leverage. If the file
  already embeds leverage, set `LEV_IN_DATA` in `leverage_engine.py` and the
  scaling adjusts.
- Starting equity $10,000,000 (implied by the file's first Daily ROI% of -0.06%
  against a NAV of $9,994,084.29).
- Returns compound daily; leverage is rebalanced at each close, frictionlessly.
- **No financing, funding or transaction costs.** At 30–50x these are material:
  $1.3bn of gross FX notional against $40m of equity carries real swap/carry cost
  that is not in these numbers, and the daily rebalancing to a leverage target is
  not free either.
- No margin call, stop-out, or broker leverage limit is modelled — the policy is
  assumed to be able to hold its target notional at any equity level down to the
  50x cap.
- 252 trading days per year, rf = 0. CAGR figures annualise a 143-day sample and
  should be read as a scaling of the period return, not a forecast.
