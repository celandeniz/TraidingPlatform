import { LiveBoard } from "@/components/core/live-board";
import { PageTitle } from "@/components/shell/page-title";
import { getPositions } from "@/lib/api";

export default async function LivePage() {
  let positions = null;
  try {
    positions = await getPositions();
  } catch {
    positions = null;
  }

  return (
    <>
      <PageTitle title="Live / Signals" description="Realtime signal, price, and order flow wired to `/api/positions` and `/ws`." />
      <LiveBoard initial={positions} />
    </>
  );
}
