# Vehicle Scraper

Scrapes car listings from several sites and normalizes them into **one schema**
(59 attributes: identity, technical specs, equipment & features), plus price,
currency and mileage. Each site has its own scraper. They all share the
label-mapping and unit-conversion layer, so the output columns are the same
for every site.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # edit USER_AGENT with your contact

python -m pytest                                       # offline tests (+ PostgreSQL ones, see below)
PYTHONPATH=src python -m vehicle_scraper sites         # list sites + status
PYTHONPATH=src python -m vehicle_scraper run --site carroya --site cofino --limit 20
```

(Or `pip install -e .` and use the `vehicle-scraper` command instead of `PYTHONPATH=src python -m vehicle_scraper`.)

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
# if script execution is blocked, run once: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

$env:PYTHONPATH="src"
python -m vehicle_scraper run --site carroya --limit 2000
```

Each run:
1. saves/updates records in `data/vehicles.sqlite` (one row per site + listing id; re-runs skip
   stored listings unless you pass `--refresh`),
2. exports `data/vehicles_<timestamp>.csv` (UTF-8 with BOM, so it opens in Excel with accents intact),
3. prints and writes `data/coverage.csv`: the % of listings with a value, for each field and site.

Other commands:

```bash
... run --all --limit 50              # every site
... run --site cars24 --browser       # render JavaScript pages with Playwright
... run --site cars24 --limit 50 --max-age 5   # only listings posted in the last 5 years (also 6m, 2w, 30d)
... export --format json --site carroya
... export --format xlsx               # vehicles table minus parse_warnings -> data/vehicles.xlsx
... coverage
```

## Site status (checked 18 Nov 2026)

| Site | Country | Status | How it works |
|---|---|---|---|
| **carroya.com** | Colombia | ✅ verified | Public JSON API behind the site: search `find-filters` → detail `find-vehicle-detail/<id>` with full technical sheet + accessories. Best coverage. |
| **cofinousados.com** | Guatemala | ✅ verified | `sitemap.xml` (~240 cars) → schema.org JSON-LD + "Detalles del auto" list. Few specs, no equipment list. JSON-LD says MXN but prices are quetzales, so currency is forced to GTQ. |
| **tucarro.com** | CO / VE | 🔑 needs token | Only a country picker for Mercado Libre's tucarro.com.co / .com.ve, whose pages show an *account-verification* wall to bots. Uses the **official Mercado Libre API** instead. Set `ML_ACCESS_TOKEN` and `ML_SITE_ID` (MCO or MLV). |
| **chileautos.cl** | Chile | ⛔ blocked by site | Every page returns a DataDome CAPTCHA. The scraper detects it and skips the site. Ask carsales.com (owner) for a data feed. The parser is ready if access is granted. |
| **cars24.com** | India | ❓ unverified | Cloudflare returned 403 from Central America (likely geo-restricted). Generic pipeline (JSON-LD + `__NEXT_DATA__` + HTML) with `--browser`. Try from India or request a partner feed. |

The scraper **never bypasses** CAPTCHAs, Cloudflare challenges or login walls. When it
detects one, it stops that site and reports `blocked: …` in the run summary.

### Getting a Mercado Libre token (TuCarro)
1. Create an app at <https://developers.mercadolibre.com> (Colombia: developers.mercadolibre.com.co).
2. Follow the OAuth flow to get an `access_token` (tokens expire after 6 h; use the refresh token).
3. Put it in `.env` as `ML_ACCESS_TOKEN=...`. The search API returns at most ~1000 results per
   query. To go deeper, pass filters: `TuCarroScraper(extra_params={"BRAND": "..."})`.

## Output schema

Defined in `src/vehicle_scraper/models.py` (Pydantic `VehicleRecord`). Units:

