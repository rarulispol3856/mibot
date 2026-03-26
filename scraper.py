import requests
import time
import json
import database as db

DATA_API  = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# ── TOP WALLETS DE POLYMARKET ────────────────────────

def fetch_top_wallets(limit=100):
    """
    Trae las top wallets por volumen/profit del leaderboard de Polymarket.
    Este endpoint es público sin auth.
    """
    try:
        r = requests.get(f"{DATA_API}/leaderboard", params={
            "limit": limit,
            "offset": 0
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        wallets = []
        for entry in data:
            addr = entry.get("proxyAddress") or entry.get("address", "")
            if addr:
                wallets.append(addr)
        print(f"[SCRAPER] {len(wallets)} wallets del leaderboard")
        return wallets
    except Exception as e:
        print(f"[SCRAPER] Error leaderboard: {e}")
        # Fallback: usar wallets conocidas si falla el leaderboard
        return []

# ── ACTIVIDAD DE UNA WALLET ──────────────────────────

def fetch_wallet_activity(wallet: str, limit=50):
    """
    Trae los trades recientes de una wallet específica.
    PÚBLICO — sin auth necesaria.
    """
    try:
        r = requests.get(f"{DATA_API}/activity", params={
            "user":          wallet.lower(),
            "type":          "TRADE",
            "limit":         limit,
            "sortBy":        "TIMESTAMP",
            "sortDirection": "DESC"
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SCRAPER] Error activity {wallet[:10]}: {e}")
        return []

# ── MERCADOS ACTIVOS ─────────────────────────────────

def fetch_active_markets(limit=200):
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={
            "active":     "true",
            "closed":     "false",
            "limit":      limit,
            "order":      "volume24hr",
            "ascending":  "false"
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SCRAPER] Error markets: {e}")
        return []

# ── CACHE DE MERCADOS ────────────────────────────────

_market_name_cache = {}

def get_market_name(market_id: str) -> str:
    if market_id in _market_name_cache:
        return _market_name_cache[market_id]
    return market_id[:30]

def build_market_cache():
    markets = fetch_active_markets(limit=200)
    for m in markets:
        mid  = m.get("conditionId") or m.get("id", "")
        name = m.get("question") or m.get("title", "")
        if mid and name:
            _market_name_cache[mid] = name
    print(f"[SCRAPER] Cache de mercados: {len(_market_name_cache)} entradas")

# ── WALLETS A MONITOREAR ─────────────────────────────

_wallets_to_monitor = set()

def update_wallets_to_monitor():
    """
    Combina: top wallets del leaderboard + wallets ya en la DB con score alto.
    """
    global _wallets_to_monitor

    # Top wallets del leaderboard
    top = fetch_top_wallets(limit=100)
    _wallets_to_monitor.update(top)

    # Wallets ya conocidas con score alto
    scored = db.get_top_wallets(limit=50)
    for w in scored:
        _wallets_to_monitor.add(w["wallet"])

    print(f"[SCRAPER] Monitoreando {len(_wallets_to_monitor)} wallets")

# ── CICLO PRINCIPAL ──────────────────────────────────

_ultimo_ts_por_wallet = {}  # wallet -> ultimo timestamp procesado

def scrape_trades():
    """Corre cada 30 segundos."""
    print("[SCRAPER] Iniciando ciclo...")
    nuevos = 0

    for wallet in list(_wallets_to_monitor):
        trades = fetch_wallet_activity(wallet, limit=20)

        for t in trades:
            ts = int(t.get("timestamp", 0))

            # Solo procesar trades más nuevos que el último visto
            ultimo = _ultimo_ts_por_wallet.get(wallet, 0)
            if ts <= ultimo:
                continue

            market_id = (
                t.get("conditionId") or
                t.get("market") or
                t.get("marketId", "")
            )

            trade = {
                "tx_hash":     t.get("transactionHash") or f"{wallet}_{ts}",
                "wallet":      wallet,
                "market_id":   market_id,
                "market_name": (
                    t.get("title") or
                    t.get("question") or
                    get_market_name(market_id)
                ),
                "side":        t.get("side", "YES"),
                "amount_usd":  float(t.get("usdcSize") or t.get("amount") or 0),
                "price":       float(t.get("price") or t.get("outcomeIndex") or 0),
                "timestamp":   ts
            }

            if trade["amount_usd"] > 0:
                db.save_trade(trade)
                if market_id:
                    db.save_price(market_id, trade["price"], ts)
                nuevos += 1

                # Actualizar ultimo timestamp
                if ts > _ultimo_ts_por_wallet.get(wallet, 0):
                    _ultimo_ts_por_wallet[wallet] = ts

        time.sleep(0.15)  # respetar rate limit

    print(f"[SCRAPER] Ciclo completado — {nuevos} trades nuevos")

# ── BACKFILL ─────────────────────────────────────────

def backfill_history(days_back=90):
    print(f"[BACKFILL] Descargando {days_back} dias de historial...")
    since_ts = int(time.time()) - (days_back * 86400)
    wallets  = fetch_top_wallets(limit=200)
    total    = len(wallets)

    for i, wallet in enumerate(wallets):
        print(f"[BACKFILL] {i+1}/{total} — {wallet[:12]}...")
        try:
            r = requests.get(f"{DATA_API}/activity", params={
                "user":          wallet.lower(),
                "type":          "TRADE",
                "limit":         500,
                "sortBy":        "TIMESTAMP",
                "sortDirection": "DESC",
                "start":         since_ts
            }, timeout=20)

            if r.status_code == 200:
                trades = r.json()
                for t in trades:
                    ts        = int(t.get("timestamp", 0))
                    market_id = t.get("conditionId") or t.get("market", "")
                    trade = {
                        "tx_hash":     t.get("transactionHash") or f"{wallet}_{ts}",
                        "wallet":      wallet,
                        "market_id":   market_id,
                        "market_name": t.get("title") or t.get("question") or "",
                        "side":        t.get("side", "YES"),
                        "amount_usd":  float(t.get("usdcSize") or t.get("amount") or 0),
                        "price":       float(t.get("price") or 0),
                        "timestamp":   ts
                    }
                    if trade["amount_usd"] > 0:
                        db.save_trade(trade)
                        if market_id and trade["price"] > 0:
                            db.save_price(market_id, trade["price"], ts)

        except Exception as e:
            print(f"[BACKFILL] Error {wallet[:12]}: {e}")

        time.sleep(0.3)

    print("[BACKFILL] Completo")
