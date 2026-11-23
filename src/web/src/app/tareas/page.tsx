import { Suspense } from "react";
import type { Metadata } from "next";

import { JobForms } from "@/components/jobs/job-forms";
import { JobPoller } from "@/components/jobs/job-poller";
import { JobTable } from "@/components/jobs/job-table";
import { Skeleton } from "@/components/ui/skeleton";
import { RunTable } from "@/components/ai-runs/run-table";
import { listJobs, pendingRuns, recentRuns } from "@/lib/queries/jobs";

export const metadata: Metadata = { title: "Tareas" };

export default function JobsPage() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Tareas</h1>
        <p className="text-sm text-muted-foreground">
          Comandos de la base de conocimiento. El sitio los deja en cola y el worker de Python (
          <code>vehicle-scraper kb worker</code>) los ejecuta uno a uno con el mismo código del CLI.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Forms />
      </Suspense>
      <section aria-labelledby="jobs-heading" className="space-y-3">
        <h2 id="jobs-heading" className="text-lg font-semibold">
          Últimas tareas
        </h2>
        <Suspense fallback={<Skeleton className="h-64" />}>
          <Jobs />
        </Suspense>
      </section>
      <section aria-labelledby="runs-heading" className="space-y-3">
        <div>
          <h2 id="runs-heading" className="text-lg font-semibold">
            Lotes de IA
          </h2>
          <p className="text-sm text-muted-foreground">
            El worker revisa cada 5 minutos si un lote enviado terminó; entonces aparece un aviso para recogerlo.
          </p>
        </div>
        <Suspense fallback={<Skeleton className="h-32" />}>
          <Runs />
        </Suspense>
      </section>
    </main>
  );
}

async function Forms() {
  return <JobForms runs={await pendingRuns()} />;
}

async function Runs() {
  return <RunTable runs={await recentRuns()} />;
}

async function Jobs() {
  const jobs = await listJobs();
  return (
    <>
      <JobPoller active={jobs.some((j) => j.status === "queued" || j.status === "running")} />
      <JobTable jobs={jobs} />
    </>
  );
}
