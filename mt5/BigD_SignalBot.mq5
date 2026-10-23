//+------------------------------------------------------------------+
//|                                              BigD_SignalBot.mq5 |
//|  Reads trade instructions from GitHub and executes them with     |
//|  hard risk limits. Attach to ONE chart (any symbol). Demo only   |
//|  unless InpAllowLive is switched on.                             |
//|                                                                  |
//|  signals.txt format (one instruction per line):                  |
//|  TYPE|ID|SYMBOL|SIDE|STOP_PCT|EXEC_AFTER_UTC|EXPIRES_UTC         |
//|  TYPE = OPEN or CLOSE. Plus "enabled=0/1" kill switch line.      |
//+------------------------------------------------------------------+
#property copyright   "Big D"
#property version     "1.00"
#property description "Executes signals from github.com/Wel44/bigd-trades with hard risk limits."

#include <Trade\Trade.mqh>

input group "Source"
input string InpUrl          = "https://raw.githubusercontent.com/Wel44/bigd-trades/main/signals.txt"; // Signals URL
input int    InpPollSec      = 120;     // Check for new signals every N seconds

input group "Risk (your rules)"
input double InpRiskPct      = 1.0;     // Risk per trade (% of balance)
input double InpMaxOpenRisk  = 3.0;     // Max total open risk (%)
input int    InpMaxLossDay   = 3;       // Losing trades per day before stopping
input double InpMaxWeekDD    = 6.0;     // Weekly drawdown (%) before stopping
input int    InpMaxHoldDays  = 16;      // Safety: close anything older than this (calendar days)
input double InpMaxSpreadPct = 0.05;    // Skip if spread is wider than this % of price
input bool   InpAllowLive    = false;   // Allow trading on a REAL account

input group "Broker symbol names (first one found is used)"
input string InpUS500 = "US500Cash,US500,SP500,SPX500,US500.cash,SP500m";
input string InpUS100 = "US100Cash,US100,NAS100,USTEC,NDX100,US100.cash";
input string InpUS30  = "US30Cash,US30,DJ30,WS30,US30.cash";
input string InpUS2000= "US2000Cash,US2000,RUSSELL2000,RTY,US2000.cash";

input group "Misc"
input ulong  InpMagic = 260124;         // Magic number

CTrade   trade;
datetime lastPoll   = 0;
string   lastStatus = "starting";
string   lastAction = "none yet";
string   genTime    = "?";
bool     enabledFlag = true;

//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(50);
   EventSetTimer(15);
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL && !InpAllowLive)
      lastStatus = "REAL account detected: trading blocked (InpAllowLive = false)";
   Poll();
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
}

void OnTimer()
{
   SafetyClose();
   if(TimeLocal() - lastPoll >= InpPollSec)
      Poll();
   ShowStatus();
}

//+------------------------------------------------------------------+
//| Download + process signals                                       |
//+------------------------------------------------------------------+
void Poll()
{
   lastPoll = TimeLocal();
   string url = InpUrl + "?t=" + IntegerToString((long)TimeGMT());   // cache buster
   char   post[], result[];
   string headers;
   ResetLastError();
   int code = WebRequest("GET", url, "", 10000, post, result, headers);
   if(code == -1)
   {
      int err = GetLastError();
      lastStatus = (err == 4014) ? "WebRequest blocked: add https://raw.githubusercontent.com in Tools > Options > Expert Advisors"
                                 : "download failed, error " + IntegerToString(err);
      Print(lastStatus);
      return;
   }
   if(code != 200)
   {
      lastStatus = "download HTTP " + IntegerToString(code);
      Print(lastStatus);
      return;
   }
   string text = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   StringReplace(text, "\r", "");
   string lines[];
   int n = StringSplit(text, '\n', lines);
   enabledFlag = true;
   for(int i = 0; i < n; i++)
   {
      string ln = lines[i];
      StringTrimLeft(ln); StringTrimRight(ln);
      if(ln == "" || StringGetCharacter(ln, 0) == '#')
         continue;
      if(StringFind(ln, "enabled=") == 0)   { enabledFlag = (StringSubstr(ln, 8) == "1"); continue; }
      if(StringFind(ln, "generated=") == 0) { genTime = StringSubstr(ln, 10); continue; }
      if(StringFind(ln, "=") > 0)            continue;
      Handle(ln);
   }
   lastStatus = "OK, last check " + TimeToString(TimeLocal(), TIME_MINUTES) + (enabledFlag ? "" : "  (KILL SWITCH ON)");
}

