"""Statistics: primary-source fetchers (FRED / SEC EDGAR / Finnhub).

Every value is upserted into stats_series keyed (source, series_id, period,
vintage); the raw API payload is also stored as a provenance document so any
number traces to its primary endpoint.
"""
from __future__ import annotations
import json
import os

import httpx

from lib import fetch

UA = fetch.UA


def _upsert(con, source, series_id, period, value, url, units=None, vintage="latest"):
    con.execute(
        "INSERT INTO stats_series(source, series_id, period, vintage, value, units, primary_url, retrieved_at) "
        "VALUES (?,?,?,?,?,?,?, current_timestamp) "
        "ON CONFLICT (source, series_id, period, vintage) DO UPDATE SET value=excluded.value, retrieved_at=excluded.retrieved_at",
        [source, series_id, period, vintage, value, units, url],
    )


def fred_series(con, corpus_dir, series_id, *, api_key=None, observation_start=None):
    api_key = api_key or os.environ.get("FRED_API_KEY")
    if not api_key:
        raise RuntimeError("FRED_API_KEY not set")
    url = (f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
           f"&file_type=json&api_key={api_key}")
    if observation_start:
        url += f"&observation_start={observation_start}"
    r = httpx.get(url, timeout=30, headers={"User-Agent": UA}); r.raise_for_status()
    j = r.json()
    obs = j.get("observations", [])
    for o in obs:
        if o.get("value") in (".", "", None):
            continue
        _upsert(con, "fred", series_id, o["date"], float(o["value"]), url)
    fetch.ingest_text(con, corpus_dir, text=json.dumps(j), source_url=url, channel="stats",
                      source_tier=1, source_id=f"fred:{series_id}", title=f"FRED {series_id}",
                      media_type="application/json", ext="json")
    return len(obs)


def sec_company_concept(con, corpus_dir, cik, concept, taxonomy="us-gaap"):
    cik10 = str(cik).zfill(10)
    url = f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik10}/{taxonomy}/{concept}.json"
    r = httpx.get(url, timeout=30, headers={"User-Agent": UA}); r.raise_for_status()
    j = r.json()
    n = 0
    for unit, rows in (j.get("units") or {}).items():
        for row in rows:
            if row.get("val") is None or not row.get("end"):
                continue
            _upsert(con, "sec", f"{cik10}:{concept}", row["end"], float(row["val"]), url,
                    units=unit, vintage=str(row.get("fy", "latest")))
            n += 1
    fetch.ingest_text(con, corpus_dir, text=json.dumps(j), source_url=url, channel="stats",
                      source_tier=1, source_id=f"sec:{cik10}", title=f"SEC {concept} {cik10}",
                      media_type="application/json", ext="json")
    return n


def finnhub_quote(con, corpus_dir, symbol, *, api_key=None):
    api_key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY not set")
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={api_key}"
    r = httpx.get(url, timeout=30, headers={"User-Agent": UA}); r.raise_for_status()
    j = r.json()
    if j.get("c") is not None:
        _upsert(con, "finnhub", f"{symbol}:price", str(j.get("t")), float(j["c"]), url, units="USD")
    return j
