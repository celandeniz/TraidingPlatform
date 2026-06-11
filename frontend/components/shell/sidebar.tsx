"use client";

import {
  Activity,
  BarChart3,
  Bot,
  ClipboardList,
  FileBarChart,
  LineChart,
  Newspaper,
  Radar,
  Settings2,
  Trophy,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const groups = [
  {
    label: "Trading",
    items: [
      { href: "/live", label: "Live / Signals", icon: Activity },
      { href: "/positions", label: "Positions", icon: ClipboardList },
      { href: "/scanner", label: "Scanner", icon: Radar },
    ],
  },
  {
    label: "Validation",
    items: [
      { href: "/backtest", label: "Backtest & Validation", icon: LineChart },
      { href: "/tournament", label: "Tournament", icon: Trophy },
    ],
  },
  {
    label: "Workspace",
    items: [
      { href: "/research", label: "Research / News", icon: Newspaper },
      { href: "/automation", label: "Automation", icon: Bot },
      { href: "/reports", label: "Reports", icon: FileBarChart },
      { href: "/setup", label: "Setup / Profiles", icon: Settings2 },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="border-r bg-secondary/35 lg:sticky lg:top-16 lg:h-[calc(100vh-4rem)]">
      <nav className="flex gap-2 overflow-x-auto p-3 lg:block lg:space-y-5 lg:overflow-y-auto">
        {groups.map((group) => (
          <div key={group.label} className="flex shrink-0 gap-2 lg:block lg:space-y-1">
            <div className="hidden px-3 py-1 text-[0.65rem] font-bold uppercase tracking-[0.16em] text-muted-foreground lg:block">
              {group.label}
            </div>
            {group.items.map((item) => {
              const active = pathname === item.href || (pathname === "/" && item.href === "/live");
              const Icon = item.icon || BarChart3;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-semibold text-muted-foreground no-underline transition-colors hover:bg-muted hover:text-foreground",
                    active && "bg-muted text-foreground shadow-sm",
                  )}
                >
                  <Icon className="size-4" />
                  <span className="whitespace-nowrap">{item.label}</span>
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
    </aside>
  );
}
