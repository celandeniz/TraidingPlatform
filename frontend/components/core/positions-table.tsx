import type { Position } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { money, number, text } from "@/components/core/format";

function posQty(position: Position) {
  return position.qty ?? position.quantity;
}

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions?.length) {
    return <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">No open positions reported.</div>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead className="text-right">Average</TableHead>
          <TableHead className="text-right">Last</TableHead>
          <TableHead className="text-right">Market Value</TableHead>
          <TableHead className="text-right">Open P&L</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {positions.map((position, idx) => {
          const side = text(position.side || (Number(posQty(position)) < 0 ? "short" : "long"));
          const pnl = Number(position.unrealized_pl ?? position.unrealized_pnl);
          return (
            <TableRow key={`${position.symbol || "position"}-${idx}`}>
              <TableCell className="font-semibold">{text(position.symbol)}</TableCell>
              <TableCell>
                <Badge variant={side.toLowerCase().includes("short") ? "danger" : "success"}>{side.toUpperCase()}</Badge>
              </TableCell>
              <TableCell className="text-right font-mono tabular-nums">{number(posQty(position), 4)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{money(position.avg_entry_price ?? position.avg_price)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{money(position.last_price)}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{money(position.market_value)}</TableCell>
              <TableCell className={pnl < 0 ? "text-right font-mono text-danger" : "text-right font-mono text-success"}>
                {money(pnl)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
