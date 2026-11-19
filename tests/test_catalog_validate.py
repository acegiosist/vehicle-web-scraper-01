from vehicle_scraper.catalog.validate import validate_answer

IDS = {"m1": "crv", "m2": "hrv"}


def _model_item(local="m1", cls="car", body="SUV"):
    return {"input_hash": "h-" + local, "item_kind": "model", "status": "pending",
            "request": {"local_id": local, "make_slug": "honda", "match_key": IDS[local], "model_ids": IDS,
                        "line": {"id": local, "class": cls, "body": body}}}


def _trim_item(cc=2.4, gear="Automatic"):
    return {"input_hash": "h-t1", "item_kind": "trim", "status": "pending",
            "request": {"local_id": "t1", "make_slug": "honda", "model_key": "crv", "alias_norm": "crv|exl",
                        "model_ids": IDS, "line": {"id": "t1", "model": "m1", "cc": cc, "gear": gear, "fuel": "-"}}}


def _m(**kw):
    return {"id": "m1", "action": "keep", "canonical_name": "CR-V", "merge_into": None, "vehicle_class": "car",
            "body_style": None, "body_source": None, "confidence": 0.9, "note": ""} | kw


def _t(**kw):
    return {"id": "t1", "model_id": "m1", "trim_name": "EX-L", "engine_displacement_l": None, "transmission_type": None,
            "fuel_type": None, "drivetrain": None, "body_style": None, "doors": None, "confidence": 0.9, "note": ""} | kw


def one(answer, items):
    (d,) = validate_answer(answer, items)
    return d


def test_confident_clean_answers_are_accepted():
    assert one({"models": [_m()], "trims": []}, {"m1": _model_item()}).status == "accepted"
    d = one({"models": [], "trims": [_t(engine_displacement_l=2.4, doors=5)]}, {"t1": _trim_item()})
    assert d.status == "accepted" and d.answer["attrs"] == {"engine_displacement_l": 2.4, "doors": 5}


def test_review_rules():
    items = {"m1": _model_item()}
    assert one({"models": [_m(confidence=0.5)]}, items).status == "review"
    assert one({"models": [_m(canonical_name="CR-V 2.4 4x4")]}, items).status == "review"   # spec words
    assert one({"models": [_m(vehicle_class="heavy")]}, items).status == "review"
    assert one({"models": [_m(action="merge", merge_into="m2", confidence=0.8)]}, items).status == "review"
    assert one({"models": [_m(body_style="Sedan", body_source="title")]}, items).status == "review"  # listings say SUV
    d = one({"models": [_m(body_style="SUV", body_source="ai_knowledge")]}, {"m1": _model_item(body="-")})
    assert d.status == "accepted" and [r[0] for r in d.reviews] == ["ai_knowledge_body"]  # knowledge always reviewed


def test_listing_evidence_wins_over_the_text():
    d = one({"trims": [_t(engine_displacement_l=1.5, transmission_type="Automatic")]}, {"t1": _trim_item()})
    assert d.status == "review" and d.answer["attrs"] == {"transmission_type": "Automatic"}
    assert "contradicts listings" in d.reasons[0]


def test_rejections():
    assert one({"models": [_m(action="merge", merge_into="m9")]}, {"m1": _model_item()}).status == "rejected"
    assert one({"models": [_m(canonical_name="  ")]}, {"m1": _model_item()}).status == "rejected"
    assert one({"models": [_m(body_style="Spaceship")]}, {"m1": _model_item()}).status == "rejected"
    assert one({"trims": [_t(model_id="m7")]}, {"t1": _trim_item()}).status == "rejected"
    assert validate_answer({"models": [_m(id="m5")], "trims": []}, {"m1": _model_item()}) == []   # not asked
