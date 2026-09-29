"""Tests fuer die Kernfunktionen von analyse.py mit kuenstlichen Kerzen."""
from datetime import timedelta

import analyse as A
from bars import kerze, serie, utc

# Drei Kerzen mit bullischem FVG: Kerze 1 Hoch 100, Kerze 3 Tief 104 -> Gap 100-104
BULL = [(98, 100, 97, 99), (99, 106, 99, 105), (105, 108, 104, 107)]


def fvgs(ohlc, live=(), minuten=30, tf_min=None):
    return A.finde_fvgs_alle(serie(utc("2026-09-28 12:00"), minuten, ohlc), live, minuten, tf_min)


# ------------------------------------------------------------ FVG (Tag 9/10)

def test_fvg_drei_kerzen_ohne_ueberlappung():
    f = fvgs(BULL)
    assert len(f) == 1 and f[0]["richtung"] == "bullish"
    assert (f[0]["von"], f[0]["bis"]) == (100, 104)
    assert f[0]["unmediated"] is True and f[0]["ifvg"] is False


def test_kein_fvg_bei_ueberlappenden_wicks():
    assert fvgs([(98, 100, 97, 99), (99, 106, 99, 105), (105, 108, 99, 107)]) == []


def test_bearisches_fvg():
    f = fvgs([(110, 112, 108, 109), (109, 109, 100, 101), (101, 106, 99, 100)])
    assert f[0]["richtung"] == "bearish" and (f[0]["von"], f[0]["bis"]) == (106, 108)


def test_wick_in_die_zone_macht_mediated_aber_kein_ifvg():
    f = fvgs(BULL + [(107, 108, 103, 106)])   # Wick bis 103 taucht in 100-104 ein
    assert f[0]["unmediated"] is False and f[0]["ifvg"] is False


def test_laufende_kerze_zaehlt_fuer_tap_aber_nicht_fuer_ifvg():
    live = serie(utc("2026-09-28 13:30"), 30, [(107, 108, 95, 96)])   # Wick UND Close unter dem Gap
    f = fvgs(BULL, live=live)
    assert f[0]["unmediated"] is False    # Wick zaehlt sofort
    assert f[0]["ifvg"] is False          # ein Close braucht eine geschlossene Kerze


def test_body_close_durch_das_ganze_gap_ist_ifvg():
    f = fvgs(BULL + [(106, 106, 98, 99)])
    assert f[0]["ifvg"] is True and f[0]["ifvg_abstand_pkt"] == 1.0


def test_roll_kerze_bildet_kein_fvg():
    bars = serie(utc("2026-09-28 12:00"), 30, BULL)
    bars[1]["roll_kerze"] = True
    assert A.finde_fvgs_alle(bars, (), 30) == []


def test_datenluecke_bildet_kein_fvg():
    bars = serie(utc("2026-09-28 12:00"), 30, BULL)
    bars[2] = kerze(utc("2026-09-28 14:00"), *BULL[2])    # 1 Kerze fehlt bei Yahoo
    assert A.finde_fvgs_alle(bars, (), 30) == []


def test_register_behaelt_durchlaufene_zonen_anzeige_wirft_sie_raus():
    durch = BULL + [(106, 106, 95, 96)]     # Gap 100-104 komplett durchlaufen -> ifvg
    alle = fvgs(durch)
    assert len(alle) == 1
    voll = fvgs(BULL + [(107, 108, 99, 107)])   # gefuellt, aber Close darueber -> kein IFVG
    assert voll[0]["_gefuellt"] and not voll[0]["ifvg"]
    assert A.kuerze_fvgs(voll) == []            # als Level erledigt
    assert len(A.kuerze_fvgs(alle)) == 1        # IFVG bleibt (Entry-Trigger)


def test_kuerze_behaelt_alle_unmediated_und_zehn_mediated():
    alle = [{"unmediated": i % 2 == 0, "_gefuellt": False, "ifvg": False, "id": i} for i in range(40)]
    k = A.kuerze_fvgs(alle)
    assert sum(1 for f in k if f["unmediated"]) == 20
    assert sum(1 for f in k if not f["unmediated"]) == 10
    assert [f["id"] for f in k] == sorted(f["id"] for f in k)      # chronologisch


