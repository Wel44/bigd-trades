"""Convert a Twelve Data get_time_series result into data/<SYM>_D1.csv.

Usage:
  python3 tools/td_to_csv.py SPY /path/to/saved_tool_result.txt   (JSON {"result": "..."} or raw text)
  python3 tools/td_to_csv.py SPY - < raw.txt
"""
import json, os, sys

sym, src = sys.argv[1], sys.argv[2]
raw = sys.stdin.read() if src == "-" else open(src).read()
try:
    raw = json.loads(raw)["result"]
except Exception:
    pass
lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
if not lines or not lines[0].lower().startswith("datetime"):
    raise SystemExit(f"{sym}: unexpected data: {lines[:2]}")
rows = sorted(lines[1:])
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", f"{sym}_D1.csv")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    f.write("date,open,high,low,close\n")
    for r in rows:
        f.write(",".join(r.split(";")[:5]) + "\n")
print(f"{sym}: {len(rows)} bars, {rows[0][:10]} -> {rows[-1][:10]}")
