"use client";

import { useState } from "react";
import { toast } from "sonner";

import { number } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { runSelect } from "@/lib/api";
import type { SelectResult } from "@/lib/types";

export function RegimeSelect() {
  const [data, setData] = useState<SelectResult | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setData(await runSelect());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "select failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Regime-Filtered Symbol Selection</CardTitle>
        <CardDescription>Walk-forward per universe symbol → a tradable whitelist. Needs intraday data; can take a while.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Button onClick={run} disabled={busy}>{busy ? "Selecting…" : "Run selection"}</Button>
        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "Selection failed."}</p>}
        {data && data.ok && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-sm">
              <Badge variant="success">tradable: {(data.tradable ?? []).join(", ") || "none"}</Badge>
              <Badge variant="secondary">excluded: {(data.excluded ?? []).length}</Badge>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead><TableHead>Tradable</TableHead>
                  <TableHead className="text-right">Avg OOS %</TableHead>
                  <TableHead className="text-right">Beat BH folds</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(data.verdicts ?? []).map((v) => (
                  <TableRow key={v.symbol}>
                    <TableCell className="font-semibold">{v.symbol}</TableCell>
                    <TableCell><Badge variant={v.tradable ? "success" : "secondary"}>{v.tradable ? "yes" : "no"}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">{number(v.avg_oos_return, 2)}</TableCell>
                    <TableCell className="text-right tabular-nums">{number(v.oos_beat_bh_folds, 0)}/{number(v.n_folds, 0)}</TableCell>
                    <TableCell className="max-w-[20rem] truncate text-muted-foreground">{v.reason}</TableCell>
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
