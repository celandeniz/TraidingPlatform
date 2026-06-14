"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getScenarios } from "@/lib/api";
import type { ScenariosResult } from "@/lib/types";

export function ScenariosGrid() {
  const [data, setData] = useState<ScenariosResult | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setBusy(true);
    try {
      setData(await getScenarios());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "scenarios failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Saved Scenario Grid</CardTitle>
        <CardDescription>The saved month grid (logs/backtest_month_30d.csv), ranked by excess vs buy-hold.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={load} disabled={busy}>{busy ? "Loading…" : "Load scenarios"}</Button>
        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "No saved grid."}</p>}
        {data && data.ok && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Scenario</TableHead>
                <TableHead className="text-right">Trades</TableHead>
                <TableHead className="text-right">Win %</TableHead>
                <TableHead className="text-right">Return %</TableHead>
                <TableHead className="text-right">PF</TableHead>
                <TableHead className="text-right">Excess %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.rows.slice(0, 100).map((r, i) => (
                <TableRow key={`${r.scenario}-${i}`}>
                  <TableCell className="font-mono text-xs">{r.scenario}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.n_trades, 0)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.win_rate, 1)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.total_return_pct, 2)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.profit_factor, 2)}</TableCell>
                  <TableCell className="text-right tabular-nums">{number(r.excess_vs_buy_hold, 2)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
