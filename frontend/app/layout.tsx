import type { Metadata } from "next";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import "@/app/globals.css";
import { Header } from "@/components/shell/header";
import { Sidebar } from "@/components/shell/sidebar";
import { ThemeProvider } from "@/components/shell/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { getProfiles } from "@/lib/api";

export const metadata: Metadata = {
  title: "TraidingPlatform",
  description: "Trading research and execution control surface",
};

async function profilesSafe() {
  try {
    return await getProfiles();
  } catch {
    return null;
  }
}

export default async function RootLayout({ children }: { children: ReactNode }) {
  const profiles = await profilesSafe();

  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <Header profiles={profiles} />
          <div className="grid min-h-[calc(100vh-4rem)] grid-cols-1 lg:grid-cols-[250px_minmax(0,1fr)]">
            <Sidebar />
            <main className="min-w-0 p-4 lg:p-6">{children}</main>
          </div>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}

export function RootRedirect() {
  redirect("/live");
}
