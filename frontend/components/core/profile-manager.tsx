"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { text } from "@/components/core/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { activateProfile } from "@/lib/api";
import type { ProfilesResponse, SetupStatus } from "@/lib/types";

export function ProfileManager({
  initialProfiles,
  setup,
}: {
  initialProfiles: ProfilesResponse | null;
  setup: SetupStatus | null;
}) {
  const [profiles, setProfiles] = useState(initialProfiles);
  const [busy, setBusy] = useState<string | null>(null);

  async function activate(name: string) {
    setBusy(name);
    try {
      const next = await activateProfile(name);
      setProfiles((current) => ({ ...current, ...next, profiles: current?.profiles || [] }));
      toast.success(`Activated ${name}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Profile activation failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Tabs defaultValue="profiles">
      <TabsList>
        <TabsTrigger value="profiles">Profiles</TabsTrigger>
        <TabsTrigger value="status">Setup Status</TabsTrigger>
      </TabsList>

      <TabsContent value="profiles">
        <div className="grid gap-4 lg:grid-cols-2">
          {(profiles?.profiles || []).map((profile) => {
            const active = profile.name === profiles?.active;
            return (
              <Card key={profile.name} className={active ? "border-primary/60 shadow-glow" : undefined}>
                <CardHeader>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <CardTitle>{profile.name}</CardTitle>
                      <CardDescription>{text(profile.description, "Configured trading profile")}</CardDescription>
                    </div>
                    {active && <Badge variant="violet">ACTIVE</Badge>}
                  </div>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    <Badge variant={profile.mode === "live" ? "danger" : "success"}>{text(profile.mode, "paper").toUpperCase()}</Badge>
                    <Badge variant="secondary">{text(profile.broker, "broker unknown")}</Badge>
                  </div>
                  <div className="grid gap-2 text-sm">
                    {Object.entries(profile.features || {}).slice(0, 8).map(([key, value]) => (
                      <div key={key} className="flex items-center justify-between rounded-md bg-muted/45 px-3 py-2">
                        <span className="text-muted-foreground">{key}</span>
                        <Badge variant={value ? "success" : "secondary"}>{value ? "ON" : "OFF"}</Badge>
                      </div>
                    ))}
                  </div>
                  <Button variant={active ? "secondary" : "default"} disabled={active || busy !== null} onClick={() => activate(profile.name)}>
                    {busy === profile.name ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
                    {active ? "Active" : "Activate"}
                  </Button>
                </CardContent>
              </Card>
            );
          })}
          {!profiles?.profiles?.length && (
            <Card>
              <CardContent className="p-6 text-sm text-muted-foreground">Profiles endpoint did not return configured profiles.</CardContent>
            </Card>
          )}
        </div>
      </TabsContent>

      <TabsContent value="status">
        <div className="grid gap-4 lg:grid-cols-3">
          <StatusCard title="Optional Dependencies" data={setup?.optional_deps} />
          <StatusCard title="Key Presence" data={setup?.api_keys_set} />
          <StatusCard title="LLM Reachability" data={setup?.llm_providers_reachable} />
        </div>
      </TabsContent>
    </Tabs>
  );
}

function StatusCard({ title, data }: { title: string; data: Record<string, boolean> | undefined }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>Boolean status only; secret values are never rendered.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {Object.entries(data || {}).map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-3 rounded-md bg-muted/45 px-3 py-2 text-sm">
            <span className="truncate text-muted-foreground">{key}</span>
            <Badge variant={value ? "success" : "secondary"}>{value ? "SET" : "OFF"}</Badge>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
