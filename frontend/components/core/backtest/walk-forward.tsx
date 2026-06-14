"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { runWalkforward } from "@/lib/api";
import type { WalkForwardResult } from "@/lib/types";

export function WalkForward() {
  const [symbol, setSymbol] = useState("AAPL");
  const [folds, setFolds] = useState(4);
  const [data, setData] = useState<WalkForwardResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setData(await runWalkforward({ symbol: symbol.trim().toUpperCase(), timeframe: "5m", folds }));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "walk-forward failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Walk-Forward Validation</CardTitle>
        <CardDescription>Out-of-sample folds; honest IS→OOS degradation. Needs intraday data.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-2">
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
            className="h-10 w-28 rounded-md border bg-background px-3 text-sm" placeholder="Symbol" />
          <input type="number" min={2} max={10} value={folds}
            onChange={(e) => setFolds(Number(e.target.value))}
            className="h-10 w-24 rounded-md border bg-background px-3 text-sm" />
          <Button onClick={run} disabled={busy || !symbol.trim()}>{busy ? "Running…" : "Run walk-forward"}</Button>
        </div>

        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "Walk-forward failed."}</p>}

        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant="outline">avg OOS {number(data.avg_oos_return, 2)}%</Badge>
              <Badge variant="outline">degradation {number(data.degradation_pct, 1)}%</Badge>
              <Badge variant="outline">OOS+ folds {number(data.oos_positive_folds, 0)}/{number(data.n_folds, 0)}</Badge>
              <Badge variant={data.oos_beat_bh_folds ? "success" : "secondary"}>{data.verdict}</Badge>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Fold</TableHead><TableHead>Chosen</TableHead>
                  <TableHead className="text-right">IS %</TableHead>
                  <TableHead className="text-right">OOS %</TableHead>
                  <TableHead className="text-right">OOS excess %</TableHead>
                  <TableHead className="text-right">OOS trades</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data.folds ?? []).map((f) => (
                  <TableRow key={f.fold}>
                    <TableCell>{f.fold}</TableCell>
                    <TableCell className="font-mono text-xs">{f.chosen}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.is_return_pct, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.oos_return_pct, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.oos_excess_pct, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(f.oos_trades, 0)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
