"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { runSynthesis } from "@/lib/api";
import type { SynthesisResult } from "@/lib/types";
import { cn } from "@/lib/utils";

export function StrategySynthesis() {
  const [text, setText] = useState("");
  const [symbol, setSymbol] = useState("AAPL");
  const [data, setData] = useState<SynthesisResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setData(
        await runSynthesis({ text: text.trim(), symbol: symbol.trim().toUpperCase() }),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "synthesis failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Strategy Synthesis</CardTitle>
        <CardDescription>
          Describe a strategy in plain English. Best-of-N LLM-generated Python is
          validated, sandbox-backtested, gated, and the best is auto-promoted to{" "}
          <strong>paper</strong>. Not investment advice.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. fade gaps over 3% on high volume, exit at VWAP"
          rows={2}
          className="w-full rounded-md border bg-background px-3 py-2 text-sm"
        />
        <div className="flex gap-2">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol"
            className="h-10 w-32 rounded-md border bg-background px-3 text-sm"
          />
          <Button onClick={run} disabled={busy || !text.trim() || !symbol.trim()}>
            {busy ? "Synthesizing…" : "Synthesize"}
          </Button>
        </div>

        {data && !data.ok && (
          <p className="text-sm text-amber-600">{data.detail || "Synthesis failed."}</p>
        )}

        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge variant="outline">
                {data.n_candidates ?? 0} candidates
              </Badge>
              <Badge variant="outline">{data.n_valid ?? 0} valid</Badge>
              <Badge variant="outline">{data.n_passing ?? 0} passed gates</Badge>
              {data.promoted ? (
                <Badge className="bg-emerald-500/15 text-emerald-500">
                  promoted: {data.promoted}
                </Badge>
              ) : (
                <span className="text-xs text-muted-foreground">
                  {data.detail || "none promoted"}
                </span>
              )}
              {data.provider && (
                <span className="text-xs text-muted-foreground">
                  via {data.provider}
                </span>
              )}
            </div>
            <ul className="space-y-1">
              {(data.outcomes ?? []).map((o) => {
                const passed = o.gates?.passed;
                return (
                  <li key={o.name} className="flex items-start gap-2 text-sm">
                    <Badge
                      className={cn(
                        "shrink-0",
                        !o.valid
                          ? "bg-red-500/15 text-red-500"
                          : passed
                            ? "bg-emerald-500/15 text-emerald-500"
                            : "bg-secondary text-muted-foreground",
                      )}
                    >
                      {!o.valid ? "invalid" : passed ? "passed" : "failed"}
                    </Badge>
                    <span className="text-muted-foreground">
                      {o.reason ||
                        (o.metrics
                          ? `trades ${o.metrics.n_trades ?? "?"}, oos_sharpe ${
                              typeof o.metrics.oos_sharpe === "number"
                                ? o.metrics.oos_sharpe.toFixed(2)
                                : "?"
                            }`
                          : "—")}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
