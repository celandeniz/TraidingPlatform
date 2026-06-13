import { AgentGateway } from "@/components/core/agent-gateway";
import { PersonaPanel } from "@/components/core/persona-panel";
import { StrategySynthesis } from "@/components/core/strategy-synthesis";
import { VibeResearch } from "@/components/core/vibe-research";
import { PageTitle } from "@/components/shell/page-title";

export default function ResearchPage() {
  return (
    <>
      <PageTitle
        title="Research / AI"
        description="Persona panel, Vibe research, NL→strategy synthesis, and the read-only agent gateway (/api/panel, /api/vibe/research, /api/synthesis, /api/agent/gateway)."
      />
      <div className="space-y-6">
        <AgentGateway />
        <StrategySynthesis />
        <PersonaPanel />
        <VibeResearch />
      </div>
    </>
  );
}