def test_kuerze_liefert_kopien_das_register_behaelt_interne_felder():
    alle = fvgs(BULL)
    k = A.kuerze_fvgs(alle)
    A.ohne_intern(k)
    assert "_i" in alle[0] and "_i" not in k[0]


# ------------------------------------------------------------ Zonen: unmediated-Regel

def zone(alle, tf="30m", tf_min=30):
    z = dict(alle[0], tf=tf)
    return z


def test_zone_zaehlt_nur_solange_unmediated_und_nicht_invertiert():
    z = zone(fvgs(BULL + [(107, 108, 103, 106)]))   # Tap um 14:00 (Kerze 4)
    zonen = A.Zonen([z], [])
    t_tap = z["_t_tap"]
    assert not zonen.offen_bei(z, z["_t_entstanden"] - timedelta(minutes=1))   # existiert noch nicht
    assert zonen.offen_bei(z, z["_t_entstanden"])
    assert zonen.offen_bei(z, t_tap)                                          # Tap selbst ist noch "davor"
    assert not zonen.offen_bei(z, t_tap + timedelta(minutes=5))               # danach mediated


def test_erste_beruehrung_ist_auf_5m_genau():
    z = zone(fvgs(BULL + [(107, 108, 103, 106)]))
    # feine Daten: die Zone (100-104) wird erst in der 3. 5m-Kerze der 30m-Kerze beruehrt
    fein = serie(z["_t_tap"], 5, [(107, 108, 106, 107), (107, 108, 105, 106), (106, 106, 103, 104),
                                   (104, 105, 104, 105), (105, 106, 105, 106), (106, 107, 106, 107)])
    zonen = A.Zonen([z], fein)
    assert zonen.erste_beruehrung(z) == z["_t_tap"] + timedelta(minutes=10)


def test_invertierte_zone_zaehlt_nicht_mehr():
    z = zone(fvgs(BULL + [(106, 106, 98, 99)]))
    zonen = A.Zonen([z], [])
    assert zonen.offen_bei(z, z["_t_entstanden"])
    assert not zonen.offen_bei(z, z["_t_ifvg"] + timedelta(minutes=30))


# ------------------------------------------------------------ Key Levels (Tag 3)

class FesteAchse:
    def __init__(self, levels):
        self._l = levels

    def levels(self, t):
        return dict(self._l)


def test_key_level_endet_erst_mit_body_close_eines_5m_close_nicht_mit_wick():
    fein = serie(utc("2026-09-28 13:00"), 5, [(99, 101, 98, 100), (100, 103, 99, 100.5),   # Wick ueber 102
                                                 (100.5, 101, 99, 100), (100, 104, 100, 103)])   # Close 103 ueber 102
    kl = A.KeyLevels("nq", FesteAchse({"pdh": 102.0}), [], fein)
    assert "pdh" in kl.alle_bei(utc("2026-09-28 13:10"))      # nur gewickt -> Sweep, Level bleibt
    assert "pdh" in kl.alle_bei(utc("2026-09-28 13:15"))      # die 4. Kerze ist noch nicht geschlossen
    assert "pdh" not in kl.alle_bei(utc("2026-09-28 13:20"))  # geschlossen mit Close darueber -> genommen


def test_statisches_level_existiert_erst_ab_t_ab():
    st = [{"name": "Data High X", "preis": 105.0, "seite": "high", "t_ab": utc("2026-09-28 13:30")}]
    kl = A.KeyLevels("nq", FesteAchse({}), st, [])
    assert "Data High X" not in kl.alle_bei(utc("2026-09-28 13:00"))
    assert "Data High X" in kl.alle_bei(utc("2026-09-28 13:30"))


# ------------------------------------------------------------ Manipulation je Session

WS, WE = utc("2026-09-28 06:00"), utc("2026-09-28 10:00")


