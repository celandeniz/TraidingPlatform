"use client";

import { Play, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { number, text } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getScan, getUniverse } from "@/lib/api";
import type { ScanResponse, UniverseResponse } from "@/lib/types";

const modes = ["m7", "sp500", "nasdaq100", "sp500_nasdaq100"];

export function ScannerClient({
  initialUniverse,
  initialScan,
}: {
  initialUniverse: UniverseResponse | null;
  initialScan: ScanResponse | null;
}) {
  const [mode, setMode] = useState("m7");
  const [topN, setTopN] = useState(25);
  const [universe, setUniverse] = useState<UniverseResponse | null>(initialUniverse);
  const [scan, setScan] = useState<ScanResponse | null>(initialScan);
  const [busy, setBusy] = useState(false);

  async function refreshUniverse(nextMode = mode) {
    setUniverse(await getUniverse(nextMode));
  }

  async function runScan() {
    setBusy(true);
    try {
      await refreshUniverse(mode);
      setScan(await getScan(mode, topN));
      toast.success("Scanner completed");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Scanner failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader>
          <CardTitle>Scanner Controls</CardTitle>
          <CardDescription>Scores are labeled as estimated edge and should not be read as a guarantee.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 md:flex-row md:items-end">
          <label className="grid gap-1 text-sm font-medium">
            Universe
            <select
              value={mode}
              onChange={(event) => {
                setMode(event.target.value);
                refreshUniverse(event.target.value).catch(() => toast.error("Universe refresh failed"));
              }}
              className="h-10 rounded-md border bg-background px-3"
            >
              {modes.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Top N
            <input
              value={topN}
              onChange={(event) => setTopN(Number(event.target.value))}
              type="number"
              min={1}
              max={100}
              className="h-10 w-28 rounded-md border bg-background px-3"
            />
          </label>
          <Button onClick={runScan} disabled={busy}>
            {busy ? <RefreshCw className="animate-spin" /> : <Play />} Run scan
          </Button>
          <div className="text-sm text-muted-foreground">
            Universe count: <span className="font-mono text-foreground">{number(universe?.count, 0)}</span>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ranked Candidates</CardTitle>
          <CardDescription>{scan?.note || "score = estimated edge (0-100), NOT a profit guarantee"}</CardDescription>
        </CardHeader>
        <CardContent>
          {scan?.candidates?.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Estimated Edge</TableHead>
                  <TableHead className="text-right">Price</TableHead>
                  <TableHead>Regime</TableHead>
                  <TableHead>Strategy</TableHead>
                  <TableHead>Reason</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {scan.candidates.map((candidate, idx) => (
                  <TableRow key={`${candidate.symbol || "candidate"}-${idx}`}>
                    <TableCell className="font-semibold">{text(candidate.symbol)}</TableCell>
                    <TableCell><Badge variant={String(candidate.side).toLowerCase() === "sell" ? "danger" : "success"}>{text(candidate.side, "buy").toUpperCase()}</Badge></TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{number(candidate.score, 2)}</TableCell>
                    <TableCell className="text-right font-mono tabular-nums">{number(candidate.price ?? candidate.close, 2)}</TableCell>
                    <TableCell>{text(candidate.regime)}</TableCell>
                    <TableCell>{text(candidate.strategy)}</TableCell>
                    <TableCell className="max-w-[22rem] truncate text-muted-foreground">{text(candidate.reason)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
              Run the scanner to populate estimated-edge candidates.
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
