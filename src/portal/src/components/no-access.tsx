import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ROLE_LABEL, type Role } from "@/lib/auth/roles";

/** Shown instead of a page (or a form) when the user lacks the role it needs. */
export function NoAccess({ needed }: { needed: Role }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>Sin acceso</AlertTitle>
      <AlertDescription>
        Esta parte del portal necesita el rol {ROLE_LABEL[needed].toLowerCase()}. Pide a un editor que te lo asigne en
        Usuarios.
      </AlertDescription>
    </Alert>
  );
}
