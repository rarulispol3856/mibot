import time
import database as db

# Cache en memoria para no recalcular en cada request
_correlation_cache: dict = {}
_cache_ts: int = 0
CACHE_TTL = 3600  # recalcular cada hora

# ── CALCULAR CORRELACIÓN ENTRE DOS SERIES ────────────

def pearson(a: list, b: list) -> float:
    """Correlación de Pearson entre dos listas de precios."""
    n = min(len(a), len(b))
    if n < 10:
        return 0.0

    a = a[:n]
    b = b[:n]

    mean_a = sum(a) / n
    mean_b = sum(b) / n

    num   = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n))
    den_a = sum((x - mean_a) ** 2 for x in a) ** 0.5
    den_b = sum((x - mean_b) ** 2 for x in b) ** 0.5

    if den_a == 0 or den_b == 0:
        return 0.0

    return round(num / (den_a * den_b), 3)

# ── CONSTRUIR MATRIZ DE CORRELACIONES ────────────────

def construir_matriz():
    """
    Corre una vez por noche.
    Calcula correlación entre todos los pares de mercados.
    """
    global _correlation_cache, _cache_ts

    print("[CORR] Construyendo matriz de correlaciones...")
    market_ids = db.get_all_market_ids()

    if len(market_ids) < 2:
        print("[CORR] No hay suficientes mercados todavía")
        return

    # Cargar historial de precios por mercado
    historiales = {}
    for mid in market_ids:
        rows = db.get_price_history(mid, limit=90)
        if len(rows) >= 10:
            historiales[mid] = [r["price"] for r in rows]

    # Calcular correlaciones para todos los pares
    matriz = {}
    ids    = list(historiales.keys())

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            id_a = ids[i]
            id_b = ids[j]
            corr = pearson(historiales[id_a], historiales[id_b])

            if abs(corr) >= 0.5:  # solo guardar correlaciones significativas
                matriz[f"{id_a}|{id_b}"] = corr
                matriz[f"{id_b}|{id_a}"] = corr

    _correlation_cache = matriz
    _cache_ts = int(time.time())
    print(f"[CORR] Matriz construida — {len(matriz)//2} pares significativos")

# ── ENCONTRAR MERCADOS RELACIONADOS ──────────────────

def encontrar_relacionados(trigger_market_id: str, top_n=6) -> list:
    """
    Dado un mercado trigger (donde el insider operó),
    retorna los mercados más correlacionados que todavía no se movieron.
    """
    global _correlation_cache, _cache_ts

    # Reconstruir cache si está vencido
    if not _correlation_cache or (int(time.time()) - _cache_ts) > CACHE_TTL:
        construir_matriz()

    resultados = []

    for key, corr in _correlation_cache.items():
        id_a, id_b = key.split("|")

        if id_a != trigger_market_id:
            continue

        # Verificar si el mercado relacionado ya se movió
        # (si ya se movió, el edge se fue)
        history = db.get_price_history(id_b, limit=6)  # últimas 6 entradas ~1 hora

        if len(history) < 2:
            continue

        precio_actual  = history[0]["price"]
        precio_anterior = history[-1]["price"]

        if precio_anterior == 0:
            continue

        movimiento_reciente = abs(precio_actual - precio_anterior) / precio_anterior

        # Solo incluir si no se movió más del 8% (todavía hay edge)
        if movimiento_reciente < 0.08:
            resultados.append({
                "market_id":         id_b,
                "correlacion":       corr,
                "precio_actual":     round(precio_actual * 100, 1),
                "movimiento_1h":     round(movimiento_reciente * 100, 2),
                "direccion":         "YES" if corr > 0 else "NO",
                "tipo":              "directo" if corr > 0 else "inverso"
            })

    # Ordenar por correlación absoluta más fuerte
    resultados.sort(key=lambda x: abs(x["correlacion"]), reverse=True)
    return resultados[:top_n]
