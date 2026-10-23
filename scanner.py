"""
BigD scanner: turns the latest daily bars into trade instructions for the MT5 EA.

Strategy (backtested 2009-2026 on SPY/QQQ/DIA/IWM, see research/):
  BUY  when close > SMA(200) and RSI(2) < 10
  EXIT when close > SMA(5), or after 10 bars, or the stop (3 x ATR20) is hit
  One position at a time (Big D runs 20% risk per trade, 15% from $80). Lowest RSI gets priority.

Signals are computed on the ETF proxies and executed on the matching index CFD
at the next US cash open. The stop is sent as a % of price so it maps onto the CFD.

Usage:  python3 scanner.py            (expects data/{SPY,QQQ,DIA,IWM}_D1.csv)
Writes: signals.txt (read by the EA), state.json (virtual positions), journal.csv
"""
import csv
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
STATE = os.path.join(HERE, "state.json")
SIGNALS = os.path.join(HERE, "signals.txt")
JOURNAL = os.path.join(HERE, "journal.csv")

PROXIES = {"SPY": "US500", "QQQ": "US100", "DIA": "US30", "IWM": "US2000"}
RSI_LO, TREND, EXIT_MA, STOP_ATR, ATR_N, MAX_BARS, MAX_OPEN = 10, 200, 5, 3.0, 20, 10, 1
NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
EXEC_WINDOW_H = 6          # an instruction stays valid this many hours after the open


# ------------------------------------------------------------------ indicators
def rsi(s, n):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def atr(df, n):
    pc = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def load(sym, now_ny):
    df = pd.read_csv(os.path.join(DATA, f"{sym}_D1.csv"), parse_dates=["date"]).sort_values("date")
    df = df[df.date.dt.dayofweek < 5].reset_index(drop=True)
    # drop today's bar if the US session hasn't closed yet (incomplete bar)
    if len(df) and df.date.iloc[-1].date() == now_ny.date() and now_ny.time() < dt.time(16, 15):
        df = df.iloc[:-1]
    if len(df) < TREND + 10:
        raise SystemExit(f"{sym}: only {len(df)} bars, need {TREND + 10}+")
    df["sma_t"] = df.close.rolling(TREND).mean()
    df["sma_x"] = df.close.rolling(EXIT_MA).mean()
    df["rsi2"] = rsi(df.close, 2)
    df["atr"] = atr(df, ATR_N)
    return df


