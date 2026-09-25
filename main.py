"""
main.py — Punto de entrada del recomendador de inversiones.

Modos:
  python main.py           → scheduler daemon (uso local)
  python main.py --now     → análisis semanal inmediato (GitHub Actions)
  python main.py --test    → prueba de conectividad Telegram
"""
import argparse
import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")

# ── Importar módulos del proyecto ──────────────────────────────────────────────
from config             import Config
from src.data_loader    import DataLoader
from src.indicators     import IndicatorCalculator
from src.scoring        import Scorer
from src.news_analyzer  import NewsAnalyzer
from src.telegram_bot   import send_weekly_report, send_test_message
from src.market_regime  import analyze_market_regime
from src              import signals as lp_mp
from src              import estado_senales
from src              import calendario
from src              import ia_sintesis
from src.regimen_cripto import indicadores_cripto
from src                import compras_etf as compras_etf_mod


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "")


# ── Helpers de precio ─────────────────────────────────────────────────────────

def _calc_target(price: float, action: str):
    pct = {"COMPRA FUERTE": 0.10, "COMPRA": 0.08, "VENTA FUERTE": -0.10, "VENTA": -0.08}.get(action)
    return price * (1 + pct) if pct and price else None

def _calc_stop_loss(price: float, action: str):
    pct = {"COMPRA FUERTE": -0.05, "COMPRA": -0.06, "VENTA FUERTE": 0.05, "VENTA": 0.06}.get(action)
    return price * (1 + pct) if pct and price else None


# ── ANÁLISIS SEMANAL ──────────────────────────────────────────────────────────

