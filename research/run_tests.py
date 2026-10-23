import sys
import pandas as pd
from engine import load, simulate, stats, portfolio, SYMBOLS
import strategies as S

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)

CANDIDATES = {
    "donchian_55_20": (S.donchian, dict(entry=55, exit_=20, stop=2.0)),
    "donchian_20_10": (S.donchian, dict(entry=20, exit_=10, stop=2.0)),
    "donchian_100_50": (S.donchian, dict(entry=100, exit_=50, stop=3.0)),
    "ema_50_200": (S.ema_cross, dict(fast=50, slow=200, stop=3.0)),
    "ema_20_100": (S.ema_cross, dict(fast=20, slow=100, stop=3.0)),
    "tsmom_12m": (S.tsmom, dict(lookback=252, stop=3.0)),
    "tsmom_6m": (S.tsmom, dict(lookback=126, stop=3.0)),
    "chandelier_50_3": (S.chandelier, dict(entry=50, stop=3.0, trail=3.0)),
    "rsi2_pullback": (S.rsi2_pullback, dict()),
}

DATA = {s: load(s) for s in SYMBOLS}


def run(name, fn, params, syms=SYMBOLS, start=None, end=None, swap=True):
    out = []
    for s in syms:
        df = DATA[s]
        sig, kw = fn(df, **params)
        tr = simulate(df, sig, s, swap=swap, **kw)
        if len(tr):
            if start: tr = tr[tr.entry_date >= start]
            if end: tr = tr[tr.entry_date <= end]
            out.append(tr)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


if __name__ == "__main__":
    rows = []
    for name, (fn, p) in CANDIDATES.items():
        tr = run(name, fn, p)
        st = stats(tr, name)
        ins = stats(tr[tr.entry_date < "2018-01-01"], "IS")
        oos = stats(tr[tr.entry_date >= "2018-01-01"], "OOS")
        pf = portfolio(tr, risk_pct=0.5, max_open_pct=3.0)
        rows.append(dict(strategy=name, n=st["n"], tr_yr=st["trades_yr"], win=st["win"], expR=st["expR"],
                         pf=st["pf"], maxDD_R=st["maxDD_R"], IS_expR=ins["expR"], OOS_expR=oos["expR"],
                         port_cagr=pf.get("cagr"), port_DD=pf.get("maxDD"), losing_yrs=pf.get("losing_years")))
    print(pd.DataFrame(rows).to_string(index=False))
