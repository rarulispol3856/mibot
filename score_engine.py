import time
import database as db

INSIDER_THRESHOLD = 75  # score mínimo para generar alerta

# ── SCORE PRINCIPAL ──────────────────────────────────

def calcular_score(wallet: str) -> dict | None:
    """
    Calcula el score insider de una wallet (0-100).
    Retorna None si no hay suficientes datos.
    """
    trades = db.get_trades_by_wallet(wallet)

    if len(trades) < 5:
        return None  # muy pocos datos

    # ── Factor 1: Win Rate (peso 30%) ─────────────────
    resueltos = [t for t in trades if t.get("outcome")]
    if len(resueltos) < 3:
        win_rate = 0.5  # neutral si no hay resoluciones
    else:
        ganados  = sum(1 for t in resueltos if t["outcome"] == t["side"])
        win_rate = ganados / len(resueltos)

    # ── Factor 2: Timing Score (peso 40%) ─────────────
    # ¿Cuántas horas antes de la resolución compró?
    # Menor tiempo = más sospechoso
    trades_con_timing = [
        t for t in resueltos
        if t.get("resolve_ts") and t.get("timestamp")
    ]

    if trades_con_timing:
        tiempos_hrs = [
            (t["resolve_ts"] - t["timestamp"]) / 3600
            for t in trades_con_timing
        ]
        promedio_hrs = sum(tiempos_hrs) / len(tiempos_hrs)
        # Normalizar: 0h=1.0 (muy sospechoso), 168h+=0.0 (una semana = normal)
        timing_score = max(0, 1 - (promedio_hrs / 168))
    else:
        timing_score = 0.3  # neutral

    # ── Factor 3: Price Efficiency (peso 20%) ──────────
    # ¿Compró a odds bajas y ganó? Eso es imposible por suerte
    compras_bajas = [
        t for t in resueltos
        if t.get("price", 1) < 0.25 and t["outcome"] == t["side"]
    ]
    if len(resueltos) > 0:
        price_eff = len(compras_bajas) / len(resueltos)
    else:
        price_eff = 0

    # ── Factor 4: Concentración temática (peso 10%) ────
    # Si siempre apuesta en el mismo mercado, puede tener fuente específica
    mercados = [t["market_id"] for t in trades]
    if mercados:
        from collections import Counter
        conteo  = Counter(mercados)
        total   = len(mercados)
        herfindahl = sum((v/total)**2 for v in conteo.values())
        # 1.0 = todo en un mercado (muy concentrado), 0 = muy diverso
        concentracion = herfindahl
    else:
        concentracion = 0

    # ── Score final ───────────────────────────────────
    score = (
        win_rate      * 0.30 +
        timing_score  * 0.40 +
        price_eff     * 0.20 +
        concentracion * 0.10
    ) * 100

    # ── P&L estimado ──────────────────────────────────
    pnl = 0
    for t in resueltos:
        if t["outcome"] == t["side"]:
            pnl += t["amount_usd"] * (1 / t["price"] - 1) if t["price"] > 0 else 0
        else:
            pnl -= t["amount_usd"]

    # ── Timing promedio en horas ───────────────────────
    avg_timing = promedio_hrs if trades_con_timing else 0

    resultado = {
        "wallet":         wallet,
        "score":          round(score, 1),
        "win_rate":       round(win_rate * 100, 1),
        "total_trades":   len(trades),
        "total_pnl":      round(pnl, 2),
        "avg_timing_hrs": round(avg_timing, 1),
        "last_updated":   int(time.time())
    }

    return resultado

# ── ACTUALIZAR TODOS LOS SCORES ──────────────────────

def recalcular_todos():
    """
    Corre cada 5 minutos.
    Recalcula el score de todas las wallets que tienen trades.
    """
    print("[SCORE] Recalculando scores...")
    wallets  = db.get_all_wallets()
    alertas  = 0

    for wallet in wallets:
        resultado = calcular_score(wallet)
        if resultado is None:
            continue

        db.save_score(resultado)

        # Generar alerta si supera el umbral
        if resultado["score"] >= INSIDER_THRESHOLD:
            _generar_alerta_si_nueva(wallet, resultado)
            alertas += 1

    print(f"[SCORE] {len(wallets)} wallets procesadas — {alertas} con score alto")

def _generar_alerta_si_nueva(wallet: str, score_data: dict):
    """Genera alerta solo si no hay una reciente (última hora) para esa wallet."""
    alertas_recientes = db.get_alerts(limit=100)
    hace_una_hora     = int(time.time()) - 3600

    ya_alertado = any(
        a["wallet"] == wallet and a["timestamp"] > hace_una_hora
        for a in alertas_recientes
    )

    if ya_alertado:
        return

    # Buscar último trade de esta wallet para los detalles
    trades = db.get_trades_by_wallet(wallet)
    if not trades:
        return

    ultimo = trades[0]

    alerta = {
        "wallet":      wallet,
        "market_id":   ultimo["market_id"],
        "market_name": ultimo["market_name"],
        "amount_usd":  ultimo["amount_usd"],
        "price_entry": ultimo["price"],
        "score":       score_data["score"],
        "timestamp":   int(time.time())
    }

    db.save_alert(alerta)
    print(f"[SCORE] 🚨 Alerta generada — {wallet[:10]}... score={score_data['score']}")