//+------------------------------------------------------------------+
void Handle(string ln)
{
   string f[];
   if(StringSplit(ln, '|', f) < 7)
      return;
   string type = f[0], id = f[1], alias = f[2], side = f[3];
   double stopPct = StringToDouble(f[4]);
   datetime after = ParseUtc(f[5]), expires = ParseUtc(f[6]);
   string doneKey = "BIGD_" + id + "_" + type;
   if(GlobalVariableCheck(doneKey))
      return;                                              // already handled
   datetime now = TimeGMT();
   if(now < after)
      return;                                              // not yet
   if(now > expires)
   {
      MarkDone(doneKey, type + " " + id + " expired before it could run");
      return;
   }

   if(type == "CLOSE")
   {
      bool found = false;
      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong t = PositionGetTicket(i);
         if(t == 0 || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
         if(PositionGetString(POSITION_COMMENT) != id) continue;
         found = true;
         if(trade.PositionClose(t))
            MarkDone(doneKey, "CLOSED " + id);
         else
            lastAction = "close failed " + id + ": " + trade.ResultRetcodeDescription();   // retry next poll
      }
      if(!found)
         MarkDone(doneKey, "CLOSE " + id + ": no open position (already stopped or skipped)");
      return;
   }

   if(type != "OPEN" || (side != "BUY" && side != "SELL"))
      return;

   //--- hard rules before any new trade
   if(!enabledFlag)                         { lastAction = "kill switch on, skipped " + id; return; }
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL && !InpAllowLive)
                                            { MarkDone(doneKey, "REAL account, blocked " + id); return; }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED))
                                            { lastAction = "Algo Trading is OFF, waiting to open " + id; return; }
   if(LossesToday() >= InpMaxLossDay)       { MarkDone(doneKey, "3 losses today, skipped " + id); return; }
   if(WeekDrawdownPct() >= InpMaxWeekDD)    { MarkDone(doneKey, "weekly loss limit hit, skipped " + id); return; }

   string sym = ResolveSymbol(alias);
   if(sym == "")                            { MarkDone(doneKey, "no broker symbol found for " + alias); return; }
   if(stopPct <= 0 || stopPct > 0.2)        { MarkDone(doneKey, "bad stop in " + id); return; }

   double ask = SymbolInfoDouble(sym, SYMBOL_ASK), bid = SymbolInfoDouble(sym, SYMBOL_BID);
   if(ask <= 0 || bid <= 0)                 { lastAction = sym + " has no price yet, waiting"; return; }
   if((ask - bid) / ask * 100.0 > InpMaxSpreadPct)
                                            { lastAction = sym + " spread too wide, waiting"; return; }

   bool   isBuy  = (side == "BUY");
   double price  = isBuy ? ask : bid;
   double slDist = price * stopPct;
   double riskPct;
   double lots   = LotsForRisk(sym, slDist, riskPct);
   if(lots < 0)
   {
      lastAction = sym + " contract info not loaded yet, waiting";
      return;
   }
   if(lots == 0)
   {
      MarkDone(doneKey, StringFormat("%s skipped: smallest size risks %.1f%% (limit %.1f%%). Needs a bigger balance.",
                                     id, riskPct, InpRiskPct));
      return;
   }
   if(OpenRiskPct() + riskPct > InpMaxOpenRisk + 1e-6)
   {
      MarkDone(doneKey, StringFormat("%s skipped: would push open risk over %.1f%%", id, InpMaxOpenRisk));
      return;
   }

   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double sl     = NormalizeDouble(isBuy ? price - slDist : price + slDist, digits);
   trade.SetTypeFillingBySymbol(sym);
   bool ok = isBuy ? trade.Buy(lots, sym, 0.0, sl, 0.0, id) : trade.Sell(lots, sym, 0.0, sl, 0.0, id);
   uint rc = trade.ResultRetcode();
   if(ok && (rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED))
      MarkDone(doneKey, StringFormat("OPENED %s %s %.2f lots, SL %s, risk %.2f%%", side, sym, lots,
                                     DoubleToString(sl, digits), riskPct));
   else
      lastAction = "open failed " + id + ": " + trade.ResultRetcodeDescription() + " (will retry)";
   Print(lastAction);
}

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
void MarkDone(string key, string msg)
{
   GlobalVariableSet(key, (double)TimeGMT());
   lastAction = msg;
   Print(msg);
}

datetime ParseUtc(string s)          // 2026-10-27T13:30:00Z -> datetime
{
   StringReplace(s, "-", ".");
   StringReplace(s, "T", " ");
   StringReplace(s, "Z", "");
   return StringToTime(s);
}

