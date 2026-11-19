"""Catalog stage 2 (rules) on a small synthetic set of raw listings, SQLite in a temp file."""
import pytest
from sqlalchemy import select

from vehicle_scraper.catalog import schema as S
from vehicle_scraper.catalog.build import build_catalog
from vehicle_scraper.catalog.canonical import MakeTable

MAKES = MakeTable({"Toyota": {"country": "Japan"}, "Chevrolet": {}, "Honda": {}, "Jeep": {}})


def row(site, lid, make, model, trim=None, **kw):
    base = {"source_site": site, "listing_id": lid, "make": make, "model": model, "trim": trim,
            "source_url": f"https://x/{lid}", "currency": {"carroya": "COP", "cofino": "GTQ"}[site],
            "scraped_at": "2026-11-18T10:00:00+00:00"}
    return base | kw


def raw_rows():
    # carroya separates model and trim (trim on every row); cofino doesn't.
    return [
        row("carroya", "c1", "Toyota", "Rav 4", "2.0 4x2 Aut", model_year=2019, fuel_type="Gasoline",
            transmission_type="Automatic", engine_displacement_l=2.0, body_style="SUV", abs=1,
            listed_at="2026-10-01T00:00:00+00:00"),
        row("carroya", "c2", "TOYOTA", "Rav4", "2.0 4X2 Automatica", model_year=2019, fuel_type="Gasoline",
            transmission_type="Automatic", engine_displacement_l=2.0, abs=0),
        row("cofino", "g1", "Toyota", "RAV4", None, model_year=2019, fuel_type="Gasoline",
            transmission_type="Automatic"),
        row("carroya", "c3", "Chevrolet", "Tahoe", "LT", model_year=2020, fuel_type="Gasoline"),
        row("cofino", "g2", "Chevrolet", "TAHOE LTZ 4X4", None, model_year=2021, fuel_type="Gasoline"),
        row("cofino", "g3", "Chevrolet", "TRAVERSE", None, model_year=2021),
        row("carroya", "c4", "Honda", "CR-V", "EXL", model_year=2018, fuel_type="Gasoline",
            transmission_type="Automatic", engine_displacement_l=2.4, drivetrain="AWD"),
        row("carroya", "c5", "Honda", "CR-V", "EXL", model_year=2018, fuel_type="Gasoline",
            transmission_type="Automatic", engine_displacement_l=2.4, drivetrain="4WD"),
        row("carroya", "c6", "Honda", "CR-V", "EXL", model_year=2018, fuel_type="Gasoline",
            transmission_type="Automatic", engine_displacement_l=2.4, drivetrain="4WD"),
        row("carroya", "c7", "Zhongtong", "Bus", "Urbano", model_year=2015, vehicle_type="Truck"),
        row("carroya", "c8", "Honda", "CB", "190R", model_year=2022, vehicle_type="Motorcycle"),
    ]


@pytest.fixture
def engine(tmp_path):
    return S.get_engine(f"sqlite:///{(tmp_path / 'catalog.sqlite').as_posix()}")


def _models(engine):
    with engine.connect() as c:
        return {(mk, name): (cls, verified) for mk, name, cls, verified in c.execute(
            select(S.make.c.slug, S.model.c.name, S.model.c.vehicle_class, S.model.c.verified)
            .join(S.make, S.make.c.id == S.model.c.make_id))}


def test_build_merges_spellings_and_splits_trims(engine):
    rep = build_catalog(engine, raw_rows(), MAKES)
    models = _models(engine)
    assert [k for k in models if k[0] == "toyota"] == [("toyota", "Rav 4")]       # Rav 4 / Rav4 / RAV4
    assert ("chevrolet", "Tahoe") in models and ("chevrolet", "TAHOE LTZ") not in models
    assert models[("chevrolet", "Traverse")] == ("car", False)                 # only on a no-trim site
    assert models[("zhongtong", "Bus")][0] == "heavy" and models[("honda", "CB")][0] == "moto"
    assert rep.listings_linked == 11 and rep.raw_makes == 5 and rep.makes == 4 + 0   # TOYOTA == Toyota
    with engine.connect() as c:
        trims = {n for (n,) in c.execute(select(S.trim.c.name))}
        assert {"LT", "LTZ", "EXL", ""} <= trims and "2.0 4x2 Aut" not in trims
        # TAHOE LTZ 4X4 -> trim LTZ under Tahoe, 4X4 read as drivetrain
        drive = c.execute(select(S.variant.c.drivetrain).join(S.trim, S.trim.c.id == S.variant.c.trim_id)
                          .where(S.trim.c.name == "LTZ")).scalar()
        assert drive == "4WD"


