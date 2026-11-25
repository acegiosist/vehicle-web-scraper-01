import { userWithRole } from "@/lib/auth/current-user";
import { templateFile } from "@/lib/queries/actions";

/** Download a capture template that kb worker prepared (an applied export_specs request). */
export async function GET(_request: Request, ctx: RouteContext<"/captura/plantilla/[id]">) {
  if (!(await userWithRole("revisor"))) return new Response("Sin acceso", { status: 403 });
  const { id } = await ctx.params;
  const file = await templateFile(id);
  if (!file) return new Response("No existe esa plantilla (o todavía no está lista).", { status: 404 });
  return new Response(new Uint8Array(file.data), {
    headers: {
      "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "content-disposition": `attachment; filename="${file.name.replace(/[^A-Za-z0-9._-]/g, "_")}"`,
      "cache-control": "private, no-store",
    },
  });
}
