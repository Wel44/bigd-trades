"""
BigD backtest engine (daily bars).

- Signals are decided on the CLOSE of day t, orders fill at the OPEN of day t+1
  (that's how the live setup works: scan after the daily close, EA fills next session).
- Every trade has a stop. Stop hits are checked intrabar on high/low; a gap
  through the stop fills at the open (worse than the stop).
- Results are in R (1R = initial stop distance). Costs (spread + slippage, and
  optionally swap per day held) are converted to R and subtracted.
- Portfolio sim sizes each trade at a fixed % of equity and caps total open risk.
"""
import os
import numpy as np
import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
START = "2009-01-01"

# Round-trip cost in price units (spread + slippage), conservative for XM Ultra Low.
COST = {
    "EURUSD": 0.00012, "GBPUSD": 0.00018, "AUDUSD": 0.00016, "NZDUSD": 0.00022,
    "USDCAD": 0.00020, "USDCHF": 0.00020, "EURGBP": 0.00020,
    "USDJPY": 0.016, "EURJPY": 0.024, "GBPJPY": 0.035,
    "XAUUSD": 0.45,
}
# Swap stress per day held, price units (ignores direction: always a cost).
SWAP = {
    "EURUSD": 0.00002, "GBPUSD": 0.00002, "AUDUSD": 0.00002, "NZDUSD": 0.00002,
    "USDCAD": 0.00002, "USDCHF": 0.00002, "EURGBP": 0.00002,
    "USDJPY": 0.002, "EURJPY": 0.002, "GBPJPY": 0.003,
    "XAUUSD": 0.15,
}
# Index CFDs (tested on ETF proxies): costs as a fraction of price.
PCT_COST = {"SPY": 0.0002, "QQQ": 0.0003, "DIA": 0.0002, "IWM": 0.0004}
PCT_SWAP = {"SPY": 0.0002, "QQQ": 0.0002, "DIA": 0.0002, "IWM": 0.0002}   # ~7%/yr financing
SYMBOLS = list(COST)
INDICES = list(PCT_COST)


# ---------------------------------------------------------------- data
def load(sym, start=START, end=None):
    df = pd.read_csv(f"{DATA_DIR}/{sym}_D1.csv", parse_dates=["date"])
    df = df[df.date.dt.dayofweek < 5].reset_index(drop=True)          # drop weekend stubs
    # drop isolated bad prints: >5% jump that fully reverts next day
    c = df.close
    jump = (c / c.shift(1) - 1).abs()
    revert = (c.shift(-1) / c.shift(1) - 1).abs()
    df = df[~((jump > 0.05) & (revert < 0.02))].reset_index(drop=True)
    # repair OHLC consistency
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    df = df[df.date >= start]
    if end:
        df = df[df.date <= end]
    return df.set_index("date")


# ---------------------------------------------------------------- indicators
def atr(df, n=20):
    pc = df.close.shift(1)
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def sma(s, n):
    return s.rolling(n).mean()


def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


# ---------------------------------------------------------------- simulator
def simulate(df, sig, sym, stop_atr=2.0, trail_atr=None, atr_n=20, swap=True, max_hold=None):
    """
    sig: DataFrame aligned to df with bool columns
         long_entry, short_entry, long_exit, short_exit (decided at close).
    stop_atr: initial stop = stop_atr * ATR at signal bar.
    trail_atr: optional ATR trailing stop (ratchets only), updated at each close.
    """
    o, h, l, c = (df[k].values for k in ("open", "high", "low", "close"))
    a = atr(df, atr_n).values
    dates = df.index
    le, se = sig.long_entry.values, sig.short_entry.values
    lx, sx = sig.long_exit.values, sig.short_exit.values
    pct = sym in PCT_COST
    cost = 0.0 if pct else COST[sym]
    sw = 0.0 if pct else (SWAP[sym] if swap else 0.0)

    trades = []
    pos = 0                 # +1 long, -1 short, 0 flat
    entry = stop = risk = 0.0
    ei = 0
    pend_entry = 0
    pend_risk = 0.0
    pend_exit = False
    warm = 210

    def close_trade(i, px, why):
        days = (dates[i] - dates[ei]).days
        gross = (px - entry) * pos
        if pct:
            costs = entry * (PCT_COST[sym] + (PCT_SWAP[sym] * days if swap else 0.0))
        else:
            costs = cost + sw * days
        trades.append(dict(sym=sym, dir=pos, entry_date=dates[ei], exit_date=dates[i],
                           entry=entry, exit=px, risk=risk, days=days, why=why,
                           R_gross=gross / risk, R=(gross - costs) / risk))

    for i in range(1, len(df)):
        # 1) pending exit at open
        if pend_exit and pos != 0:
            close_trade(i, o[i], "signal")
            pos = 0
        pend_exit = False
        # 2) pending entry at open
        if pend_entry != 0 and pos == 0:
            pos = pend_entry
            entry = o[i]
            risk = pend_risk
            stop = entry - pos * risk
            ei = i
        pend_entry = 0
        # 3) intrabar stop
        if pos == 1 and l[i] <= stop:
            close_trade(i, min(o[i], stop), "stop"); pos = 0
        elif pos == -1 and h[i] >= stop:
            close_trade(i, max(o[i], stop), "stop"); pos = 0
        # 4) end-of-day decisions
        if i < warm or np.isnan(a[i]):
            continue
        if pos != 0:
            if trail_atr:
                if pos == 1:
                    stop = max(stop, c[i] - trail_atr * a[i])
                else:
                    stop = min(stop, c[i] + trail_atr * a[i])
            if (pos == 1 and lx[i]) or (pos == -1 and sx[i]):
                pend_exit = True
            if max_hold and (i - ei) >= max_hold:
                pend_exit = True
        if pos == 0 or pend_exit:
            if le[i] and not (pos == 1):
                pend_entry, pend_risk = 1, stop_atr * a[i]
            elif se[i] and not (pos == -1):
                pend_entry, pend_risk = -1, stop_atr * a[i]
            if pend_entry != 0 and pos != 0:
                pend_exit = True       # reversal: exit then enter at the same open
    return pd.DataFrame(trades)


