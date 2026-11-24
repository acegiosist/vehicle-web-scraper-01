import { Badge } from "@/components/ui/badge";

const LABELS: Record<string, [string, "secondary" | "destructive" | "outline" | "default"]> = {
  queued: ["En cola", "outline"],
  running: ["Aplicando", "outline"],
  applied: ["Aplicada", "secondary"],
  failed: ["Falló", "destructive"],
};

export function ActionStatusBadge({ status }: { status: string | null }) {
  const [label, variant] = LABELS[status ?? ""] ?? [status ?? "—", "outline"];
  return <Badge variant={variant}>{label}</Badge>;
}
