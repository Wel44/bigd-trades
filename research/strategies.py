"""Strategy signal builders. Each returns (signals_df, sim_kwargs)."""
import numpy as np
import pandas as pd
from engine import atr, ema, sma, rsi


def _frame(df, le, se, lx, sx):
    return pd.DataFrame(dict(long_entry=le, short_entry=se, long_exit=lx, short_exit=sx), index=df.index).fillna(False)


def donchian(df, entry=55, exit_=20, stop=2.0, trail=None, longs=True, shorts=True):
    """Turtle-style breakout: close beyond N-day channel, exit on opposite M-day channel."""
    hi_e = df.high.rolling(entry).max().shift(1)
    lo_e = df.low.rolling(entry).min().shift(1)
    hi_x = df.low.rolling(exit_).min().shift(1)    # long exit level
    lo_x = df.high.rolling(exit_).max().shift(1)   # short exit level
    le = (df.close > hi_e) & longs
    se = (df.close < lo_e) & shorts
    lx = df.close < hi_x
    sx = df.close > lo_x
    return _frame(df, le, se, lx, sx), dict(stop_atr=stop, trail_atr=trail)


def ema_cross(df, fast=50, slow=200, stop=3.0, trail=None):
    f, s = ema(df.close, fast), ema(df.close, slow)
    up = (f > s) & (f.shift(1) <= s.shift(1))
    dn = (f < s) & (f.shift(1) >= s.shift(1))
    return _frame(df, up, dn, f < s, f > s), dict(stop_atr=stop, trail_atr=trail)


def tsmom(df, lookback=252, stop=3.0, trail=None):
    """Time-series momentum: at each month end, go with the sign of the 12-month return."""
    mret = df.close / df.close.shift(lookback) - 1
    month_end = pd.Series(df.index.month, index=df.index) != pd.Series(df.index.month, index=df.index).shift(-1)
    le = month_end & (mret > 0)
    se = month_end & (mret < 0)
    return _frame(df, le, se, month_end & (mret < 0), month_end & (mret > 0)), dict(stop_atr=stop, trail_atr=trail)


def chandelier(df, entry=50, stop=3.0, trail=3.0):
    """Breakout entry, exit only on an ATR trailing stop."""
    hi_e = df.high.rolling(entry).max().shift(1)
    lo_e = df.low.rolling(entry).min().shift(1)
    le = df.close > hi_e
    se = df.close < lo_e
    never = pd.Series(False, index=df.index)
    return _frame(df, le, se, never, never), dict(stop_atr=stop, trail_atr=trail)


def rsi2_pullback(df, lo=10, hi=90, trend=200, exit_ma=5, stop=3.0):
    """Connors-style: buy short dips inside an uptrend, sell rallies inside a downtrend."""
    r = rsi(df.close, 2)
    t = sma(df.close, trend)
    m = sma(df.close, exit_ma)
    le = (df.close > t) & (r < lo)
    se = (df.close < t) & (r > hi)
    return _frame(df, le, se, df.close > m, df.close < m), dict(stop_atr=stop, trail_atr=None, max_hold=10)


def ibs_reversion(df, lo=0.2, trend=200, stop=3.0, max_hold=5):
    """Internal bar strength: buy when today closed near its low, inside an uptrend; exit on close > prior high."""
    ibs = (df.close - df.low) / (df.high - df.low).replace(0, float("nan"))
    t = sma(df.close, trend)
    le = (ibs < lo) & (df.close > t)
    never = pd.Series(False, index=df.index)
    return _frame(df, le, never, df.close > df.high.shift(1), never), dict(stop_atr=stop, trail_atr=None, max_hold=max_hold)


def rsi2_long(df, lo=10, trend=200, exit_ma=5, stop=3.0, max_hold=10):
    r = rsi(df.close, 2)
    le = (df.close > sma(df.close, trend)) & (r < lo)
    never = pd.Series(False, index=df.index)
    return _frame(df, le, never, df.close > sma(df.close, exit_ma), never), dict(stop_atr=stop, trail_atr=None, max_hold=max_hold)


def trend_long(df, fast=50, slow=200, stop=3.0, trail=None):
    f, s = ema(df.close, fast), ema(df.close, slow)
    up = (f > s) & (f.shift(1) <= s.shift(1))
    never = pd.Series(False, index=df.index)
    return _frame(df, up, never, f < s, never), dict(stop_atr=stop, trail_atr=trail)
