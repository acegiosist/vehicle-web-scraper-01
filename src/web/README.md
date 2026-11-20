# Sitio de revisión de conflictos (`kb-review-web`)

Sitio web para tomar las decisiones humanas sobre la base de conocimiento de vehículos: la
misma revisión que `vehicle-scraper kb review export/import` hace con un CSV, pero caso por caso,
con la evidencia a la vista.

```
Navegador ──> Next.js (127.0.0.1:3000)
               │  lee: vista kb.review_queue, evidencia y anuncios (staging)
               │  escribe: SOLO INSERT en kb.review_decision (rol kb_review_web)
               ▼
          PostgreSQL ── NOTIFY kb_review_decision ──> vehicle-scraper kb review worker (Python)
                                                      review.decide_item() → apply_decision()
                                                      normalize + consolidate tras inactividad
```

El sitio **no aplica** decisiones: las encola. Las aplica el worker de Python con el mismo código
del CLI (fusiones de marcas y modelos, alias, conversión de unidades, cierre de lotes de muestreo),
así que la lógica existe en un solo lugar.

## Tecnologías

Next.js 16 (App Router, Cache Components) · React 19 · TypeScript estricto · Tailwind CSS 4 ·
shadcn/ui (Radix) · Kysely + `pg` (tipos generados con kysely-codegen; el esquema lo manda Alembic) ·
Zod · Vitest · Playwright.

## Puesta en marcha

Requisitos: Node ≥ 22.14, pnpm 10, la base migrada hasta `0002_review_web`
(`alembic upgrade head` en la raíz del repositorio) y el entorno Python del repositorio.

1. **Rol de la base** (una vez, como dueño de la base):
   ```bash
   psql "postgresql://OWNER@HOST:PORT/DB" -v pw='una-clave-fuerte' -f ../../docs/sql/review_web_role.sql
   ```
2. **Configuración:** copia `.env.example` a `.env.local` y pon la URL con ese rol:
   `REVIEW_WEB_DATABASE_URL=postgresql://kb_review_web:una-clave-fuerte@HOST:PORT/DB`
3. **Instalar y arrancar el sitio:**
   ```bash
   pnpm install
   pnpm dev            # http://127.0.0.1:3000  (producción: pnpm build && pnpm start)
   ```
4. **Arrancar el worker** (en la raíz del repositorio, con la URL del dueño en `KB_DATABASE_URL`):
   ```bash
   vehicle-scraper kb review worker                     # --propagate-idle 120 por defecto
   vehicle-scraper kb review worker --propagate-idle 0  # sin recalcular (solo aplicar)
   ```
   Tras `--propagate-idle` segundos sin decisiones nuevas corre `normalize` + `consolidate` (unos
   minutos con los datos completos); mientras tanto las decisiones nuevas esperan en cola. Toma el
   mismo candado que los comandos `kb`: nunca corren dos escritores a la vez.

## Uso

- **Cola** (`/cola`): casos pendientes en orden de revisión (nivel, individuales antes que muestra,
  más anuncios primero), con filtros por nivel, tipo de caso, entidad, marca y texto.
- **Caso** (`/cola/[id]`): propuesta, datos actuales, evidencia, valor publicado, cómo se reparten
  los anuncios y la lista de anuncios. Decisión: **Aprobar / Rechazar / Corregir** (el valor
  corregido se valida con el tipo y rango del campo). Atajos: `a`, `r`, `c`; `Ctrl+Enter` envía;
  `n` pasa al siguiente caso.
- **Decisiones** (`/decisiones`): historial con revisor, estado (`En cola`, `Aplicada`, `Falló`,
  `Ya decidido`) y el error si lo hubo.

## Seguridad

- Sin login por ahora: el sitio escucha solo en `127.0.0.1` y el revisor escribe su nombre (cookie
  `httpOnly`). `src/lib/reviewer.ts` (`getReviewer()`) es el único punto donde conectar SSO.
- El rol `kb_review_web` lee `kb`/`staging` y solo puede **insertar** decisiones (sin `status`):
  un error en el sitio no puede cambiar fichas ni identidades.
- Todo lo que llega del navegador se valida con Zod en el servidor (la Server Action se puede
  llamar por POST directo). Los filtros de la URL que no son válidos se descartan.
- Cabeceras: CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`.
- `.env.local` nunca se commitea.

## Desarrollo

```bash
pnpm lint && pnpm typecheck && pnpm test     # ESLint, tsc, Vitest (sin base de datos)
pnpm format                                  # Prettier
pnpm db:types                                # regenera src/generated/db.d.ts desde la base
KB_TEST_DATABASE_URL=postgresql://kb:kbtest@localhost:55432/kb pnpm test:e2e
```

- `pnpm test:e2e` (Playwright) recrea la base `kb_e2e_review` en ese servidor con
  `../../tests/e2e_review_web.py`, corre el worker real y un build de producción del sitio. En
  Windows usa Edge (sin descargar navegadores); en otros sistemas: `pnpm exec playwright install chromium`.
- `src/generated/kb-fields.json` (tipos, rangos y unidades de cada campo) lo genera Python:
  `python -m vehicle_scraper kb fields-json`. Un test de pytest falla si queda desactualizado.
- Next.js 16 cambia APIs respecto a versiones anteriores: antes de tocar código, lee la guía en
  `node_modules/next/dist/docs/` (ver `AGENTS.md`).
