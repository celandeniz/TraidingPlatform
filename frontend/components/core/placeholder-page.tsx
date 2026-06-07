import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { PageTitle } from "@/components/shell/page-title";

export function PlaceholderPage({
  title,
  description,
  endpoint,
}: {
  title: string;
  description: string;
  endpoint: string;
}) {
  return (
    <>
      <PageTitle title={title} description={description} />
      <Card>
        <CardHeader>
          <CardTitle>Scaffolded Route</CardTitle>
          <CardDescription>Navigation is in place; deeper workflow wiring can build on the existing FastAPI endpoint.</CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          Planned integration surface: <span className="font-mono text-foreground">{endpoint}</span>
        </CardContent>
      </Card>
    </>
  );
}
