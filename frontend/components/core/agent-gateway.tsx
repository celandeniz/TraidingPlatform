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
import { askGateway } from "@/lib/api";
import type { GatewayReply } from "@/lib/types";

type Turn = { id: string; q: string; reply: GatewayReply };

function turnId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random()}`;
}

export function AgentGateway() {
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);

  const ask = async () => {
    const q = message.trim();
    if (!q) return;
    setBusy(true);
    try {
      const reply = await askGateway(q);
      setTurns((t) => [{ id: turnId(), q, reply }, ...t]);
      setMessage("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "gateway failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Agent Gateway</CardTitle>
        <CardDescription>
          Ask about positions, account, orders, signals, market data,
          fundamentals, backtests, or research. Read-only — it never places trades.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-2">
          <input
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="e.g. what's my exposure?"
            className="h-10 flex-1 rounded-md border bg-background px-3 text-sm"
            onKeyDown={(e) => e.key === "Enter" && !busy && !!message.trim() && ask()}
          />
          <Button onClick={ask} disabled={busy || !message.trim()}>
            {busy ? "Asking…" : "Ask"}
          </Button>
        </div>

        <ul className="space-y-3">
          {turns.map((t) => (
            <li key={t.id} className="space-y-1 border-b pb-2 last:border-0">
              <p className="text-sm font-medium">{t.q}</p>
              {t.reply.ok ? (
                <div className="flex items-start gap-2">
                  <Badge variant="outline" className="shrink-0">
                    {t.reply.intent}
                  </Badge>
                  <p className="text-sm text-muted-foreground">{t.reply.answer}</p>
                </div>
              ) : (
                <p className="text-sm text-amber-600">
                  {t.reply.answer || t.reply.detail || "Gateway unavailable."}
                </p>
              )}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
