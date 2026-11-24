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

# knowledge base (PostgreSQL "omnibase", optional extra: pip install -e .[kb]); URL from OMNIBASE_DATABASE_URL
PYTHONPATH=src python -m vehicle_scraper kb migrate                     # or: alembic upgrade head
PYTHONPATH=src python -m vehicle_scraper kb import --sqlite data/vehicles.sqlite
PYTHONPATH=src python -m vehicle_scraper kb clean                       # makes, models, trims, fields + review cases
PYTHONPATH=src python -m vehicle_scraper kb build                       # generations, powertrains, variants (after clean)
PYTHONPATH=src python -m vehicle_scraper kb status
# re-extract only some listings after a parser fix (one id per line; ask before running)
PYTHONPATH=src python -m vehicle_scraper run --site driveway --ids-file data/reextract/ids.txt
# kb tests against a throwaway Postgres (they drop the schemas; never point them at omnibase)
OMNIBASE_TEST_DATABASE_URL=postgresql://postgres:test@localhost:55441/omnibase_test python -m pytest tests/test_kb_pg.py
```

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

## Knowledge base (`kb/`, PostgreSQL `omnibase`)

Open items are tracked in `docs/kb-pendientes.md` (keep it current). Being built in phases toward three levels: generation (per body style, global years) →
powertrain → commercial variant per country and trim, with structured evolution notes.
So far (migrations `0001_catalogs_staging` … `0006_three_levels`):
- **The database is created by its owner.** Code only creates objects, through Alembic
  (`kb/migrations/`, `alembic.ini` at the root); `downgrade base` drops the `kb` and `staging`
  schemas. `alembic_version` stays in `public`.
- `kb`: closed catalogs (`country`, `vehicle_class`, `fuel_type`, `transmission_type`,
  `drivetrain`, `body_style`, `segment`, `headlight_type`, `brake_type`), each
  `code`/`name_es`/`name_en`. Segments: cars A-F (body style is a separate axis, so "SUV
  segment B" = SUV + B), pickups their own (`PickupCompact`/`Midsize`/`Fullsize`, with
  `body_style_code = 'Pickup'`), motorcycles their own; `vehicle_class_code` says which. Codes for fuel/transmission/drivetrain/body are exactly the
  `models.py` values (`tests/test_kb_catalogs.py` fails when they drift, so add a migration).
  `source_site` holds each site's country and `ai_allowed`/`training_allowed`, all false until
  the site's terms are reviewed (Cofino must stay false).
- `staging.raw_listing`: each vehicles.sqlite row as read (`data` jsonb), opened read-only; a
  new version only when `row_hash` (sha256 without `scraped_at`) changes. Rows from sites not
  in `kb.source_site` are skipped and reported, never imported with a guessed country.
- Writers take `db.take_writer_lock` (transaction-scoped advisory lock); each command is one
  transaction. Seed values are frozen in the migration, never imported from live code; a new
  catalog value goes in a new migration's `CATALOG_ADDITIONS` (read by the catalog test).
- `kb clean` (`kb/clean.py`, helpers in `kb/identity.py`, make list `config/kb/makes.yaml`)
  rebuilds `kb.clean_listing` from the current staging versions:
  - Makes by spelling-insensitive alias (`compact_key`); a make not in makes.yaml becomes
    `pending_review` + `unknown_make`. The make's `class` decides scope: heavy, machinery,
    golf_cart, bicycle, trailer, atv are excluded with a `kb.exclusion_reason`; so are ATV
    names, motocarros/mototaxis (`ThreeWheeler`, migration 0005), heavy trucks (body Truck that isn't a chassis cab), and model years outside
    1990 .. current year + 1. Excluded listings keep their row. Chassis cabs count as Pickup.
  - `split_tokens` moves mechanical words out of model/trim names ("Touring 2.0 Suv Automatico
    4x2" -> "Touring" + 2.0 L, SUV, Automatic, 2WD). Plain-number models stay (Ram 1500,
    Mazda 3); a model of only a displacement ("1.3") opens `model_is_attributes`.
  - New model names: accepted with >= 5 listings or >= 2 sites, else `weak_model`. Model
    families split by the version's number (`split_models` in makes.yaml: Duke + "390").
  - The listing's structured field wins over a word in its name; a disagreement opens
    `field_conflict` (4x4 vs AWD and 4x2 vs FWD/RWD are not disagreements). A name only
    refines a generic value: Automatic + "CVT" -> CVT, 2WD + "FWD" -> FWD
    (provenance `trim_text_refines_listing`). Implausible values stay and open a case.
  - `kb.review_item`: one row per case for good (decided cases are never asked again; pending
    ones the rules stop seeing become `obsolete`, but only for the issues of the command that
    opened them: `clean.write_cases(cur, cases, ISSUES)`). Decided `unknown_make`/`weak_model`
    set the make/model status with `source = 'manual'`, which the rules never change.
- `kb build` (`kb/build.py`, field placement in `kb/levels.py`) builds the three levels from
  in-scope listings of accepted models:
  - `kb.generation` starts `provisional`, one per model + body (observed years); `year_from`/
    `year_to` are the official cycle. A listing without body joins its model's only generation.
    Engine changes between years open `generation_split` (a person decides; an approved split
    cuts the generation at that year, `split_from`). A trigger checks the segment against the
    model's class and the body (pickups need pickup segments).
  - `kb.powertrain` keyed by fuel|transmission|drivetrain|displacement|cylinders (`match_key`,
    frozen; cylinders only without displacement). Keys go most complete first; a key joins the
    only compatible powertrain (Automatic~CVT/DCT, 2WD~FWD/RWD, AWD~4WD, 0.1 L), creates one if
    none, and stays `ambiguous_powertrain` if several. Never guessed.
  - `kb.commercial_variant` = generation + powertrain + country + `trim_key` (`''` = trim
    unknown, kept apart). `kb.listing_level` says where each listing landed or why not.
  - `kb.spec_evidence` holds candidates per entity/field/source; listing evidence is recomputed
    each run (mechanical: 1 plausible listing, most repeated, >10 % spread opens
    `spec_disagreement`; equipment: >= 2 listings and >= 70 %), other sources are never
    touched. Level columns are **derived**: the best accepted evidence wins (manual > external >
    listings > ai), so change a value by adding evidence, never by editing the column.
  - Year-consistent equipment flips open `evolution_note`; an approved one becomes a
    `kb.evolution_note` (field, value, year_from).

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
