import { Card, CardContent } from "@/components/ui/card";
import { money, number } from "@/components/core/format";

const keys = [
  ["Equity", ["equity", "portfolio_value"]],
  ["Cash", ["cash", "buying_power"]],
  ["Open P&L", ["open_pnl", "unrealized_pl", "unrealized_pnl"]],
  ["Buying Power", ["buying_power"]],
];

export function AccountStrip({ account }: { account: Record<string, unknown> | null | undefined }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {keys.map(([label, candidates]) => {
        const value = (candidates as string[]).map((key) => account?.[key]).find((item) => item !== undefined);
        return (
          <Card key={label as string}>
            <CardContent className="p-4">
              <div className="metric-label">{label}</div>
              <div className="mt-2 font-mono text-xl font-semibold tabular-nums">
                {(label as string).includes("P&L") ? number(value) : money(value)}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
