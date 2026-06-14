"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { runBacktest } from "@/lib/api";
import type { BacktestResult } from "@/lib/types";

const STRATEGIES = [
  "spike_fade", "ema_momentum", "donchian", "rsi_reversion",
  "macd_cross", "vwap_reversion", "keltner_breakout", "atr_trend",
];
const TIMEFRAMES = ["1d", "1h", "15m", "5m"];

export function BacktestRunner() {
  const [symbol, setSymbol] = useState("AAPL");
  const [timeframe, setTimeframe] = useState("1d");
  const [strategy, setStrategy] = useState("rsi_reversion");
  const [data, setData] = useState<BacktestResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setData(await runBacktest({ symbol: symbol.trim().toUpperCase(), timeframe, strategy }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "backtest failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Backtest Runner</CardTitle>
        <CardDescription>
          No-lookahead backtest on real bars (costs in). Daily timeframe uses the
          cached yfinance path; intraday needs a live feed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-2">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
            className="h-10 w-28 rounded-md border bg-background px-3 text-sm" placeholder="Symbol" />
          <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}
            className="h-10 rounded-md border bg-background px-3 text-sm">
            {TIMEFRAMES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <select value={strategy} onChange={(e) => setStrategy(e.target.value)}
            className="h-10 rounded-md border bg-background px-3 text-sm">
            {(data?.available_strategies ?? STRATEGIES).map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <Button onClick={run} disabled={busy || !symbol.trim()}>
            {busy ? "Running…" : "Run backtest"}
          </Button>
        </div>

        {data && !data.ok && (
          <p className="text-sm text-amber-600">{data.detail || "Backtest failed."}</p>
        )}

        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant="outline">trades {number(data.n_trades, 0)}</Badge>
              <Badge variant="outline">win {number(data.win_rate, 1)}%</Badge>
              <Badge variant="outline">return {number(data.total_return_pct, 2)}%</Badge>
              <Badge variant="outline">PF {number(data.profit_factor, 2)}</Badge>
              <Badge variant="outline">maxDD {number(data.max_drawdown_pct, 1)}%</Badge>
              <Badge variant="outline">Sharpe {number(data.sharpe, 2)}</Badge>
              <Badge variant={data.significant ? "success" : "secondary"}>
                {data.significance_label || (data.significant ? "significant" : "not significant")}
              </Badge>
            </div>
            {data.ai?.available && (
              <p className="text-sm text-muted-foreground">
                <span className="font-medium">AI:</span> {data.ai.verdict}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
