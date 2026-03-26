"""
backfill.py — Corre UNA SOLA VEZ antes de deployar.

Descarga historial completo de Polymarket para que el bot
arranque con correlaciones ya calculadas desde el primer día.

Uso:
    python backfill.py
"""

import database as db
import scraper
import correlation_engine

if __name__ == "__main__":
    print("=" * 50)
    print("BACKFILL — Descargando historial de Polymarket")
    print("Esto puede tardar 4-8 horas. Déjalo correr.")
    print("=" * 50)

    # 1. Inicializar DB
    db.init_db()

    # 2. Descargar historial (90 días)
    scraper.backfill_history(days_back=90)

    # 3. Calcular correlaciones con el historial descargado
    print("\n[BACKFILL] Calculando correlaciones...")
    correlation_engine.construir_matriz()

    print("\n✅ Backfill completo. Ya puedes deployar el bot.")
