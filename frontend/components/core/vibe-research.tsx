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
import { getVibeResearch } from "@/lib/api";
import type { VibeResearchResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const sideColor: Record<string, string> = {
  long: "bg-emerald-500/15 text-emerald-500",
  short: "bg-red-500/15 text-red-500",
  pass: "bg-secondary text-muted-foreground",
};

export function VibeResearch() {
  const [symbol, setSymbol] = useState("AAPL");
  const [data, setData] = useState<VibeResearchResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setData(await getVibeResearch(symbol.trim().toUpperCase()));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "vibe research failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Vibe Research</CardTitle>
        <CardDescription>
          Advisory summary from the Vibe-Trading sidecar (HKUDS/Vibe-Trading).
          Requires the container running and <code>vibe_trading.enabled</code>.
          Advisory only — not investment advice, never trades.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="Symbol, e.g. AAPL"
            className="h-10 w-40 rounded-md border bg-background px-3 text-sm"
            onKeyDown={(e) => e.key === "Enter" && !busy && !!symbol.trim() && load()}
          />
          <Button onClick={load} disabled={busy || !symbol.trim()}>
            {busy ? "Asking Vibe…" : "Run research"}
          </Button>
        </div>

        {data && !data.ok && (
          <p className="text-sm text-amber-600">
            {data.detail || "Vibe sidecar unavailable."}
          </p>
        )}

        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <Badge className={cn("text-sm", sideColor[data.side ?? "pass"])}>
                lean: {data.side ?? "pass"}
                {typeof data.confidence === "number" &&
                  ` (${(data.confidence * 100).toFixed(0)}%)`}
              </Badge>
              <span className="text-xs text-muted-foreground">
                source: vibe · {data.events ?? 0} events
              </span>
            </div>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">
              {data.summary}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
