import { ProfileManager } from "@/components/core/profile-manager";
import { PageTitle } from "@/components/shell/page-title";
import { getProfiles, getSetupStatus } from "@/lib/api";

export default async function SetupPage() {
  const [profiles, setup] = await Promise.all([
    getProfiles().catch(() => null),
    getSetupStatus().catch(() => null),
  ]);

  return (
    <>
      <PageTitle title="Setup / Profiles" description="Profile activation, feature flags, optional dependency status, and booleans-only key presence." />
      <ProfileManager initialProfiles={profiles} setup={setup} />
    </>
  );
}
