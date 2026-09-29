"""Tests fuer levelcheck.py: der deterministische Durchgang gegen 'Level uebersehen'."""
import levelcheck as L


def block(**extra):
    d = {"preis": 100.0, "letzte_bar_et": "2026-09-29 08:30", "datenende_utc": "x",
         "key_levels": {"pdh": 120.0, "pdl": 90.0, "asia_high": 105.0, "asia_low": None},
         "level_status": {"pdh": {"status_seit_entstehung": "unberuehrt"}, "pdl": {"status_seit_entstehung": "unberuehrt"},
                          "asia_high": {"status_seit_entstehung": "body_close"}},
         "fvg_1h": [], "fvg_4h": [], "ith_itl": [], "equal_levels_1h": [], "data_levels": [], "offene_nwog": []}
    d.update(extra)
    return d


def fvg(richtung, von, bis, **kw):
    return {"richtung": richtung, "von": von, "bis": bis, "unmediated": True, "ifvg": False, **kw}


def test_unmediated_fvg_zwischen_preis_und_dol_wird_gefunden_genommenes_level_nicht():
    d = block(fvg_1h=[fvg("bearish", 108, 110)])
    erg = L.auswerten(d, dol=120.0)
    namen = [c["name"] for c in erg["abschnitte"]["zwischen_preis_und_dol"]["levels"]]
    assert "1h FVG bearish" in namen
    assert "Asia High" not in namen and "PDH" not in namen       # Asia High per Body Close genommen, PDH ist das DOL selbst


def test_mediated_und_invertierte_fvgs_zaehlen_nicht():
    d = block(fvg_1h=[dict(fvg("bearish", 108, 110), unmediated=False), dict(fvg("bearish", 111, 112), ifvg=True)])
    assert L.auswerten(d, dol=120.0)["abschnitte"]["zwischen_preis_und_dol"]["levels"] == []


def test_gegenseite_naeher_als_dol_wird_gemeldet():
    d = block()
    d["key_levels"]["pdl"] = 95.0        # 5 Pkt entfernt, DOL PDH 20 Pkt
    erg = L.auswerten(d, dol=120.0)
    assert [c["name"] for c in erg["gegenseite_naeher_als_dol"]] == ["PDL"]


def test_itl_mit_body_close_zaehlt_nicht_gesweepte_schon():
    d = block(ith_itl=[{"art": "1h ITL", "preis": 95.0, "status": "body_close"},
                       {"art": "4h ITL", "preis": 92.0, "status": "sweep"}])
    erg = L.auswerten(d, dol=120.0)
    unter = [c["name"] for c in erg["abschnitte"]["gegenseite_unter"]["levels"]]
    assert "4h ITL" in unter and "1h ITL" not in unter


def test_ohne_dol_werden_beide_seiten_gezeigt_und_zone_wird_ausgewertet():
    d = block(fvg_4h=[fvg("bullish", 96, 98)])
    erg = L.auswerten(d, zone=95.0)
    assert "naechste_ueber" in erg["abschnitte"] and "naechste_unter" in erg["abschnitte"]
    assert [c["tf"] for c in erg["abschnitte"]["zwischen_preis_und_zone"]["levels"]] == ["4h"]


def test_textausgabe_enthaelt_timeframe_und_abstand():
    t = L.text(L.auswerten(block(fvg_1h=[fvg("bearish", 108, 110)]), dol=120.0), 12)
    assert "1h FVG bearish 108-110" in t and "8.0 Pkt" in t
