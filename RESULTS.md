# Backtest results (run 2026-10-24)

Daily bars 2009-01 to 2026-10, signals at the close, fills at the next open, stops
checked intrabar. Costs: spread + slippage on every trade, plus a swap/financing charge
for every day held. In-sample = trades before 2018, out-of-sample = 2018 onward.

## Forex + gold (11 markets): no edge
EURUSD GBPUSD AUDUSD NZDUSD USDCAD USDCHF EURGBP USDJPY EURJPY GBPJPY XAUUSD

| Strategy | Trades | Win % | Exp. R | PF | Exp. R before 2018 | Exp. R 2018+ |
|---|---|---|---|---|---|---|
| Donchian 55/20 | 774 | 26.1 | -0.16 | 0.77 | 0.00 | -0.29 |
| Donchian 20/10 | 1488 | 30.7 | -0.10 | 0.82 | -0.03 | -0.16 |
| Donchian 100/50 | 403 | 21.6 | -0.12 | 0.84 | 0.06 | -0.27 |
| EMA 50/200 cross | 339 | 17.4 | -0.06 | 0.92 | 0.18 | -0.25 |
| EMA 20/100 cross | 650 | 20.5 | -0.11 | 0.82 | 0.00 | -0.19 |
| 12-month momentum | 405 | 26.2 | -0.09 | 0.87 | 0.01 | -0.20 |
| 6-month momentum | 606 | 25.1 | -0.16 | 0.77 | 0.07 | -0.34 |
| 50-day breakout + 3 ATR trail | 839 | 31.5 | -0.12 | 0.75 | -0.08 | -0.15 |
| RSI(2) pullback, long + short | 2174 | 60.5 | -0.01 | 0.94 | -0.02 | 0.00 |

Walk-forward check: picking only the markets that worked before 2018 and trading them
from 2018 on lost money for every strategy.

## US stock indices (SPY, QQQ, DIA, IWM as proxies for the index CFDs)

| Strategy | Trades | Win % | Exp. R | PF | Before 2018 | 2018+ |
|---|---|---|---|---|---|---|
| **RSI(2) < 10 dip buy (live)** | 614 | 68.1 | **+0.062** | 1.39 | +0.080 | +0.046 |
| RSI(2) < 5 | 326 | 68.1 | +0.075 | 1.47 | +0.064 | +0.084 |
| RSI(2) < 15 | 876 | 66.3 | +0.055 | 1.36 | +0.069 | +0.043 |
| IBS < 0.1 | 931 | 69.0 | +0.059 | 1.38 | +0.034 | +0.082 |
| IBS < 0.2 | 1464 | 66.3 | +0.032 | 1.20 | +0.031 | +0.032 |
| EMA 50/200 trend, long only | 37 | 21.6 | -0.39 | 0.64 | -0.48 | -0.32 |
| Random uptrend entries, same exits | | | +0.003 | | | |

Live strategy as a portfolio (1% risk per trade, max 3% open): about **+1.6% a year**,
max drawdown **-11.9%**, 5 losing years out of 17 (worst -6.3%).
Monte Carlo, 1 year (36 trades): median +2.3%, 5th percentile -2.8%, 23% chance of a losing year.
Holds up when the stop, hold time and trend filter are changed.
