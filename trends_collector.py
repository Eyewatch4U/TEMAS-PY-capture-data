#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Colector de Google Trends -> Monitor Temas de Interés · Paraguay (NSGroup)
===========================================================================
Obtiene el "interés en el tiempo" (0-100) de cada búsqueda en Google Trends
para Paraguay y lo publica en el worker de Cloudflare (endpoint /update-trends),
que lo guarda en KV y lo sirve al dashboard junto al feed de Meltwater.

Usa pytrends (API no oficial de Google Trends). Pensado para correr en el
self-hosted runner de GitHub Actions (IP propia = menos bloqueos de Google).

ENV requeridas:
  WORKER_BASE_URL   Base del worker, p.ej. https://temas-py.<cuenta>.workers.dev
  SYNC_TOKEN        Igual al secret SYNC_TOKEN del worker (header x-sync-token)
ENV opcionales:
  TRENDS_GEO        País/región Trends (default: PY)
  TRENDS_HL         Idioma de la consulta (default: es-PY)
  TRENDS_TZ         Offset de zona en minutos para Trends (default: 180 = UTC-3)
  TRENDS_KEYWORDS   Lista "label=query" separada por ';'. Si falta, usa el default.
                    El 'label' debe coincidir con la búsqueda de Meltwater para que
                    el color del dashboard sea el mismo (BCP, Dólar, Combustible,
                    Presupuesto). El 'query' es lo que se le pide a Google.

Salida (POST JSON a /update-trends):
  { ts, geo, terms:[{key,label}], periods:{ d30|d7|h24:{ points:[{d, v:{key:score}}] } } }
