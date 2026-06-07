import { PlaceholderPage } from "@/components/core/placeholder-page";

export default function ResearchPage() {
  return <PlaceholderPage title="Research / News" description="Unified headlines, catalyst explanations, and committee verdicts." endpoint="/api/news/latest, /api/copilot/{symbol}, /api/committee/{symbol}" />;
}
