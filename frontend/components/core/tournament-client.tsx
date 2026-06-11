"use client";

import { Play, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getTournamentLatest, runTournament } from "@/lib/api";
import type { TournamentLatest, TournamentReport } from "@/lib/types";
import { cn } from "@/lib/utils";

function Sparkline({ curve }: { curve: [string, number][] }) {
  if (!curve || curve.length < 2) return <span className="text-muted-foreground">—</span>;
  const vals = curve.map(([, v]) => v);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const pts = vals
    .map((v, i) => `${(i / (vals.length - 1)) * 100},${28 - ((v - min) / span) * 26}`)
    .join(" ");
  return (
    <svg viewBox="0 0 100 30" className="h-7 w-24" preserveAspectRatio="none">
      <polyline
        points={pts}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className={vals[vals.length - 1] >= vals[0] ? "text-emerald-500" : "text-red-500"}
      />
    </svg>
  );
}

function GateBadges({ report }: { report: TournamentReport }) {
  if (report.error) {
    return (
      <span
        className="rounded bg-red-500/15 px-2 py-0.5 text-xs text-red-500"
        title={report.error}
      >
        error
      </span>
    );
  }
  if (report.gates?.passed) {
    return (
      <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-500">
        all gates passed
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1">
      {report.gates?.failures.map((f) => (
        <span key={f} className="rounded bg-amber-500/15 px-2 py-0.5 text-xs text-amber-600">
          {f}
        </span>
      ))}
    </div>
  );
}

const fmt = (v: number | undefined, digits = 2) =>
  v === undefined || v === null ? "—" : v.toFixed(digits);

export function TournamentClient({ initial }: { initial: TournamentLatest | null }) {
  const [data, setData] = useState<TournamentLatest | null>(initial);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setData(await getTournamentLatest());
    } catch {
      /* 404 until the first run exists */
    }
  }, []);

  useEffect(() => {
    if (!data?.status?.running) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [data?.status?.running, refresh]);

  const onRun = async () => {
    setBusy(true);
    try {
      await runTournament();
      await refresh();
      toast.success("Tournament started");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Tournament failed to start");
    } finally {
      setBusy(false);
    }
  };

  const isRunning = data?.status?.running;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>Tournament Controls</CardTitle>
          <CardDescription>
            Runs every configured strategy through out-of-sample validation and ranks them by OOS
            Sharpe with hard risk gates.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 md:flex-row md:items-center">
          <Button onClick={onRun} disabled={busy || !!isRunning}>
            {busy || isRunning ? <RefreshCw className="animate-spin" /> : <Play />}
            {isRunning ? `Running… ${data?.status?.progress ?? ""}` : "Run tournament"}
          </Button>
          {data?.started_at && (
            <span className="text-sm text-muted-foreground">
              Last run {data.started_at} · config {data.config_hash}
            </span>
          )}
          {data?.status?.error && (
            <span className="text-sm text-red-500">{data.status.error}</span>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Strategy Leaderboard</CardTitle>
          <CardDescription>
            Out-of-sample results only. Greyed rows failed a hard gate (named in the badge) —
            shown anyway so nothing hides. Rankings are estimated edge, not a guarantee.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!data ? (
            <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
              No tournament runs yet. Run one to rank every strategy on out-of-sample results.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead className="text-right">OOS Sharpe</TableHead>
                  <TableHead className="text-right">Return %</TableHead>
                  <TableHead className="text-right">Max DD %</TableHead>
                  <TableHead className="text-right">PF</TableHead>
                  <TableHead className="text-right">Trades / Rebal.</TableHead>
                  <TableHead>Equity</TableHead>
                  <TableHead>Gates</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.reports.map((r, i) => (
                  <TableRow
                    key={r.name}
                    className={cn(!r.gates?.passed && !r.error && "opacity-50")}
                  >
                    <TableCell className="tabular-nums">{i + 1}</TableCell>
                    <TableCell className="font-semibold">{r.name}</TableCell>
                    <TableCell className="text-muted-foreground">{r.kind}</TableCell>
                    <TableCell className="text-right tabular-nums font-mono">
                      {fmt(r.metrics.oos_sharpe)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-mono">
                      {fmt(r.metrics.total_return_pct, 1)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-mono">
                      {fmt(r.metrics.max_drawdown_pct, 1)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-mono">
                      {fmt(r.metrics.profit_factor)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums font-mono">
                      {r.kind === "portfolio"
                        ? (r.metrics.n_rebalances ?? "—")
                        : (r.metrics.n_trades ?? "—")}
                    </TableCell>
                    <TableCell>
                      <Sparkline curve={r.equity_curve} />
                    </TableCell>
                    <TableCell>
                      <GateBadges report={r} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