"""

import os
import sys
import json
import time
import urllib.request

# --- Config ------------------------------------------------------------------
WORKER_BASE_URL = os.environ.get("WORKER_BASE_URL", "").rstrip("/")
SYNC_TOKEN      = os.environ.get("SYNC_TOKEN", "")
GEO             = os.environ.get("TRENDS_GEO", "PY")
HL              = os.environ.get("TRENDS_HL", "es-PY")
TZ_OFFSET       = int(os.environ.get("TRENDS_TZ", "180"))  # minutos; UTC-3 = 180

# label=query ; el label define el color (debe igualar la búsqueda de Meltwater)
DEFAULT_KEYWORDS = [
    ("BCP", "BCP"),
    ("Dólar", "dólar"),
    ("Combustible", "combustible"),
    ("Presupuesto", "presupuesto"),
]

def load_keywords():
    raw = os.environ.get("TRENDS_KEYWORDS", "").strip()
    if not raw:
        return DEFAULT_KEYWORDS
    out = []
    for part in raw.split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            label, query = part.split("=", 1)
        else:
            label = query = part
        out.append((label.strip(), query.strip()))
    return out or DEFAULT_KEYWORDS

# Timeframes de Trends alineados a los períodos del dashboard.
# y1 = vista anual del año en curso (como el explore de todo 2026), semanal.
_YEAR = int(os.environ.get("TRENDS_YEAR", time.strftime("%Y")))
TIMEFRAMES = {
    "y1":  f"{_YEAR}-01-01 {_YEAR}-12-31",  # año completo, resolución semanal
    "d30": "today 1-m",   # ~30 días, resolución diaria
    "d7":  "now 7-d",     # 7 días, resolución horaria
    "h24": "now 1-d",     # 24 horas, resolución ~8 min
}

# --- Conversión DataFrame -> puntos -----------------------------------------
def df_to_points(df, keywords):
    """pytrends.interest_over_time() -> [{d: ISO8601Z, v:{label:score}}]."""
    points = []
    if df is None or getattr(df, "empty", True):
        return points
    cols = list(df.columns)
    for idx, row in df.iterrows():
        # idx es un Timestamp (pandas); lo pasamos a ISO UTC 'Z'
        try:
            iso = idx.tz_localize("UTC").strftime("%Y-%m-%dT%H:%M:%SZ") if idx.tzinfo is None \
                  else idx.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            iso = str(idx)
        v = {}
        for label, query in keywords:
            col = query if query in cols else (label if label in cols else None)
            v[label] = int(row[col]) if (col is not None and row.get(col) is not None) else 0
        points.append({"d": iso, "v": v})
    return points

def _wait(attempt, is429):
    import random
    return min(150, (40 if is429 else 20) * (attempt + 1) + random.randint(0, 12))

# --- pytrends con reintentos (best-effort: devuelve None si no pudo) ----------
def fetch_timeframe(queries, timeframe, retries=4):
    from pytrends.request import TrendReq
    last = None
    for attempt in range(retries):
        try:
            py = TrendReq(hl=HL, tz=TZ_OFFSET, timeout=(10, 30))
            py.build_payload(kw_list=queries, timeframe=timeframe, geo=GEO)
            return py.interest_over_time()
        except Exception as e:  # noqa
            last = e
            wait = _wait(attempt, "429" in str(e))
            sys.stderr.write(f"[trends] {timeframe} intento {attempt+1} falló: {e} · reintento en {wait}s\n")
            time.sleep(wait)
    sys.stderr.write(f"[trends] {timeframe} agotó reintentos: {last}\n")
    return None  # best-effort: no corta el resto

# --- Búsquedas relacionadas EN ASCENSO (rising) de las últimas 24h, por término
def fetch_related(keywords, retries=4):
    from pytrends.request import TrendReq
    queries = [q for (_l, q) in keywords]
    last = None
    for attempt in range(retries):
        try:
            py = TrendReq(hl=HL, tz=TZ_OFFSET, timeout=(10, 30))
            py.build_payload(kw_list=queries, timeframe="now 1-d", geo=GEO)
            rq = py.related_queries()  # {query: {'top': df, 'rising': df}}
            out = {}
            for (label, query) in keywords:
                d = (rq or {}).get(query) or {}
                rising = d.get("rising")
                items = []
                if rising is not None and not getattr(rising, "empty", True):
                    for _, row in rising.iterrows():
                        q = str(row.get("query", "")).strip()
                        if q:
                            items.append({"query": q, "value": int(row.get("value", 0) or 0)})
                out[label] = items[:10]
            return out
        except Exception as e:  # noqa
            last = e
            wait = _wait(attempt, "429" in str(e))
            sys.stderr.write(f"[trends] related intento {attempt+1} falló: {e} · reintento en {wait}s\n")
            time.sleep(wait)
    sys.stderr.write(f"[trends] related agotó reintentos: {last}\n")
    return {}

def build_payload():
    import random
    keywords = load_keywords()
    queries = [q for (_l, q) in keywords]
    if len(queries) > 5:
        raise SystemExit("Google Trends admite máximo 5 términos por consulta.")
    periods = {}
    for pk, tf in TIMEFRAMES.items():
        df = fetch_timeframe(queries, tf)
        pts = df_to_points(df, keywords) if df is not None else []
        if pts:
            periods[pk] = {"points": pts}
            sys.stderr.write(f"[trends] {pk} OK ({len(pts)} puntos)\n")
        time.sleep(10 + random.randint(0, 8))  # pausa con jitter para no gatillar 429
    related = fetch_related(keywords)
    nrel = sum(len(v) for v in related.values())
    sys.stderr.write(f"[trends] relacionados en ascenso: {nrel} items\n")
    if not periods and not related:
        raise SystemExit("Trends no devolvió datos (probable 429 de Google).")
    out = {
        "ts": int(time.time() * 1000),
        "geo": GEO,
        "terms": [{"key": l, "label": l} for (l, _q) in keywords],
        "periods": periods,
    }
    if related:
        out["related"] = related
    return out

# --- POST al worker ----------------------------------------------------------
def post_to_worker(payload):
    if not WORKER_BASE_URL or not SYNC_TOKEN:
        raise SystemExit("Faltan WORKER_BASE_URL o SYNC_TOKEN en el entorno.")
    url = WORKER_BASE_URL + "/update-trends"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
        # Cloudflare delante del worker rechaza con 403 el User-Agent por defecto
        # de urllib ("Python-urllib/..."). Identificamos el cliente para evitarlo.
        "User-Agent": "NSG-Trends-Collector/1.0 (+Eyewatch Intelligence Unit)",
        "x-sync-token": SYNC_TOKEN,
    })
    with urllib.request.urlopen(req, timeout=40) as r:
        resp = r.read().decode("utf-8")
        print(f"[trends] HTTP {r.status} · {resp}")
        return r.status

def main():
    payload = build_payload()
    counts = {pk: len(p["points"]) for pk, p in payload["periods"].items()}
    print(f"[trends] geo={payload['geo']} terms={[t['label'] for t in payload['terms']]} puntos={counts}")
    status = post_to_worker(payload)
    if status < 200 or status >= 300:
        raise SystemExit(f"POST falló con HTTP {status}")

if __name__ == "__main__":
    main()
