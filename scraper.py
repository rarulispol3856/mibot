import requests
import time
import json
import database as db

DATA_API  = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

def fetch_top_wallets(limit=100):
    endpoints = [
        f"{DATA_API}/leaderboard?limit={limit}",
        f"{DATA_API}/leaderboard?limit={limit}&window=monthly",
        f"{DATA_API}/leaderboard?limit={limit}&window=all",
        f"{GAMMA_API}/leaderboard?limit={limit}",
    ]

    for url in endpoints:
        try:
            r = requests.get(url, timeout=15)
            print(f"[SCRAPER] {url} -> {r.status_code} | {r.text[:200]}")

            if r.status_code == 200:
                data = r.json()

                if isinstance(data, list) and len(data) > 0:
                    wallets = []

                    for entry in data:
                        addr = (
                            entry.get("proxyWallet")
                            or entry.get("proxyAddress")
                            or entry.get("address")
                            or entry.get("user")
                            or ""
                        )

                        if addr:
                            wallets.append(addr)

                    if wallets:
                        print(f"[SCRAPER] Encontradas {len(wallets)} wallets")
                        return wallets

        except Exception as e:
            print(f"[SCRAPER] Error {url}: {e}")

    print("[SCRAPER] Todos los endpoints fallaron — usando wallets hardcoded")

    return [
        "0x4B1C56e3fC2Be265E2a4E28d64CC7CF5a2694f6",
        "0xe28B9d5e1c5D59e20aD09ABb9B3562F4FfAabEC",
        "0xC7E04d0E86f4E2E95c19b8b29aF2E0F75C1d6a4",
    ]

def fetch_wallet_activity(wallet: str, limit=50):
    try:
        r = requests.get(f"{DATA_API}/activity", params={
            "user":          wallet.lower(),
            "type":          "TRADE",
            "limit":         limit,
            "sortBy":        "TIMESTAMP",
            "sortDirection": "DESC"
        }, timeout=15)
        print(f"[SCRAPER] activity {wallet[:10]} -> {r.status_code} | {r.text[:150]}")
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SCRAPER] Error activity {wallet[:10]}: {e}")
        return []

def fetch_active_markets(limit=200):
    try:
        r = requests.get(f"{GAMMA_API}/markets", params={
            "active": "true", "closed": "false",
            "limit": limit, "order": "volume24hr", "ascending": "false"
        }, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[SCRAPER] Error markets: {e}")
        return []

_market_name_cache = {}
_wallets_to_monitor = set()
_ultimo_ts_por_wallet = {}

def build_market_cache():
    markets = fetch_active_markets(limit=200)
    for m in markets:
        mid  = m.get("conditionId") or m.get("id", "")
        name = m.get("question") or m.get("title", "")
        if mid and name:
            _market_name_cache[mid] = name
    print(f"[SCRAPER] Cache mercados: {len(_market_name_cache)} entradas")

def get_market_name(market_id: str) -> str:
    return _market_name_cache.get(market_id, market_id[:30])

def update_wallets_to_monitor():
    global _wallets_to_monitor
    top = fetch_top_wallets(limit=100)
    _wallets_to_monitor.update(top)
    scored = db.get_top_wallets(limit=50)
    for w in scored:
        _wallets_to_monitor.add(w["wallet"])
    print(f"[SCRAPER] Monitoreando {len(_wallets_to_monitor)} wallets")

def scrape_trades():
    print("[SCRAPER] Iniciando ciclo...")
    nuevos = 0

    for wallet in list(_wallets_to_monitor):
        trades = fetch_wallet_activity(wallet, limit=20)
        for t in trades:
            ts        = int(t.get("timestamp", 0))
            ultimo    = _ultimo_ts_por_wallet.get(wallet, 0)
            if ts <= ultimo:
                continue
            market_id = (t.get("conditionId") or t.get("market") or t.get("marketId", ""))
            trade = {
                "tx_hash":     t.get("transactionHash") or f"{wallet}_{ts}",
                "wallet":      wallet,
                "market_id":   market_id,
                "market_name": (t.get("title") or t.get("question") or get_market_name(market_id)),
                "side":        t.get("side", "YES"),
                "amount_usd":  float(t.get("usdcSize") or t.get("amount") or 0),
                "price":       float(t.get("price") or 0),
                "timestamp":   ts
            }
            if trade["amount_usd"] > 0:
                db.save_trade(trade)
                if market_id and trade["price"] > 0:
                    db.save_price(market_id, trade["price"], ts)
                nuevos += 1
                if ts > _ultimo_ts_por_wallet.get(wallet, 0):
                    _ultimo_ts_por_wallet[wallet] = ts
        time.sleep(0.15)

    print(f"[SCRAPER] Ciclo completado — {nuevos} trades nuevos")

def backfill_history(days_back=90):
    print(f"[BACKFILL] Iniciando...")
    since_ts = int(time.time()) - (days_back * 86400)
    wallets  = fetch_top_wallets(limit=200)
    for i, wallet in enumerate(wallets):
        print(f"[BACKFILL] {i+1}/{len(wallets)} — {wallet[:12]}...")
        try:
            r = requests.get(f"{DATA_API}/activity", params={
                "user": wallet.lower(), "type": "TRADE",
                "limit": 500, "start": since_ts
            }, timeout=20)
            if r.status_code == 200:
                for t in r.json():
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
        except Exception as e:
            print(f"[BACKFILL] Error {wallet[:12]}: {e}")
        time.sleep(0.3)
    print("[BACKFILL] Completo")