| Field | Unit | | Field | Unit |
|---|---|---|---|---|
| engine_displacement_l | L | | fuel_economy_kml | km/L |
| horsepower_hp | hp | | ev_range_km | km |
| fuel_tank_capacity_l | L | | ev_charging_speed_kw | kW |
| cargo_capacity_l | L | | wheel_size_in / screen_size_in | in |

Enums: `fuel_type` Gasoline/Diesel/Hybrid/EV/CNG (bi-fuel and LPG stay null) · `transmission_type` Manual/Automatic/CVT/DCT ·
`drivetrain` FWD/RWD/AWD/4WD/2WD · `body_style`/`vehicle_type` SUV/Sedan/Pickup/Hatchback/Coupe/Van/...
(`vehicle_type` can also be `Motorcycle`, set from a site's own category, e.g. CarroYa's "Motos")

**Normalization rules**
- Missing or unknown → `null`. A feature is set to `false` only when the site explicitly says
  so (e.g. "Sunroof: No", or `N` in CarroYa's technical sheet). A feature that simply isn't listed stays `null`.
- Free text (seller comments) can only set features to `true`. It skips negated mentions like "sin sunroof".
- Units are converted automatically: cc→L, gallons→L, mpg / L/100 km→km/L, cu ft→L, miles→km, kW/CV→hp.
- Colombian quirks: "Modelo: 2010" is treated as the year, "Cilindraje 2.700" as 2.7 L, and "wagon" as SUV.
- `4x2`/`2WD` doesn't say front or rear, so `drivetrain` is `2WD`, never guessed as FWD or RWD.
- On an EV, an engine size (`0.0 L`, or a motor description like "Motor sincrónico") means
  "no combustion engine", so it stays null with no warning.
- An explicit unit next to the number wins: "1.5 L (1.496 cc)" is 1.5 L, "10 HP (7.5 kW)" is 10 hp.
- If no spec gives the engine size, an explicit `d.d` token in the title/trim is used ("1.4 LS" → 1.4 L).
- Motorcycles accept small engines and keep exact cc (125 cc → 0.125 L); body_style stays null.
- Rim and tire sizes typed under each other's label are swapped back ("Llantas: R16" → 16" rim).
- Vague body values ("Deportivo" → Coupe) are used only when no other source gives a body style.
- Anything that couldn't be parsed is listed in `parse_warnings`.
- Personal data (plates, seller names, phones, emails) is never stored.

## Adding a site

**Fastest: scaffold it from a URL.**

```bash
PYTHONPATH=src python -m vehicle_scraper new-site https://www.example-autos.com/usados --dry-run
PYTHONPATH=src python -m vehicle_scraper new-site https://www.example-autos.com/usados --country CR --currency CRC
```

The URL can be a listing page, a car's page or the homepage. The command:

1. Probes the site politely (robots.txt, crawl delay, block detection). If it hits a CAPTCHA or a
   robots.txt rule, it stops and generates nothing.
2. Finds listings from the sitemap or from the paginated listing pages, and infers the
   detail-URL and listing-id regexes.
3. Parses 1–3 sample cars to see where the specs are: JSON-LD, embedded JSON, or the HTML section
   that holds them.
4. Writes:
   - `sites/<name>.py`, a dedicated scraper with its own `parse()` for you to refine;
   - the import line in `sites/__init__.py`;
   - `tests/fixtures/<name>_detail.html`, with contact details blanked;
   - `tests/test_site_<name>.py`, a snapshot test.

It then prints a report showing which fields the samples filled, the labels it couldn't map, and
any warnings (wrong currency, JS-rendered page → retry with `--browser`). Other options:
`--name`, `--force`, `--dry-run`. New sites start as `unverified`.

**Option A: YAML, no code.** Add an entry to `config/sites.yaml` with either a sitemap
(`sitemap_url` + `sitemap_pattern`) or paginated listing pages (`page_url_template` +
`link_pattern`). The generic pipeline reads JSON-LD, embedded JSON and HTML spec tables.

**Option B: a dedicated scraper**, for sites with an API or unusual markup. Create
`src/vehicle_scraper/sites/<name>.py`, subclass `SiteScraper` (or `HtmlSiteScraper`), and
implement `discover()` and `parse()`. Decorate the class with `@register` and import it
in `sites/__init__.py`. `cofino.py` (≈50 lines) and `carroya.py` are good templates.

**New labels or languages:** add regexes to `LABEL_RULES` (label → field) or
`FEATURE_PATTERNS` (equipment keywords) in `mapping.py`, then add a test case in
`tests/test_mapping.py`.

Workflow for a new site: run it with `--limit 5 -v`, then check `coverage.csv` and the
`parse_warnings` column. Set `SAVE_RAW=true` to keep the parsed records for debugging.

## Project layout

```
src/vehicle_scraper/
  models.py      VehicleRecord schema (+ column order)
  normalize.py   number parsing, unit conversion, enum/boolean normalization
  mapping.py     ES/EN label rules, feature keywords, RecordBuilder
  extract.py     JSON-LD, HTML label/value pairs, embedded JSON, anti-bot detection
  http.py        polite client: robots.txt, crawl delay, retries, Playwright fallback
  storage.py     SQLite upsert + CSV/JSON/Excel export
  report.py      field-coverage report
  cli.py         command line
  scaffold.py    `new-site`: probe a site from a URL and generate its scraper + test
  sites/         one module per site + generic YAML-driven scraper
  kb/            knowledge base in PostgreSQL (see below)
src/web/         review website (Next.js): human decisions on the knowledge base
config/sites.yaml  extra sites without code
config/kb/makes.yaml  curated list of makes for the knowledge base
migrations/      Alembic migrations of the knowledge base
docs/            data dictionary + ER diagram (diccionario_datos.md), SQL for the site's DB role
tests/           offline tests with fixtures captured from the real sites
```

## Knowledge base (PostgreSQL)

Turns the scraped listings into a catalog: **make → model → trim → variant** (year + engine +
fuel + transmission + drivetrain). Each value carries its source and confidence, so a vehicle's
specs can be looked up without a third-party service, and every listing can be exported in the
strict schema with its gaps filled. `data/vehicles.sqlite` is only ever read (read-only mode).

```bash
pip install -e .[kb]            # Windows behind an inspecting proxy: uv pip install --native-tls -e .[kb]
export KB_DATABASE_URL=postgresql://user:pass@host:5432/vehicles_kb

alembic upgrade head                            # migrations, by hand (or: vehicle-scraper kb migrate)
alembic -x url=postgresql://... downgrade base  # undo everything (drops the kb and staging schemas)

vehicle-scraper kb import --sqlite data/vehicles.sqlite   # idempotent; keeps each listing's history
vehicle-scraper kb normalize                    # rules: makes, models, trims, years (no AI, no cost)
vehicle-scraper kb consolidate                  # variants, consensus, cross-checks, published sheets
vehicle-scraper kb ai-identity --estimate       # Claude batch: price it first (sends nothing)
vehicle-scraper kb ai-identity --submit --confirm   # spends money; then --collect
vehicle-scraper kb ai-specs --estimate --min-listings 3
vehicle-scraper kb review export --out data/review.csv  # fill `decision` in Excel
vehicle-scraper kb review import data/review.csv --reviewer ana
vehicle-scraper kb worker                       # applies decisions + runs jobs from the review website
vehicle-scraper kb golden sample / golden score FILE    # measure identity accuracy
vehicle-scraper kb export --format xlsx [--with-sources]
vehicle-scraper kb status
```

**Data model.** `staging` keeps every imported listing version (a new version only when its
content changes). `kb` holds `make`/`model`/`trim` (+ `*_alias` tables: a new spelling adds an
alias, never a duplicate), `variant`, the mechanical sheet `variant_spec` (shared across
countries), the equipment sheet `variant_market_spec` (one per country), `spec_evidence`
(provenance of every value), `spec_history`, `review_item`/`review_batch`, `ai_run`/`ai_decision`,
`listing`/`listing_cluster`, and the views `listing_standardized` and `training_safe_evidence`.

**Rules.**
- Conflicts are solved top-down: make → model → trim/year → variant → mechanical → equipment,
  each through *rule → AI proposal → human decision*. A model with open identity questions
  waits; the others move on.
- Published value precedence: human > listing consensus > single listing > neighbouring years
  > AI. A human value is never replaced automatically: contradicting evidence opens a review case.
- Mechanical values: one plausible listing is enough (confidence 0.6), two or more agreeing
  (≥ 70 %) give high confidence. Equipment needs two or more listings of that country with
  ≥ 70 % agreement (one car may have an option fitted).
- Cross-checks only flag, never correct: motorcycle name number vs cc (BMW G 310 at 1.0 L),
  trim "1.8" vs displacement, EV with an engine size, hp per litre, seats vs body, outliers
  within a model.
- The same car on two portals (or reposted) counts as one vote (same model/year, mileage ±2 %,
  price ±5 %, dates within 30 days); a person can undo a cluster.
- AI (Claude Opus 5.5, Message Batches): only text from sites with `kb.source_site.ai_allowed`
  is sent — **Cofino is excluded** (`ai-train=no`). Every AI value starts `pending_review`:
  critical fields one by one, the rest by sampling (≥ 95 % correct in a stratified sample →
  the batch's values with confidence ≥ 0.8 become `accepted_sampled`). Identical requests are
  never resent (`input_hash`).

**Review website (`src/web`).** The same human decisions as the CSV, on a web page: the queue in
review order, each case with its evidence and listings, and *approve / reject / correct* with
the corrected value checked against the field's type and range. The site only queues decisions
in `kb.review_decision`; `vehicle-scraper kb review worker` applies them with the same code as
`kb review import` (Postgres `LISTEN/NOTIFY`, within a second) and, after a quiet period, runs
`normalize` + `consolidate` so the next level of cases appears. From **Tareas** the site also
queues `kb` commands (recalculate, export with download, AI estimate/collect) that the same worker
runs, and **Estado** shows what `kb status` shows. Sending a batch to Claude from the site is off
unless both `KB_WEB_AI_SUBMIT` (site) and `KB_ALLOW_WEB_AI_SUBMIT` (worker) are `true`, and then it
asks for the estimated amount. Every submission, from the site or the CLI, must also fit the
spending limit `KB_AI_BUDGET_USD` per `KB_AI_BUDGET_PERIOD` (daily, weekly or monthly) in `.env`;
without it nothing is sent. The site connects with its own role (`docs/sql/review_web_role.sql`
+ `review_web_grants.sql`) that can read the knowledge base and only insert decisions and jobs. No login yet: it listens on 127.0.0.1 only and the reviewer types their name. Setup
and commands: [`src/web/README.md`](src/web/README.md).

**Tests against PostgreSQL** run when `KB_TEST_DATABASE_URL` points to a server where the user
can create databases (each test makes and drops its own):

```bash
docker run -d --name vehicle-kb-test -e POSTGRES_USER=kb -e POSTGRES_PASSWORD=kbtest -p 55432:5432 postgres:16-alpine
KB_TEST_DATABASE_URL=postgresql://kb:kbtest@localhost:55432/kb python -m pytest tests/test_kb_pg.py
```

## Responsible use
- `robots.txt` is checked before every request, with a default 2 s per-host delay and
  `Crawl-delay` respected. Keep `USER_AGENT` honest and include a contact.
- cofinousados.com's robots.txt allows crawling but sets `ai-train=no`. Don't use that data
  to train models.
- Check each site's Terms of Service before scraping at scale. Prefer official APIs and feeds
  where they exist.
