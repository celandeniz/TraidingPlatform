"use client";

import { RadioTower, RefreshCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AccountStrip } from "@/components/core/account-strip";
import { money, number, text } from "@/components/core/format";
import { PositionsTable } from "@/components/core/positions-table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getPositions, wsUrl } from "@/lib/api";
import type { PositionsResponse, WsEvent } from "@/lib/types";

export function LiveBoard({ initial }: { initial: PositionsResponse | null }) {
  const [positions, setPositions] = useState<PositionsResponse | null>(initial);
  const [events, setEvents] = useState<WsEvent[]>([]);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const socket = new WebSocket(wsUrl());
    socket.onopen = () => setConnected(true);
    socket.onclose = () => setConnected(false);
    socket.onerror = () => setConnected(false);
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data) as WsEvent;
        setEvents((current) => [event, ...current].slice(0, 80));
      } catch {
        setEvents((current) => [{ type: "parse_error", detail: "Invalid WebSocket payload" }, ...current].slice(0, 80));
      }
    };
    return () => socket.close();
  }, []);

  async function refresh() {
    setPositions(await getPositions());
  }

  const latestBySymbol = useMemo(() => {
    const map = new Map<string, WsEvent>();
    for (const event of events) {
      if (event.symbol && !map.has(event.symbol)) map.set(event.symbol, event);
    }
    return Array.from(map.values()).slice(0, 12);
  }, [events]);

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <Badge variant={connected ? "success" : "danger"} className="w-fit gap-2">
          <span className={connected ? "size-2 rounded-full bg-success shadow-glow" : "size-2 rounded-full bg-danger"} />
          {connected ? "WS CONNECTED" : "WS DISCONNECTED"}
        </Badge>
        <Button variant="outline" size="sm" onClick={refresh}>
          <RefreshCcw /> Refresh positions
        </Button>
      </div>

      <AccountStrip account={positions?.account} />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Live / Signals</CardTitle>
            <CardDescription>Signal, price, order, and scanner events from FastAPI `/ws`.</CardDescription>
          </CardHeader>
          <CardContent>
            {latestBySymbol.length ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Symbol</TableHead>
                    <TableHead>Event</TableHead>
                    <TableHead>Strategy</TableHead>
                    <TableHead>Side</TableHead>
                    <TableHead className="text-right">Last</TableHead>
                    <TableHead className="text-right">Strength</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {latestBySymbol.map((event, idx) => (
                    <TableRow key={`${event.symbol}-${idx}`}>
                      <TableCell className="font-semibold">{event.symbol}</TableCell>
                      <TableCell><Badge variant="violet">{text(event.type).toUpperCase()}</Badge></TableCell>
                      <TableCell>{text(event.strategy)}</TableCell>
                      <TableCell>{text(event.side).toUpperCase()}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">{money(event.close)}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">{number(event.strength, 4)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="flex min-h-[14rem] items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground">
                <div className="flex items-center gap-2"><RadioTower className="size-4" /> Waiting for live events.</div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Open Positions</CardTitle>
            <CardDescription>Fetched from `/api/positions`; refresh leaves broker behavior untouched.</CardDescription>
          </CardHeader>
          <CardContent>
            <PositionsTable positions={positions?.positions || []} />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Event Tape</CardTitle>
          <CardDescription>Most recent WebSocket messages, rendered as escaped React text.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="max-h-80 overflow-auto rounded-md border">
            {events.length ? events.map((event, idx) => (
              <div key={idx} className="grid grid-cols-[6rem_1fr] gap-3 border-b px-3 py-2 text-sm last:border-0">
                <span className="font-mono text-xs text-muted-foreground">{text(event.type)}</span>
                <span className="truncate">
                  {text(event.symbol, "market")} {text(event.side, "")} {text(event.status || event.detail || event.strategy, "")}
                </span>
              </div>
            )) : <div className="p-5 text-sm text-muted-foreground">No events received yet.</div>}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
