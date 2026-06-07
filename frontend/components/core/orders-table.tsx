import type { OrderRecord } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { number, text } from "@/components/core/format";

function stateVariant(state: string) {
  if (state.includes("pushed") || state.includes("filled")) return "success";
  if (state.includes("commit")) return "violet";
  if (state.includes("reject") || state.includes("fail")) return "danger";
  return "secondary";
}

export function OrdersTable({ orders }: { orders: OrderRecord[] }) {
  if (!orders?.length) {
    return <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">No OMS order history yet.</div>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>ID</TableHead>
          <TableHead>State</TableHead>
          <TableHead>Symbol</TableHead>
          <TableHead>Side</TableHead>
          <TableHead className="text-right">Qty</TableHead>
          <TableHead>Message</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {orders.map((order) => {
          const state = text(order.state, "staged").toLowerCase();
          return (
            <TableRow key={order.id}>
              <TableCell className="max-w-[9rem] truncate font-mono text-xs">{order.id}</TableCell>
              <TableCell><Badge variant={stateVariant(state)}>{state.toUpperCase()}</Badge></TableCell>
              <TableCell className="font-semibold">{text(order.request?.symbol)}</TableCell>
              <TableCell>{text(order.request?.side).toUpperCase()}</TableCell>
              <TableCell className="text-right font-mono tabular-nums">{number(order.request?.qty, 4)}</TableCell>
              <TableCell className="max-w-[22rem] truncate text-muted-foreground">{text(order.message || order.note || order.result?.detail)}</TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
