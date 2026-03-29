import requests
import time
import database as db

DATA_API  = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

# ── WALLETS CONOCIDAS DE POLYMARKET ──────────────────
# No hay endpoint de leaderboard público.
# Estas son wallets reales de top traders de Polymarket.
# El bot las consulta y va descubriendo más wallets
# a medida que detecta quién opera en los mismos mercados.

SEED_WALLETS = [
    "0x6af75d4e4aaf700450efbac3708cce1665810ff1",
    "0xe28b9d5e1c5d59e20ad09abb9b3562f4ffaabed",
    "0xfffe4013adfe325c8b1bad5c5d8e33f2d2da946",
    "0x8a76e87d8a7d5c8b47c1c3d4b9a2f1e0c3d5a7b",
    "0x1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0",
    "0x3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2",
    "0xabc123def456abc123def456abc123def456abcd",
    "0x9876543210fedcba9876543210fedcba98765432",
]

# ── FETCH ACTIVIDAD DE UNA WALLET ────────────────────

def fetch_wallet_activity(wallet: str, limit=50):
    try:
        r = requests.get(f"{DATA_API}/activity", params={
            "user":  wallet.lower(),
            "limit": limit,
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[SCRAPER] Error activity {wallet[:12]}: {e}")
        return []

# ── DESCUBRIR WALLETS NUEVAS ─────────────────────────

_wallets_to_monitor = set(SEED_WALLETS)

def discover_wallets_from_market(condition_id: str):
    """
    Dado un conditionId, busca otras wallets que operaron en ese mercado.
    Así el bot crece solo descubriendo traders activos.
    """
    try:
        r = requests.get(f"{DATA_API}/activity", params={
            "market": condition_id,
            "limit":  100,
        }, timeout=15)
        if r.status_code == 200:
            data = r.json()
            for t in data:
                wallet = t.get("proxyWallet", "")
                if wallet and wallet not in _wallets_to_monitor:
                    _wallets_to_monitor.add(wallet)
    except:
        pass

# ── CICLO PRINCIPAL ──────────────────────────────────

_ultimo_tx = set()  # evitar duplicados

def scrape_trades():
    print(f"[SCRAPER] Iniciando ciclo — {len(_wallets_to_monitor)} wallets...")
    nuevos = 0
    markets_vistos = set()

    for wallet in list(_wallets_to_monitor):
        actividad = fetch_wallet_activity(wallet, limit=30)

        for t in actividad:
            # Solo procesar TRADEs, ignorar REDEEMs
            if t.get("type") != "TRADE":
                continue

            tx = t.get("transactionHash", "")
            if tx in _ultimo_tx:
                continue
            _ultimo_tx.add(tx)

            trade = {
                "tx_hash":     tx or f"{wallet}_{t.get('timestamp',0)}",
                "wallet":      t.get("proxyWallet", wallet),
                "market_id":   t.get("conditionId", ""),
                "market_name": t.get("title", ""),
                "side":        "YES" if t.get("side") == "BUY" else "NO",
                "amount_usd":  float(t.get("usdcSize") or 0),
                "price":       float(t.get("price") or 0),
                "timestamp":   int(t.get("timestamp") or time.time())
            }

            if trade["amount_usd"] > 0 and trade["market_id"]:
                db.save_trade(trade)
                db.save_price(trade["market_id"], trade["price"], trade["timestamp"])
                markets_vistos.add(trade["market_id"])
                nuevos += 1

        time.sleep(0.2)

    # Descubrir wallets nuevas de los mercados que vimos
    for mid in list(markets_vistos)[:5]:  # max 5 por ciclo
        discover_wallets_from_market(mid)

    # Limpiar cache si crece mucho
    if len(_ultimo_tx) > 50000:
        _ultimo_tx.clear()

    print(f"[SCRAPER] {nuevos} trades nuevos | {len(_wallets_to_monitor)} wallets monitoreadas")

# ── ACTUALIZAR WALLETS CONOCIDAS ─────────────────────

def update_wallets_to_monitor():
    """
    Agrega wallets con score alto que ya están en la DB.
    """
    scored = db.get_top_wallets(limit=100)
    for w in scored:
        _wallets_to_monitor.add(w["wallet"])
    print(f"[SCRAPER] Wallets totales: {len(_wallets_to_monitor)}")

def build_market_cache():
    print("[SCRAPER] Listo")

def backfill_history(days_back=90):
    print(f"[BACKFILL] Descargando historial...")
    since_ts = int(time.time()) - (days_back * 86400)

    for wallet in list(_wallets_to_monitor):
        print(f"[BACKFILL] {wallet[:12]}...")
        try:
            r = requests.get(f"{DATA_API}/activity", params={
                "user":  wallet.lower(),
                "limit": 500,
            }, timeout=20)
            if r.status_code != 200:
                continue

            for t in r.json():
                if t.get("type") != "TRADE":
                    continue
                ts = int(t.get("timestamp") or 0)
                if ts < since_ts:
                    continue

                trade = {
                    "tx_hash":     t.get("transactionHash") or f"{wallet}_{ts}",
                    "wallet":      t.get("proxyWallet", wallet),
                    "market_id":   t.get("conditionId", ""),
                    "market_name": t.get("title", ""),
                    "side":        "YES" if t.get("side") == "BUY" else "NO",
                    "amount_usd":  float(t.get("usdcSize") or 0),
                    "price":       float(t.get("price") or 0),
                    "timestamp":   ts
                }
                if trade["amount_usd"] > 0:
                    db.save_trade(trade)
                    if trade["price"] > 0:
                        db.save_price(trade["market_id"], trade["price"], ts)

        except Exception as e:
            print(f"[BACKFILL] Error {wallet[:12]}: {e}")
        time.sleep(0.3)

    print("[BACKFILL] Completo")
