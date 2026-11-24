import { ActionStatusBadge } from "@/components/action-status";
import { RefreshWhile } from "@/components/refresh-while";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { ACTION_LABELS, describePayload } from "@/lib/action-labels";
import type { RecentAction } from "@/lib/queries/actions";

/** Requests about this page's entity: what is waiting, what was applied, what failed and why. */
export function RecentActions({ actions }: { actions: RecentAction[] }) {
  if (!actions.length) return null;
  const inFlight = actions.some((a) => a.status === "queued" || a.status === "running");
  return (
    <Card size="sm">
      <RefreshWhile active={inFlight} />
      <CardHeader>
        <CardTitle>Cambios recientes</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {actions.map((a) => (
          <div key={String(a.id)} data-testid="recent-action">
            <div className="flex flex-wrap items-center gap-2">
              <ActionStatusBadge status={a.status} />
              <span>{ACTION_LABELS[a.kind] ?? a.kind}</span>
              <span className="text-muted-foreground">{describePayload(a.kind, a.payload)}</span>
              <span className="text-xs text-muted-foreground">
                {a.requested_by} · {formatDate(a.requested_at)}
              </span>
            </div>
            {a.error && <p className="text-destructive">{a.error}</p>}
          </div>
        ))}
        {inFlight && <p className="text-xs text-muted-foreground">Los anuncios se mueven de generación o variante al recalcular.</p>}
      </CardContent>
    </Card>
  );
}
