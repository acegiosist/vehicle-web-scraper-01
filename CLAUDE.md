# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Scrapes car listings from several sites and normalizes them into **one schema** (59 attributes:
identity, technical specs, equipment & features, plus price/currency/mileage), defined in
`src/vehicle_scraper/models.py` as a Pydantic `VehicleRecord`. Every site scraper feeds the same
label-mapping and unit-conversion layer so output columns line up across sites.

## Commands

```bash
# setup
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # edit USER_AGENT with a real contact

# tests (offline, run against fixtures in tests/fixtures/, no network)
python -m pytest
python -m pytest tests/test_mapping.py                 # single file
python -m pytest tests/test_mapping.py::test_name -v   # single test

# running the scraper (needs PYTHONPATH=src unless installed with `pip install -e .`)
PYTHONPATH=src python -m vehicle_scraper sites                      # list sites + status
PYTHONPATH=src python -m vehicle_scraper run --site carroya --limit 20
PYTHONPATH=src python -m vehicle_scraper run --all --limit 50 --refresh
PYTHONPATH=src python -m vehicle_scraper run --site cars24 --browser   # Playwright-rendered pages
PYTHONPATH=src python -m vehicle_scraper run --site cars24 --limit 50 --max-age 5   # posted in last 5y (6m, 2w, 30d)
PYTHONPATH=src python -m vehicle_scraper export --format json --site carroya
PYTHONPATH=src python -m vehicle_scraper export --format xlsx   # stdlib-only writer in xlsx.py
PYTHONPATH=src python -m vehicle_scraper coverage
PYTHONPATH=src python -m vehicle_scraper new-site <url> [--name --country --currency --browser --force --dry-run]

# knowledge base (PostgreSQL, optional extra: pip install -e .[kb]); URL from KB_DATABASE_URL
alembic upgrade head                                   # or: ... kb migrate ; undo: alembic downgrade base
PYTHONPATH=src python -m vehicle_scraper kb import --sqlite data/vehicles.sqlite
PYTHONPATH=src python -m vehicle_scraper kb normalize && PYTHONPATH=src python -m vehicle_scraper kb consolidate
PYTHONPATH=src python -m vehicle_scraper kb ai-identity --estimate     # --submit --confirm spends money
PYTHONPATH=src python -m vehicle_scraper kb review export --out data/review.csv
PYTHONPATH=src python -m vehicle_scraper kb status
KB_TEST_DATABASE_URL=postgresql://kb:kbtest@localhost:55432/kb python -m pytest tests/test_kb_pg.py   # needs a Postgres
PYTHONPATH=src python -m vehicle_scraper kb worker                   # applies decisions + runs jobs queued by the review site

# review website (src/web, Next.js; needs src/web/.env.local with REVIEW_WEB_DATABASE_URL)
cd src/web && pnpm install && pnpm dev                 # http://127.0.0.1:3000
cd src/web && pnpm lint && pnpm typecheck && pnpm test # ESLint, tsc, Vitest (no database)
cd src/web && KB_TEST_DATABASE_URL=postgresql://kb:kbtest@localhost:55432/kb pnpm test:e2e   # Playwright: real worker + prod build
PYTHONPATH=src python -m vehicle_scraper kb fields-json # regenerate src/web/src/generated/kb-fields.json after models.py changes
```

What each `kb` command does, with its flags: see "Knowledge base commands" below.

There is no lint/format command configured in this repo.

## Architecture

**Pipeline, per listing:** `discover()` yields a `Listing(listing_id, url, payload)` → `parse()`
fetches/reads it and builds a `VehicleRecord` → `cli.run_site` stores it (SQLite, skipping
already-stored listings unless `--refresh`) → at the end of a run, CSV export + a per-field
coverage report are written.