def manip(fein, levels, zonen=(), achse_zu=None):
    kl = A.KeyLevels("nq", FesteAchse(levels), [], achse_zu if achse_zu is not None else fein)
    return A.session_manipulation(WS, WE, fein, achse_zu if achse_zu is not None else fein, kl,
                                  A.Zonen(list(zonen), fein), WE)


def test_sweep_eines_vorher_existierenden_levels_ist_manipulation():
    fein = serie(WS, 5, [(100, 101, 99, 100), (100, 103, 100, 101), (101, 101, 99, 100)])   # Wick 103, Close 101
    m = manip(fein, {"pdh": 102.0})
    assert m["hat_manipuliert"] and m["sweeps"][0]["level"] == "pdh" and m["richtung"] == "nach oben"


def test_body_close_ueber_das_level_ist_bruch_keine_manipulation():
    fein = serie(WS, 5, [(100, 101, 99, 100), (100, 104, 100, 103), (103, 104, 102.5, 103.5)])
    assert not manip(fein, {"pdh": 102.0})["hat_manipuliert"]


def test_keine_beruehrung_keine_manipulation():
    fein = serie(WS, 5, [(100, 101, 99, 100)] * 3)
    m = manip(fein, {"pdh": 120.0, "pdl": 80.0})
    assert not m["hat_manipuliert"] and m["richtung"] is None


def test_erster_tap_einer_unmediated_zone_ist_manipulation_ein_zweiter_nicht():
    z = zone(fvgs(BULL + [(107, 108, 103, 106)]))
    z["_t_entstanden"] = WS - timedelta(hours=2)
    z["_t_tap"] = WS + timedelta(minutes=5)
    fein = serie(WS, 5, [(107, 108, 106, 107), (107, 107, 103, 104), (104, 105, 103, 104)])
    m = manip(fein, {}, [z])
    assert m["hat_manipuliert"] and m["fvg_taps"][0]["seite"] == "low"
    # war die Zone schon VOR dem Fenster getappt (mediated), zaehlt sie nicht
    z2 = dict(z, _t_tap=WS - timedelta(hours=1))
    assert not manip(fein, {}, [z2])["hat_manipuliert"]


def test_nach_dem_fenster_gibt_es_nichts_zu_pruefen():
    assert manip([], {"pdh": 1.0}) is None


# ------------------------------------------------------------ Wochenkerzen / Tage

def test_wochenkerze_ist_erst_nach_freitag_17_uhr_et_geschlossen():
    # Freitag 2026-09-25: 17:00 ET = 21:00 UTC
    bars = (serie(utc("2026-09-21 22:00"), 30, [(100, 105, 95, 102)] * 4)      # Montag (Handelstag)
            + serie(utc("2026-09-25 19:00"), 30, [(102, 110, 90, 108)] * 3))     # Freitag Nachmittag
    zu, live = A.zu_wochenkerzen(bars, utc("2026-09-25 20:00"), "nq")
    assert zu == [] and len(live) == 1
    zu, live = A.zu_wochenkerzen(bars, utc("2026-09-25 21:00"), "nq")
    assert len(zu) == 1 and live == []
    assert zu[0]["h"] == 110 and zu[0]["l"] == 90 and zu[0]["o"] == 100 and zu[0]["c"] == 108


# ------------------------------------------------------------ Daily Profile (Tag 19)

def london(o, h, l, c):
    return {"open": o, "high": h, "low": l, "close": c}


def profil(manip_london, lond, asia, tag_bars, median=None):
    manip = {"sessions": {"london": manip_london}} if manip_london is not None else {"sessions": {"london": None}}
    return A.daily_profile_berechnen("nq", None, tag_bars, asia, lond, None, manip, median)["profil"]


LM_MIT = {"beendet": True, "sweeps": [{"level": "asia_high"}], "fvg_taps": [], "hat_manipuliert": True}
LM_OHNE = {"beendet": True, "sweeps": [], "fvg_taps": [], "hat_manipuliert": False}


