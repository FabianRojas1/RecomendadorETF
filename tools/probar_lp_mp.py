"""
Prueba manual del motor LP/MP con datos reales.

Uso (desde la raiz del repo, con el entorno del proyecto activo):
    python tools/probar_lp_mp.py                 -> 6 tickers de muestra
    python tools/probar_lp_mp.py SPY QQQ BTC     -> los que le indiques
    python tools/probar_lp_mp.py --todos         -> todo el portafolio

No envia nada a Telegram ni genera PDF: solo imprime el checklist en pantalla.
"""
import sys, os, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING)

from config import Config
from src.data_loader import DataLoader
from src.indicators import IndicatorCalculator
from src import signals as lp_mp

MUESTRA = ["SPY", "QQQ", "XLV", "BTC", "ETH", "VWO"]


def marca(cumple):
    return "[x]" if cumple is True else "[ ]" if cumple is False else "[?]"


def imprimir_bloque(titulo, items):
    print(f"  {titulo}")
    for i in items:
        print(f"    {marca(i['cumple'])} {i['item']}")
        if i.get("detalle"):
            print(f"        {i['detalle']}")


def analizar(ticker, loader):
    print("=" * 74)
    print(f"  {ticker}")
    print("=" * 74)
    df = loader.download_history(ticker)
    if df is None or df.empty or len(df) < 60:
        print("  Sin datos suficientes.\n")
        return

    calc = IndicatorCalculator(df)
    vals = calc.get_current(calc.calculate())
    r = lp_mp.evaluar(vals)
    lp, mp, comb = r["lp"], r["mp"], r["combinada"]

    print(f"  Velas: {len(df)} diarias | {vals.get('sem_barras')} semanales | "
          f"{vals.get('men_barras')} mensuales")
    print(f"  Precio: {vals.get('close'):,.2f}")
    e200 = vals.get("men_ema200")
    print(f"  EMA200 de referencia: {e200:,.2f}" if e200 else "  EMA200: sin datos",
          "(proxy semanal)" if vals.get("men_ema200_proxy") else "")
    print(f"  SQZ mensual: {vals.get('men_sqz_color')} | "
          f"SQZ semanal: {vals.get('sem_sqz_color')} (previo {vals.get('sem_sqz_color_prev')})")
    print()

    print(f"  LARGO PLAZO: {lp['estado']} ({lp['confianza_pct']}%)")
    imprimir_bloque("Tendencia:", lp["tendencia"])
    imprimir_bloque("Zona de compra:", lp["zona_compra"])
    if lp.get("invalidacion"):
        print(f"    Nivel de invalidacion: {lp['invalidacion']:,.2f}")
    print()

    print(f"  MEDIANO PLAZO: {mp['estado']} ({mp['confianza_pct']}%)")
    imprimir_bloque("Contexto (mensual):", mp["contexto"])
    imprimir_bloque("Ubicacion (semanal):", mp["ubicacion"])
    imprimir_bloque("Gatillo (semanal):", mp["gatillo"])
    if mp["ventas"].get("motivos"):
        print(f"    Señales de venta MP: {', '.join(mp['ventas']['motivos'])}")
    print()

    print(f"  >>> {comb['accion']} [{comb['horizonte']}] — {comb['texto']}")
    for a in comb["avisos"]:
        print(f"      ! {a}")
    for n in lp["notas"] + mp["notas"]:
        print(f"      nota: {n}")
    print()


def main():
    config = Config()
    loader = DataLoader(config)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if "--todos" in sys.argv:
        tickers = loader.load_portfolio()["ticker"].tolist()
    elif args:
        tickers = args
    else:
        tickers = MUESTRA

    for t in tickers:
        try:
            analizar(t, loader)
        except Exception as e:
            print(f"  ERROR en {t}: {e}\n")


if __name__ == "__main__":
    main()
