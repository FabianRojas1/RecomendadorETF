# Recomendador de Inversiones

Sistema automático que analiza tu portafolio ETF y envía recomendaciones a Telegram.

## Setup

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Verificar que el bot funciona
python main.py --test

# 3. Correr análisis completo ahora (+ envío a Telegram)
python main.py --now

# 4. Dejar corriendo en background (análisis cada domingo 19:00)
python main.py
```

## Comandos

| Comando | Descripción |
|---------|-------------|
| `python main.py` | Inicia el scheduler (corre indefinidamente) |
| `python main.py --now` | Ejecuta análisis completo ahora mismo |
| `python main.py --test` | Verifica configuración + mensaje de prueba a Telegram |

## Estructura

```
recomendador-inversiones/
├── main.py           # Punto de entrada
├── config.py         # Configuración y constantes
├── .env              # Tokens y API keys (no subir a git)
├── portfolio.csv     # Tu portafolio actual
├── requirements.txt
├── data/
│   └── inversiones.db  # SQLite (se crea automáticamente)
├── src/
│   ├── data_loader.py   # yfinance + SQLite
│   ├── indicators.py    # SMA, EMA, RSI, ADX, Squeeze, OBV, CMF
│   ├── scoring.py       # Matriz de scoring -40 a +40
│   ├── news_analyzer.py # NewsAPI + sentimiento
│   ├── telegram_bot.py  # Notificaciones
│   └── scheduler.py     # APScheduler (daily + weekly)
└── output/           # Reportes generados
```

## Tickers de Trii

Los tickers de Trii (IUITCO, IUFSCO, etc.) son mapeados a sus equivalentes
en yfinance para el análisis técnico:

| Trii | yfinance | Descripción |
|------|----------|-------------|
| IUITCO | IYW | iShares US Technology |
| IUFSCO | IYF | iShares US Financials |
| IUESCO | XLU | SPDR Utilities |
| CSPXCO | SPY | S&P 500 |
| BACCO | BAC | Bank of America |
| AAPLCO | AAPL | Apple Inc. |
