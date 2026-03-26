import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "mibot.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()

    # Todos los trades que el scraper detecta
    c.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_hash     TEXT UNIQUE,
            wallet      TEXT,
            market_id   TEXT,
            market_name TEXT,
            side        TEXT,
            amount_usd  REAL,
            price       REAL,
            timestamp   INTEGER,
            resolved    INTEGER DEFAULT 0,
            outcome     TEXT,
            resolve_ts  INTEGER
        )
    """)

    # Score calculado por wallet
    c.execute("""
        CREATE TABLE IF NOT EXISTS wallet_scores (
            wallet          TEXT PRIMARY KEY,
            score           REAL,
            win_rate        REAL,
            total_trades    INTEGER,
            total_pnl       REAL,
            avg_timing_hrs  REAL,
            last_updated    INTEGER
        )
    """)

    # Historial de precios por mercado (para correlaciones)
    c.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            market_id  TEXT,
            price      REAL,
            timestamp  INTEGER
        )
    """)

    # Alertas generadas
    c.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet      TEXT,
            market_id   TEXT,
            market_name TEXT,
            amount_usd  REAL,
            price_entry REAL,
            score       REAL,
            timestamp   INTEGER,
            seen        INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    conn.close()
    print("[DB] Inicializada correctamente")

# ── TRADES ──────────────────────────────────────────

def save_trade(trade: dict):
    conn = get_conn()
    try:
        conn.execute("""
            INSERT OR IGNORE INTO trades
            (tx_hash, wallet, market_id, market_name, side, amount_usd, price, timestamp)
            VALUES (:tx_hash, :wallet, :market_id, :market_name, :side, :amount_usd, :price, :timestamp)
        """, trade)
        conn.commit()
    finally:
        conn.close()

def get_trades_by_wallet(wallet: str):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades WHERE wallet=? ORDER BY timestamp DESC", (wallet,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_recent_trades(limit=50):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_wallets():
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT wallet FROM trades"
    ).fetchall()
    conn.close()
    return [r["wallet"] for r in rows]

# ── SCORES ──────────────────────────────────────────

def save_score(data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO wallet_scores
        (wallet, score, win_rate, total_trades, total_pnl, avg_timing_hrs, last_updated)
        VALUES (:wallet, :score, :win_rate, :total_trades, :total_pnl, :avg_timing_hrs, :last_updated)
    """, data)
    conn.commit()
    conn.close()

def get_top_wallets(limit=20):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM wallet_scores ORDER BY score DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_wallet_score(wallet: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM wallet_scores WHERE wallet=?", (wallet,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

# ── PRICE HISTORY ────────────────────────────────────

def save_price(market_id: str, price: float, timestamp: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO price_history (market_id, price, timestamp) VALUES (?,?,?)",
        (market_id, price, timestamp)
    )
    conn.commit()
    conn.close()

def get_price_history(market_id: str, limit=90):
    conn = get_conn()
    rows = conn.execute("""
        SELECT price, timestamp FROM price_history
        WHERE market_id=?
        ORDER BY timestamp DESC LIMIT ?
    """, (market_id, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_market_ids():
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT market_id FROM price_history"
    ).fetchall()
    conn.close()
    return [r["market_id"] for r in rows]

# ── ALERTS ──────────────────────────────────────────

def save_alert(alert: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO alerts
        (wallet, market_id, market_name, amount_usd, price_entry, score, timestamp)
        VALUES (:wallet, :market_id, :market_name, :amount_usd, :price_entry, :score, :timestamp)
    """, alert)
    conn.commit()
    conn.close()

def get_alerts(limit=30):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
