import { PersonaPanel } from "@/components/core/persona-panel";
import { VibeResearch } from "@/components/core/vibe-research";
import { PageTitle } from "@/components/shell/page-title";

export default function ResearchPage() {
  return (
    <>
      <PageTitle
        title="Research / News"
        description="Persona panel verdicts, Vibe sidecar research, unified headlines, and committee endpoints (/api/panel, /api/vibe/research, /api/news/latest, /api/copilot)."
      />
      <div className="space-y-6">
        <PersonaPanel />
        <VibeResearch />
      </div>
    </>
  );
}
