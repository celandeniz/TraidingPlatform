import Link from "next/link";

import { ThemeToggle } from "@/components/shell/theme-toggle";
import { Badge } from "@/components/ui/badge";
import type { ProfilesResponse } from "@/lib/types";

export function Header({ profiles }: { profiles: ProfilesResponse | null }) {
  const runtime = profiles?.runtime;
  const paper = runtime?.paper_mode ?? true;
  const active = profiles?.active || runtime?.active_profile || "test";
  const risk = runtime?.risk_enabled;

  return (
    <header className="sticky top-0 z-40 border-b bg-background/92 backdrop-blur">
      <div className="flex min-h-16 items-center gap-3 px-4 lg:px-6">
        <Link href="/live" className="mr-1 flex flex-col no-underline">
          <span className="font-display text-base font-bold tracking-normal text-foreground">TraidingPlatform</span>
          <span className="text-xs font-medium text-muted-foreground">M7 Spike-Fade control surface</span>
        </Link>

        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Badge variant={paper ? "success" : "danger"}>{paper ? "PAPER MODE" : "LIVE MODE"}</Badge>
          <Badge variant="violet">PROFILE {active}</Badge>
          <Badge variant={risk ? "warning" : "secondary"}>{risk ? "RISK ON" : "RISK OFF"}</Badge>
          <span className="hidden max-w-[34rem] truncate border-l pl-3 text-xs text-muted-foreground md:inline">
            score = estimated edge, not a guarantee / paper by default
          </span>
        </div>

        <ThemeToggle />
      </div>
      <div className="border-t px-4 py-2 text-xs text-muted-foreground md:hidden">
        score = estimated edge, not a guarantee / paper by default
      </div>
    </header>
  );
}
