"""Tests fuer regeltest.py (Rueckwaertstest) und den Konsistenz-Check in biascheck.py."""
import biascheck as C
import regeltest as R


def block(**kw):
    d = {"preis": 100.0, "key_levels": {"pdh": 120.0, "pdl": 80.0}, "level_status": {}, "fvg_1h": [], "fvg_4h": [], "ith_itl": [],
         "equal_levels_1h": [], "data_levels": [], "offene_nwog": [],
         "trend_1w": {"richtung": "bearish"}, "trend_1d": {"richtung": "bearish"}, "trend_4h": {"richtung": "range"}, "trend_1h": {"richtung": "range"},
         "range_ote_1d": {"preis_in": "premium"}, "market_condition": {"bewertung": "gut"}}
    d.update(kw)
    return d


# ---- Konsistenz
def test_dol_auf_falscher_seite_wird_gemeldet():
    warn, info = C.konsistenz(block(), "bullish", 90.0, text="Retracement")
    assert any("falschen Seite" in w for _, w in warn)


def test_bias_gegen_mehrheit_braucht_gegenkontext():
    warn, info = C.konsistenz(block(), "bullish", 120.0, text="Bullish bis PDH 120")
    assert info["ausrichtung"] == 0.0 and any("Mehrheit der Signale" in w for _, w in warn)
    warn2, _ = C.konsistenz(block(), "bullish", 120.0, text="Bullish Pullback bis PDH 120")
    assert not any("Mehrheit der Signale" in w for _, w in warn2)


def test_ausrichtung_zaehlt_nur_klare_signale_und_range_nicht():
    _, info = C.konsistenz(block(), "bearish", 80.0, text="")
    assert info["ausrichtung"] == 1.0 and set(info["signale"]) == {"trend_1w", "trend_1d", "range_ote_1d (premium)"}


def test_levels_im_pfad_ohne_erwaehnung_sind_hinweis_kein_fehler():
    d = block(fvg_1h=[{"richtung": "bearish", "von": 108.0, "bis": 110.0, "unmediated": True, "ifvg": False}])
    warn, info = C.konsistenz(d, "bullish", 120.0, text="Bullish Pullback DOL 120")
    assert any("108.0" in h for h in info["hinweise"])
    warn2, info2 = C.konsistenz(d, "bullish", 120.0, text="Bullish Pullback DOL 120, 1h FVG 108")
    assert not any("108.0" in h for h in info2["hinweise"])


# ---- Rueckwaertstest
def faelle(n_mit, fehler_mit, n_ohne, fehler_ohne):
    rows = []
    for i in range(n_mit):
        rows.append({"datum": f"2026-09-{i + 1:02d}", "symbol": "NQ1!", "richtung": "bullish", "ergebnis": "DANEBEN" if i < fehler_mit else "TREFFER",
                     "fehlerarten": [], "snapshot_commit": "MIT", "dol_preis": 120.0})
    for i in range(n_ohne):
        rows.append({"datum": f"2026-08-{i + 1:02d}", "symbol": "NQ1!", "richtung": "bullish", "ergebnis": "DANEBEN" if i < fehler_ohne else "TREFFER",
                     "fehlerarten": [], "snapshot_commit": "OHNE", "dol_preis": 120.0})
    return rows


def lader(commit, symbol, repo):
    return block() if commit == "MIT" else block(trend_1w={"richtung": "bullish"}, trend_1d={"richtung": "bullish"}, range_ote_1d={"preis_in": "discount"})


def test_backtest_belegt_risikofaktor():
    r = R.backtest(faelle(6, 5, 6, 1), "gegen_htf_signale", laden=lader)
    assert r["urteil"] == "belegt" and r["mit_bedingung"]["rate"] > r["ohne_bedingung"]["rate"]


def test_backtest_nicht_belegt_ohne_unterschied():
    r = R.backtest(faelle(6, 3, 6, 3), "gegen_htf_signale", laden=lader)
    assert r["urteil"] == "nicht belegt"


def test_backtest_zu_wenig_daten_und_breiter_anschlag():
    assert R.backtest(faelle(3, 3, 6, 0), "gegen_htf_signale", laden=lader)["urteil"] == "zu wenig Daten"
    r = R.backtest(faelle(9, 9, 5, 0), "gegen_htf_signale", laden=lader)          # 64 % aller Faelle schlagen an
    assert r["urteil"] == "nicht belegt" and "keine Auswahl" in r["grund"]


def test_backtest_ueberspringt_zeilen_ohne_snapshot():
    rows = faelle(6, 5, 6, 1) + [{"datum": "2026-07-01", "symbol": "NQ1!", "ergebnis": "DANEBEN", "fehlerarten": []}]
    assert R.backtest(rows, "gegen_htf_signale", laden=lader)["uebersprungen"] == 1
