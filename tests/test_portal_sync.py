"""The portal (TypeScript) repeats a few Python tables; these checks fail when one drifts.

* Review texts: review.ISSUES / CLASSES / ISSUE_ORDER  <->  src/portal/src/lib/issues.ts
* Roles: worker.ROLE_RANK / REQUIRED_ROLE              <->  src/portal/src/lib/auth/roles.ts
* Field labels: every level column (kb/levels.py)      ->   src/portal/src/lib/fields.ts
* Source precedence: levels.SOURCE_RANK               <->  fields.ts SOURCE_RANK
* Final record: final.SOURCES columns                  <->  final-listing.ts FINAL_SHEET_GROUPS
* Identity sheet: vehicle.VALUES                        <->  the same FINAL_SHEET_GROUPS
* Unassigned reasons: listing_level's check (latest migration) <-> final-listing.ts UNASSIGNED_REASONS
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

from vehicle_scraper.kb import final, levels, review, vehicle, worker

PORTAL = Path(__file__).resolve().parents[1] / "src" / "portal" / "src" / "lib"
ISSUES_TS = (PORTAL / "issues.ts").read_text(encoding="utf-8")
ROLES_TS = (PORTAL / "auth" / "roles.ts").read_text(encoding="utf-8")
FIELDS_TS = (PORTAL / "fields.ts").read_text(encoding="utf-8")
FINAL_TS = (PORTAL / "final-listing.ts").read_text(encoding="utf-8")


def _ts_string(text: str) -> str:
    """How a Python string looks inside the TS file (JS string literal contents)."""
    return text.replace("\\", "\\\\")


def test_review_texts_match():
    for issue, (what, approve, reject, correct) in review.ISSUES.items():
        block = re.search(rf"\n  {issue}: \{{(.*?)\n  \}}", ISSUES_TS, re.S)
        assert block, f"{issue} missing from issues.ts"
        body = block.group(1)
        for key, text in (("what", what), ("approve", approve), ("reject", reject), ("correct", correct)):
            m = re.search(rf"{key}:\s*(['\"])(.*?)\1,", body, re.S)
            assert m and m.group(2) == _ts_string(text).replace('"', '\\"' if m.group(1) == '"' else '"'), \
                f"{issue}.{key} differs between review.py and issues.ts"
    order = re.search(r"ISSUE_ORDER = \[(.*?)\]", ISSUES_TS, re.S).group(1)
    assert re.findall(r'"(\w+)"', order) == review.ISSUE_ORDER
    classes = re.search(r"MAKE_CLASSES = \{(.*?)\}", ISSUES_TS, re.S).group(1)
    assert re.findall(r"\n\s+(\w+):", classes) == list(review.CLASSES)


def test_roles_match():
    roles = re.search(r"ROLES = \[(.*?)\]", ROLES_TS).group(1)
    assert re.findall(r'"(\w+)"', roles) == sorted(worker.ROLE_RANK, key=worker.ROLE_RANK.get)
    table = dict(re.findall(r"\n\s+(\w+): \"(\w+)\",", re.search(r"ACTION_ROLE = \{(.*?)\}", ROLES_TS, re.S).group(1)))
    kinds = set(worker.HANDLERS) | {"recalculate"}
    assert set(table) == kinds
    assert table == {k: worker.REQUIRED_ROLE.get(k, "editor") for k in kinds}


def test_every_level_column_has_a_label():
    labelled = set(re.findall(r"\n  (\w+): ", FIELDS_TS))
    columns = set(levels.GENERATION_COLUMNS) | set(levels.POWERTRAIN_COLUMNS) | set(levels.VARIANT_COLUMNS)
    assert columns - labelled == set()


# final_listing columns shown in the record's header or used as links, not in its field groups
FINAL_HEADER = {"source_site", "listing_id", "raw_version", "country_code", "source_url", "listed_at", "price",
                "currency", "mileage_km", "generation_id", "powertrain_id", "variant_id", "unassigned_reason",
                "vehicle_class_code", "make_id", "make", "model_id", "model", "trim", "model_year",
                "generation_name"}


def test_final_sheet_shows_every_column():
    groups = re.search(r"FINAL_SHEET_GROUPS: \[string, string\[\]\]\[\] = \[(.*?)\n\];", FINAL_TS, re.S).group(1)
    shown = [f for inner in re.findall(r'\["[^"]+", \[(.*?)\]\]', groups) for f in re.findall(r'"(\w+)"', inner)]
    assert len(shown) == len(set(shown))
    assert set(shown) == set(final.SOURCES) - FINAL_HEADER


def test_unassigned_reasons_match_the_constraint():
    # the latest migration that rewrites listing_level's reason check holds the current list
    versions = sorted((Path(__file__).resolve().parents[1] / "src" / "vehicle_scraper" / "kb" / "migrations"
                       / "versions").glob("0*.py"))
    latest = [p for p in versions if "listing_level_unassigned_reason_check" in p.read_text(encoding="utf-8")][-1]
    tree = ast.parse(latest.read_text(encoding="utf-8"))
    consts = {n.targets[0].id: n.value for n in tree.body if isinstance(n, ast.Assign) and hasattr(n.targets[0], "id")}
    after = ast.literal_eval(consts["BEFORE"]) + ast.literal_eval(consts["AFTER"].right)
    block = re.search(r"UNASSIGNED_REASONS: Record<string, string> = \{(.*?)\n\};", FINAL_TS, re.S).group(1)
    assert re.findall(r"\n  (\w+): ", block) == list(after)


def test_source_rank_matches():
    m = re.search(r"SOURCE_RANK: Record<string, number> = (\{.*?\})", FIELDS_TS)
    ts = json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)))
    assert ts == levels.SOURCE_RANK
