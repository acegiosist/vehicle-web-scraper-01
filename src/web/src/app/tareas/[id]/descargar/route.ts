import { gunzipSync } from "node:zlib";

import { jobFile } from "@/lib/queries/jobs";
import { safeFilename } from "@/lib/jobs";

/** Download a job's file (exports). CSV/JSON are stored gzip-compressed in kb.job_file. */
export async function GET(_req: Request, ctx: RouteContext<"/tareas/[id]/descargar">) {
  const { id } = await ctx.params;
  const file = await jobFile(id);
  if (!file) return new Response("No encontrado", { status: 404 });
  const body = file.gzipped ? gunzipSync(file.bytes) : file.bytes;
  return new Response(new Uint8Array(body), {
    headers: {
      "Content-Type": file.content_type,
      "Content-Disposition": `attachment; filename="${safeFilename(file.filename)}"`,
      "Content-Length": String(body.length),
      "Cache-Control": "no-store",
    },
  });
}