# ---------------------------------------------------------------- stats
def stats(tr, label=""):
    if tr is None or len(tr) == 0:
        return dict(label=label, n=0)
    R = tr.R.values
    eq = np.cumsum(R)
    dd = (eq - np.maximum.accumulate(np.concatenate([[0], eq]))[1:]).min()
    wins, losses = R[R > 0], R[R <= 0]
    years = max((tr.exit_date.max() - tr.entry_date.min()).days / 365.25, 0.1)
    return dict(
        label=label, n=len(R), trades_yr=round(len(R) / years, 1),
        win=round(len(wins) / len(R) * 100, 1),
        avg_win=round(wins.mean(), 2) if len(wins) else 0,
        avg_loss=round(losses.mean(), 2) if len(losses) else 0,
        expR=round(R.mean(), 3),
        pf=round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else np.inf,
        totR=round(R.sum(), 1), maxDD_R=round(dd, 1),
        R_yr=round(R.sum() / years, 1),
    )


def portfolio(trades, risk_pct=0.5, max_open_pct=3.0, start_equity=10000.0):
    """Fixed-fractional sizing on equity at entry, cap on total open risk.
    Equity is marked at exits only (no open MTM), so real drawdowns are a bit deeper."""
    t = trades.sort_values("entry_date").reset_index(drop=True)
    events = []
    for idx, r in t.iterrows():
        events.append((r.entry_date, 1, idx))
        # exits of older trades free risk before new entries; a trade that opens
        # and closes on the same day must exit AFTER its own entry
        events.append((r.exit_date, 2 if r.exit_date == r.entry_date else 0, idx))
    events.sort(key=lambda x: (x[0], x[1]))
    eq = start_equity
    open_risk = {}
    curve = []
    taken = 0
    for d, kind, idx in events:
        if kind == 1:
            if (len(open_risk) + 1) * risk_pct <= max_open_pct + 1e-9:
                open_risk[idx] = eq * risk_pct / 100.0
                taken += 1
        else:
            if idx in open_risk:
                eq += open_risk.pop(idx) * t.loc[idx, "R"]
                curve.append((d, eq))
    if not curve:
        return dict(taken=0)
    cv = pd.Series([e for _, e in curve], index=[d for d, _ in curve])
    peak = cv.cummax()
    dd = ((cv - peak) / peak).min() * 100
    years = (cv.index[-1] - t.entry_date.min()).days / 365.25
    cagr = ((cv.iloc[-1] / start_equity) ** (1 / years) - 1) * 100
    yearly = cv.groupby(cv.index.year).last()
    prev = yearly.shift(1).fillna(start_equity)
    yr_ret = ((yearly / prev - 1) * 100).round(1)
    return dict(taken=taken, skipped=len(t) - taken, final=round(cv.iloc[-1], 0),
                cagr=round(cagr, 1), maxDD=round(dd, 1),
                worst_year=yr_ret.min(), best_year=yr_ret.max(),
                losing_years=int((yr_ret < 0).sum()), years=round(years, 1),
                yearly=yr_ret.to_dict(), curve=cv)


def monte_carlo(R, n_trades, risk_pct, sims=5000, ruin_dd=50.0, seed=7):
    """Resample trade R values with replacement; compounding at risk_pct per trade."""
    rng = np.random.default_rng(seed)
    R = np.asarray(R)
    draws = rng.choice(R, size=(sims, n_trades), replace=True)
    growth = 1 + draws * risk_pct / 100.0
    curves = np.cumprod(growth, axis=1)
    peaks = np.maximum.accumulate(np.concatenate([np.ones((sims, 1)), curves], axis=1), axis=1)[:, 1:]
    dds = ((curves - peaks) / peaks).min(axis=1) * 100
    final = curves[:, -1]
    return dict(
        median_return=round((np.median(final) - 1) * 100, 1),
        p5_return=round((np.percentile(final, 5) - 1) * 100, 1),
        p95_return=round((np.percentile(final, 95) - 1) * 100, 1),
        prob_loss=round((final < 1).mean() * 100, 1),
        median_maxDD=round(np.median(dds), 1),
        worst5_maxDD=round(np.percentile(dds, 5), 1),
        ruin_pct=round((dds <= -ruin_dd).mean() * 100, 2),
    )
