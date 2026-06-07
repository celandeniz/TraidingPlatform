import { ScannerClient } from "@/components/core/scanner-client";
import { PageTitle } from "@/components/shell/page-title";
import { getScan, getUniverse } from "@/lib/api";

export default async function ScannerPage() {
  const [universe, scan] = await Promise.all([
    getUniverse("m7").catch(() => null),
    getScan("m7", 25).catch(() => null),
  ]);

  return (
    <>
      <PageTitle title="Scanner" description="On-demand universe scan via `/api/universe` and `/api/scan?mode=&top_n=`." />
      <ScannerClient initialUniverse={universe} initialScan={scan} />
    </>
  );
}
