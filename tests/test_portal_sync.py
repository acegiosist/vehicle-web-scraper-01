"""The portal (TypeScript) repeats a few Python tables; these checks fail when one drifts.

* Review texts: review.ISSUES / CLASSES / ISSUE_ORDER  <->  src/portal/src/lib/issues.ts
* Roles: worker.ROLE_RANK / REQUIRED_ROLE              <->  src/portal/src/lib/auth/roles.ts
* Field labels: every level column (kb/levels.py)      ->   src/portal/src/lib/fields.ts
* Source precedence: levels.SOURCE_RANK               <->  fields.ts SOURCE_RANK
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from vehicle_scraper.kb import levels, review, worker

PORTAL = Path(__file__).resolve().parents[1] / "src" / "portal" / "src" / "lib"
ISSUES_TS = (PORTAL / "issues.ts").read_text(encoding="utf-8")
ROLES_TS = (PORTAL / "auth" / "roles.ts").read_text(encoding="utf-8")
FIELDS_TS = (PORTAL / "fields.ts").read_text(encoding="utf-8")


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


def test_source_rank_matches():
    m = re.search(r"SOURCE_RANK: Record<string, number> = (\{.*?\})", FIELDS_TS)
    ts = json.loads(re.sub(r"(\w+):", r'"\1":', m.group(1)))
    assert ts == levels.SOURCE_RANK
