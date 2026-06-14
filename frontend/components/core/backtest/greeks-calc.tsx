"use client";

import type * as React from "react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getGreeks } from "@/lib/api";
import type { GreeksResult } from "@/lib/types";

export function GreeksCalc() {
  const [form, setForm] = useState({ spot: 100, strike: 100, days: 30, vol: 0.25, call: true });
  const [data, setData] = useState<GreeksResult | null>(null);
  const [busy, setBusy] = useState(false);

  const compute = async () => {
    setBusy(true);
    try {
      setData(await getGreeks(form));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "greeks failed");
    } finally {
      setBusy(false);
    }
  };

  const num = (k: "spot" | "strike" | "days" | "vol") => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: Number(e.target.value) });

  return (
    <Card>
      <CardHeader>
        <CardTitle>Options Greeks (Black-Scholes)</CardTitle>
        <CardDescription>Offline calculator. vol as a decimal (0.25 = 25%), days to expiry.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-2 text-sm">
          <label className="grid gap-1">spot<input type="number" value={form.spot} onChange={num("spot")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">strike<input type="number" value={form.strike} onChange={num("strike")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">days<input type="number" value={form.days} onChange={num("days")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">vol<input type="number" step="0.01" value={form.vol} onChange={num("vol")} className="h-10 w-24 rounded-md border bg-background px-3" /></label>
          <label className="grid gap-1">type
            <select value={form.call ? "call" : "put"} onChange={(e) => setForm({ ...form, call: e.target.value === "call" })}
              className="h-10 rounded-md border bg-background px-3">
              <option value="call">call</option><option value="put">put</option>
            </select>
          </label>
          <Button onClick={compute} disabled={busy}>{busy ? "Computing…" : "Compute"}</Button>
        </div>
        {data && !data.ok && <p className="text-sm text-amber-600">{data.detail || "Failed."}</p>}
        {data && data.ok && (
          <div className="flex flex-wrap gap-2 text-sm">
            {Object.entries(data)
              .filter(([k]) => k !== "ok")
              .map(([k, v]) => (
                <Badge key={k} variant="outline">{k}: {typeof v === "number" ? v.toFixed(4) : String(v)}</Badge>
              ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