def test_consensus_conflicts_and_provenance(engine):
    build_catalog(engine, raw_rows(), MAKES)
    with engine.connect() as c:
        v = c.execute(select(S.variant).join(S.trim, S.trim.c.id == S.variant.c.trim_id)
                      .where(S.trim.c.name == "EXL")).mappings().one()
        assert v["drivetrain"] == "4WD" and v["n_listings"] == 3 and v["needs_review"]    # 1 of 3 = 33 % > 30 %
        src = c.execute(select(S.variant_field_source).where(S.variant_field_source.c.variant_id == v["id"],
                                                             S.variant_field_source.c.field == "drivetrain")).mappings().one()
        assert (src["n_support"], src["n_conflict"], src["source"]) == (2, 1, "listing")
        reasons = {(r.entity_type, r.reason) for r in c.execute(select(S.review_item))}
        assert ("make", "unknown_make") in reasons                                # Zhongtong isn't in the seed
        assert ("variant", "spec_conflict") in reasons                            # the CR-V drivetrain split
        # Rav 4 2019: the cofino listing had no engine size -> filled from its trim+year siblings, so
        # all three spellings land in one variant ("2.0 4x2 Aut" cleans to no trim, like cofino's).
        rav = c.execute(select(S.variant.c.variant_key, S.variant.c.n_listings)
                        .join(S.trim, S.trim.c.id == S.variant.c.trim_id)
                        .join(S.model, S.model.c.id == S.trim.c.model_id).where(S.model.c.match_key == "rav4")).all()
        assert rav == [("2019|Gasoline|Automatic|2.0", 3)]
        feat = c.execute(select(S.variant_feature.c.n_true, S.variant_feature.c.n_false)
                         .join(S.feature, S.feature.c.id == S.variant_feature.c.feature_id)
                         .where(S.feature.c.code == "abs")).one()
        assert tuple(feat) == (1, 1)
        market = c.execute(select(S.variant_market).where(S.variant_market.c.country == "CO")
                           .order_by(S.variant_market.c.first_listed)).mappings().first()
        assert market["first_listed"] is not None


def test_rebuild_is_idempotent_with_stable_ids(engine):
    build_catalog(engine, raw_rows(), MAKES)
    with engine.connect() as c:
        before = sorted(c.execute(select(S.variant.c.id, S.variant.c.variant_key)).all())
    rep = build_catalog(engine, raw_rows(), MAKES)
    with engine.connect() as c:
        after = sorted(c.execute(select(S.variant.c.id, S.variant.c.variant_key)).all())
    assert before == after and not any(rep.pruned.values())
    rep = build_catalog(engine, [r for r in raw_rows() if r["make"] != "Honda"], MAKES)
    assert rep.pruned["models"] == 2                                              # CR-V and CB lost their listings


def test_ddl_is_postgres():
    sql = S.ddl("postgresql")
    assert sql.count("CREATE TABLE") == 15 and "JSONB" in sql and "SERIAL" in sql
    assert "CHECK (fuel_type IS NULL OR fuel_type IN ('Gasoline', 'Diesel', 'Hybrid', 'EV', 'CNG'))" in sql


def test_committed_ddl_is_up_to_date():
    from pathlib import Path
    committed = Path(__file__).resolve().parents[1] / "sql" / "catalog_schema.postgresql.sql"
    assert committed.read_text(encoding="utf-8") == S.ddl("postgresql"), \
        "schema changed: run `catalog export-ddl --out sql/catalog_schema.postgresql.sql`"
