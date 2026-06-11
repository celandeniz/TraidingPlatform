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
import { getPanel } from "@/lib/api";
import type { PanelResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const sideColor: Record<string, string> = {
  long: "bg-emerald-500/15 text-emerald-500",
  short: "bg-red-500/15 text-red-500",
  pass: "bg-secondary text-muted-foreground",
};

export function PersonaPanel() {
  const [symbol, setSymbol] = useState("AAPL");
  const [data, setData] = useState<PanelResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async (refresh = false) => {
    setBusy(true);
    try {
      setData(await getPanel(symbol.trim().toUpperCase(), refresh));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "panel failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Persona Panel</CardTitle>
        <CardDescription>
          Five investing philosophies judge one symbol from fundamentals, price
          history, and headlines. Not investment advice.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol, e.g. AAPL"
            className="h-10 w-40 rounded-md border bg-background px-3 text-sm"
            onKeyDown={(e) => e.key === "Enter" && load()}
          />
          <Button onClick={() => load()} disabled={busy || !symbol.trim()}>
            {busy ? "Asking the panel…" : "Run panel"}
          </Button>
          {data && (
            <Button variant="outline" onClick={() => load(true)} disabled={busy}>
              Refresh
            </Button>
          )}
        </div>

        {data && (
          <>
            <div className="flex items-center gap-3">
              <Badge className={cn("text-sm", sideColor[data.verdict])}>
                consensus: {data.verdict} ({data.score >= 0 ? "+" : ""}
                {data.score.toFixed(2)})
              </Badge>
              {!data.fundamentals_available && (
                <span className="text-xs text-amber-600">
                  fundamentals unavailable — low-confidence verdicts
                </span>
              )}
              <span className="text-xs text-muted-foreground">
                {data.cached ? "cached" : "fresh"} · {data.generated_at}
              </span>
            </div>
            <ul className="space-y-2">
              {data.votes.map((v) => (
                <li key={v.name} className="flex items-start gap-2 text-sm">
                  <Badge className={cn("shrink-0", sideColor[v.side])}>
                    {v.side} {(v.confidence * 100).toFixed(0)}%
                  </Badge>
                  <span className="font-medium">{v.name}</span>
                  <span className="text-muted-foreground">{v.rationale}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
