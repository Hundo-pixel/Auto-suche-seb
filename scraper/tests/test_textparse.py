from autosuche import textparse as tp


def test_parse_numbers_and_dates():
    assert tp.parse_int("174.917 km") == 174917
    assert tp.parse_int("1.234 € VB") == 1234
    assert tp.parse_first_registration("09/2012") == "2012-09"
    assert tp.parse_first_registration("2012-09-01") == "2012-09"
    assert tp.parse_first_registration("Januar 2009") == "2009-01"
    assert tp.parse_first_registration("EZ 02/2005") == "2005-02"
    assert tp.parse_power("105 kW (143 PS)") == (105, 143)
    assert tp.parse_power("75 PS") == (55, 75)


def test_normalizers():
    assert tp.normalize_fuel("Elektro/Benzin") == "Hybrid"
    assert tp.normalize_fuel("Autogas (LPG)") == "LPG"
    assert tp.normalize_gearbox("Manuell") == "Schaltgetriebe"
    assert tp.model_key("BMW", "320", "3er") == "3er"
    assert tp.model_key("BMW", "3er Reihe") == "3er"
    assert tp.model_key("Mercedes", "C-Klasse") == tp.model_key("Mercedes-Benz", "C Klasse")
    assert tp.make_key("Mercedes Benz") == tp.make_key("Mercedes-Benz") == "mercedes-benz"
    assert tp.make_key("VW") == "volkswagen"


def test_tyres():
    t = tp.tyre_info("Sommer- und Winterreifen auf Alufelgen dabei")
    assert t["sets"] == 2 and "Sommer" in t["labels"] and "Winter" in t["labels"]
    assert tp.tyre_info("Allwetterreifen aus 2024")["labels"] == ["Ganzjahr"]
    assert tp.tyre_info("8-fach bereift")["sets"] == 2
    assert tp.tyre_info("Neue Winterreifen montiert")["sets"] == 1
    t = tp.tyre_info("Zusätzlich ein Satz Winterreifen auf Felgen")
    assert t["sets"] == 2
    assert tp.tyre_info("Bremsen neu, Zahnriemen gewechselt")["sets"] is None


def test_plate_hints():
    kinds = {h["type"] for h in tp.plate_hints("Fahrzeug hat Kurzzeitkennzeichen, Überführung möglich")}
    assert "Kurzzeitkennzeichen" in kinds
    assert {h["type"] for h in tp.plate_hints("mit Ausfuhrkennzeichen")} == {"Ausfuhrkennzeichen"}
    assert {h["type"] for h in tp.plate_hints("Auto ist in Polen zugelassen, Zulassung in Polen")} == {"Auslandszulassung"}
    assert {h["type"] for h in tp.plate_hints("Probefahrt mit roten Kennzeichen möglich")} == {"Rotes Kennzeichen"}
    assert tp.plate_hints("Deutsche Zulassung, scheckheftgepflegt") == []


def test_keyword_warnings_with_negation():
    kinds = {w["type"] for w in tp.keyword_warnings("Motorschaden, nur für Export oder Bastler")}
    assert {"Motorschaden", "Export", "Bastlerfahrzeug"} <= kinds
    assert tp.keyword_warnings("Kein Motorschaden, kein Export, nichts defekt") == []
    assert {w["type"] for w in tp.keyword_warnings("Klima defekt")} == {"Defekt"}
    assert {w["type"] for w in tp.keyword_warnings("Verkauf ohne TÜV")} == {"Ohne TÜV"}


def test_accident_from_text():
    assert tp.accident_from_text("Fahrzeug ist unfallfrei, Scheckheft") == "free"
    assert tp.accident_from_text("Unfall: nein") == "free"
    assert tp.accident_from_text("Leichter Frontschaden, fahrbereit") == "accident"
    assert tp.accident_from_text("Top Zustand") == "unknown"


def test_redact_contact_data():
    from autosuche.export import redact
    out = redact("Tel. 0176 12345678 oder +49 (0)221 - 2929622800, Mail max@web.de. 174.917 km, Baujahr 2012, 12.500 €")
    assert "12345678" not in out and "2929622800" not in out and "max@web.de" not in out
    assert "174.917 km" in out and "2012" in out and "12.500 €" in out
