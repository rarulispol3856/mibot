import requests
import time
import json
import database as db

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API  = "https://clob.polymarket.com"

# ── MERCADOS ACTIVOS ─────────────────────────────────

def fetch_active_markets(limit=50):
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={
            "active": "true",
            "closed": "false",
            "limit":  limit,
            "order":  "volume24hr",
            "ascending": "false"
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SCRAPER] Error fetching markets: {e}")
        return []

# ── PRECIO ACTUAL ────────────────────────────────────

def fetch_market_price(token_id: str):
    try:
        r = requests.get(f"{CLOB_API}/midpoint", params={"token_id": token_id}, timeout=10)
        r.raise_for_status()
        return float(r.json().get("mid", 0))
    except:
        return 0.0

# ── TRADES POR TOKEN ─────────────────────────────────

def fetch_trades_for_token(token_id: str, limit=30):
    try:
        r = requests.get(f"{CLOB_API}/trades", params={"market": token_id, "limit": limit}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        print(f"[SCRAPER] Error trades token {token_id[:20]}: {e}")
        return []

# ── PARSEAR TOKEN IDS ────────────────────────────────

def parse_token_ids(market: dict):
    raw = market.get("clobTokenIds") or market.get("tokens", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except:
            return []
    if isinstance(raw, list):
        ids = []
        for t in raw:
            if isinstance(t, str):
                ids.append(t)
            elif isinstance(t, dict):
                ids.append(t.get("token_id", ""))
        return [i for i in ids if i]
    return []

# ── CICLO PRINCIPAL ──────────────────────────────────

_procesados = set()

def scrape_trades():
    print("[SCRAPER] Iniciando ciclo...")
    markets = fetch_active_markets(limit=30)
    nuevos  = 0

    for market in markets:
        market_id   = market.get("conditionId") or market.get("id", "")
        market_name = market.get("question") or market.get("title", "Sin titulo")
        token_ids   = parse_token_ids(market)

        if not market_id or not token_ids:
            continue

        # Guardar precio para correlaciones
        precio = fetch_market_price(token_ids[0])
        if precio > 0:
            db.save_price(market_id, precio, int(time.time()))

        # Traer trades de cada token (YES=0, NO=1)
        for i, token_id in enumerate(token_ids):
            trades = fetch_trades_for_token(token_id, limit=20)
            for t in trades:
                tx = t.get("transaction_hash") or t.get("id", "")
                if not tx or tx in _procesados:
                    continue
                _procesados.add(tx)

                wallet = (t.get("maker_address") or t.get("taker_address") or
                          t.get("trader_address") or "")
                price  = float(t.get("price", 0))
                size   = float(t.get("size", 0))
                side   = t.get("side", "BUY")
                ts     = int(t.get("match_time") or t.get("timestamp") or time.time())

                if not wallet or size <= 0:
                    continue

                trade = {
                    "tx_hash":     tx,
                    "wallet":      wallet,
                    "market_id":   market_id,
                    "market_name": market_name,
                    "side":        "YES" if i == 0 else "NO",
                    "amount_usd":  round(price * size, 2),
                    "price":       price,
                    "timestamp":   ts
                }
                db.save_trade(trade)
                nuevos += 1

        time.sleep(0.2)

    if len(_procesados) > 10000:
        _procesados.clear()

    print(f"[SCRAPER] Ciclo completado — {nuevos} trades nuevos")

# ── BACKFILL ─────────────────────────────────────────

def backfill_history(days_back=90):
    print(f"[BACKFILL] Descargando {days_back} dias de historial...")
    since_ts = int(time.time()) - (days_back * 86400)
    markets  = fetch_active_markets(limit=100)

    for i, market in enumerate(markets):
        market_id = market.get("conditionId") or market.get("id", "")
        name      = market.get("question") or market.get("title", "")
        token_ids = parse_token_ids(market)

        if not market_id or not token_ids:
            continue

        print(f"[BACKFILL] {i+1}/{len(markets)} — {name[:50]}")
        try:
            r = requests.get(f"{CLOB_API}/prices-history", params={
                "market":   token_ids[0],
                "startTs":  since_ts,
                "interval": "1h"
            }, timeout=15)
            if r.status_code == 200:
                for point in r.json().get("history", []):
                    db.save_price(market_id, float(point.get("p", 0)), int(point.get("t", 0)))
        except Exception as e:
            print(f"[BACKFILL] Error {market_id[:20]}: {e}")

        time.sleep(0.3)

    print("[BACKFILL] Completo")
