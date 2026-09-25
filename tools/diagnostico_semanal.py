"""
Diagnóstico vela a vela del marco SEMANAL, para comparar con TradingView.

Uso (desde la raíz del repo, con el entorno del proyecto activo):
    python tools/diagnostico_semanal.py GNRC
    python tools/diagnostico_semanal.py GNRC --velas 12

Imprime las últimas velas semanales CERRADAS (la semana en curso no cuenta,
igual que el motor) con los mismos cálculos que usa el reporte, y luego el
checklist LP/MP completo. En TradingView compara contra la vela ANTERIOR a la
actual: la última vela del gráfico es la semana que todavía no ha cerrado.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pandas_ta as ta

from config import Config
from src.data_loader import DataLoader
from src.indicators import IndicatorCalculator
from tools.probar_lp_mp import analizar

COLOR = {"green_strong": "verde_claro", "green_weak": "verde_oscuro",
         "red_strong": "rojo_claro", "red_weak": "rojo_oscuro"}


def _color(cur, prev):
    """Misma regla que indicators._calc_squeeze_lazybear."""
    if pd.isna(cur) or pd.isna(prev):
        return "—"
    if cur >= 0 and cur >= prev:
        return "verde_claro"
    if cur >= 0:
        return "verde_oscuro"
    if cur <= prev:
        return "rojo_claro"
    return "rojo_oscuro"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ticker = (args or ["GNRC"])[0].upper()
    n = int(sys.argv[sys.argv.index("--velas") + 1]) if "--velas" in sys.argv else 8

    loader = DataLoader(Config())
    df = loader.download_history(ticker)
    calc = IndicatorCalculator(df)
    w = calc._resample_ohlcv("W")          # velas semanales cerradas (lunes-viernes, cierre del viernes)
    c, h, l, v = w["Close"], w["High"], w["Low"], w["Volume"]

    adx = calc._calc_adx_extended(h, l, c)
    L = 20
    delta = c - ((h.rolling(L).max() + l.rolling(L).min()) / 2 + ta.sma(c, length=L)) / 2
    hist = ta.linreg(delta, length=L)
    obv = ta.obv(c, v)

    t = pd.DataFrame({
        "cierre": c, "EMA10": ta.ema(c, length=10), "EMA55": ta.ema(c, length=55),
        "ATR14": ta.atr(h, l, c, length=14), "ADX": adx["adx"], "+DI": adx["plus_di"], "-DI": adx["minus_di"],
        "SQZ": hist, "OBV": obv, "OBV_EMA20": ta.ema(obv, length=20),
    })
    t["SQZ color"] = [_color(hist.iloc[i], hist.iloc[i - 1]) if i else "—" for i in range(len(hist))]
    t["cierre>EMA10"] = t["cierre"] > t["EMA10"]
    t["OBV>EMA20"] = t["OBV"] > t["OBV_EMA20"]
    t["ADX hace2"] = t["ADX"].shift(2)
    t["ADX ok"] = (t["ADX"] > 20) & ((t["ADX"] >= t["ADX hace2"]) == (t["+DI"] > t["-DI"]))
    t.index = t.index.strftime("%Y-%m-%d")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 30)
    print(f"\n{ticker} — últimas {n} velas SEMANALES CERRADAS (fecha = cierre de la semana)\n")
    print(t.tail(n).round(2).to_string())
    print("\nADX = versión de TradingView 'ADX and DI for v4' (DI con suma de Wilder, ADX = media simple de DX, 14)")
    print("Gatillo MP (semanal) = [SQZ pasa de rojo_oscuro a verde  O  (cierre > EMA10 con SQZ fuera de rojo_claro)]"
          "  Y  [OBV > EMA20 o divergencia alcista]")
    print("Ubicación MP        = precio a ≤ 1 ATR de EMA55s / EMA200s / mínimo de 12 semanas  Y  ADX > 20 con "
          "pendiente a favor\n                      (ADX subiendo con +DI dominante, o ADX bajando con -DI dominante;"
          " pendiente = ADX vs. 2 velas atrás)\n")
    analizar(ticker, loader)


if __name__ == "__main__":
    main()
