import requests
import time
import database as db

POLYMARKET_API = "https://data-api.polymarket.com"
GAMMA_API      = "https://gamma-api.polymarket.com"

# ── MERCADOS ─────────────────────────────────────────

def fetch_active_markets(limit=200):
    """Trae los mercados activos de Polymarket."""
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={
            "active": "true",
            "closed": "false",
            "limit": limit
        }, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SCRAPER] Error fetching markets: {e}")
        return []

# ── TRADES EN TIEMPO REAL ────────────────────────────

_last_seen_ts = {}  # market_id -> último timestamp procesado

def fetch_recent_trades(market_id: str, since_ts: int = None):
    """Trae trades recientes de un mercado específico."""
    try:
        params = {"market": market_id, "limit": 50}
        if since_ts:
            params["startTs"] = since_ts
        r = requests.get(f"{POLYMARKET_API}/activity", params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SCRAPER] Error fetching trades for {market_id}: {e}")
        return []

def scrape_trades():
    """
    Corre cada 30 segundos.
    Trae trades nuevos de los mercados activos y los guarda en la DB.
    """
    print("[SCRAPER] Iniciando ciclo de scraping...")
    markets = fetch_active_markets(limit=50)  # empieza con 50 mercados

    new_trades = 0
    for market in markets:
        market_id   = market.get("id") or market.get("conditionId", "")
        market_name = market.get("question", "Sin título")

        if not market_id:
            continue

        since = _last_seen_ts.get(market_id)
        trades = fetch_recent_trades(market_id, since_ts=since)

        for t in trades:
            # Normalizar campos según la respuesta real de Polymarket
            trade = {
                "tx_hash":     t.get("transactionHash", f"{market_id}_{t.get('timestamp',0)}"),
                "wallet":      t.get("maker") or t.get("address", ""),
                "market_id":   market_id,
                "market_name": market_name,
                "side":        t.get("side", "YES"),
                "amount_usd":  float(t.get("usdcSize") or t.get("size", 0)),
                "price":       float(t.get("price", 0)),
                "timestamp":   int(t.get("timestamp", time.time()))
            }

            if trade["wallet"] and trade["amount_usd"] > 0:
                db.save_trade(trade)
                new_trades += 1

                # Guardar precio para correlaciones
                db.save_price(market_id, trade["price"], trade["timestamp"])

                # Actualizar último timestamp visto
                if market_id not in _last_seen_ts or trade["timestamp"] > _last_seen_ts[market_id]:
                    _last_seen_ts[market_id] = trade["timestamp"]

    print(f"[SCRAPER] Ciclo completado — {new_trades} trades nuevos guardados")

# ── BACKFILL HISTÓRICO ───────────────────────────────

def backfill_history(days_back=90):
    """
    Corre UNA SOLA VEZ al inicio.
    Descarga historial completo para tener datos desde el primer día.
    """
    print(f"[BACKFILL] Iniciando descarga de {days_back} días de historial...")
    since_ts = int(time.time()) - (days_back * 86400)

    markets = fetch_active_markets(limit=200)
    total = len(markets)

    for i, market in enumerate(markets):
        market_id   = market.get("id") or market.get("conditionId", "")
        market_name = market.get("question", "Sin título")

        if not market_id:
            continue

        print(f"[BACKFILL] {i+1}/{total} — {market_name[:50]}")

        try:
            # Precio histórico
            r = requests.get(f"{POLYMARKET_API}/prices-history", params={
                "market":   market_id,
                "startTs":  since_ts,
                "fidelity": 60  # un punto por hora
            }, timeout=15)

            if r.status_code == 200:
                history = r.json()
                for point in history.get("history", []):
                    db.save_price(market_id, float(point.get("p", 0)), int(point.get("t", 0)))

            # Trades históricos
            trades = fetch_recent_trades(market_id, since_ts=since_ts)
            for t in trades:
                trade = {
                    "tx_hash":     t.get("transactionHash", f"{market_id}_{t.get('timestamp',0)}"),
                    "wallet":      t.get("maker") or t.get("address", ""),
                    "market_id":   market_id,
                    "market_name": market_name,
                    "side":        t.get("side", "YES"),
                    "amount_usd":  float(t.get("usdcSize") or t.get("size", 0)),
                    "price":       float(t.get("price", 0)),
                    "timestamp":   int(t.get("timestamp", 0))
                }
                if trade["wallet"] and trade["amount_usd"] > 0:
                    db.save_trade(trade)

            time.sleep(0.3)  # respetar rate limit de la API

        except Exception as e:
            print(f"[BACKFILL] Error en {market_id}: {e}")
            continue

    print("[BACKFILL] ✅ Historial descargado correctamente")
