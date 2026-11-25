import { Suspense } from "react";
import type { Metadata } from "next";

import { ActionForm } from "@/components/edit/action-form";
import { RecentActions } from "@/components/edit/recent-actions";
import { NoAccess } from "@/components/no-access";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { upsertUser } from "@/lib/actions/request";
import { userWithRole } from "@/lib/auth/current-user";
import { ROLE_LABEL, ROLES } from "@/lib/auth/roles";
import { formatDate } from "@/lib/format";
import { recentActionsFor, users } from "@/lib/queries/actions";

export const metadata: Metadata = { title: "Usuarios" };

export default function UsersPage() {
  return (
    <main className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Usuarios</h1>
        <p className="text-sm text-muted-foreground">
          Quién entra (su correo de Google, vía IAP) y con qué rol: lector ve todo, revisor además decide casos y usa Captura, editor
          además edita fichas, catálogos y usuarios.
        </p>
      </div>
      <Suspense fallback={<Skeleton className="h-96" />}>
        <Users />
      </Suspense>
    </main>
  );
}

function RoleSelect({ defaultValue }: { defaultValue?: string }) {
  return (
    <NativeSelect name="role" required defaultValue={defaultValue ?? ""} aria-label="Rol">
      <option value="" disabled>
        Rol…
      </option>
      {ROLES.map((r) => (
        <option key={r} value={r}>
          {ROLE_LABEL[r]}
        </option>
      ))}
    </NativeSelect>
  );
}

async function Users() {
  // Who has access is itself sensitive: only editors see and change it.
  if (!(await userWithRole("editor"))) return <NoAccess needed="editor" />;
  // Requests first, then the data they change (see recentActionsFor).
  const actions = await recentActionsFor([{ role: "lector" }, { role: "revisor" }, { role: "editor" }]);
  const rows = await users();
  return (
    <div className="space-y-6">
      <RecentActions actions={actions.filter((a) => a.kind === "user_upsert")} />
      <Card size="sm">
        <CardHeader>
          <CardTitle>Dar acceso</CardTitle>
          <CardDescription>Si el correo ya existe, se actualiza su rol.</CardDescription>
        </CardHeader>
        <CardContent>
          <ActionForm action={upsertUser} submitLabel="Guardar" className="grid gap-2 sm:grid-cols-[1fr_1fr_10rem_auto]" testId="user-form">
            <Input name="email" type="email" required placeholder="correo@empresa.com" aria-label="Correo" />
            <Input name="name" placeholder="Nombre (opcional)" aria-label="Nombre" />
            <RoleSelect />
            <input type="hidden" name="active" value="true" />
          </ActionForm>
        </CardContent>
      </Card>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Correo</TableHead>
            <TableHead>Nombre</TableHead>
            <TableHead>Rol</TableHead>
            <TableHead>Actualizado</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((u) => (
            <TableRow key={u.email}>
              <TableCell>{u.email}</TableCell>
              <TableCell>{u.name ?? "—"}</TableCell>
              <TableCell>
                <Badge variant={u.active ? "secondary" : "outline"}>
                  {ROLE_LABEL[u.role as keyof typeof ROLE_LABEL] ?? u.role}
                  {!u.active && " · inactivo"}
                </Badge>
              </TableCell>
              <TableCell className="text-xs text-muted-foreground">
                {formatDate(u.updated_at)} {u.updated_by && `· ${u.updated_by}`}
              </TableCell>
              <TableCell>
                <details className="text-xs">
                  <summary className="cursor-pointer text-muted-foreground">Editar</summary>
                  <ActionForm action={upsertUser} submitLabel="Guardar" className="mt-2 space-y-2">
                    <input type="hidden" name="email" value={u.email} />
                    <input type="hidden" name="name" value={u.name ?? ""} />
                    <RoleSelect defaultValue={u.role} />
                    <label className="flex items-center gap-2">
                      <input type="checkbox" name="active" defaultChecked={u.active} /> Activo
                    </label>
                  </ActionForm>
                </details>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
