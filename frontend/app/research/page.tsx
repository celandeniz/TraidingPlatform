import { PersonaPanel } from "@/components/core/persona-panel";
import { PageTitle } from "@/components/shell/page-title";

export default function ResearchPage() {
  return (
    <>
      <PageTitle
        title="Research / News"
        description="Persona panel verdicts, unified headlines, and committee endpoints (/api/panel, /api/news/latest, /api/copilot)."
      />
      <PersonaPanel />
    </>
  );
}
