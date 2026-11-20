"""Consensus and cross-check rules (offline, no database)."""
from datetime import datetime, timezone

import pytest

pytest.importorskip("psycopg")

from vehicle_scraper.kb.consensus import (Settings, _L, crosscheck_evidence, listing_evidence, name_cc,
                                          same_value, vote)

NOW = datetime(2026, 11, 20, tzinfo=timezone.utc)


def L(n, country="CO", cluster=None, **row):
    l = _L("carroya", str(n), country, 1, None, 2020, row, "car", "Tracker", "Tracker", None, NOW, NOW)
    l.cluster_id = cluster
    return l


def ev(evs, field, country=""):
    return [e for e in evs if e.field == field and e.country == country]


def test_vote_is_tolerance_aware():
    assert vote("horsepower_hp", [138, 140, 141, 200]) == (140, 3, 4)
    assert same_value("horsepower_hp", 140, 146) and not same_value("horsepower_hp", 140, 160)
    assert not same_value("seats", 5, 7)


def test_mechanical_single_listing_is_accepted():
    (e,) = ev(listing_evidence({1: [L(1, horsepower_hp=138)]}, Settings()), "horsepower_hp")
    assert (e.kind, e.status, e.confidence) == ("listing_single", "accepted", 0.6)


def test_mechanical_consensus_and_disagreement():
    evs = listing_evidence({1: [L(1, seats=5), L(2, seats=5), L(3, seats=5)],
                            2: [L(4, seats=5), L(5, seats=7)]}, Settings())
    ok = [e for e in ev(evs, "seats") if e.variant_id == 1][0]
    bad = [e for e in ev(evs, "seats") if e.variant_id == 2][0]
    assert (ok.kind, ok.status, ok.support) == ("listing_consensus", "accepted", 3)
    assert (bad.status, bad.reason) == ("pending_review", "listings_disagree")


def test_equipment_needs_two_listings_of_that_country():
    one = listing_evidence({1: [L(1, sunroof=True)]}, Settings())
    assert ev(one, "sunroof", "CO") == []                   # one car may have an option fitted
    two = listing_evidence({1: [L(1, sunroof=True), L(2, sunroof=True), L(3, country="IN", sunroof=False)]}, Settings())
    (e,) = ev(two, "sunroof", "CO")
    assert e.value is True and e.status == "accepted"
    assert ev(two, "sunroof", "IN") == []                    # India has a single listing


def test_explicit_false_majority_sets_false():
    evs = listing_evidence({1: [L(1, abs=False), L(2, abs=False), L(3, abs=True)]}, Settings())
    assert ev(evs, "abs", "CO") == []                        # 2/3 = 67 % < 70 %
    evs = listing_evidence({1: [L(1, abs=False), L(2, abs=False), L(3, abs=False)]}, Settings())
    assert ev(evs, "abs", "CO")[0].value is False


def test_same_car_on_two_portals_is_one_vote():
    a, b = L(1, cluster=9, seats=5), L(2, cluster=9, seats=5)
    (e,) = ev(listing_evidence({1: [a, b]}, Settings()), "seats")
    assert e.kind == "listing_single" and e.support == 1


def test_name_number_check():
    assert name_cc("G 310 R") == 310 and name_cc("Pulsar 200 NS") == 200
    assert name_cc("Serie 3 320i") == 320 and name_cc("Model 3") is None
    assert name_cc("2008") is None                           # Peugeot 2008: out of the cc range


def test_hp_per_litre_flag():
    from vehicle_scraper.kb.consensus import _Ev
    e = _Ev(1, "", "horsepower_hp", 700, "listing_single", 1, 1.0, 0.6, "accepted", ["carroya"])
    variants = {1: {"model_id": 1, "engine_displacement_l": 1.0, "fuel_type": "Gasoline"}}
    assert [f[1] for f in crosscheck_evidence([e], variants, {1: "car"})] == ["hp_per_litre"]
