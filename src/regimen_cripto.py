"""
regimen_cripto.py - Indicadores propios del bloque cripto.

Cripto no hereda el regimen de las acciones: tiene sus propios drivers. Todos
los indicadores de aqui son gratuitos y sin registro.

  Fear & Greed        api.alternative.me   sentimiento del mercado cripto
  Dominancia de BTC   api.coingecko.com    rotacion entre BTC y el resto
  Oferta de stables   api.coingecko.com    proxy de entrada/salida de capital
  Correlacion BTC-NDX yfinance             si cripto cotiza como tecnologia

Cada indicador falla por separado: si una API no responde, ese indicador queda
en "N/D" y los demas siguen. Nunca lanza excepcion.
"""
import logging

logger = logging.getLogger(__name__)

TIMEOUT_S = 15


def _nd(nombre, nota="Sin datos"):
    return {"name": nombre, "value": "N/D", "prev": "—", "dir": "—",
            "signal": "N/D", "note": nota}


def _dir(actual, previo, umbral=0.0):
    if previo is None:
        return "—"
    if actual > previo + umbral:
        return "↑"
    if actual < previo - umbral:
        return "↓"
    return "↔"


# ── Fear & Greed ──────────────────────────────────────────────────────────────

def _fear_greed() -> dict:
    try:
        import requests
        r = requests.get("https://api.alternative.me/fng/?limit=8", timeout=TIMEOUT_S)
        datos = r.json().get("data") or []
        if not datos:
            return _nd("Fear & Greed cripto")
        actual = int(datos[0]["value"])
        previo = int(datos[1]["value"]) if len(datos) > 1 else None
        etiqueta = str(datos[0].get("value_classification", "")).strip()

        # Racha: cuantas lecturas seguidas en zona extrema. Un valor extremo
        # aislado es ruido; sostenido en el tiempo si dice algo.
        racha = 0
        for d in datos:
            v = int(d["value"])
            if (actual >= 75 and v >= 75) or (actual <= 25 and v <= 25):
                racha += 1
            else:
                break
        nota = "Contrario: >75 euforia, <25 panico"
        if racha >= 3:
            nota = f"{racha} lecturas seguidas en zona extrema"

        return {"name": "Fear & Greed cripto", "value": f"{actual} ({etiqueta})",
                "prev": f"{previo}" if previo is not None else "—",
                "dir": _dir(actual, previo, 2),
                "signal": "BAJISTA" if actual >= 75 else "ALCISTA" if actual <= 25 else "NEUTRAL",
                "note": nota}
    except Exception as e:
        logger.debug("Fear & Greed: %s", e)
        return _nd("Fear & Greed cripto", "API no disponible")


# ── Dominancia de BTC ─────────────────────────────────────────────────────────

def _dominancia_btc() -> dict:
    try:
        import requests
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=TIMEOUT_S)
        d = (r.json().get("data") or {})
        dom = float((d.get("market_cap_percentage") or {}).get("btc"))
        cambio = d.get("market_cap_change_percentage_24h_usd")
        return {"name": "Dominancia de BTC", "value": f"{dom:.1f}%",
                "prev": "—", "dir": "—", "signal": "NEUTRAL",
                "note": ("Dominancia alta: el capital se refugia en BTC; "
                         "si cae con mercado al alza, hay rotacion a altcoins"
                         + (f" | Capitalizacion total 24h: {cambio:+.1f}%"
                            if isinstance(cambio, (int, float)) else ""))}
    except Exception as e:
        logger.debug("Dominancia BTC: %s", e)
        return _nd("Dominancia de BTC", "API no disponible")


# ── Oferta de stablecoins ─────────────────────────────────────────────────────

def _oferta_stablecoins() -> dict:
    """USDT como proxy: si su capitalizacion crece, entra capital al ecosistema."""
    try:
        import requests
        r = requests.get(
            "https://api.coingecko.com/api/v3/coins/tether/market_chart",
            params={"vs_currency": "usd", "days": "30", "interval": "daily"},
            timeout=TIMEOUT_S)
        serie = r.json().get("market_caps") or []
        if len(serie) < 2:
            return _nd("Oferta de stablecoins (USDT)")
        actual, previo = float(serie[-1][1]), float(serie[0][1])
        var = (actual - previo) / previo * 100 if previo else 0.0
        return {"name": "Oferta de stablecoins (USDT)",
                "value": f"${actual/1e9:,.1f}B",
                "prev": f"${previo/1e9:,.1f}B (hace 30d)",
                "dir": _dir(actual, previo, previo * 0.005),
                "signal": "ALCISTA" if var > 1 else "BAJISTA" if var < -1 else "NEUTRAL",
                "note": f"{var:+.1f}% en 30 dias — proxy de capital entrando o saliendo"}
    except Exception as e:
        logger.debug("Stablecoins: %s", e)
        return _nd("Oferta de stablecoins (USDT)", "API no disponible")


# ── Correlacion BTC vs Nasdaq ─────────────────────────────────────────────────

def _correlacion_btc_ndx() -> dict:
    try:
        import yfinance as yf
        datos = yf.download(["BTC-USD", "^NDX"], period="6mo",
                            auto_adjust=True, progress=False)["Close"].dropna()
        if len(datos) < 40:
            return _nd("Correlacion BTC vs Nasdaq")
        ret = datos.pct_change().dropna()
        corr_actual = float(ret["BTC-USD"].tail(30).corr(ret["^NDX"].tail(30)))
        corr_previa = float(ret["BTC-USD"].head(30).corr(ret["^NDX"].head(30)))
        if corr_actual >= 0.6:
            nota = "Cripto cotiza como tecnologia: no diversifica frente a QQQ"
        elif corr_actual <= 0.2:
            nota = "Cripto se mueve por su cuenta: aporta diversificacion"
        else:
            nota = "Correlacion intermedia"
        return {"name": "Correlacion BTC vs Nasdaq (30d)", "value": f"{corr_actual:.2f}",
                "prev": f"{corr_previa:.2f} (hace 6m)",
                "dir": _dir(corr_actual, corr_previa, 0.05),
                "signal": "NEUTRAL", "note": nota}
    except Exception as e:
        logger.debug("Correlacion BTC-NDX: %s", e)
        return _nd("Correlacion BTC vs Nasdaq (30d)", "Datos no disponibles")


# ── Entrada publica ───────────────────────────────────────────────────────────

def indicadores_cripto() -> dict:
    """Devuelve los indicadores del bloque cripto. Nunca lanza excepcion."""
    out = {}
    for clave, fn in (("fear_greed", _fear_greed),
                      ("dominancia_btc", _dominancia_btc),
                      ("stablecoins", _oferta_stablecoins),
                      ("correlacion_ndx", _correlacion_btc_ndx)):
        try:
            out[clave] = fn()
        except Exception as e:                      # cinturon y tirantes
            logger.warning("Indicador cripto %s fallo: %s", clave, e)
            out[clave] = _nd(clave)
    disponibles = sum(1 for v in out.values() if v.get("value") != "N/D")
    logger.info("Indicadores cripto obtenidos: %d/%d", disponibles, len(out))
    return out