def test_profil_2_wenn_london_manipuliert_und_das_tageshoch_bildet():
    tag = [kerze(utc("2026-09-28 08:00"), 100, 110, 95, 105)]
    p = profil(LM_MIT, london(100, 110, 95, 105), london(99, 101, 98, 100), tag)
    assert p.startswith("2")


def test_profil_offen_wenn_london_manipuliert_aber_kein_tageshoch_oder_tief():
    tag = [kerze(utc("2026-09-28 08:00"), 100, 120, 90, 105)]
    p = profil(LM_MIT, london(100, 110, 95, 105), london(99, 101, 98, 100), tag)
    assert p.startswith("offen")


def test_profil_3_bei_starkem_london_ohne_manipulation_sonst_1():
    tag = [kerze(utc("2026-09-28 08:00"), 100, 120, 90, 105)]
    stark = profil(LM_OHNE, london(100, 130, 100, 128), london(99, 101, 98, 100), tag, median=10)
    assert stark.startswith("3")
    seitwaerts = profil(LM_OHNE, london(100, 103, 98, 101), london(99, 101, 98, 100), tag, median=10)
    assert seitwaerts.startswith("1")


def test_profil_nicht_bestimmbar_solange_london_laeuft_und_nichts_manipuliert_hat():
    tag = [kerze(utc("2026-09-28 06:00"), 100, 103, 98, 101)]
    lm = dict(LM_OHNE, beendet=False)
    assert profil(lm, london(100, 103, 98, 101), london(99, 101, 98, 100), tag).startswith("noch nicht")


# ------------------------------------------------------------ Struktur

def test_equal_highs_meldet_das_letzte_high_der_reihe():
    # Swing-Highs bei 110 (i=2), 110 (i=6), 110.05 (i=10): exakt gleich, Toleranz weit unterschritten
    def p(h):
        return (h - 5, h, h - 8, h - 4)
    ohlc = [p(100), p(102), p(110), p(102), p(101), p(103), p(110), p(103), p(101), p(103), p(110.05), p(103), p(100)]
    lv = A.equal_levels_alle(serie(utc("2026-09-28 12:00"), 60, ohlc))
    eqh = [x for x in lv if x["art"].endswith("EQH")]
    assert eqh and eqh[0]["preis"] == 110.05 and eqh[0]["anzahl"] == 3


# ------------------------------------------------------------ Rollover

def test_roll_luecke_am_verfallsfreitag_wird_erkannt_und_normale_luecken_nicht():
    # Dritter Freitag im September 2024 ist der 20.09. Sprung NQ +200 (1 %), ES +55 (1 %) zwischen 13:00 und 20:00 UTC.
    start = utc("2024-09-19 12:00")
    nq, es = [], []
    for i in range(200):
        t = start + timedelta(hours=i)
        if t.weekday() >= 5:
            continue
        stufe = 200.0 if t >= utc("2024-09-20 20:00") else 0.0
        nq.append(kerze(t, 19700 + stufe, 19710 + stufe, 19690 + stufe, 19700 + stufe))
        es.append(kerze(t, 5600 + stufe / 3.6, 5602 + stufe / 3.6, 5598 + stufe / 3.6, 5600 + stufe / 3.6))
    # Luecke auch fuer die Zeitreihe erzwingen: ES-Sprung 55 (gleiche Richtung, NQ/ES-Verhaeltnis passt)
    r = A.finde_roll_luecken(nq, es, "1h")
    assert len(r) == 1 and r[0]["art"] == "luecke" and r[0]["zeit_utc"] == "2024-09-20 20:00"
    assert r[0]["nq"] == 200.0
    # ohne den Sprung: nichts
    flach_nq = [kerze(k["t"], 19700, 19710, 19690, 19700) for k in nq]
    flach_es = [kerze(k["t"], 5600, 5602, 5598, 5600) for k in es]
    assert A.finde_roll_luecken(flach_nq, flach_es, "1h") == []


# ------------------------------------------------------------ Rejection Block (Tag 12)

def rb_bars(werte):
    return serie(utc("2026-09-28 13:00"), 30, werte)