async def run_weekly_analysis():
    """Descarga datos, calcula indicadores y envía reporte + PDF a Telegram."""
    logger.info("=== Iniciando análisis semanal ===")

    config    = Config()
    loader    = DataLoader(config)
    scorer    = Scorer()
    news_a    = NewsAnalyzer(config)
    cop_rate  = loader.get_cop_usd_rate()
    portfolio = loader.load_portfolio()

    logger.info("Tasa COP/USD: %.0f | Activos: %d", cop_rate, len(portfolio))

    # Análisis macro de régimen de mercado (bull/bear)
    logger.info("Analizando régimen de mercado...")
    regime_data = analyze_market_regime()
    logger.info("Régimen: %s (%.0f%% señales alcistas)",
                regime_data["regime"], regime_data["bull_pct"] * 100)

    # Bloque cripto: indicadores propios, independientes de los de acciones
    logger.info("Descargando indicadores de cripto...")
    cripto_ind = indicadores_cripto()

    # Titulares generales para el contexto (no para puntuar: solo contexto)
    titulares = []
    for t in ("SPY", "BTC"):
        try:
            titulares.extend(news_a.get_news_for_ticker(t, days=30))
        except Exception as e:
            logger.debug("Sin titulares para %s: %s", t, e)

    # Síntesis cualitativa: IA si hay proveedor, reglas en Python si no
    sintesis = ia_sintesis.sintetizar({
        "acciones": {"bull_pct": regime_data.get("bull_pct"),
                     "signals":  regime_data.get("signals"),
                     "macro":    regime_data.get("macro_data")},
        "cripto":   {"indicadores": {k: v.get("value")
                                     for k, v in cripto_ind.items()}},
        "titulares": titulares,
    })
    logger.info("Síntesis de régimen: acciones %s / cripto %s (fuente: %s)",
                sintesis["acciones_usa"]["estado"], sintesis["cripto"]["estado"],
                sintesis["fuente"])

    # Las fechas del bloque "qué vigilar" salen del calendario oficial, no del modelo
    regime_data["sintesis"]           = sintesis
    regime_data["cripto_indicadores"] = cripto_ind
    regime_data["eventos"]            = calendario.proximos_eventos()

    # Memoria de cuanto lleva activa cada señal (sobrevive entre corridas
    # porque el workflow hace commit del JSON al terminar).
    ruta_estado = estado_senales.ruta_por_defecto(config)
    estado_sen  = estado_senales.cargar(ruta_estado)

    recommendations = []
    for _, row in portfolio.iterrows():
        ticker = row["ticker"]
        try:
            df = loader.download_history(ticker)

            if df is None or df.empty or len(df) < 60:
                logger.warning("%s: datos insuficientes, omitido", ticker)
                continue

            calc   = IndicatorCalculator(df)
            ind    = calc.calculate()
            values = calc.get_current(ind)

            news   = news_a.get_news_for_ticker(ticker, days=30)
            result = scorer.score(values, news)

            # Motor LP/MP (checklists de largo y mediano plazo)
            tiene_posicion = float(row.get("current_value", 0) or 0) > 0
            lp_res = lp_mp.evaluar_lp(values)
            mp_res = lp_mp.evaluar_mp(values)

            # Cuanto lleva activa esta lectura (reinicia si cambia LP o MP)
            vigencia = estado_senales.actualizar(
                estado_sen, ticker, f"{lp_res['estado']}|{mp_res['estado']}")

            # Catalizador de la semana que afecta a este activo (informativo,
            # no puntua): se infiere cruzando NEWS_KEYWORDS con las palabras
            # clave del catalizador, sin mapeos escritos a mano.
            catalizador = ia_sintesis.catalizador_para_ticker(
                sintesis.get("catalizadores"), ticker,
                row.get("asset_type", ""), config.NEWS_KEYWORDS.get(ticker, []))

            comb = lp_mp.combinar(lp_res, mp_res,
                                  semanas_en_estado=vigencia["semanas"],
                                  tiene_posicion=tiene_posicion)
            senales = {"lp": lp_res, "mp": mp_res, "combinada": comb}

            score     = result["score"]
            # Action primaria: combinar() de LP/MP (no scorer técnico)

            # Razón: LP/MP contiene la recomendación de TENER/NO TENER/SALIR

            #        scorer solo mide momentum técnico y puede contradecir LP/MP

            accion_combinada = senales["combinada"].get("accion", "SIN DATOS")

            

            # Mapeo: conversión de acciones LP/MP a categorías de PDF
            # (tabla única en signals.py, compartida con compras_etf.py)
            action = lp_mp.ACCION_A_CATEGORIA.get(accion_combinada, "MANTENER")

            

            # Guardar también el score técnico para referencia

            tech_score = result["score"]

            tech_action = result["action"]
            breakdown = result["breakdown"]

            price_usd = values.get("close") or 0
            price_cop = round(price_usd * cop_rate, 0) if price_usd else 0
            target    = _calc_target(price_usd, action)
            sl        = _calc_stop_loss(price_usd, action)

            n_active   = sum(1 for c in breakdown.values() if abs(c.get("weighted", 0)) >= 0.5)
            confidence = {"score": n_active, "total": len(breakdown)}

            reasons = []
            for comp in breakdown.values():
                w      = comp.get("weighted", 0)
                detail = comp.get("details", "") or comp.get("signal", "")
                if abs(w) >= 1.0 and detail:
                    reasons.append(f"{'[+]' if w > 0 else '[-]'} {detail}")

            # weighted_score alias para compatibilidad con pdf_generator
            score_components = {
                k: {**v, "weighted_score": v.get("weighted", 0)}
                for k, v in breakdown.items()
            }

            rec = {
                "ticker":           ticker,
                "asset_name":       config.ASSET_NAMES.get(ticker, ""),
                "action":           action,
                "score":            score,
                "score_components": score_components,
                "confidence":       confidence,
                "price_usd":        round(price_usd, 2),
                "price_cop":        price_cop,
                "target_usd":       round(target, 2) if target else None,
                "stop_loss_usd":    round(sl, 2)     if sl     else None,
                "reasons":          reasons[:5],
                "news":             news[:5],
                "squeeze_state":    values.get("squeeze_state", ""),
                "adx_value":        values.get("adx") or 0,
                "current_value_cop": float(row.get("current_value", 0)),
                "pct_portfolio":    row.get("pct_of_total_portfolio", ""),
                "asset_type":       row.get("asset_type", "Otro"),
                "asset_subtype":    row.get("asset_subtype", ""),
                "lp":               senales["lp"],
                "mp":               senales["mp"],
                "combinada":        senales["combinada"],
                "vigencia":         vigencia,
                "catalizador":      catalizador,
            }

            recommendations.append(rec)
            loader.save_recommendation(ticker, rec)
            logger.info("%s → %s (score %.1f) | LP %s / MP %s → %s",
                        ticker, rec["action"], rec["score"],
                        senales["lp"]["estado"], senales["mp"]["estado"],
                        senales["combinada"]["accion"])

        except Exception as e:
            logger.error("Error procesando %s: %s", ticker, e)

    if estado_senales.guardar(estado_sen, ruta_estado):
        logger.info("Estado de señales guardado (%d activos)", len(estado_sen))

    if not recommendations:
        logger.error("Sin recomendaciones generadas. Abortando.")
        return

    portfolio_total = portfolio["current_value"].astype(float).sum()

    # Última sección del PDF: compras en acciones individuales de los ETFs de
    # referencia, con la misma lógica LP/MP. Si falla, el reporte sale igual.
    compras_etf = None
    try:
        en_portafolio = set(portfolio["ticker"].astype(str)) | {
            loader.get_yf_ticker(t) for t in portfolio["ticker"].astype(str)}
        compras_etf = compras_etf_mod.analizar(
            excluir=en_portafolio,
            periodo=getattr(config, "HISTORY_PERIOD", None) or f"{config.HISTORY_DAYS}d",
            config=config)
    except Exception as e:
        logger.error("Compras en acciones de ETFs: omitido (%s)", e)

    logger.info("Enviando reporte a Telegram (chat_id=%s)...", CHAT_ID[:6] + "***" if CHAT_ID else "VACÍO")
    # Obtener noticias macro de la semana
    macro_news = news_a.get_macro_news(days=7, max_results=10)
    logger.info("Noticias macro obtenidas: %d items", len(macro_news))
    
    ok = await send_weekly_report(
        recommendations=recommendations,
        portfolio_total_cop=portfolio_total,
        cop_usd_rate=cop_rate,
        bot_token=BOT_TOKEN,
        chat_id=CHAT_ID,
        regime_data=regime_data,
        macro_news=macro_news,
        compras_etf=compras_etf,
    )
    if ok:
        logger.info("Reporte enviado a Telegram: OK")
    else:
        logger.error("FALLO al enviar reporte a Telegram — revisar BOT_TOKEN y CHAT_ID en GitHub Secrets")
        sys.exit(1)



