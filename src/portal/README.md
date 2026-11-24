# Portal de omnibase

Sitio para revisar, explorar y corregir la base de conocimiento de vehículos. Next.js 16 (App
Router, Cache Components) + Kysely + Zod. Lee omnibase con un rol de solo lectura y escribe solo
peticiones en `kb.web_action`; el worker de Python (`python -m vehicle_scraper kb worker`, en la
raíz del repo) las valida y aplica.

## Puesta en marcha local

1. En omnibase (como dueño de la base), una sola vez:
   `CREATE ROLE omnibase_portal LOGIN PASSWORD '...';` y luego `docs/sql/portal_role.sql`
   (repetirlo después de cada migración).
2. El primer editor: poner `KB_FIRST_EDITOR_EMAIL` (y opcionalmente `KB_FIRST_EDITOR_NAME`) en el
   `.env` de la raíz antes de `kb migrate`; la migración `0008_first_editor` lo crea. Los demás
   usuarios se agregan desde la página Usuarios.
3. `cp .env.example .env.local` y completar `PORTAL_DATABASE_URL` y `PORTAL_DEV_USER`.
4. `pnpm install` y `pnpm dev` → http://127.0.0.1:3000
5. En otra terminal, desde la raíz del repo: `PYTHONPATH=src python -m vehicle_scraper kb worker`.

## Identidad

- En GCP: Identity-Aware Proxy. El portal verifica la cabecera firmada `x-goog-iap-jwt-assertion`
  (`src/lib/auth/iap.ts`) con `PORTAL_AUTH=iap` y `PORTAL_IAP_AUDIENCE`. La cabecera de correo sin
  firma nunca se usa sola. `/api/salud` responde sin identidad (health check).
- En local: `PORTAL_AUTH=dev` + `PORTAL_DEV_USER`. Se rechaza en producción y en Cloud Run.
- El rol (lector, revisor, editor) sale de `kb.app_user`; el worker lo vuelve a comprobar.

## Comandos

- `pnpm lint`, `pnpm typecheck`, `pnpm test` (Vitest, sin base de datos)
- `pnpm test:e2e`: pruebas de punta a punta con Playwright (build de producción en modo IAP y el
  worker real). Necesita el contenedor desechable de pruebas en el puerto 55441:

  ```
  docker run -d --name omnibase-test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=omnibase_test -p 55441:5432 postgres:16-alpine
  ```

  `tests/e2e_portal.py` (en la raíz del repositorio) recrea ahí la base `omnibase_e2e` en cada
  corrida; nunca toca omnibase.
- `pnpm db:types`: regenera `src/generated/db.d.ts` después de una migración.