**Listing age (`run --max-age`)** filters on `Listing.listed_at` (when the listing was posted,
UTC), not on `model_year`. `discover()` sets it when known up front — CarroYa's `clfechapub`, or
the sitemap `<lastmod>` via `SiteScraper.sitemap_entries` — so old listings are skipped without
fetching; `parse()` may overwrite it (TrueCar's page `listedAt`). `run_site` stores it in the
record's `listed_at` column (a metadata field, like `scraped_at`). Listings with no date at all
aren't saved under `--max-age`, and `--limit` then counts only listings that pass.
`run_site` also sets `scraper.listed_since` to the cutoff before `discover()`, so a site whose
discovery is sorted newest-first (Driveway, by `inventoryDate`) stops paging once it reaches it.

**Two ways a site is implemented**, both registered in a shared `REGISTRY` (`sites/base.py`):
- A **dedicated scraper** (`sites/carroya.py`, `cofino.py`, `tucarro.py`, `chileautos.py`,
  `cars24.py`) subclasses `SiteScraper` and implements `discover()`/`parse()` directly — for
  sites with a JSON API (CarroYa, TuCarro via the official Mercado Libre API) or markup the
  generic pipeline can't handle.
- A **config-only site** in `config/sites.yaml` is turned into a `GenericScraper` subclass at
  load time (`sites/__init__.py:load_yaml_sites`, called from `cli.main`) via
  `GenericScraper.from_config`, with YAML keys becoming class attributes
  (`sitemap_url`/`sitemap_pattern` or `page_url_template`/`link_pattern`, etc.). No Python needed.
- Both discovery styles (sitemap vs. paginated listing pages) and the JSON-LD → embedded-JSON →
  HTML-table parsing chain live in `sites/html_site.py:HtmlSiteScraper`, which the dedicated
  scrapers typically also subclass/reuse rather than reimplement.

**Extraction → mapping → normalization is a strict pipeline**, and understanding any one site
means following a value through all three layers:
1. `extract.py` pulls raw `(label, value)` pairs and feature-list items out of a page/JSON blob:
   `jsonld_vehicles`/`apply_jsonld` (schema.org Car), `embedded_json`/`walk_json_pairs`
   (`__NEXT_DATA__`/`window.__STATE__`-style blobs), `html_pairs`/`html_feature_items` (`<dl>`,
   2-cell `<tr>`, label:value text, equipment `<li>` lists). It also hosts `detect_block`, which
   raises on a CAPTCHA/Cloudflare/Mercado-Libre-verification page.
2. `mapping.py:RecordBuilder` is what every scraper feeds pairs/features/free-text into, in order
   from most to least reliable (structured API/JSON first, then HTML spec tables, then feature
   lists, then free text) — **first value set for a field wins**, later sources never overwrite
   it. `match_label` (regex table `LABEL_RULES`, Spanish+English, first match wins — order
   matters) maps a label string to a schema field; `match_features` (regex table
   `FEATURE_PATTERNS`) matches equipment keywords, with negation handling (`"sin sunroof"` must
   not set `sunroof=True`). `RecordBuilder.build()` does cross-field cleanup (e.g. clears EV fields
   on non-EV/non-Hybrid records, combines tire+rim into a tire size string) and finally constructs
   the `VehicleRecord`.
3. `normalize.py` holds every unit conversion and parser (`to_hp`, `to_liters`, `to_km`, `to_kml`,
   `to_bool`, enum matchers like `to_fuel`/`to_body`/`to_drivetrain`, `parse_number`'s ES/EN
   thousands-separator handling). **Every function returns `None` on anything it can't confidently
   parse — nothing is guessed**, and unparseable values are recorded in `VehicleRecord.parse_warnings`
   instead of silently dropped.

**Networking goes through `http.py:PoliteClient`** for every site: it checks `robots.txt`
(`DisallowedError` if disallowed), applies a per-host crawl delay (`Crawl-delay` or
`REQUEST_DELAY_SECONDS`, whichever is larger), retries 5xx/429 with backoff, and calls
`extract.detect_block` on every response — raising `BlockedError` on a CAPTCHA/Cloudflare/login
wall. **The scraper never bypasses these; it stops the site and reports `blocked: ...`** in the
run summary (see `cli.run_site`). `client.render()` is the Playwright fallback for JS-rendered
pages, only used when `USE_BROWSER=true` or `--browser`.

**Normalization rules worth knowing before touching `mapping.py`/`normalize.py`:**
- Missing/unknown → `null`. A boolean feature becomes `false` only when a site explicitly says so;
  a feature that's simply not listed stays `null` (free text can only ever set a feature to `true`).
- Units are auto-converted: cc→L, gallons→L, mpg/L per 100km→km/L, cu ft→L, miles→km, kW/CV→hp.
- `4x2`/`2WD` is ambiguous (front- or rear-wheel), so `drivetrain` is `2WD` (its own enum value)
  instead of guessing FWD/RWD. Unparseable displacement on an EV stays `null` without a warning.
- `vehicle_type = "Motorcycle"` is only ever set explicitly by a scraper (carroya's category "Motos"),
  and it must be set first: `RecordBuilder.set` then uses `MOTO_CONVERTERS` (from 50 cc / 3 hp,
  3-decimal litres). `add_title` also reads a `d.d` displacement token as a last-resort fallback.
- Colombian-market quirks are handled explicitly: `"Modelo: 2010"` is the model year (not literally
  the model), `"Cilindraje 2.700"` means 2.7 L.
- Personal data (plates, seller names, phones, emails) is never captured into the schema.

**Scaffolding a site:** `new-site <url>` (`scaffold.py`) probes the site through `PoliteClient`
and infers discovery: a sitemap first, then listing-page links plus pagination. URLs are grouped
by path shape in `url_groups`. It locates the spec section on a sample page (`find_spec_section`:
a stable id, a heading, or a non-utility class) and renders a dedicated `HtmlSiteScraper`
subclass with an explicit `parse()`. It also writes a cleaned fixture and a snapshot test, and
edits the `from . import ...` line in `sites/__init__.py`. The generated module is exec'd
offline against the samples (`load_module_class`, which leaves `REGISTRY` untouched) to build
the snapshot, so the generated test matches what the generated code really produces.

**Adding a site:** prefer Option A (a `config/sites.yaml` entry, no code) when the site has a
sitemap or simple paginated listings and exposes JSON-LD/embedded JSON/HTML spec tables — see the
commented examples already in that file. Use Option B (a dedicated module in `sites/`,
`@register`-decorated, imported in `sites/__init__.py`) only when a site needs its own
discovery/auth (API token, unusual markup) — `cofino.py` is the shortest template. New
label/feature synonyms go in `mapping.py`'s `LABEL_RULES`/`FEATURE_PATTERNS` with a matching case
in `tests/test_mapping.py`. Workflow: run the new site with `--limit 5 -v`, then check
`data/coverage.csv` and the `parse_warnings` column; set `SAVE_RAW=true` to keep parsed JSON for
debugging.

**Knowledge base (`kb/`, PostgreSQL).** A second pipeline on top of the scraper's output:
`importer.py` (vehicles.sqlite, opened read-only → `staging.raw_listing`, a new version only when
`row_hash` changes) → `identity.py` (`kb normalize`: aliases by `compact_key`, seed
`config/kb/makes.yaml`, `split_model`/`split_trim` strip attribute tokens, weak models/unknown makes
become `review_item`s) → `consensus.py` (`kb consolidate`: variants, cross-portal clusters, listing
evidence, cross-checks, publish to `variant_spec`/`variant_market_spec`) → `ai_batch.py` +
`prompts.py` (Claude Opus 5.5 via Message Batches) → `review.py` (CSV round-trip, sampling).
Invariants worth keeping:
- Everything is idempotent and goes through alias tables + `UNIQUE` keys: re-running never
  duplicates; listing-derived evidence is recomputed, AI/manual evidence is never touched by
  `consolidate`. `identity.open_review` refreshes an open case, but a case with an
  `ai_decision_id` keeps its AI `source` and `kind` when the rules re-open it.
- Precedence `RANK` in consensus.py: manual > listing_consensus > listing_single > sibling > AI. A
  manual value is never replaced; conflicting evidence opens `conflicts_with_human`.
- Spending on Claude goes only through `commands.ai_submit`, which checks the budget
  (`budget.budget_status`) under the writer lock. Nothing from the AI is accepted without review; text from sites with `ai_allowed = false`
  (Cofino) must never reach a prompt. `--submit` needs `--confirm` (it costs money).
- Cross-checks flag (`pending_review` + review case), they never correct. A decided case
  (`_decision`) is not asked again.
- `fields.py` splits the schema (KEY/MECH/EQUIP); the migration freezes those column lists and
  `tests/test_kb_migrations.py` fails when models.py changes without a new migration.
- Prompts are byte-deterministic (sorted TSV, no dates) for prompt caching and `input_hash`
  memoization; bump `PROMPT_VERSION` when changing them.
- One writer at a time: every `kb` command except `status`/`export`/`golden`, and each cycle of
  the review worker, takes `db.writer_lock` (a transaction-scoped advisory lock).
- `kb/commands.py` holds the commands the CLI and the worker share (normalize, consolidate,
  recalculate, export, AI estimate/submit/collect). The CLI only prints their `summary`.
- `review.decide_item` is the **only** path that applies a human decision (CSV import and the
  worker both call it). A correction that doesn't fit its field raises `InvalidValue` and leaves
  the case pending (`invalid_value`), it is never silently dropped.

**Review website (`src/web`, Next.js 16 App Router + Kysely + Zod).** Human decisions on the
web instead of the CSV. The site reads `kb.review_queue` (migration 0002: each case with a
readable `entity_label`, make/model, `in_queue`) and only INSERTs into `kb.review_decision`,
through the least-privilege role in `docs/sql/review_web_role.sql`. An AFTER INSERT trigger
NOTIFYs `kb_review_decision`; `kb/worker.py` (`kb review worker`) applies each queued decision
with `decide_item` in its own savepoint (`applied` / `failed` + error / `superseded`), closes
sample batches, and after `--propagate-idle` quiet seconds runs normalize + consolidate.
**Jobs** (migration 0003): `/tareas` INSERTs into `kb.job` (whitelisted `command` + `params`); the
worker claims one at a time (`running`, committed), runs `commands.py` under the writer lock and
commits the changes together with `done` + `summary`/`result` (exports go to `kb.job_file`, gzip
for csv/json, last 10 kept); any error rolls back and marks it `failed`. The site can only cancel
a queued job, through `kb.cancel_job()` (SECURITY DEFINER). `/estado` reads the same numbers as
`kb status` directly. The layout shows `AiRunNotice` on every page: runs `ended` (with "Recoger
resultados", an `ai_collect` job) and `submitted` ones (refreshed every minute while processing);
`/tareas` lists the latest runs. `/base` browses the whole knowledge base read-only (every `kb.variant`,
any status; filters make/model/year by id, LIMIT/OFFSET pagination); `/base/[id]` shows the
published `variant_spec`/`variant_market_spec`, all `spec_evidence` (the published one picked with
`lib/knowledge.ts:winningEvidence`, which mirrors `consensus.RANK`/`PUBLISHED` — keep them in sync),
open cases, `spec_history` and listings. **Sending to Claude from the site** needs `KB_WEB_AI_SUBMIT=true` (site, shows
the form) and `KB_ALLOW_WEB_AI_SUBMIT=true` (worker, the real guard); the worker also requires an
`ai_estimate` job finished < 60 min ago, the same request fingerprint, and `confirm_usd` ≥ the
estimate. The spending limit (`kb/budget.py`) applies on top, to the site and the CLI: the estimate
carries `budget` and the site disables "Enviar a Claude" with its message. Tests replace `worker._submit_fn`; never send a real batch without the user's approval.
Things to keep in sync:
- `src/web/src/lib/issues.ts` describes each `issue` and what approve/reject/correct do; it
  mirrors `apply_decision`. A new issue or a new effect needs both.
- `src/web/src/generated/kb-fields.json` comes from `kb fields-json` (`fields.fields_catalog`);
  `tests/test_kb_fields_json.py` fails when it is stale. `src/web/src/generated/db.d.ts` comes
  from `pnpm db:types` after a migration.
- The model correction markers (`merge:`, `split:`) are parsed in `review.apply_decision` and
  validated in `src/web/src/lib/decision-input.ts`; `queries/case.ts:splitPreview` approximates
  `identity.split_number` for the preview. Change them together.
- Job parameters are validated twice: `src/web/src/lib/jobs.ts` (Zod) and `worker.execute_job`.
  A new command needs both, plus the CHECK in the migration and `COMMAND_LABELS`.
- After a migration, re-run `docs/sql/review_web_grants.sql` (the site's role) and `pnpm db:types`.
- `kb.listing_number()` (SQL, sha256) and `identity.listing_number()` (Python) must agree.
- Next.js 16 with Cache Components: request data (`searchParams`, `cookies`, `usePathname`) and
  DB reads (`io()` in `lib/queries`) must sit inside `<Suspense>`. Read
  `src/web/node_modules/next/dist/docs/` before changing Next code (see `src/web/AGENTS.md`).

## Knowledge base commands (`vehicle-scraper kb ...`)

Defined in `kb/cli.py`. `--database-url` goes **before** the subcommand (default
`$KB_DATABASE_URL`). Every command except `migrate` runs in one transaction, so a failure
leaves nothing half-done, and all of them are safe to re-run (invariants above). Commands,
in pipeline order:

- **`migrate [REVISION] [--downgrade]`**: wraps `alembic -x url=... upgrade|downgrade`
  (default `head`). `--downgrade base` drops the `staging` and `kb` schemas. Revisions:
  `0001_kb_schema`, `0002_review_web` (decision inbox, `review_queue` view), `0003_web_jobs`
  (`job`, `job_file`, `cancel_job()`), `0004_queue_ai_origin` (`review_queue.from_ai`/`ai_run_id`),
  `0005_ai_run_cost` (`ai_run.actual_cost_usd`, `cache_write_tokens`), `0006_ai_run_batch_check`
  (`ai_run.batch_checked_at`, `batch_counts`; status `ended` = finished, not collected),
  `0007_model_split` (`model.split_by_number`, `split_from`).
- **`import [--sqlite data/vehicles.sqlite]`**: copies listings into `staging.raw_listing`,
  opening the file read-only.
  - A file whose sha256 was already imported is skipped.
  - A listing gets a new version only when its `row_hash` changes.
  - A site not yet in `kb.source_site` is registered with `ai_allowed` and
    `training_allowed` false. Review its terms, then UPDATE the row.
- **`normalize`**: rule-based identity (make, model, trim, year), free.
  - Resolves spellings through aliases (`compact_key`) and `config/kb/makes.yaml`.
  - `split_model`/`split_trim` move attribute tokens ("4X4", "Diesel", "2.8") to the variant.
  - Model families (`model.split_by_number`, set by a `split:` decision, or `split_models` in
    makes.yaml): a version starting with a 2-4 digit number sends the listing to "<family>
    <number>" (CarroYa "LV" + "150 Bus" = LV 150, trim "Bus"), created and accepted on demand
    with `split_from`; the family's variants (and their human/AI evidence) move along through
    `consensus.move_variants`. Listings without the number stay on the family.
  - What the rules can't settle becomes `pending_review` plus a `review_item`.
- **`consolidate [--min-support 2] [--min-agreement 0.7]`**: builds the spec sheets.
  - Builds variants, and clusters the same car across portals so it counts as one vote.
  - Votes each field. Mechanical fields accept one plausible listing; equipment needs
    `--min-support` listings in that country and `--min-agreement`.
  - Runs the cross-checks, then publishes `variant_spec`/`variant_market_spec` and logs
    every change to `spec_history`.
  - Models whose identity is still unresolved are counted as "waiting" and skipped.
- **`ai-identity` / `ai-specs`**: Claude Message Batches. Identity sends one request per
  make; specs sends one per model and country. Both are chunked. Exactly one mode is
  required:
  - `--estimate`: builds the requests and prints the cost, without sending anything.
    `--count-tokens` makes the count exact through the free `count_tokens` API, but it
    sends the text to Anthropic.
  - `--submit --confirm`: sends the batch. **It costs money**, so never run it without the
    user's approval. Refused (nothing sent, exit 2) when it doesn't fit the spending limit:
    `KB_AI_BUDGET_USD` per `KB_AI_BUDGET_PERIOD` (`daily` by default, `weekly`, `monthly`, in
    the machine's local time), re-read from `.env` on every submission. Spent = each run
    submitted in the period, at its real cost once collected (`ai_run.actual_cost_usd`) or its
    estimate until then. Without a valid limit nothing is sent.
  - `--collect [--run-id N]`: fetches the finished results (default: the latest `submitted`
    or `ended` run) and applies them. Identity results become review cases, individual or sampled.
    Spec results become `ai_knowledge` evidence in `pending_review`.
  - Other flags: `--makes Toyota,Mazda` (pilot), `--limit N`, and `--effort` (default `low`
    for identity, `medium` for specs). `ai-specs` also takes `--min-listings 3`.
  - Requests already answered are dropped by `input_hash`.
- **`review export [--out data/review.csv]`**: writes the open review cases as a CSV with
  a BOM, so Excel opens it correctly.
  - Rows are ordered by level (makes, models, trims, specs), then by listings unblocked.
  - Critical fields and identity changes are exported for individual review.
  - Other AI values are grouped into stratified sample batches of `--sample-size 50`
    (`--seed 20261120`).
  - `--min-accuracy 0.95` and `--min-confidence 0.8` set how a sample batch is decided;
    `--limit` caps the number of rows.
- **`review import PATH --reviewer NAME`**: applies the filled `decision` column (`approve`,
  `reject` or `correct`, with `corrected_value`) and records the reviewer.
  - A sample batch with ≥ 95 % correct turns its values with confidence ≥ 0.8 into
    `accepted_sampled`. Otherwise the whole batch is rejected.
  - A correction that doesn't parse or is out of range is counted as `invalid_value` and the
    case stays pending.
  - For a model, `corrected_value` may be a name, `merge:<existing model>`, or
    `split:[car|motorcycle|heavy]` (a family split by version number; optional class).
  - Then run `normalize` and `consolidate` to propagate the decisions.
- **`worker [--propagate-idle 120] [--poll 30] [--batch-check 300] [--once]`** (alias `review worker`): applies the
  decisions the review website queues in `kb.review_decision` and runs its jobs from `kb.job`
  (LISTEN/NOTIFY on both, plus a poll as a fallback). Decisions go first, then one job at a time.
  - Each decision goes through `decide_item` in a savepoint: `applied`, `failed` with the
    error, or `superseded` when the case was already decided.
  - Creates sample batches for newly applied AI runs, like `review export` does.
  - After `--propagate-idle` seconds without decisions it runs `normalize` + `consolidate`
    (minutes on the full data; queued decisions wait meanwhile). `0` turns it off.
  - `--once` applies the queue, runs the queued jobs (and propagates if a decision was
    applied), then exits.
  - On start it marks jobs left `running` by a stopped worker as `failed`.
  - Every `--batch-check` seconds (and on start; `0` = never), while some `ai_run` is
    `submitted`, it asks Anthropic for the batch status (`ai_batch.retrieve_batch`, a free read
    that needs `ANTHROPIC_API_KEY`; without it, it logs a warning once). A finished batch moves
    the run to `ended` with `ended_at` and `batch_counts`; the site then shows a notice on every
    page with "Recoger resultados" (an `ai_collect` job). It never collects by itself. Tests
    replace `worker._retrieve_fn`. `kb status` lists `ended` runs too.
  - `ai_submit` jobs are refused unless `KB_ALLOW_WEB_AI_SUBMIT=true`. The worker re-reads it
    from `.env` on every submission (`worker.ai_submit_allowed`), so no restart is needed to
    switch it; a value in `.env` wins over the process environment (`kb/settings.py`, also used
    for the spending limit, which `ai_submit` jobs must fit too).
- **`golden sample [--out data/golden_sample.csv] [--size 300] [--seed]`**: a random
  sample for the team to label, stratified by site, vehicle class and model frequency.
- **`golden score PATH`**: compares the validated labels with the pipeline. Targets: make
  and model ≥ 98 %, year ≥ 95 %, trim ≥ 90 %.
- **`export [--format csv|xlsx|json] [--out PATH] [--with-sources]`**: writes
  `kb.listing_standardized`, every listing in the strict schema with gaps filled from the
  knowledge base. The default output is `data/kb_listings.<format>`. `--with-sources` adds a
  `<field>__src` column per field, saying whether the value came from the listing or from
  the knowledge base.
- **`status`**: row counts per table, open review cases by level, and per-field coverage
  of the published sheets.
- **`fields-json [--out PATH]`**: writes the field catalog (type, group, unit, range, enum
  values) the review website validates corrections with. No database needed.

Typical order: `migrate` → `import` → `normalize` → `consolidate` → `review export` / `review
import` → `normalize` + `consolidate` → `export`. The `ai-*` commands go between `normalize`
and review, and only with the user's approval. With the review website, `kb worker` runs
instead of `review export`/`import`, propagates by itself, and runs the jobs queued on `/tareas`.

## Current site status (see README.md for the up-to-date table)

- **carroya.com** (Colombia) — verified, best coverage, uses the site's own JSON API.
- **cofinousados.com** (Guatemala) — verified via sitemap + JSON-LD; its `robots.txt` sets
  `ai-train=no`, so don't use its data to train models.
- **tucarro.com** (CO/VE) — blocked by an account-verification wall for bots; scraper instead uses
  the official Mercado Libre API and needs `ML_ACCESS_TOKEN`/`ML_SITE_ID` in `.env`.
- **chileautos.cl** (Chile) — blocked by a DataDome CAPTCHA on every page; scraper detects and
  skips it rather than solving the CAPTCHA.
- **cars24.com** (India) — unverified; Cloudflare 403s from outside India, likely geo-restricted.
- **driveway.com** (US) — unverified; uses two internal APIs its own pages call (public
  frontend key, `DRIVEWAY_API_KEY` overrides): the /shop search, sorted newest-first with
  `inventoryDate` as the listing date, and the car page's GraphQL query for the overview and
  equipment lists (no browser needed), 50 cars per GraphQL request (aliases). One search query
  pages through ~30k results at most (500 per page), so big groups are split by price; a run
  without `--limit` fetches the whole list up front. A full run takes about an hour.

## Git Commit & Push Workflow
When the user says "commit my changes" or "commit and push my changes", perform the following steps automatically:
1. Run `git status` and `git diff` (staged and unstaged) to inspect all changes.
2. Check for secrets, `.env` files, debug statements (`console.log`, `print`), or unrelated files. Do not stage or commit them.
3. Stage only the relevant files using `git add`.
4. Commit using the Conventional Commits format (`<type>(<optional scope>): <short summary>`):
   - Use standard types (`feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`).
   - Keep the subject line lowercase, imperative mood, and under 50 characters.
   - Add a concise body explaining *why* the change was made if the change is non-trivial.
5. **If the user specifically said "commit and push my changes"**:
   - Check the current branch (`git branch --show-current`).
   - If the branch is `main` or `master`, ask for confirmation before pushing.
   - Otherwise, run `git push` (or `git push -u origin <branch>` if no upstream is set).
6. Output the resulting commit hash, message, and current `git status`.
