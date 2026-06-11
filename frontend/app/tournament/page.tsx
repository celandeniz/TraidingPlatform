import { TournamentClient } from "@/components/core/tournament-client";
import { PageTitle } from "@/components/shell/page-title";
import { getTournamentLatest } from "@/lib/api";

export default async function TournamentPage() {
  const latest = await getTournamentLatest().catch(() => null);

  return (
    <>
      <PageTitle
        title="Strategy Tournament"
        description="Walk every strategy through out-of-sample validation; rank by OOS Sharpe with hard risk gates."
      />
      <TournamentClient initial={latest} />
    </>
  );
}