def test_rejection_block_wick_am_key_level_body_close_zurueck():
    # Kerze 2: Wick bis 105 ueber das Level 104, Body 100-101 -> Wick > 50 %; naechste Kerze schliesst bearisch
    bars = rb_bars([(100, 101, 99, 100), (101, 105, 100, 100.5), (100.5, 101, 98, 99), (99, 100, 98, 99)])
    kl = A.KeyLevels("nq", FesteAchse({"pdh": 104.0}), [], [])
    rb = A.rejection_blocks(bars, kl, A.Zonen([], []))
    assert rb and rb[0]["richtung"] == "bearish" and rb[0]["level"] == "pdh"
    assert (rb[0]["von"], rb[0]["bis"]) == (101.0, 105.0)


def test_kein_rejection_block_ohne_key_level_oder_mit_schwachem_wick():
    bars = rb_bars([(100, 101, 99, 100), (101, 105, 100, 100.5), (100.5, 101, 98, 99), (99, 100, 98, 99)])
    assert A.rejection_blocks(bars, A.KeyLevels("nq", FesteAchse({}), [], []), A.Zonen([], [])) == []
    schwach = rb_bars([(100, 101, 99, 100), (100, 104.2, 100, 103), (103, 103, 98, 99), (99, 100, 98, 99)])
    assert A.rejection_blocks(schwach, A.KeyLevels("nq", FesteAchse({"pdh": 104.0}), [], []), A.Zonen([], [])) == []


def test_rejection_block_ignoriert_ein_level_das_es_noch_nicht_gab():
    bars = rb_bars([(100, 101, 99, 100), (101, 105, 100, 100.5), (100.5, 101, 98, 99), (99, 100, 98, 99)])
    spaet = [{"name": "Data High", "preis": 104.0, "seite": "high", "t_ab": utc("2026-09-28 20:00")}]
    assert A.rejection_blocks(bars, A.KeyLevels("nq", FesteAchse({}), spaet, []), A.Zonen([], [])) == []


# ------------------------------------------------------------ Sponsorship (Tag 22)

def test_fvg_aus_offener_htf_zone_ist_gesponsort_aus_mediated_zone_nicht():
    # 15m-FVG bullish, Leg startet bei Tief 100.5 innerhalb der 30m-Zone 100-104
    bars = serie(utc("2026-09-28 13:00"), 15, [(102, 103, 100.5, 101), (101, 108, 101, 107), (107, 112, 106, 111)])
    f = A.finde_fvgs_alle(bars, (), 15)
    z = dict(zone(fvgs(BULL)), _t_entstanden=utc("2026-09-28 12:00"))
    kl = A.KeyLevels("nq", FesteAchse({}), [], [])
    ok = A.markiere_sponsorship(A.kuerze_fvgs(f), bars, A.Zonen([z], []), kl)
    assert ok[0]["gesponsort"] and ok[0]["sponsor"].startswith("30m-FVG")
    getappt = dict(z, _t_tap=utc("2026-09-28 12:30"))
    aus = A.markiere_sponsorship(A.kuerze_fvgs(f), bars, A.Zonen([getappt], []), kl)
    assert not aus[0]["gesponsort"]


# ------------------------------------------------------------ Stacked PO3 (Tag 23)

def test_stacked_po3_erste_kerze_ohne_zweite_mit_tap():
    # NY-AM ET 09:30 = 13:30 UTC (Sommerzeit). Level 108: 1. Kerze bleibt darunter, 2. erreicht es neu.
    bars = serie(utc("2026-09-28 13:30"), 15, [(100, 102, 99, 101), (101, 109, 100, 105), (105, 106, 104, 105)])
    from datetime import date
    kl = A.KeyLevels("nq", FesteAchse({"pdh": 108.0}), [], [])
    st = A.stacked_po3(bars, kl, A.Zonen([], []), date(2026, 9, 28))
    assert [k["hat_manipuliert"] for k in st["kerzen"]] == [False, True, False]
    assert "nachgeholt" in st["fazit"]