string ResolveSymbol(string alias)
{
   string list = "";
   if(alias == "US500")  list = InpUS500;
   if(alias == "US100")  list = InpUS100;
   if(alias == "US30")   list = InpUS30;
   if(alias == "US2000") list = InpUS2000;
   if(list == "")        list = alias;
   string c[];
   int n = StringSplit(list, ',', c);
   for(int i = 0; i < n; i++)
   {
      string s = c[i];
      StringTrimLeft(s); StringTrimRight(s);
      bool custom;
      if(s != "" && SymbolExist(s, custom) && SymbolSelect(s, true))
         return s;
   }
   return "";
}

double LossPerLot(string sym, double dist)
{
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS);
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   if(tv <= 0 || ts <= 0) return 0;
   return dist / ts * tv;
}

double LotsForRisk(string sym, double slDist, double &riskPctOut)
{
   riskPctOut = 0;
   double bal  = AccountInfoDouble(ACCOUNT_BALANCE);
   double lpl  = LossPerLot(sym, slDist);
   double mn   = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(bal <= 0 || lpl <= 0 || step <= 0) return -1;            // data not ready: retry later
   double lots = MathFloor(bal * InpRiskPct / 100.0 / lpl / step + 1e-9) * step;
   if(lots < mn) lots = mn;
   if(lots > mx) lots = mx;
   riskPctOut = lots * lpl / bal * 100.0;
   if(riskPctOut > InpRiskPct * 1.05) return 0;      // never exceed the per-trade rule
   return NormalizeDouble(lots, 2);
}

double OpenRiskPct()
{
   double bal = AccountInfoDouble(ACCOUNT_BALANCE), total = 0;
   if(bal <= 0) return 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      string sym = PositionGetString(POSITION_SYMBOL);
      double open = PositionGetDouble(POSITION_PRICE_OPEN), sl = PositionGetDouble(POSITION_SL);
      double vol = PositionGetDouble(POSITION_VOLUME);
      long   typ = PositionGetInteger(POSITION_TYPE);
      double dist = (typ == POSITION_TYPE_BUY) ? open - sl : sl - open;
      if(sl == 0) dist = open * 0.05;                    // no stop: assume 5% (should never happen)
      if(dist > 0) total += vol * LossPerLot(sym, dist);
   }
   return total / bal * 100.0;
}

int LossesToday()
{
   MqlDateTime d;
   TimeToStruct(TimeCurrent(), d);
   d.hour = 0; d.min = 0; d.sec = 0;
   if(!HistorySelect(StructToTime(d), TimeCurrent() + 60)) return 0;
   int n = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong t = HistoryDealGetTicket(i);
      if((ulong)HistoryDealGetInteger(t, DEAL_MAGIC) != InpMagic) continue;
      if(HistoryDealGetInteger(t, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;
      if(HistoryDealGetDouble(t, DEAL_PROFIT) + HistoryDealGetDouble(t, DEAL_SWAP) + HistoryDealGetDouble(t, DEAL_COMMISSION) < 0) n++;
   }
   return n;
}

double WeekDrawdownPct()
{
   MqlDateTime d;
   TimeToStruct(TimeCurrent(), d);
   int back = (d.day_of_week + 6) % 7;                   // days since Monday
   datetime monday = TimeCurrent() - back * 86400 - (d.hour * 3600 + d.min * 60 + d.sec);
   MqlDateTime m;
   TimeToStruct(monday, m);
   string key = StringFormat("BIGD_WEEK_%04d%02d%02d", m.year, m.mon, m.day);
   if(!GlobalVariableCheck(key))
      GlobalVariableSet(key, AccountInfoDouble(ACCOUNT_BALANCE));
   double start = GlobalVariableGet(key);
   if(start <= 0) return 0;
   return MathMax(0.0, (start - AccountInfoDouble(ACCOUNT_EQUITY)) / start * 100.0);
}

void SafetyClose()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || (ulong)PositionGetInteger(POSITION_MAGIC) != InpMagic) continue;
      datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
      if(TimeCurrent() - opened > (long)InpMaxHoldDays * 86400)
         if(trade.PositionClose(t))
         {
            lastAction = "safety close: held over " + IntegerToString(InpMaxHoldDays) + " days";
            Print(lastAction);
         }
   }
}

void ShowStatus()
{
   int mine = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t != 0 && (ulong)PositionGetInteger(POSITION_MAGIC) == InpMagic) mine++;
   }
   Comment(StringFormat("BigD SignalBot\nStatus: %s\nSignals generated: %s\nOpen positions: %d  |  open risk %.2f%%\n"
                        "Losses today: %d/%d  |  week drawdown %.1f%%/%.1f%%\nLast: %s",
                        lastStatus, genTime, mine, OpenRiskPct(), LossesToday(), InpMaxLossDay,
                        WeekDrawdownPct(), InpMaxWeekDD, lastAction));
}
//+------------------------------------------------------------------+
