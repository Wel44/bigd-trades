# bigd-trades

Automated signals for the BigD MT5 demo account.

**How it runs**
1. Every US trading day at 17:17 New York time, a scheduled Claude task fetches daily bars
   for SPY / QQQ / DIA / IWM, runs `scanner.py`, and pushes `signals.txt`.
2. `mt5/BigD_SignalBot.mq5` (running in MT5 on the laptop) downloads `signals.txt` every
   2 minutes and executes new instructions at the next US cash open (09:30 New York),
   on the matching index CFD (US500 / US100 / US30 / US2000).

**Strategy:** buy short dips in an uptrend on US stock indices.
Buy when close > SMA(200) and RSI(2) < 10. Exit when close > SMA(5), after 10 bars,
or at the stop (3 x ATR(20)). Max 3 positions.

**Risk rules enforced by the EA:** 1% risk per trade, 3% total open risk, stop on every
trade, stop after 3 losing trades in a day, stop after -6% in a week, demo only unless
`InpAllowLive` is switched on. Kill switch: `enabled=0` in `signals.txt`.

**Backtest (2009-2026, costs + financing included):** see `RESULTS.md`.
Small but consistent edge. Not a money printer.

Files: `scanner.py` (live signals) · `state.json` (open virtual positions) ·
`journal.csv` (every decision) · `research/` (backtest engine + all tests) ·
`tools/td_to_csv.py` (data helper). Price data is not stored here.
