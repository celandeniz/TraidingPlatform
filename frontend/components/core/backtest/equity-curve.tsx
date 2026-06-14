"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getEquityCurve } from "@/lib/api";
import type { EquityCurveResult } from "@/lib/types";

export function EquityCurve() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<EquityCurveResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setData(await getEquityCurve(days));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "equity curve failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Account Equity Curve</CardTitle>
        <CardDescription>From periodic snapshots (requires snapshots.enabled).</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-end gap-2">
          <input type="number" min={1} max={90} value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-10 w-24 rounded-md border bg-background px-3 text-sm" />
          <Button onClick={load} disabled={busy}>{busy ? "Loading…" : "Load curve"}</Button>
        </div>
        {data && !data.available && <p className="text-sm text-amber-600">{data.detail || "Snapshots disabled."}</p>}
        {data && data.available && (
          <p className="text-sm text-muted-foreground">
            {data.points.length} points over {days}d. Latest:{" "}
            <span className="font-mono text-foreground">
              {JSON.stringify(data.points[data.points.length - 1] ?? {})}
            </span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}
