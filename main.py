import time
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

import database as db
import scraper
import score_engine
import correlation_engine

load_dotenv()

app = FastAPI(title="Mibot — Polymarket Insider Tracker")

# ── SCHEDULER (tareas automáticas) ───────────────────

scheduler = BackgroundScheduler()

@app.on_event("startup")
def startup():
    print("[APP] Iniciando bot...")
    db.init_db()

    # Scraping cada 30 segundos
    scheduler.add_job(scraper.scrape_trades, "interval", seconds=30, id="scraper")

    # Recalcular scores cada 5 minutos
    scheduler.add_job(score_engine.recalcular_todos, "interval", minutes=5, id="scores")

    # Reconstruir correlaciones cada hora
    scheduler.add_job(correlation_engine.construir_matriz, "interval", hours=1, id="corr")

    scheduler.start()

    # Primer ciclo inmediato
    scraper.scrape_trades()
    score_engine.recalcular_todos()

    print("[APP] ✅ Bot corriendo")

@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown()

# ── ENDPOINTS API ─────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "ts": int(time.time())}

@app.get("/api/trades")
def get_trades(limit: int = 50):
    """Feed en vivo — últimos trades detectados."""
    trades = db.get_recent_trades(limit=limit)
    return {"trades": trades, "count": len(trades)}

@app.get("/api/wallets")
def get_wallets(limit: int = 20):
    """Top wallets sospechosas ordenadas por score."""
    wallets = db.get_top_wallets(limit=limit)
    return {"wallets": wallets, "count": len(wallets)}

@app.get("/api/wallet/{wallet}")
def get_wallet_detail(wallet: str):
    """Detalle completo de una wallet."""
    score  = db.get_wallet_score(wallet)
    trades = db.get_trades_by_wallet(wallet)
    return {
        "wallet": wallet,
        "score":  score,
        "trades": trades[:30]
    }

@app.get("/api/alerts")
def get_alerts(limit: int = 30):
    """Alertas generadas por el score engine."""
    alerts = db.get_alerts(limit=limit)
    return {"alerts": alerts, "count": len(alerts)}

@app.get("/api/correlated/{market_id}")
def get_correlated(market_id: str):
    """
    Dado un market_id, retorna mercados correlacionados
    que todavía no se movieron.
    """
    relacionados = correlation_engine.encontrar_relacionados(market_id)
    return {"market_id": market_id, "related": relacionados}

@app.get("/api/stats")
def get_stats():
    """Stats generales para el header del dashboard."""
    wallets      = db.get_all_wallets()
    alerts       = db.get_alerts(limit=1000)
    alertas_hoy  = [
        a for a in alerts
        if a["timestamp"] > int(time.time()) - 86400
    ]
    return {
        "wallets_monitored": len(wallets),
        "alerts_today":      len(alertas_hoy),
        "total_alerts":      len(alerts)
    }

# ── SERVIR EL DASHBOARD ───────────────────────────────

# Archivos estáticos (CSS, JS extra si los hubiera)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_dashboard():
    """Sirve el dashboard HTML."""
    return FileResponse(os.path.join(static_dir, "index.html"))
