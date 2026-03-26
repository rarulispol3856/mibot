# Mibot — Polymarket Insider Tracker

Bot que detecta wallets sospechosas en Polymarket y encuentra mercados correlacionados.

## Archivos

```
mibot/
├── main.py              # FastAPI — servidor principal
├── scraper.py           # Lee trades de Polymarket cada 30s
├── score_engine.py      # Calcula score insider por wallet
├── correlation_engine.py# Encuentra mercados relacionados
├── database.py          # SQLite — guarda todo
├── backfill.py          # Descarga historial (correr una vez)
├── requirements.txt     # Dependencias Python
├── Procfile             # Para Railway
├── .env                 # Variables de entorno (no subir a GitHub)
└── static/
    └── index.html       # Dashboard web
```

## Setup

### 1. Variables de entorno
En Railway → Variables, agregar:
```
ALCHEMY_API_KEY = tu_api_key_de_alchemy
```

### 2. Deploy en Railway
1. Subir todos los archivos a GitHub
2. Railway detecta el Procfile y hace deploy automático

### 3. Opcional: Backfill histórico
Para tener correlaciones desde el día 1, correr localmente antes de deployar:
```bash
pip install -r requirements.txt
python backfill.py
```
Luego subir el archivo `data/mibot.db` generado al servidor.

## Uso
- Abre la URL de Railway en el browser
- El bot scraping cada 30s automáticamente
- Click en una alerta para ver mercados correlacionados