def next_us_open(after_date):
    """Next weekday 09:30 New York after `after_date` (US holidays not handled: the EA
    simply fills at the first price it gets inside the window)."""
    d = after_date + dt.timedelta(days=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return dt.datetime.combine(d, dt.time(9, 30), NY).astimezone(UTC)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ main
def main():
    now_ny = dt.datetime.now(NY)
    state = json.load(open(STATE)) if os.path.exists(STATE) else {"positions": {}, "last_bar": {}}
    instructions, log = [], []
    bars = {s: load(s, now_ny) for s in PROXIES}

    # bar dates must agree, otherwise the data is stale or half-updated
    last_dates = {s: df.date.iloc[-1].date() for s, df in bars.items()}
    bar_date = max(last_dates.values())
    stale = [s for s, d in last_dates.items() if d != bar_date]
    if stale:
        raise SystemExit(f"data out of sync: {last_dates}")

    exec_after = next_us_open(bar_date)
    expires = exec_after + dt.timedelta(hours=EXEC_WINDOW_H)
    positions = state["positions"]
    closed_now = set()

    # ---- update and exit existing virtual positions
    for sym in list(positions):
        p = positions[sym]
        df = bars[sym]
        new = df[df.date.dt.date > dt.date.fromisoformat(p["last_seen"])]
        for _, row in new.iterrows():
            if p.get("entry_price") is None:                   # first bar after the signal: fill at open
                p["entry_price"] = float(row.open)
                p["stop_price"] = float(row.open) * (1 - p["stop_pct"])
            p["bars"] += 1
            p["last_seen"] = row.date.date().isoformat()
            if row.low <= p["stop_price"]:
                p["closed"] = "stop"
                break
        last = df.iloc[-1]
        if p.get("closed") == "stop":
            log.append((sym, "STOPPED", f"proxy low hit stop {p['stop_price']:.2f}"))
            del positions[sym]
            continue
        if p.get("entry_price") is None:
            continue                                          # not filled yet
        why = None
        if last.close > last.sma_x:
            why = f"close {last.close:.2f} > SMA{EXIT_MA} {last.sma_x:.2f}"
        elif p["bars"] - 1 >= MAX_BARS:                       # entry bar counts as bar 0
            why = f"held {p['bars']} bars"
        if why:
            instructions.append(("CLOSE", p["id"], PROXIES[sym], "", "", exec_after, expires))
            log.append((sym, "CLOSE", why))
            del positions[sym]
            closed_now.add(sym)

    # ---- new entries
    cands = []
    for sym, df in bars.items():
        if sym in positions or sym in closed_now:
            continue
        last = df.iloc[-1]
        if last.close > last.sma_t and last.rsi2 < RSI_LO:
            cands.append((last.rsi2, sym, last))
    cands.sort()
    for r, sym, last in cands:
        if len(positions) >= MAX_OPEN:
            log.append((sym, "SKIP", f"RSI2 {r:.1f} but {MAX_OPEN} positions already open"))
            continue
        stop_pct = float(STOP_ATR * last.atr / last.close)
        sid = f"{bar_date:%Y%m%d}-{sym}"
        positions[sym] = dict(id=sid, signal_date=bar_date.isoformat(), last_seen=bar_date.isoformat(),
                              stop_pct=round(stop_pct, 5), bars=0, entry_price=None)
        instructions.append(("OPEN", sid, PROXIES[sym], "BUY", f"{stop_pct:.5f}", exec_after, expires))
        log.append((sym, "OPEN", f"RSI2 {r:.1f}, close {last.close:.2f} > SMA200 {last.sma_t:.2f}, stop {stop_pct*100:.2f}%"))

    for sym, df in bars.items():
        if not any(l[0] == sym for l in log):
            last = df.iloc[-1]
            trend = "uptrend" if last.close > last.sma_t else "downtrend"
            log.append((sym, "NONE", f"RSI2 {last.rsi2:.1f}, {trend}" + (", holding" if sym in positions else "")))

    # ---- write outputs
    state["positions"] = positions
    state["last_run_utc"] = iso(dt.datetime.now(UTC))
    state["last_bar_date"] = bar_date.isoformat()
    json.dump(state, open(STATE, "w"), indent=2)

    with open(SIGNALS, "w") as f:
        f.write("# BigD signals. Format: TYPE|ID|SYMBOL|SIDE|STOP_PCT|EXEC_AFTER_UTC|EXPIRES_UTC\n")
        f.write(f"enabled={int(os.environ.get('BIGD_ENABLED', '1'))}\n")
        f.write(f"generated={state['last_run_utc']}\n")
        f.write(f"bar_date={bar_date.isoformat()}\n")
        for t, sid, sym, side, sp, ea, ex in instructions:
            f.write(f"{t}|{sid}|{sym}|{side}|{sp}|{iso(ea)}|{iso(ex)}\n")

    new_file = not os.path.exists(JOURNAL)
    with open(JOURNAL, "a", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["run_utc", "bar_date", "proxy", "symbol", "action", "detail"])
        for sym, action, detail in log:
            w.writerow([state["last_run_utc"], bar_date.isoformat(), sym, PROXIES[sym], action, detail])

    print(f"bar {bar_date}  exec {iso(exec_after)}  open positions: {list(positions)}")
    for sym, action, detail in log:
        print(f"  {sym:4} {PROXIES[sym]:7} {action:7} {detail}")


if __name__ == "__main__":
    main()
