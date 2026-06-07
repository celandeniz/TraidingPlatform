import { AccountStrip } from "@/components/core/account-strip";
import { OrdersTable } from "@/components/core/orders-table";
import { PositionsTable } from "@/components/core/positions-table";
import { PageTitle } from "@/components/shell/page-title";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getOrders, getPositions } from "@/lib/api";

export default async function PositionsPage() {
  const [positions, orders] = await Promise.all([
    getPositions().catch(() => null),
    getOrders().catch(() => null),
  ]);

  return (
    <>
      <PageTitle title="Positions" description="Broker account state and OMS order ledger fetched from FastAPI." />
      <div className="space-y-5">
        <AccountStrip account={positions?.account} />
        <Card>
          <CardHeader>
            <CardTitle>Open Positions</CardTitle>
            <CardDescription>Source: `GET /api/positions`.</CardDescription>
          </CardHeader>
          <CardContent><PositionsTable positions={positions?.positions || []} /></CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>OMS Orders</CardTitle>
            <CardDescription>Source: `GET /api/orders`.</CardDescription>
          </CardHeader>
          <CardContent><OrdersTable orders={orders?.orders || []} /></CardContent>
        </Card>
      </div>
    </>
  );
}
