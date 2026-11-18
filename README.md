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

python -m pytest                                       # 28 offline tests
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
... export --format json --site carroya
... export --format xlsx               # every column of the vehicles table -> data/vehicles.xlsx
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

Enums: `fuel_type` Gasoline/Diesel/Hybrid/EV · `transmission_type` Manual/Automatic/CVT/DCT ·
`drivetrain` FWD/RWD/AWD/4WD/2WD · `body_style`/`vehicle_type` SUV/Sedan/Pickup/Hatchback/Coupe/Van/...

**Normalization rules**
- Missing or unknown → `null`. A feature is set to `false` only when the site explicitly says
  so (e.g. "Sunroof: No", or `N` in CarroYa's technical sheet). A feature that simply isn't listed stays `null`.
- Free text (seller comments) can only set features to `true`. It skips negated mentions like "sin sunroof".
- Units are converted automatically: cc→L, gallons→L, mpg / L/100 km→km/L, cu ft→L, miles→km, kW/CV→hp.
- Colombian quirks: "Modelo: 2010" is treated as the year, "Cilindraje 2.700" as 2.7 L, and "wagon" as SUV.
- `4x2`/`2WD` doesn't say front or rear, so `drivetrain` is `2WD`, never guessed as FWD or RWD.
- An engine size of `0.0 L` on an EV means "no combustion engine", so it stays null with no warning.
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
config/sites.yaml  extra sites without code
tests/           offline tests with fixtures captured from the real sites
```

## Responsible use
- `robots.txt` is checked before every request, with a default 2 s per-host delay and
  `Crawl-delay` respected. Keep `USER_AGENT` honest and include a contact.
- cofinousados.com's robots.txt allows crawling but sets `ai-train=no`. Don't use that data
  to train models.
- Check each site's Terms of Service before scraping at scale. Prefer official APIs and feeds
  where they exist.
