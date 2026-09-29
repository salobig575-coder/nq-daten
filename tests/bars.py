"""Hilfen zum Bauen kuenstlicher Kerzen fuer die Tests."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def utc(text):
    """'2026-09-28 10:00' (UTC) -> datetime."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)


def kerze(t, o, h, l, c, **extra):
    k = {"t": t, "et": t.astimezone(ET), "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": 1}
    k.update(extra)
    return k


def serie(start, minuten, ohlc):
    """Aufeinanderfolgende Kerzen ab start (UTC) im Abstand `minuten`."""
    return [kerze(start + timedelta(minutes=minuten * i), *x) for i, x in enumerate(ohlc)]