# ── TEST ──────────────────────────────────────────────────────────────────────

async def run_test():
    logger.info("Enviando mensaje de prueba...")
    ok = await send_test_message(BOT_TOKEN, CHAT_ID)
    logger.info("Prueba: %s", "OK" if ok else "FALLO")


# ── SCHEDULER LOCAL (daemon) ──────────────────────────────────────────────────

def run_scheduler():
    """Modo daemon con APScheduler para ejecución local."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        import pytz
        import time
    except ImportError:
        logger.error("APScheduler no instalado. Para modo local: pip install APScheduler")
        sys.exit(1)

    tz = pytz.timezone(os.getenv("TIMEZONE", "America/Bogota"))
    sched = BackgroundScheduler(timezone=tz)

    sched.add_job(
        lambda: asyncio.run(run_weekly_analysis()),
        "cron", day_of_week="sun", hour=19, minute=0,
        id="weekly_analysis", name="Analisis semanal dominical",
    )

    sched.start()
    logger.info("Scheduler iniciado. Analisis: domingos 19:00 Bogota")
    logger.info("Presiona Ctrl+C para detener.")

    try:
        while True:
            import time; time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        sched.shutdown()
        logger.info("Scheduler detenido.")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Recomendador de Inversiones ETF")
    parser.add_argument("--now",     action="store_true", help="Analisis semanal inmediato")
    parser.add_argument("--test",    action="store_true", help="Test de conectividad Telegram")
    args = parser.parse_args()

    if not BOT_TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID son requeridos en .env o variables de entorno")
        sys.exit(1)

    if args.now:
        asyncio.run(run_weekly_analysis())
    elif args.test:
        asyncio.run(run_test())
    else:
        run_scheduler()


if __name__ == "__main__":
    main()