# ------------------------------------------------------------ Yahoo-Luecken auffuellen

def test_fehlende_1h_kerze_wird_aus_30m_gebaut_ohne_30m_daten_bleibt_die_luecke():
    fein = serie(utc("2026-09-28 10:00"), 30, [(100, 101, 99, 100.5), (100.5, 103, 100, 102),   # 10:00-11:00
                                                (102, 104, 101, 103), (103, 105, 102, 104)])    # 11:00-12:00
    grob = [kerze(utc("2026-09-28 09:00"), 99, 100, 98, 99.5), kerze(utc("2026-09-28 11:00"), 102, 105, 101, 104)]
    erg = A.fuelle_luecken(fein, grob, 60)
    neu = [b for b in erg if b.get("gefuellt")]
    assert len(erg) == 3 and len(neu) == 1 and neu[0]["t"] == utc("2026-09-28 10:00")
    assert (neu[0]["o"], neu[0]["h"], neu[0]["l"], neu[0]["c"]) == (100, 103, 99, 102)
    assert [b["t"] for b in erg] == sorted(b["t"] for b in erg)
    ohne = A.fuelle_luecken([], grob, 60)
    assert ohne == grob


# ------------------------------------------------------------ Befunde aus dem Zweit-Audit

def test_kuerzen_schneidet_bei_wenigen_eintraegen_nicht_falsch_ab():
    med = [{"unmediated": False, "_gefuellt": False, "ifvg": False, "id": i} for i in range(9)]
    assert len(A.kuerze_fvgs(med)) == 9          # frueher: nur 1 (negativer Index)
    ith = [{"status": "body_close", "n": i} for i in range(2)]
    assert len(A.kuerze_ith(ith, 3)) == 2


def test_ith_existiert_erst_ab_der_delivery_nicht_ab_der_bestaetigung():
    # bearisches FVG 106-108; Preis laeuft hinein (Tap), bearische Bestaetigungskerze, dann Delivery unter deren Tief
    basis = [(110, 112, 108, 109), (109, 109, 100, 101), (101, 106, 99, 100), (103, 107, 99, 100)]
    bars = serie(utc("2026-09-28 12:00"), 60, basis + [(100, 100, 97, 98)])
    r = A.intermediate_levels_alle(bars, "1h", 60)
    assert len(r) == 1 and r[0]["art"] == "1h ITL" and r[0]["preis"] == 99.0
    assert r[0]["_t_ab"] == bars[4]["t"] + timedelta(hours=1)          # Ende der Delivery-Kerze, nicht der Bestaetigung
    # ohne Delivery gibt es (noch) keinen ITL
    assert A.intermediate_levels_alle(bars[:4] + serie(utc("2026-09-28 16:00"), 60, [(100, 101, 99.5, 100)]), "1h", 60) == []


def test_rejection_block_naechste_kerze_die_das_level_per_body_close_nimmt_bestaetigt_nicht():
    bars = rb_bars([(100, 101, 99, 100), (101, 105, 100, 100.5), (100.5, 110, 100.5, 109), (109, 110, 108, 109)])
    kl = A.KeyLevels("nq", FesteAchse({"pdh": 104.0}), [], [])
    # Kerze 2 hat ein Doji-Body nach oben (c>o) => Bestaetigung nur ueber die Folgekerze, die aber ueber dem Level schliesst
    bars[1] = kerze(bars[1]["t"], 100, 105, 99.5, 100.6)
    bars[2] = kerze(bars[2]["t"], 110, 111, 100.5, 105)     # bearische Kerze, Close 105 > Level 104
    assert A.rejection_blocks(bars, kl, A.Zonen([], [])) == []


def test_fuelle_luecken_baut_keine_halbe_stunde():
    fein = serie(utc("2026-09-28 10:00"), 30, [(100, 101, 99, 100.5)])
    grob = [kerze(utc("2026-09-28 09:00"), 99, 100, 98, 99.5), kerze(utc("2026-09-28 11:00"), 102, 105, 101, 104)]
    assert A.fuelle_luecken(fein, grob, 60) == grob
