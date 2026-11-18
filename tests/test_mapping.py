from vehicle_scraper.mapping import RecordBuilder, match_features, match_label


def test_labels_es_en():
    assert match_label("Cilindrada (c.c³)") == "engine_displacement_l"
    assert match_label("Potencia (H.P)") == "horsepower_hp"
    assert match_label("Relación Peso / Potencia") is None
    assert match_label("Cantidad de válvulas por cilindro") is None
    assert match_label("Capacidad del tanque de combustible (Galones)") == "fuel_tank_capacity_l"
    assert match_label("Tipo de combustible") == "fuel_type"
    assert match_label("Tracción") == "drivetrain"
    assert match_label("Control de tracción") is None
    assert match_label("Bolsas de aire") == "airbags_count"
    assert match_label("Wheel drive") == "drivetrain"
    assert match_label("Puertas") == "doors"


def test_features():
    assert match_features("Cámara de reversa") == {"reverse_camera"}
    assert match_features("Tapicería en cuero") == {"leather_seats"}
    assert "sunroof" in match_features("Techo panorámico") and "panoramic_roof" in match_features("Techo panorámico")
    assert match_features("Apple CarPlay y Android Auto") == {"apple_carplay", "android_auto"}
    assert match_features("sin sunroof") == set()
    assert match_features("Rines de aluminio") == {"alloy_wheels"}


def test_modelo_means_year_in_colombia():
    b = RecordBuilder("t", "u", "1")
    b.add_pair("Modelo", "2010")
    b.add_pair("Modelo", "Tucson")
    rec = b.build()
    assert rec.model_year == 2010 and rec.model == "Tucson"


def test_boolean_pairs_and_counts():
    b = RecordBuilder("t", "u", "1")
    b.add_pair("Frenos ABS", "Sí")
    b.add_pair("Sunroof", "No")
    b.add_pair("Con airbags", "Sí")               # flag, not a count
    b.add_pair("Bolsas de aire", "6")
    rec = b.build()
    assert rec.abs is True and rec.sunroof is False and rec.airbags_count == 6


def test_first_value_wins_and_missing_stays_null():
    b = RecordBuilder("t", "u", "1")
    b.set("make", "Toyota")
    b.set("make", "Other")
    rec = b.build()
    assert rec.make == "Toyota"
    assert rec.heated_seats is None                # never guessed as False


def test_leather_and_heated_only_for_seats():
    assert match_features("Volante forrado en cuero") == set()
    assert match_features("Palanca de cambios en cuero") == set()
    assert match_features("Espejos calefactados") == set()
    assert match_features("Volante y asientos en cuero") == {"leather_seats"}
    assert match_features("Asientos delanteros calefactados") == {"heated_seats"}
    assert match_features("Cuero") == {"leather_seats"}


def test_esp_abbreviation_is_not_stability_control():
    assert "stability_control" not in match_features("Esp. eléctricos")
    assert "stability_control" not in match_features("esp electricos")
    assert "stability_control" in match_features("Control de estabilidad ESP")
    assert "stability_control" in match_features("ESP")


def test_seat_split_ratio_is_not_a_seat_count():
    b = RecordBuilder("t", "u", "1")
    b.add_pair("Asientos traseros abatibles", "60/40")
    b.add_pair("Pasajeros", "5")
    assert b.build().seats == 5
    b = RecordBuilder("t", "u", "1")
    b.add_pair("Asientos", "60/40")
    assert b.build().seats is None


def test_out_of_range_year_is_null_not_rejected():
    b = RecordBuilder("t", "u", "1")
    b.add_pair("Año", "2049")
    b.set("make", "Mazda")
    rec = b.build()                                 # must not raise ValidationError
    assert rec.model_year is None and rec.make == "Mazda"
    assert any("model_year" in w for w in rec.parse_warnings)


def _titled(*parts):
    b = RecordBuilder("t", "u", "1")
    b.add_title(*parts)
    return b.build()


def test_title_explicit_body_drivetrain_doors():
    r = _titled("3", "2.0 Sedan Touring Aut")
    assert r.body_style == "Sedan" and r.vehicle_type == "Sedan"
    assert _titled("Frontier NP300", "2.5 4x2 Doble Cabina Pro-D Diesel").body_style == "Pickup"
    assert _titled("Tucson", "IX35 4x4 2.0 Gasolina Mecanica").drivetrain == "4WD"
    assert _titled("Clase GLK", "220 CDI 4Matic 2.2 Diesel").drivetrain == "AWD"
    assert _titled("Blazer 4x4", "Automatica").drivetrain == "4WD"
    assert _titled("206", "1.4 X-Desing 5 Puertas").doors == 5
    assert _titled("Grand Touring 2.5 Suv Automatica").body_style == "SUV"


def test_title_never_guesses():
    r = _titled("Frontier NP300", "2.5 4x2 Doble Cabina")
    assert r.drivetrain is None                       # not FWD from "Frontier"
    assert any("4x2" in w for w in r.parse_warnings)
    assert _titled("DS 7", "Crossback Audace 1.6").body_style is None
    assert _titled("206", "1.4 5 Puertas").body_style is None    # doors alone don't imply a body
    assert _titled("HB20s", "Advance").body_style is None
    assert _titled("Duster Oroch", "Intens").body_style is None


def test_title_does_not_override_structured_specs():
    b = RecordBuilder("t", "u", "1")
    b.add_pair("Carrocería", "SUV")
    b.add_pair("Tracción", "Delantera")
    b.add_title("Mazda 3", "2.0 Sedan 4x4")
    r = b.build()
    assert r.body_style == "SUV" and r.drivetrain == "FWD"
