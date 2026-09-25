"""
pdf_generator.py — Reporte PDF usando matplotlib (ya en requirements.txt).
Sin dependencias nuevas. Usa matplotlib.backends.backend_pdf.PdfPages.
"""
import logging
import textwrap
from datetime import datetime
from typing import List, Dict, Any

import matplotlib
matplotlib.use("Agg")   # Sin GUI — funciona en servidores y GitHub Actions
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

logger = logging.getLogger(__name__)

# ── Paleta de colores ─────────────────────────────────────────────────────────
COLORS = {
    "COMPRA FUERTE": "#1a7a1a",
    "COMPRA DEBIL":  "#5cbd5c",
    "MANTENER":      "#888888",
    "VENTA DEBIL":   "#e07030",
    "VENTA":         "#d05000",
    "VENTA FUERTE":  "#b00000",
    "bg_header":     "#1e1e4a",
    "bg_light":      "#f0f0f8",
    "text_dark":     "#1a1a1a",
    "text_gray":     "#555555",
    "green":         "#1a7a1a",
    "red":           "#b00000",
    "neutral":       "#555555",
}

INDICATOR_LABELS = {
    "moving_averages": "Medias Moviles EMA10/55 (diario)",
    "squeeze_adx":     "Squeeze+ADX Trading Latino (semanal)",
    "rsi":             "RSI 14 (semanal)",
    "volume":          "Volumen OBV/CMF (diario)",
    "news":            "Noticias / Contexto",
}


def generate_report_pdf(
    recommendations: List[Dict[str, Any]],
    portfolio_total_cop: float,
    cop_usd_rate: float,
    output_path: str,
    regime_data: dict = None,
    compras_etf: dict = None,
) -> bool:
    """
    Genera el PDF completo del reporte semanal usando matplotlib.
    compras_etf: salida de src.compras_etf.analizar(); va como última sección.
    No requiere fpdf2 ni reportlab — matplotlib ya está en requirements.txt.
    """
    try:
        plt.rcParams.update({
            "font.family":    "DejaVu Sans",
            "font.size":      9,
            "figure.facecolor": "white",
            "axes.facecolor":   "white",
        })

        compras  = sorted([r for r in recommendations if "COMPRA" in r.get("action","")],
                          key=lambda x: -x.get("score", 0))
        ventas   = sorted([r for r in recommendations if "VENTA"  in r.get("action","")],
                          key=lambda x:  x.get("score", 0))
        mantener = [r for r in recommendations if r.get("action","") == "MANTENER"]

        with PdfPages(output_path) as pdf:
            # Portada
            pdf.savefig(_make_cover(recommendations, portfolio_total_cop, cop_usd_rate,
                                    len(compras), len(ventas), len(mantener)),
                        bbox_inches="tight")
            plt.close("all")

            # Análisis de régimen de mercado (bull/bear) — primera página de contenido
            if regime_data:
                sintesis = regime_data.get("sintesis") or {}
                eventos  = regime_data.get("eventos") or []
                fuente   = sintesis.get("fuente", "fallback")
                hoy_es   = _fecha_es(datetime.now())

                # Acciones EE.UU. y cripto son bloques independientes:
                # cripto no hereda el regimen de las acciones.
                pdf.savefig(_make_regimen_page(
                    sintesis.get("acciones_usa"),
                    "Régimen de Mercado — Acciones EE.UU.",
                    f"Análisis macroeconómico y técnico  |  {hoy_es}",
                    regime_data.get("macro_data"), eventos, fuente,
                ), bbox_inches="tight")
                plt.close("all")

                pdf.savefig(_make_regimen_page(
                    sintesis.get("cripto"),
                    "Régimen de Mercado — Cripto",
                    f"Bloque independiente del de acciones  |  {hoy_es}",
                    regime_data.get("cripto_indicadores"), eventos, fuente,
                ), bbox_inches="tight")
                plt.close("all")
                # Dashboard completo de indicadores macro (FRED + geopolítico)
                pdf.savefig(_make_indicators_table_page(regime_data), bbox_inches="tight")
                plt.close("all")

            # Tabla de composición del portafolio
            pdf.savefig(_make_holdings_table(recommendations, portfolio_total_cop), bbox_inches="tight")
            plt.close("all")

            # Sugerencia de rebalanceo (perfil agresivo)
            pdf.savefig(_make_rebalancing_page(recommendations, portfolio_total_cop), bbox_inches="tight")
            plt.close("all")

            # Distribución por horizonte (LP / MP) + señales accionables
            pdf.savefig(_make_lp_mp_page(recommendations), bbox_inches="tight")
            plt.close("all")

            # Sección COMPRAS
            if compras:
                pdf.savefig(_make_section_header("COMPRAS", compras, COLORS["COMPRA FUERTE"]),
                            bbox_inches="tight")
                plt.close("all")
                for figura in _make_ticker_pages(compras):
                    pdf.savefig(figura, bbox_inches="tight")
                    plt.close("all")

            # Sección VENTAS
            if ventas:
                pdf.savefig(_make_section_header("VENTAS", ventas, COLORS["VENTA FUERTE"]),
                            bbox_inches="tight")
                plt.close("all")
                for figura in _make_ticker_pages(ventas):
                    pdf.savefig(figura, bbox_inches="tight")
                    plt.close("all")

            # MANTENER (resumen compacto)
            if mantener:
                pdf.savefig(_make_mantener_page(mantener), bbox_inches="tight")
                plt.close("all")

            # Última sección: compras en acciones individuales de los ETFs
            if compras_etf is not None:
                for figura in _make_compras_etf_pages(compras_etf):
                    pdf.savefig(figura, bbox_inches="tight")
                    plt.close("all")

            # Metadata
            d = pdf.infodict()
            d["Title"]   = "Reporte Semanal de Inversiones"
            d["Subject"] = f"Análisis {datetime.now().strftime('%d/%m/%Y')}"

        logger.info("PDF generado: %s", output_path)
        return True

    except Exception as e:
        logger.exception("Error generando PDF: %s", e)
        return False


# ── Páginas ───────────────────────────────────────────────────────────────────

# ── Colores por régimen ───────────────────────────────────────────────────────
# ── Páginas de régimen (acciones y cripto) ────────────────────────────────────

_REG_COLOR = {
    "BULL":  {"fuerte": "#1a5c1a", "suave": "#e8f5e8", "texto": "#0d3d0d"},
    "BEAR":  {"fuerte": "#8c0000", "suave": "#fdecea", "texto": "#700000"},
    "RANGO": {"fuerte": "#8a6d00", "suave": "#fff8e0", "texto": "#5a4500"},
}
_REG_TITULO = {
    "BULL":  "MERCADO ALCISTA",
    "BEAR":  "MERCADO BAJISTA",
    "RANGO": "RANGO — sin tendencia definida",
}
_PROB_ESTILO = [
    ("bear",  "BAJISTA", "#8c0000", "#fdecea"),
    ("rango", "RANGO",   "#8a6d00", "#fff8e0"),
    ("bull",  "ALCISTA", "#1a5c1a", "#e8f5e8"),
]


def _caja(fig, rect, titulo, lineas, color_borde="#c9cbe0", color_fondo="#fbfbfe",
          color_titulo="#2d2d5a", vacia="Sin datos esta semana."):
    """Caja con título y viñetas. Devuelve el eje por si hace falta."""
    ax = fig.add_axes(rect)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    ax.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.008",
                                         fc=color_fondo, ec=color_borde, linewidth=0.9))
    ax.text(0.018, 0.88, titulo, fontsize=8.6, fontweight="bold",
            color=color_titulo, va="center")
    if not lineas:
        ax.text(0.03, 0.45, vacia, fontsize=7.6, color="#888888", style="italic", va="center")
        return ax
    visibles = lineas[:4]
    paso = 0.62 / len(visibles)
    y = 0.72 - paso / 2
    for linea in visibles:
        ax.text(0.03, y, "• " + textwrap.shorten(str(linea), width=105, placeholder="..."),
                fontsize=7.6, color="#333333", va="center")
        y -= paso
    return ax


def _make_regimen_page(bloque: dict, titulo: str, subtitulo: str,
                       indicadores: dict, eventos: list, fuente: str):
    """
    Página de régimen: estado actual, probabilidades a 3 y 6 meses en tarjetas,
    qué pasó, qué vigilar (fechas reales) y qué invalidaría la lectura.
    Sirve igual para acciones EE.UU. y para cripto.
    """
    bloque = bloque or {}
    estado = bloque.get("estado", "RANGO")
    estilo = _REG_COLOR.get(estado, _REG_COLOR["RANGO"])
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.945, 1, 0.055])
    ax_h.set_xlim(0, 1); ax_h.set_ylim(0, 1); ax_h.axis("off")
    ax_h.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax_h.transAxes,
                                 facecolor=COLORS["bg_header"], edgecolor="none"))
    ax_h.text(0.5, 0.63, titulo, ha="center", va="center", fontsize=13,
              fontweight="bold", color="white")
    ax_h.text(0.5, 0.22, subtitulo, ha="center", va="center", fontsize=8, color="#cfd0e8")

    # ── Estado actual ─────────────────────────────────────────────────────────
    ax_e = fig.add_axes([0.04, 0.845, 0.92, 0.085])
    ax_e.set_xlim(0, 1); ax_e.set_ylim(0, 1); ax_e.axis("off")
    ax_e.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.01",
                                           fc=estilo["suave"], ec=estilo["fuerte"], linewidth=1.4))
    ax_e.text(0.5, 0.70, _REG_TITULO.get(estado, estado), ha="center", va="center",
              fontsize=13.5, fontweight="bold", color=estilo["texto"])
    resumen = bloque.get("resumen") or "Sin resumen disponible."
    ax_e.text(0.5, 0.26, textwrap.shorten(resumen, width=125, placeholder="..."),
              ha="center", va="center", fontsize=8.3, color=estilo["texto"])

    # ── Probabilidades por horizonte ──────────────────────────────────────────
    ax_t = fig.add_axes([0.04, 0.805, 0.92, 0.025])
    ax_t.axis("off")
    ax_t.text(0, 0.5, "Escenarios probables (cada horizonte suma 100%):",
              fontsize=9.2, fontweight="bold", color=COLORS["text_dark"], va="center")

    probs = bloque.get("probabilidades") or {}
    for fila, (clave, etiqueta) in enumerate((("3m", "Próximos 3 meses"),
                                              ("6m", "Próximos 6 meses"))):
        y = 0.685 - fila * 0.115
        ax_l = fig.add_axes([0.04, y + 0.075, 0.92, 0.022])
        ax_l.axis("off")
        ax_l.text(0, 0.5, etiqueta, fontsize=8.4, fontweight="bold",
                  color="#444444", va="center")
        valores = probs.get(clave) or {}
        for col, (k, nombre, fuerte, suave) in enumerate(_PROB_ESTILO):
            ax_c = fig.add_axes([0.04 + col * 0.313, y, 0.29, 0.072])
            ax_c.set_xlim(0, 1); ax_c.set_ylim(0, 1); ax_c.axis("off")
            destaca = valores.get(k, 0) == max(valores.values()) if valores else False
            ax_c.add_patch(mpatches.FancyBboxPatch(
                (0, 0), 1, 1, boxstyle="round,pad=0.02", fc=suave, ec=fuerte,
                linewidth=2.0 if destaca else 0.8))
            ax_c.text(0.5, 0.62, f"{valores.get(k, 0)}%", ha="center", va="center",
                      fontsize=17, fontweight="bold", color=fuerte)
            ax_c.text(0.5, 0.20, nombre, ha="center", va="center",
                      fontsize=7.6, fontweight="bold", color=fuerte)

    # ── Qué pasó / qué vigilar / qué invalidaría ──────────────────────────────
    _caja(fig, [0.04, 0.395, 0.92, 0.115], "Qué pasó recientemente",
          bloque.get("que_paso") or [],
          vacia="Sin cambios macro relevantes registrados esta semana.")

    lineas_ev = []
    for e in (eventos or []):
        marca = "" if e.get("exacta", True) else " (fecha aproximada)"
        lineas_ev.append(f"{e['fecha_texto']} — {e['nombre']}: {e['detalle']}{marca}")
    _caja(fig, [0.04, 0.245, 0.92, 0.135], "Qué vigilar próximamente",
          lineas_ev, color_borde="#9db4d8", color_fondo="#f4f8fd",
          vacia="Sin publicaciones relevantes en el horizonte cercano.")

    _caja(fig, [0.04, 0.125, 0.92, 0.105], "Qué invalidaría esta lectura",
          [bloque.get("que_invalidaria")] if bloque.get("que_invalidaria") else [],
          color_borde=estilo["fuerte"], color_fondo=estilo["suave"],
          color_titulo=estilo["texto"],
          vacia="No se definió una condición de invalidación.")

    # ── Indicadores usados ────────────────────────────────────────────────────
    ax_i = fig.add_axes([0.04, 0.035, 0.92, 0.075])
    ax_i.set_xlim(0, 1); ax_i.set_ylim(0, 1); ax_i.axis("off")
    ax_i.text(0, 0.92, "Indicadores considerados:", fontsize=8,
              fontweight="bold", color="#444444", va="top")
    usados = [f"{d.get('name')}: {d.get('value')}"
              for d in (indicadores or {}).values()
              if isinstance(d, dict) and d.get("value") not in (None, "N/D")]
    faltantes = [d.get("name") for d in (indicadores or {}).values()
                 if isinstance(d, dict) and d.get("value") in (None, "N/D")]
    ax_i.text(0, 0.60, textwrap.fill("  |  ".join(usados) or "sin indicadores disponibles",
                                     width=140)[:400],
              fontsize=6.9, color="#333333", va="top")
    if faltantes:
        ax_i.text(0, 0.12, "Sin dato esta semana: " + ", ".join(faltantes[:6]),
                  fontsize=6.6, color="#b06000", va="top", style="italic")

    # ── Pie: de dónde salió la lectura ────────────────────────────────────────
    ax_f = fig.add_axes([0, 0, 1, 0.03])
    ax_f.set_xlim(0, 1); ax_f.set_ylim(0, 1); ax_f.axis("off")
    origen = ("Lectura cualitativa generada por IA sobre datos calculados en Python"
              if fuente == "groq" else
              "IA no disponible esta semana: lectura generada por reglas en Python")
    ax_f.text(0.5, 0.5, origen + ".  Las fechas provienen de los calendarios "
              "oficiales de la Fed y el BLS, no del modelo.",
              ha="center", va="center", fontsize=6.6, color="#888888", style="italic")
    return fig


def _make_indicators_table_page(regime_data: dict):
    """
    Página: Dashboard completo de indicadores macroeconómicos.

    Secciones:
      1. Señales de mercado (yfinance): VIX, 10Y nivel/tendencia, curva, DXY, SPY
      2. Indicadores macroeconómicos (FRED): Fed, CPI, NFP, GDP, UMich, Claims, ISM
      3. Catalizadores de la semana (bandas dinámicas, las que haya)
    """
    signals    = regime_data.get("signals", [])
    macro_data = regime_data.get("macro_data", {})
    fetch_dt   = regime_data.get("fetch_date", "")
    regime     = regime_data.get("regime", "NEUTRAL")

    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.935, 1, 0.065])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax_h.text(0.5, 0.67, "Dashboard de Indicadores Macroeconómicos",
              ha="center", va="center", fontsize=13, fontweight="bold", color="white")
    ax_h.text(0.5, 0.20,
              f"Mapa completo de riesgo  |  Régimen: {regime}  |  {fetch_dt}",
              ha="center", va="center", fontsize=8, color="#aaaadd")

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _sig_style(signal):
        if signal == "ALCISTA":
            return "#0d7a0d", "#e4f7e4"
        elif signal == "BAJISTA":
            return "#b00000", "#fde4e4"
        return "#555555", "#f4f4f4"

    def _dir_color(d):
        if d == "↑": return "#b00000"
        if d == "↓": return "#0d7a0d"
        return "#888888"

    def _section_label(pos, text):
        ax_l = fig.add_axes(pos)
        ax_l.axis("off")
        ax_l.add_patch(mpatches.FancyBboxPatch(
            (0, 0), 1, 1, boxstyle="square,pad=0",
            fc="#e8eaf6", ec="#3949ab", linewidth=0.5))
        ax_l.text(0.012, 0.5, text,
                  fontsize=7.5, fontweight="bold", color="#1a237e",
                  va="center", transform=ax_l.transAxes)

    # ── Sección 1: Señales de mercado (yfinance) ──────────────────────────────
    _section_label([0.01, 0.902, 0.98, 0.026],
                   "  Señales de mercado financiero — yfinance  (^VIX · ^TNX · ^IRX · DX-Y.NYB · SPY)")

    if signals:
        mkt_rows, mkt_styles = [], []
        for sig in signals:
            bull    = sig.get("bull")
            sig_txt = "ALCISTA" if bull is True else ("BAJISTA" if bull is False else "NEUTRAL")
            name    = sig.get("name", "")
            name_s  = name.split(" (")[0] if " (" in name else name
            desc    = sig.get("desc", "")
            desc_s  = (desc[:70] + "…") if len(desc) > 70 else desc
            mkt_rows.append([name_s, sig.get("value", ""), sig_txt, desc_s])
            mkt_styles.append(_sig_style(sig_txt))

        ax_m = fig.add_axes([0.01, 0.748, 0.98, 0.152])
        ax_m.axis("off")
        tbl = ax_m.table(
            cellText=mkt_rows,
            colLabels=["Indicador", "Valor actual", "Señal", "Impacto en portafolio agresivo"],
            loc="upper center", bbox=[0, 0, 1, 1],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(7.2)
        tbl.auto_set_column_width([0, 1, 2, 3])
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#e0e0e0")
            if r == 0:
                cell.set_facecolor("#1e2d4a")
                cell.set_text_props(fontweight="bold", color="white", fontsize=7.5)
            elif r <= len(mkt_styles):
                sig_col, row_bg = mkt_styles[r - 1]
                cell.set_facecolor(row_bg)
                if c == 2:
                    cell.set_text_props(fontweight="bold", color=sig_col)
            cell.set_height(cell.get_height() * 1.3)
    else:
        ax_m = fig.add_axes([0.01, 0.748, 0.98, 0.152])
        ax_m.axis("off")
        ax_m.text(0.5, 0.5, "Sin datos de mercado (yfinance no disponible)",
                  ha="center", va="center", fontsize=9, color="#cc0000", style="italic")

    # ── Sección 2: Indicadores macro FRED ────────────────────────────────────
    _section_label([0.01, 0.718, 0.98, 0.026],
                   "  Indicadores macroeconómicos — FRED  "
                   "(FEDFUNDS · CPIAUCSL · PAYEMS · GDP · UMCSENT · ICSA · NAPM)")

    fred_keys = ["fed_rate", "cpi_yoy", "nfp", "gdp", "umich", "initial_claims", "ism_pmi"]

    if macro_data:
        fred_rows, fred_styles = [], []
        for key in fred_keys:
            ind = macro_data.get(key, {})
            if not ind:
                continue
            sig_txt = ind.get("signal", "N/D")
            d_txt   = ind.get("dir", "—")
            prev    = ind.get("prev", "—")
            vs_ant  = f"{d_txt} {prev}" if d_txt not in ("—", "↔") else prev
            note    = (ind.get("note", ""))[:46]
            fred_rows.append([
                ind.get("name", key),
                ind.get("value", "N/D"),
                vs_ant,
                sig_txt,
                note,
            ])
            sc, rb = _sig_style(sig_txt)
            fred_styles.append((sc, rb, d_txt))

        ax_f2 = fig.add_axes([0.01, 0.530, 0.98, 0.186])
        ax_f2.axis("off")
        tbl2 = ax_f2.table(
            cellText=fred_rows,
            colLabels=["Indicador", "Valor actual", "vs Anterior", "Señal", "Nota"],
            loc="upper center", bbox=[0, 0, 1, 1],
        )
        tbl2.auto_set_font_size(False); tbl2.set_fontsize(7.2)
        tbl2.auto_set_column_width([0, 1, 2, 3, 4])
        for (r, c), cell in tbl2.get_celld().items():
            cell.set_edgecolor("#e0e0e0")
            if r == 0:
                cell.set_facecolor("#1e2d4a")
                cell.set_text_props(fontweight="bold", color="white", fontsize=7.5)
            elif r <= len(fred_styles):
                sig_col, row_bg, d_txt = fred_styles[r - 1]
                cell.set_facecolor(row_bg)
                if c == 2:
                    cell.set_text_props(color=_dir_color(d_txt), fontweight="bold")
                elif c == 3:
                    cell.set_text_props(fontweight="bold", color=sig_col)
            cell.set_height(cell.get_height() * 1.28)
    else:
        ax_f2 = fig.add_axes([0.01, 0.530, 0.98, 0.186])
        ax_f2.axis("off")
        ax_f2.add_patch(mpatches.FancyBboxPatch(
            (0.05, 0.15), 0.9, 0.68,
            boxstyle="round,pad=0.04", fc="#fff8e0", ec="#e8c000", linewidth=1))
        ax_f2.text(0.5, 0.58,
                   "Datos FRED no disponibles.",
                   ha="center", va="center", fontsize=10,
                   color="#7a6000", fontweight="bold")
        ax_f2.text(0.5, 0.36,
                   "Instalar: pip install pandas-datareader>=0.10.0",
                   ha="center", va="center", fontsize=8.5,
                   color="#7a6000", style="italic")

    # ── Sección 3: Catalizadores dinámicos ───────────────────────────────────
    # No hay temas fijos en el código: cada semana la IA elige los catalizadores
    # relevantes (máx. 2 geopolíticos y 2 de materias primas) y aquí solo se
    # dibujan los que vengan. Si no hay ninguno, la sección se dice a sí misma.
    catalizadores = ((regime_data.get("sintesis") or {}).get("catalizadores") or [])[:4]

    _section_label([0.01, 0.500, 0.98, 0.026],
                   "  Catalizadores de la semana — seleccionados por impacto en el portafolio")

    _CAT_ETIQUETA = {"geopolitica": "GEOPOLÍTICA", "materias_primas": "MATERIAS PRIMAS"}
    _CAT_RIESGO = {
        "alto":  ("#b00000", "#fde4e4", "#cc4444", "#fff4f4"),
        "medio": ("#7a6000", "#fff3cc", "#cc8800", "#fffcf2"),
        "bajo":  ("#00509e", "#e4f0ff", "#3344cc", "#f5f8ff"),
    }

    # Bandas horizontales apiladas, no cuadrícula: el número de catalizadores
    # varía cada semana y una rejilla fija deja huecos o queda desbalanceada.
    TOPE, ALTO_BANDA, HUECO = 0.495, 0.085, 0.012

    if not catalizadores:
        ax_v = fig.add_axes([0.01, TOPE - 0.07, 0.98, 0.07])
        ax_v.set_xlim(0, 1); ax_v.set_ylim(0, 1); ax_v.axis("off")
        ax_v.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.01",
                                               fc="#f7f7fa", ec="#cccccc", linewidth=1.0))
        ax_v.text(0.5, 0.5, "Sin catalizadores relevantes esta semana.",
                  ha="center", va="center", fontsize=9.5, color="#666666")
    else:
        for i, cat in enumerate(catalizadores):
            y = TOPE - (i + 1) * ALTO_BANDA - i * HUECO
            txt_riesgo, bg_riesgo, borde, fondo = _CAT_RIESGO.get(
                cat.get("riesgo", "medio"), _CAT_RIESGO["medio"])

            ax_b = fig.add_axes([0.01, y, 0.98, ALTO_BANDA])
            ax_b.set_xlim(0, 1); ax_b.set_ylim(0, 1); ax_b.axis("off")
            ax_b.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.006",
                                                   fc=fondo, ec=borde, linewidth=1.1))
            # Franja de color a la izquierda: identifica el riesgo de un vistazo
            ax_b.add_patch(plt.Rectangle((0.004, 0.08), 0.007, 0.84,
                                         transform=ax_b.transAxes, fc=borde, ec="none"))

            # Identidad del catalizador (izquierda)
            ax_b.text(0.025, 0.70, textwrap.shorten(cat.get("titulo", ""), width=30,
                                                    placeholder="..."),
                      fontsize=9, fontweight="bold", color="#1a1a2e", va="center")
            ax_b.text(0.025, 0.36, _CAT_ETIQUETA.get(cat.get("categoria"), ""),
                      fontsize=6.2, fontweight="bold", color="#777777", va="center")
            ax_b.text(0.025, 0.14, f" RIESGO {cat.get('riesgo', 'medio').upper()} ",
                      fontsize=5.8, fontweight="bold", color=txt_riesgo, va="center",
                      bbox=dict(facecolor=bg_riesgo, edgecolor=txt_riesgo,
                                boxstyle="round,pad=0.25", linewidth=0.6))

            # Contenido (derecha), separado por una línea vertical
            ax_b.plot([0.25, 0.25], [0.12, 0.88], color=borde, linewidth=0.6, alpha=0.5)
            ax_b.text(0.27, 0.72, textwrap.fill(cat.get("que_paso", ""), width=98)[:200],
                      fontsize=7.2, color="#2a2a2a", va="top", linespacing=1.35)
            ax_b.text(0.27, 0.34, textwrap.fill("Impacto: " + cat.get("impacto", ""),
                                                width=98)[:200],
                      fontsize=7.2, color="#333333", va="top", linespacing=1.35,
                      fontweight="medium")


    # ── Footer ────────────────────────────────────────────────────────────────
    ax_ft = fig.add_axes([0, 0, 1, 0.085])
    ax_ft.axis("off")
    ax_ft.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                    boxstyle="square,pad=0", fc="#f0f0f8", ec="none"))
    ax_ft.text(0.5, 0.72,
               "Señales de mercado: yfinance (^VIX · ^TNX · ^IRX · DX-Y.NYB · SPY)  |  "
               "Macro FRED: FEDFUNDS · CPIAUCSL · PAYEMS · GDP · UMCSENT · ICSA · NAPM",
               ha="center", va="center", fontsize=6.2, color="#777777")
    ax_ft.text(0.5, 0.26,
               "Catalizadores seleccionados cada semana por impacto esperado en el portafolio. "
               "No constituye asesoría financiera.",
               ha="center", va="center", fontsize=6.2, color="#999999", style="italic")

    return fig


def _make_holdings_table(recs: list, total_cop: float):
    """
    Tabla de posiciones propias: ticker, tipo, valor COP y % del portafolio.
    Solo activos con posición (value > 0), ordenados de mayor a menor peso.
    """
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.93, 1, 0.07])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax_h.text(0.5, 0.6, "Composición del Portafolio",
              ha="center", va="center", fontsize=14, fontweight="bold", color="white")
    ax_h.text(0.5, 0.18, f"COP ${total_cop:,.0f} en activos propios",
              ha="center", va="center", fontsize=9, color="#aaaadd")

    owned = [r for r in recs if (r.get("current_value_cop") or 0) > 0]
    owned.sort(key=lambda x: -(x.get("current_value_cop") or 0))

    # ── Tabla portafolio propio ───────────────────────────────────────────────
    ax_p = fig.add_axes([0.01, 0.04, 0.98, 0.87])
    ax_p.axis("off")
    ax_p.text(0, 0.99, "Posiciones actuales (ordenadas por peso):", fontsize=10,
              fontweight="bold", color=COLORS["text_dark"], va="top", transform=ax_p.transAxes)

    tbl_data   = []
    tbl_colors = []
    for r in owned:
        val  = float(r.get("current_value_cop", 0) or 0)
        pct  = val / total_cop * 100 if total_cop else 0
        act  = r.get("action", "—")
        bar  = "█" * int(pct / 2) if pct >= 1 else "▏"
        tbl_data.append([
            r.get("ticker", ""),
            r.get("asset_type", ""),
            r.get("asset_subtype", ""),
            f"COP {val:,.0f}",
            f"{pct:.2f}%",
            bar,
        ])
        rc = COLORS.get(act, "#f5f5f5")
        tbl_colors.append([rc, "#f0f0f0", "#f0f0f0", "#f5f5f5", "#f5f5f5", "#e8f0ff"])

    if tbl_data:
        tbl = ax_p.table(
            cellText=tbl_data,
            colLabels=["Ticker", "Tipo", "Subtipo", "Valor COP", "% Port.", "Peso visual"],
            loc="upper center", bbox=[0, 0, 1, 0.97],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        tbl.auto_set_column_width(list(range(6)))
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#2d3a5a")
                cell.set_text_props(fontweight="bold", color="white")
            elif r <= len(tbl_colors):
                cell.set_facecolor(tbl_colors[r-1][c])
                if c == 0:
                    cell.set_text_props(fontweight="bold", color="white")
                if c == 5:
                    cell.set_text_props(color="#3355aa", fontfamily="monospace")

    # ── Footer ────────────────────────────────────────────────────────────────
    ax_f = fig.add_axes([0, 0, 1, 0.03])
    ax_f.axis("off")
    ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#f0f0f0", ec="none"))
    ax_f.text(0.5, 0.5,
              "Color de ticker = señal actual del analisis tecnico",
              ha="center", va="center", fontsize=7, color="#999999")
    return fig


# ── Perfil agresivo: targets y sugerencias ────────────────────────────────────
_AGRESIVO_TARGETS = {
    "Crecimiento":     0.50,
    "Defensiva":       0.15,
    "Materias Primas": 0.08,
    "Sectorial":       0.07,
    "Cripto":          0.10,
    "Emergentes":      0.10,
}

def _format_cop_delta(delta_cop: float) -> str:
    """Formatea un delta COP como etiqueta compacta, ej. '+~COP 2.5M' o '-~COP 340K'."""
    sign = "+" if delta_cop >= 0 else "-"
    v = abs(delta_cop)
    if v >= 1_000_000:
        return f"{sign}~COP {v/1_000_000:.1f}M"
    return f"{sign}~COP {v/1_000:.0f}K"


def _compute_rebal_suggestions(recs: list, type_totals: dict, total: float, threshold_pp: float = 2.0):
    """
    Genera sugerencias de rebalanceo de forma dinamica, cruzando:
      - La brecha entre asignacion actual y el objetivo por categoria (_AGRESIVO_TARGETS)
      - La señal tecnica semanal (score) de cada activo, para elegir un ticker concreto

    Categoria sobreponderada  -> sugiere REDUCIR el activo de la categoria con peor score.
    Categoria subponderada    -> sugiere AUMENTAR (si ya hay posicion) o INICIAR (si no la hay)
                                  en el activo de la categoria con mejor score.
    Categorias dentro de +/- threshold_pp puntos porcentuales del objetivo no generan sugerencia.

    Devuelve una lista de tuplas (ticker, accion, razon, cop_delta_label), mismo formato
    que antes tenia la lista estatica _REBAL_SUGGESTIONS, ordenada por magnitud de la brecha.
    """
    by_type: dict = {}
    for r in recs:
        atype = r.get("asset_type", "Otro") or "Otro"
        by_type.setdefault(atype, []).append(r)

    raw = []
    for cat, target_frac in _AGRESIVO_TARGETS.items():
        actual_val = type_totals.get(cat, 0)
        actual_pct = (actual_val / total * 100) if total else 0
        target_pct = target_frac * 100
        diff_pp = actual_pct - target_pct

        if abs(diff_pp) < threshold_pp:
            continue

        delta_cop  = abs(diff_pp) / 100 * total
        candidates = by_type.get(cat, [])

        if diff_pp > 0:
            # Sobreponderada -> reducir el activo con peor score dentro de la categoria
            owned = [r for r in candidates if (r.get("current_value_cop") or 0) > 0]
            if not owned:
                continue
            worst = min(owned, key=lambda r: r.get("score", 0))
            razon = (f"{cat} sobreponderada ({actual_pct:.1f}% actual vs {target_pct:.0f}% objetivo). "
                     f"Score tecnico mas debil dentro de la categoria.")
            raw.append((worst.get("ticker", "?"), "REDUCIR", razon, -delta_cop))
        else:
            # Subponderada -> reforzar/iniciar el activo con mejor score dentro de la categoria
            if not candidates:
                continue
            best     = max(candidates, key=lambda r: r.get("score", 0))
            ya_tiene = (best.get("current_value_cop") or 0) > 0
            accion   = "AUMENTAR" if ya_tiene else "INICIAR"
            razon = (f"{cat} subponderada ({actual_pct:.1f}% actual vs {target_pct:.0f}% objetivo). "
                     f"Mejor score tecnico dentro de la categoria" +
                     (" (ya en portafolio)." if ya_tiene else " (aun sin posicion, ver watchlist)."))
            raw.append((best.get("ticker", "?"), accion, razon, delta_cop))

    raw.sort(key=lambda s: -abs(s[3]))
    return [(t, a, r, _format_cop_delta(d)) for (t, a, r, d) in raw[:8]]


def _make_rebalancing_page(recs: list, total_cop: float):
    """
    Sugerencia de rebalanceo para perfil agresivo (arriesgado):
      - Grafica barras: asignacion actual vs objetivo
      - Tabla: acciones concretas con razon y COP estimado
    """
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.93, 1, 0.07])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#2d1a5a", ec="none"))
    ax_h.text(0.5, 0.62, "Sugerencia de Rebalanceo - Perfil Agresivo",
              ha="center", va="center", fontsize=13, fontweight="bold", color="white")
    ax_h.text(0.5, 0.18,
              "Objetivo: maximizar crecimiento con exposicion controlada a defensivos, materias primas, cripto y emergentes",
              ha="center", va="center", fontsize=8, color="#ccaaff")

    # ── Calcular asignacion actual por tipo ───────────────────────────────────
    owned = [r for r in recs if (r.get("current_value_cop") or 0) > 0]
    type_totals: dict = {}
    for r in owned:
        atype = r.get("asset_type", "Otro")
        val = float(r.get("current_value_cop", 0) or 0)
        type_totals[atype] = type_totals.get(atype, 0) + val

    # Consolidar tipos menores en su categoría más cercana
    for extra_type in list(type_totals.keys()):
        if extra_type not in _AGRESIVO_TARGETS:
            # Poner en Sectorial si no clasificado
            type_totals["Sectorial"] = type_totals.get("Sectorial", 0) + type_totals.pop(extra_type)

    total = sum(type_totals.values()) or total_cop or 1

    categories = list(_AGRESIVO_TARGETS.keys())
    actual_pcts  = [type_totals.get(c, 0) / total * 100 for c in categories]
    target_pcts  = [_AGRESIVO_TARGETS[c] * 100 for c in categories]

    # ── Grafica barras ───────────────────────────────────────────────────────
    ax_b = fig.add_axes([0.08, 0.62, 0.88, 0.28])
    x = np.arange(len(categories))
    w = 0.35
    bars_act = ax_b.bar(x - w/2, actual_pcts, w, label="Actual",
                        color=["#3366cc","#cc3333","#cc8833","#228833","#aa3388","#00aacc"], alpha=0.85, zorder=3)
    bars_tgt = ax_b.bar(x + w/2, target_pcts, w, label="Objetivo agresivo",
                        color=["#99bbff","#ffaaaa","#ffcc88","#88dd88","#ddaadd","#aaeeff"], alpha=0.85,
                        edgecolor="#555555", linewidth=0.8, zorder=3)

    ax_b.set_xticks(x)
    ax_b.set_xticklabels(categories, fontsize=9)
    ax_b.set_ylabel("% del portafolio", fontsize=8)
    ax_b.set_title("Asignacion Actual vs Objetivo (Perfil Agresivo)", fontsize=10, fontweight="bold", pad=6)
    ax_b.legend(fontsize=8, loc="upper right")
    ax_b.set_ylim(0, max(max(actual_pcts), max(target_pcts)) * 1.18)
    ax_b.yaxis.grid(True, linestyle="--", alpha=0.4, zorder=0)
    ax_b.set_axisbelow(True)
    ax_b.tick_params(axis="both", labelsize=8)

    # Etiquetas sobre las barras
    for bar, pct in zip(bars_act, actual_pcts):
        ax_b.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                  f"{pct:.1f}%", ha="center", va="bottom", fontsize=7, color="#222222")
    for bar, pct in zip(bars_tgt, target_pcts):
        ax_b.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                  f"{pct:.0f}%", ha="center", va="bottom", fontsize=7, color="#444444")

    # ── Lookup señales tecnicas del analisis semanal ─────────────────────────
    signals = {}
    for r in recs:
        tk     = r.get("ticker", "")
        action = r.get("action", "")
        score  = float(r.get("score", 0) or 0)
        sq     = r.get("squeeze_state", "")
        adx    = float(r.get("adx_value", 0) or 0)
        signals[tk] = {"action": action, "score": score, "squeeze": sq, "adx": adx}

    def _entry_assessment(ticker, accion_rebal):
        """
        Cruza la sugerencia de rebalanceo con la señal tecnica semanal.
        Devuelve (etiqueta, color_fondo).
        """
        sig = signals.get(ticker)
        if not sig:
            return "Sin datos", "#eeeeee"
        action = sig["action"]
        score  = sig["score"]
        sq     = sig["squeeze"]
        is_buy_rebal  = accion_rebal in ("AUMENTAR", "INICIAR")
        is_sell_rebal = accion_rebal in ("REDUCIR", "VENDER")

        if is_buy_rebal:
            if "COMPRA FUERTE" in action:
                return "ENTRADA IDEAL", "#b8f0b8"      # verde fuerte
            elif "COMPRA" in action:
                return "Entrada favorable", "#d8f4d8"  # verde suave
            elif "MANTENER" in action:
                if sq == "compressed":
                    return "Esperar release", "#fff3cc"  # amarillo — squeeze comprimido, esperar
                return "Sin señal clara", "#f0f0f0"
            else:  # VENTA
                return "Señal contraria", "#fdd8c8"    # naranja — tecnico dice vender
        elif is_sell_rebal:
            if "VENTA FUERTE" in action:
                return "MOMENTO OPORTUNO", "#ffa8a8"   # rojo fuerte
            elif "VENTA" in action:
                return "Buen momento", "#ffc8b0"       # naranja suave
            elif "MANTENER" in action:
                return "Sin urgencia", "#f0f0f0"
            else:  # COMPRA
                return "Señal contraria", "#d8f4d8"    # verde — tecnico dice comprar, cuidado vender
        return "—", "#f5f5f5"

    # ── Tabla de sugerencias ──────────────────────────────────────────────────
    ax_t = fig.add_axes([0.01, 0.07, 0.98, 0.52])
    ax_t.axis("off")
    ax_t.text(0, 0.99, "Acciones sugeridas (con señal tecnica semanal):",
              fontsize=10, fontweight="bold", color=COLORS["text_dark"],
              va="top", transform=ax_t.transAxes)

    rebal_suggestions = _compute_rebal_suggestions(recs, type_totals, total)

    sug_data   = []
    sug_colors = []
    for ticker, accion, razon, cop_delta in rebal_suggestions:
        sig         = signals.get(ticker, {})
        tech_action = sig.get("action", "—")
        tech_score  = sig.get("score", 0)
        tech_str    = f"{tech_action} ({tech_score:+.0f})" if tech_action != "—" else "Sin datos"
        entry_lbl, entry_bg = _entry_assessment(ticker, accion)
        wrapped = textwrap.fill(razon, width=48)
        sug_data.append([ticker, accion, wrapped, tech_str, entry_lbl, cop_delta])

        if "VENDER" in accion or "REDUCIR" in accion:
            base_ticker_col = COLORS["VENTA FUERTE"]
            base_row_col    = "#fff0ec"
        else:
            base_ticker_col = COLORS["COMPRA FUERTE"]
            base_row_col    = "#f0fff0"

        sug_colors.append([
            base_ticker_col,  # ticker col
            base_row_col,     # accion col
            "#fafafa",        # razon col
            "#f5f5f5",        # señal tecnica col
            entry_bg,         # momento col
            base_row_col,     # COP col
        ])

    if not sug_data:
        ax_t.text(0.5, 0.5,
                  "Portafolio dentro de las bandas objetivo (+/-2 puntos porcentuales).\nSin acciones de rebalanceo sugeridas esta semana.",
                  ha="center", va="center", fontsize=9, color="#666666",
                  transform=ax_t.transAxes)
        return fig

    tbl = ax_t.table(
        cellText=sug_data,
        colLabels=["Ticker", "Accion", "Razon", "Señal tecnica", "Momento entrada", "COP est."],
        loc="upper center", bbox=[0, 0, 1, 0.94],
    )
    tbl.auto_set_font_size(False); tbl.set_fontsize(7)
    tbl.auto_set_column_width([0, 1, 2, 3, 4, 5])

    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#cccccc")
        if r == 0:
            cell.set_facecolor("#2d1a5a")
            cell.set_text_props(fontweight="bold", color="white", fontsize=7.5)
        elif r <= len(sug_colors):
            cell.set_facecolor(sug_colors[r-1][c])
            if c == 0:
                cell.set_text_props(fontweight="bold", color="white")
            if c == 4:
                cell.set_text_props(fontweight="bold", fontsize=6.5)
        cell.set_height(cell.get_height() * 1.5)

    # ── Leyenda de momento ─────────────────────────────────────────────────────
    ax_l = fig.add_axes([0.02, 0.01, 0.96, 0.055])
    ax_l.axis("off")
    leyenda = [
        ("ENTRADA IDEAL / MOMENTO OPORTUNO", "#b8f0b8"),
        ("Entrada favorable / Buen momento", "#d8f4d8"),
        ("Esperar release / Sin urgencia",   "#fff3cc"),
        ("Señal contraria — revisar",        "#fdd8c8"),
    ]
    for i, (label, color) in enumerate(leyenda):
        x0 = i / len(leyenda)
        ax_l.add_patch(mpatches.FancyBboxPatch((x0 + 0.005, 0.1), 0.23, 0.8,
                       boxstyle="round,pad=0.02", fc=color, ec="#aaaaaa", linewidth=0.6))
        ax_l.text(x0 + 0.12, 0.5, label, ha="center", va="center",
                  fontsize=5.8, color="#333333")

    return fig


# ── Distribución por horizonte (LP / MP) ──────────────────────────────────────

_LP_ORDEN = ["TENER", "VIGILAR", "NO TENER", "SIN DATOS"]
_LP_COLOR = {"TENER": "#2e7d32", "VIGILAR": "#c9a227",
             "NO TENER": "#a63737", "SIN DATOS": "#bbbbbb"}

_MP_ORDEN = ["ENTRAR AHORA", "ESPERAR GATILLO", "MANTENER", "SALIR", "SIN DATOS"]
_MP_COLOR = {"ENTRAR AHORA": "#2e7d32", "ESPERAR GATILLO": "#7fb37f",
             "MANTENER": "#9e9e9e", "SALIR": "#a63737", "SIN DATOS": "#bbbbbb"}

# Orden en que se muestran las acciones en la tabla (lo urgente primero)
_PRIORIDAD_ACCION = {
    "VENTA TOTAL": 0, "REDUCIR 50%": 1, "RECORTE TACTICO": 2,
    "COMPRAR": 3, "COMPRAR (LP)": 4, "ENTRADA TACTICA": 5,
    "NO TENER": 6, "VIGILAR": 7, "MANTENER": 8, "SIN DATOS": 9,
}
_SIN_ACCION = ("MANTENER", "VIGILAR", "SIN DATOS")

_COLOR_ACCION = {
    "VENTA TOTAL":     ("#b00000", "#fdecea"),
    "REDUCIR 50%":     ("#c25400", "#fdf0e6"),
    "RECORTE TACTICO": ("#d08000", "#fff6e6"),
    "COMPRAR":         ("#1a7a1a", "#e8f5e9"),
    "COMPRAR (LP)":    ("#2e7d32", "#eef7ee"),
    "ENTRADA TACTICA": ("#4a8fbd", "#eaf3f9"),
}


def _dona(ax, conteo: dict, orden: list, colores: dict, titulo: str):
    """Dona de distribución. Devuelve True si habia algo que graficar."""
    etiquetas = [k for k in orden if conteo.get(k)]
    valores   = [conteo[k] for k in etiquetas]
    ax.set_title(titulo, fontsize=9.5, fontweight="bold", pad=10)
    if not valores:
        ax.text(0.5, 0.5, "Sin datos", ha="center", va="center",
                fontsize=9, color="#888888", transform=ax.transAxes)
        ax.axis("off")
        return False
    ax.pie(valores, colors=[colores[k] for k in etiquetas],
           startangle=90, counterclock=False,
           wedgeprops=dict(width=0.42, edgecolor="white"),
           autopct=lambda p: f"{p:.0f}%", pctdistance=0.78,
           textprops={"color": "white", "fontsize": 8, "fontweight": "bold"})
    ax.legend([f"{k} ({conteo[k]})" for k in etiquetas],
              loc="lower center", bbox_to_anchor=(0.5, -0.26),
              ncol=2, fontsize=7, frameon=False)
    return True


def _make_lp_mp_page(recs: list):
    """
    Distribución del portafolio por horizonte:
      - Arriba: una dona para LP (¿debo tener el activo?) y otra para MP
        (¿cuándo entrar o salir?).
      - Abajo:  tabla compacta SOLO con lo accionable de la semana. Los activos
        en "mantener sin cambios" no aparecen: ya están en el resumen MANTENER.
    """
    fig = plt.figure(figsize=(8.5, 11))

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.945, 1, 0.055])
    ax_h.axis("off")
    ax_h.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax_h.transAxes,
                                 facecolor=COLORS["bg_header"], edgecolor="none"))
    ax_h.text(0.5, 0.63, "Distribución del Portafolio — Largo Plazo vs Mediano Plazo",
              ha="center", va="center", fontsize=12.5, fontweight="bold",
              color="white", transform=ax_h.transAxes)
    ax_h.text(0.5, 0.22, f"{len(recs)} activos analizados  —  {_fecha_es(datetime.now())}",
              ha="center", va="center", fontsize=8, color="#cfd0e8",
              transform=ax_h.transAxes)

    # ── Conteos por estado ────────────────────────────────────────────────────
    conteo_lp, conteo_mp = {}, {}
    for r in recs:
        e_lp = (r.get("lp") or {}).get("estado", "SIN DATOS")
        e_mp = (r.get("mp") or {}).get("estado", "SIN DATOS")
        conteo_lp[e_lp] = conteo_lp.get(e_lp, 0) + 1
        conteo_mp[e_mp] = conteo_mp.get(e_mp, 0) + 1

    _dona(fig.add_axes([0.04, 0.70, 0.44, 0.22]), conteo_lp, _LP_ORDEN, _LP_COLOR,
          "Largo Plazo (LP) — ¿debo tener el activo?")
    _dona(fig.add_axes([0.52, 0.70, 0.44, 0.22]), conteo_mp, _MP_ORDEN, _MP_COLOR,
          "Mediano Plazo (MP) — ¿cuándo entrar o salir?")

    # ── Selección de lo accionable ────────────────────────────────────────────
    accionables = []
    for r in recs:
        comb = r.get("combinada") or {}
        accion = comb.get("accion", "SIN DATOS")
        cambio = (r.get("vigencia") or {}).get("cambio", False)
        if accion in _SIN_ACCION and not cambio:
            continue
        accionables.append(r)

    accionables.sort(key=lambda r: (
        _PRIORIDAD_ACCION.get((r.get("combinada") or {}).get("accion", ""), 9),
        -float(r.get("current_value_cop", 0) or 0),
    ))
    accionables = accionables[:10]

    ax_t = fig.add_axes([0.04, 0.05, 0.92, 0.52])
    ax_t.axis("off")
    ax_t.text(0, 1.0, "Señales accionables esta semana (LP + MP combinados):",
              fontsize=10.5, fontweight="bold", transform=ax_t.transAxes)
    ax_t.text(0, 0.968,
              "Solo aparecen los activos con lectura relevante o cambio reciente. "
              "Los que siguen en 'mantener' sin cambios están en el resumen MANTENER.",
              fontsize=7, color="#666666", style="italic", transform=ax_t.transAxes)

    if not accionables:
        ax_t.text(0.5, 0.5,
                  "Ninguna señal accionable esta semana.\n"
                  "Todo el portafolio sigue en su estado anterior.",
                  ha="center", va="center", fontsize=9.5, color="#666666",
                  transform=ax_t.transAxes)
        return fig

    filas, colores_fila = [], []
    for r in accionables:
        comb   = r.get("combinada") or {}
        accion = comb.get("accion", "-")
        e_lp   = (r.get("lp") or {}).get("estado", "-")
        e_mp   = (r.get("mp") or {}).get("estado", "-")
        vig    = r.get("vigencia") or {}
        sem    = vig.get("semanas")
        desde  = "nueva" if vig.get("cambio") or not sem else f"{sem} sem."

        texto = comb.get("texto", "")
        if comb.get("avisos"):
            texto += "  " + comb["avisos"][0]
        # Acotado a 3 lineas: la fila de la tabla no crece y el detalle completo
        # vive en la tarjeta individual del activo.
        texto = textwrap.shorten(texto, width=168, placeholder="...")
        filas.append([r.get("ticker", "?"), e_lp, e_mp,
                      textwrap.fill(texto, width=56), desde])

        ticker_col, fondo = _COLOR_ACCION.get(accion, ("#666666", "#f5f5f5"))
        colores_fila.append([
            ticker_col,
            _LP_COLOR.get(e_lp, "#eeeeee"),
            _MP_COLOR.get(e_mp, "#eeeeee"),
            fondo,
            "#f5f5f5",
        ])

    tbl = ax_t.table(cellText=filas,
                     colLabels=["Ticker", "LP", "MP", "Recomendación combinada", "Activa\ndesde"],
                     loc="upper center", bbox=[0, 0, 1, 0.93],
                     colWidths=[0.09, 0.13, 0.16, 0.52, 0.10])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7)

    for (f, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#dddddd")
        if f == 0:
            cell.set_facecolor(COLORS["bg_header"])
            cell.set_text_props(fontweight="bold", color="white", fontsize=7.5)
        else:
            cell.set_facecolor(colores_fila[f - 1][c])
            if c in (0, 1, 2):
                cell.set_text_props(fontweight="bold", color="white", fontsize=6.8)
        cell.set_height(cell.get_height() * 1.45)

    ax_t.text(0, -0.035,
              "LP = tendencia mensual (¿tener el activo?)   |   "
              "MP = táctica semanal (¿cuándo entrar o salir?)   |   "
              "Una salida de MP recorta como máximo 25%; solo el LP vende todo.",
              fontsize=6.8, color="#888888", style="italic", transform=ax_t.transAxes)

    return fig


_DIAS_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
_MESES_ES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_es(dt) -> str:
    """Formatea una fecha en español, sin depender del locale del sistema operativo."""
    return f"{_DIAS_ES[dt.weekday()]} {dt.day} de {_MESES_ES[dt.month]} de {dt.year}"


def _make_cover(recs, total_cop, cop_rate, n_comp, n_vent, n_mant):
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    # Header band
    ax.add_patch(mpatches.FancyBboxPatch((0, 0.82), 1, 0.18,
                 boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax.text(0.5, 0.93, "Reporte Semanal de Inversiones",
            ha="center", va="center", fontsize=20, fontweight="bold",
            color="white", transform=ax.transAxes)
    ax.text(0.5, 0.86, _fecha_es(datetime.now()),
            ha="center", va="center", fontsize=12, color="#aaaadd",
            transform=ax.transAxes)

    # Portfolio summary box
    ax.add_patch(mpatches.FancyBboxPatch((0.05, 0.65), 0.90, 0.14,
                 boxstyle="round,pad=0.01", fc=COLORS["bg_light"], ec="#cccccc"))
    ax.text(0.5, 0.75, f"Portafolio Total:  COP ${total_cop:,.0f}",
            ha="center", va="center", fontsize=13, fontweight="bold",
            color=COLORS["text_dark"], transform=ax.transAxes)
    ax.text(0.5, 0.70, f"Tasa USD/COP: {cop_rate:,.0f}  |  Activos analizados: {len(recs)}",
            ha="center", va="center", fontsize=10, color=COLORS["text_gray"],
            transform=ax.transAxes)

    # Signal summary
    for i, (label, n, color) in enumerate([
        ("COMPRAS", n_comp, COLORS["COMPRA FUERTE"]),
        ("VENTAS",  n_vent, COLORS["VENTA FUERTE"]),
        ("MANTENER",n_mant, COLORS["MANTENER"]),
    ]):
        x = 0.18 + i * 0.32
        ax.add_patch(mpatches.FancyBboxPatch((x - 0.12, 0.50), 0.24, 0.12,
                     boxstyle="round,pad=0.01", fc=color, ec="none", alpha=0.9))
        ax.text(x, 0.59, str(n),    ha="center", va="center",
                fontsize=22, fontweight="bold", color="white", transform=ax.transAxes)
        ax.text(x, 0.52, label, ha="center", va="center",
                fontsize=9, color="white", transform=ax.transAxes)

    ax.text(0.5, 0.05,
            "Este reporte es generado automáticamente. No constituye asesoría financiera.\n"
            "Siempre realiza tu propio análisis antes de tomar decisiones de inversión.",
            ha="center", va="center", fontsize=7.5, color="#999999",
            transform=ax.transAxes, linespacing=1.5)
    return fig


def _make_section_header(title, recs, color):
    fig, ax = plt.subplots(figsize=(8.5, 4))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.add_patch(mpatches.FancyBboxPatch((0, 0.55), 1, 0.45,
                 boxstyle="square,pad=0", fc=color, ec="none"))
    ax.text(0.5, 0.78, f"SECCIÓN: {title}", ha="center", va="center",
            fontsize=22, fontweight="bold", color="white", transform=ax.transAxes)
    ax.text(0.5, 0.62, f"{len(recs)} activo(s) con señal",
            ha="center", va="center", fontsize=12, color="white", alpha=0.85,
            transform=ax.transAxes)

    # Mini tabla de resumen. Ni "Target" ni "Stop Loss" del score viejo: eran
    # porcentajes fijos (+8% / -5%) sin relacion con la estrategia. Aqui van los
    # niveles reales del checklist, los mismos que muestra cada tarjeta.
    col_labels = ["Ticker", "LP", "MP", "Precio USD", "Invalidación LP", "Stop MP"]
    rows = []
    for r in recs[:10]:
        lp = r.get("lp") or {}
        mp = r.get("mp") or {}
        inval = lp.get("invalidacion")
        stop  = mp.get("stop_mp")
        rows.append([
            r.get("ticker", ""),
            lp.get("estado", "—"),
            mp.get("estado", "—"),
            f"${r.get('price_usd', 0):.2f}",
            f"${inval:,.2f}" if inval else "—",
            f"${stop:,.2f}" if stop else "—",
        ])

    if rows:
        tbl = ax.table(cellText=rows, colLabels=col_labels,
                       loc="center", bbox=[0.02, -0.05, 0.96, 0.48])
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        for (r, c), cell in tbl.get_celld().items():
            if r == 0:
                cell.set_facecolor("#eeeeee"); cell.set_text_props(fontweight="bold")
            else:
                cell.set_facecolor("white" if r % 2 == 0 else "#fafafa")
            cell.set_edgecolor("#dddddd")

    return fig


# Colores de TEXTO por estado (la paleta de las donas es muy clara sobre blanco)
_TXT_ESTADO = {
    "TENER": "#1a7a1a", "ENTRAR AHORA": "#1a7a1a",
    "ESPERAR GATILLO": "#6a7f00", "MANTENER": "#555555",
    "VIGILAR": "#8a6d00", "NO TENER": "#b00000", "SALIR": "#b00000",
    "SIN DATOS": "#777777",
}


def _marca(cumple) -> str:
    return "[x]" if cumple is True else "[ ]" if cumple is False else "[?]"


def _color_marca(cumple) -> str:
    return "#1a7a1a" if cumple is True else "#b00000" if cumple is False else "#999999"


def _dibujar_checklist(ax, x, y, bloques, alto_linea=0.072):
    """Escribe bloques de checklist. bloques = [(subtitulo, items), ...]."""
    for subtitulo, items in bloques:
        ax.text(x, y, subtitulo, fontsize=6.6, fontweight="bold",
                color="#444444", va="top", transform=ax.transAxes)
        y -= alto_linea
        for it in items:
            ax.text(x, y, _marca(it["cumple"]), fontsize=6.4, family="monospace",
                    color=_color_marca(it["cumple"]), va="top", transform=ax.transAxes)
            ax.text(x + 0.035, y, textwrap.shorten(it["item"], width=58, placeholder="..."),
                    fontsize=6.4, color="#222222", va="top", transform=ax.transAxes)
            y -= alto_linea
        y -= alto_linea * 0.25
    return y


def _dibujar_tarjeta_ticker(fig, rec: dict, y_top: float, alto: float):
    """Dibuja la tarjeta de un activo dentro de la franja indicada de la figura."""
    ticker = rec.get("ticker", "—")
    nombre = rec.get("asset_name", "")
    asset_type = rec.get("asset_type", "")
    lp     = rec.get("lp") or {}
    mp     = rec.get("mp") or {}
    comb   = rec.get("combinada") or {}
    vig    = rec.get("vigencia") or {}
    accion = comb.get("accion", "—")

    color_acc, fondo_acc = _COLOR_ACCION.get(accion, ("#555555", "#f2f2f2"))

    # ── Encabezado ────────────────────────────────────────────────────────────
    h_head = 0.048
    ax_h = fig.add_axes([0.02, y_top - h_head, 0.96, h_head])
    ax_h.set_xlim(0, 1); ax_h.set_ylim(0, 1); ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="square,pad=0",
                                           fc=color_acc, ec="none"))
    # Formato: TICKER - Nombre (Tipo) o solo TICKER si no hay nombre
    if nombre and asset_type:
        ticker_display = f"{ticker} - {nombre} ({asset_type})"
    elif nombre:
        ticker_display = f"{ticker} - {nombre}"
    else:
        ticker_display = ticker
    ax_h.text(0.015, 0.66, ticker_display, fontsize=13, fontweight="bold", color="white", va="center")
    ax_h.text(0.985, 0.68, f"LP: {lp.get('estado','—')}  ({lp.get('confianza_pct',0)}%)",
              fontsize=8.5, fontweight="bold", color="white", va="center", ha="right")
    ax_h.text(0.985, 0.28, f"MP: {mp.get('estado','—')}  ({mp.get('confianza_pct',0)}%)",
              fontsize=8.5, fontweight="bold", color="white", alpha=0.92,
              va="center", ha="right")

    # ── Recomendación combinada ───────────────────────────────────────────────
    h_rec = 0.042
    ax_r = fig.add_axes([0.02, y_top - h_head - h_rec, 0.96, h_rec])
    ax_r.set_xlim(0, 1); ax_r.set_ylim(0, 1); ax_r.axis("off")
    ax_r.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="square,pad=0",
                                           fc=fondo_acc, ec="#cccccc", linewidth=0.5))
    ax_r.text(0.012, 0.72, f"{accion}  [{comb.get('horizonte','—')}]",
              fontsize=9, fontweight="bold", color=color_acc, va="center")
    ax_r.text(0.012, 0.28, textwrap.shorten(comb.get("texto", ""), width=120, placeholder="..."),
              fontsize=7.2, color="#333333", va="center")

    # ── Checklists ────────────────────────────────────────────────────────────
    h_chk = alto - h_head - h_rec - 0.046
    ax_c = fig.add_axes([0.02, y_top - h_head - h_rec - h_chk, 0.96, h_chk])
    ax_c.set_xlim(0, 1); ax_c.set_ylim(0, 1); ax_c.axis("off")

    ax_c.text(0.0, 0.99, "LARGO PLAZO — ¿debo tener el activo?",
              fontsize=7.4, fontweight="bold", color=_TXT_ESTADO.get(lp.get("estado"), "#333333"),
              va="top", transform=ax_c.transAxes)
    y_fin_lp = _dibujar_checklist(ax_c, 0.0, 0.93, [
        ("Tendencia (mensual):", lp.get("tendencia", [])),
        ("Zona de compra (mensual):", lp.get("zona_compra", [])),
    ])

    ax_c.text(0.52, 0.99, "MEDIANO PLAZO — ¿cuándo entrar o salir?",
              fontsize=7.4, fontweight="bold", color=_TXT_ESTADO.get(mp.get("estado"), "#333333"),
              va="top", transform=ax_c.transAxes)
    _dibujar_checklist(ax_c, 0.52, 0.93, [
        ("Contexto (mensual):", mp.get("contexto", [])),
        ("Ubicación (semanal):", mp.get("ubicacion", [])),
        ("Gatillo (semanal):", mp.get("gatillo", [])),
    ])

    # Avisos y motivos de venta, debajo de la columna izquierda
    extras = []
    cat = rec.get("catalizador")
    if cat:
        extras.append("Catalizador activo — {}: {}".format(
            cat.get("titulo", ""), cat.get("impacto", "") or cat.get("que_paso", "")))
    extras.extend(comb.get("avisos", []))
    motivos = (mp.get("ventas") or {}).get("motivos", [])
    if motivos and mp.get("estado") == "SALIR":
        extras.append("Motivos de salida MP: " + ", ".join(motivos))
    extras.extend((lp.get("notas") or []) + (mp.get("notas") or []))
    # Las viñetas viven en la columna izquierda: se envuelven a su ancho para
    # no invadir la columna del MP, y se corta cuando se acaba el espacio.
    y_ex = y_fin_lp - 0.02
    for linea in extras[:4]:
        if y_ex < 0.04:
            break
        es_catalizador = linea.startswith("Catalizador activo")
        envuelto = textwrap.fill(
            textwrap.shorten(linea, width=128, placeholder="..."), width=62)
        ax_c.text(0.0, y_ex, "• " + envuelto,
                  fontsize=6.3, color="#1a4e8a" if es_catalizador else "#8a6d00",
                  fontweight="bold" if es_catalizador else "normal",
                  va="top", transform=ax_c.transAxes, linespacing=1.35)
        y_ex -= 0.040 * (envuelto.count("\n") + 1) + 0.014

    # ── Datos de ejecución ────────────────────────────────────────────────────
    ax_d = fig.add_axes([0.02, y_top - alto, 0.96, 0.046])
    ax_d.set_xlim(0, 1); ax_d.set_ylim(0, 1); ax_d.axis("off")
    ax_d.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="square,pad=0",
                                           fc="#f7f7fa", ec="#dddddd", linewidth=0.5))
    precio = rec.get("price_usd") or 0
    inval  = lp.get("invalidacion")
    stop   = mp.get("stop_mp")
    sem    = vig.get("semanas")
    partes = [f"Precio: ${precio:,.2f}"]
    if inval:
        partes.append(f"Invalidación LP: ${inval:,.2f}")
    if stop:
        partes.append(f"Stop MP (soporte − 2·ATR): ${stop:,.2f}")
    partes.append("Señal nueva esta semana" if vig.get("cambio") or not sem
                  else f"Señal activa hace {sem} sem.")
    ax_d.text(0.012, 0.5, "   |   ".join(partes), fontsize=7.2,
              color="#333333", va="center")


def _make_ticker_pages(recs: list):
    """Genera las páginas de detalle: dos tarjetas de activo por hoja."""
    ALTO, SEP = 0.37, 0.025
    figuras = []
    for i in range(0, len(recs), 2):
        grupo = recs[i:i + 2]
        fig = plt.figure(figsize=(8.5, 11))
        fig.patch.set_facecolor("white")
        for j, rec in enumerate(grupo):
            _dibujar_tarjeta_ticker(fig, rec, y_top=0.965 - j * (ALTO + SEP), alto=ALTO)

        # El pie va debajo de la ultima tarjeta, no al fondo de la hoja:
        # asi bbox_inches="tight" recorta el sobrante en paginas de una sola tarjeta.
        y_pie = 0.965 - len(grupo) * (ALTO + SEP) - 0.01
        ax_f = fig.add_axes([0, max(y_pie, 0.005), 1, 0.03])
        ax_f.set_xlim(0, 1); ax_f.set_ylim(0, 1); ax_f.axis("off")
        ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="square,pad=0",
                                               fc="#f0f0f0", ec="none"))
        ax_f.text(0.5, 0.5,
                  "[x] condición cumplida   [ ] no cumplida   [?] sin datos   |   "
                  "LP manda sobre MP: una salida de MP recorta máximo 25%",
                  ha="center", va="center", fontsize=6.5, color="#888888")
        figuras.append(fig)
    return figuras


def _make_mantener_page(mantener: list):
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.add_patch(mpatches.FancyBboxPatch((0, 0.92), 1, 0.08,
                 boxstyle="square,pad=0", fc=COLORS["MANTENER"], ec="none"))
    ax.text(0.5, 0.96, f"MANTENER - {len(mantener)} activos",
            ha="center", va="center", fontsize=16, fontweight="bold",
            color="white", transform=ax.transAxes)

    rows = []
    for r in mantener:
        sq = r.get("squeeze_state", "")
        sc = r.get("sqzm_color",    "")
        rows.append([
            r.get("ticker", ""),
            f"{r.get('score', 0):+.1f}",
            f"${r.get('price_usd', 0):.2f}",
            sq,
            sc,
            r.get("asset_subtype", ""),
        ])

    if rows:
        tbl = ax.table(
            cellText=rows,
            colLabels=["Ticker", "Score", "Precio", "Squeeze", "SQZM Color", "Sector"],
            loc="center", bbox=[0.02, 0.10, 0.96, 0.80],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8.5)
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#eeeeee"); cell.set_text_props(fontweight="bold")
            else:
                cell.set_facecolor("white" if r % 2 == 0 else "#fafafa")
    return fig





# ── Última sección: compras en acciones individuales (universo de calidad) ────

_ETF_GRUPO = {
    "gatillo": ("COMPRA — LP con respaldo en MP (gatillo dado)", COLORS["COMPRA FUERTE"]),
    "cerca":   ("CERCA DEL GATILLO — LP en zona, MP al 60%", "#8a6d00"),
}
_ETF_ETIQUETA_COLOR = {"Calidad": "#1a7a1a", "Datos parciales": "#6a7f00", "Especulativa": "#b26a00"}
_ETF_ALTO_FILA, _ETF_ALTO_SUB, _ETF_Y0, _ETF_Y_MIN = 0.174, 0.034, 0.862, 0.070


def _pct_txt(nivel, precio):
    try:
        return f" ({nivel / precio - 1:+.0%})" if nivel and precio else ""
    except Exception:
        return ""


def _sin_math(t: str) -> str:
    """Evita que matplotlib lea dos signos de dólar como una fórmula (mathtext)."""
    return str(t).replace("$", r"\$")


def _etf_encabezado(ax, meta, n_pag, total):
    ax.add_patch(mpatches.FancyBboxPatch((0, 0.925), 1, 0.075, boxstyle="square,pad=0",
                 fc=COLORS["COMPRA FUERTE"], ec="none"))
    titulo = "SECCIÓN: COMPRAS EN ACCIONES INDIVIDUALES"
    if total > 1:
        titulo += f"  ({n_pag}/{total})"
    ax.text(0.5, 0.968, titulo, ha="center", va="center", fontsize=15, fontweight="bold", color="white")
    ax.text(0.5, 0.940, "Universo de calidad: S&P 1500 + ADRs de índices internacionales, con filtro de "
            "fundamentales", ha="center", va="center", fontsize=7.5, color="white", alpha=0.9)
    if meta.get("error") or n_pag > 1:
        return
    ax.text(0.02, 0.908, f"Universo {meta.get('universo', 0):,} acciones (foto del {meta.get('fecha_universo', 'N/D')})"
            f"  ·  pasan LP {meta.get('pasan_lp', 0):,}  ·  con gatillo MP {meta.get('con_gatillo', 0)} "
            f"(se muestran {meta.get('gatillo_mostradas', 0)})  ·  cerca del gatillo {meta.get('cerca_total', 0)} "
            f"(se muestran {meta.get('cerca_mostradas', 0)})", fontsize=7.4, color=COLORS["text_gray"], va="center")
    ax.text(0.02, 0.893, "Misma lógica de la sección COMPRAS: LP decide si se tiene, MP decide cuándo. "
            "Aplica solo si no has ingresado antes; tesis fundamental: confirmar a mano.",
            fontsize=7.2, color=COLORS["text_gray"], va="center", style="italic")


def _etf_tarjeta(ax, r, y):
    """Tarjeta grande: franja de color con ticker/empresa, ficha a la izquierda, niveles a la derecha."""
    alto = _ETF_ALTO_FILA - 0.010
    color = _ETF_GRUPO[r["grupo"]][1]
    base = y - alto
    ax.add_patch(mpatches.FancyBboxPatch((0.01, base), 0.98, alto, boxstyle="round,pad=0.002,rounding_size=0.008",
                 fc="#fcfdfc", ec="#cfdccf", lw=0.8))
    ax.add_patch(mpatches.FancyBboxPatch((0.01, y - 0.032), 0.98, 0.032, boxstyle="round,pad=0.002,rounding_size=0.008",
                 fc=color, ec="none"))
    ax.text(0.025, y - 0.016, r["ticker"], fontsize=13, fontweight="bold", color="white", va="center")
    ax.text(0.125, y - 0.016, _sin_math(textwrap.shorten(r["empresa"], 50, placeholder="…")), fontsize=11,
            fontweight="bold", color="white", va="center")
    etiqueta = r.get("etiqueta") or ""
    derecha = etiqueta + (f"  ·  calidad {r['calidad']}/100" if r.get("calidad") is not None else "")
    ax.text(0.975, y - 0.016, derecha, fontsize=9, fontweight="bold", color="white", va="center", ha="right")

    # Ficha (izquierda)
    x, yy, paso = 0.025, y - 0.048, 0.016
    for etiqueta_txt, valor in (("Actividad", f"{r['actividad']} ({r['sector']})"),
                                ("Categoría", f"{r.get('categoria_universo') or '—'}   ·   País: {r['pais']}"),
                                ("Tipo", r.get("tipo") or "—")):
        ax.text(x, yy, f"{etiqueta_txt}:", fontsize=8.6, fontweight="bold", color=COLORS["text_dark"], va="center")
        ax.text(x + 0.105, yy, _sin_math(textwrap.shorten(valor, 62, placeholder="…")), fontsize=8.6,
                color=COLORS["text_dark"], va="center")
        yy -= paso
    desc = textwrap.wrap(r.get("descripcion") or "", 86)[:3]
    if len(textwrap.wrap(r.get("descripcion") or "", 86)) > 3:
        desc[-1] = desc[-1].rstrip(" .,;") + "…"
    ax.text(x, y - 0.090, _sin_math("\n".join(desc)), fontsize=8, color=COLORS["text_gray"], va="top",
            style="italic", linespacing=1.4)

    # Niveles (derecha)
    ax.plot([0.66, 0.66], [y - 0.124, y - 0.040], color="#e0e6e0", lw=0.8)
    inval, stop, precio = r.get("invalidacion"), r.get("stop_mp"), r["precio"]
    vig = r.get("vigencia") or {}
    filas = [("Precio", f"${precio:,.2f}"),
             ("Invalidación LP", f"${inval:,.2f}{_pct_txt(inval, precio)}" if inval else "—"),
             ("Stop MP", f"${stop:,.2f}{_pct_txt(stop, precio)}" if stop else "—"),
             ("Confianza", f"LP {r['lp_conf']}%  ·  MP {r['mp_conf']}%"),
             ("Señal activa", f"hace {vig['semanas']} sem." if vig.get("semanas") else "nueva esta semana")]
    yy = y - 0.048
    for k, v in filas:
        ax.text(0.675, yy, k, fontsize=8.4, color=COLORS["text_gray"], va="center")
        ax.text(0.975, yy, _sin_math(v), fontsize=8.6, fontweight="bold", color=COLORS["text_dark"], va="center",
                ha="right")
        yy -= 0.016

    # Pie de la tarjeta: qué falta (cerca del gatillo), riesgo y ETFs
    pie_y = base + 0.010
    if r["grupo"] == "cerca" and r.get("cercania"):
        ax.text(0.025, pie_y + 0.015, _sin_math("Falta para el gatillo: " + "; ".join(r["cercania"]["faltan"] or ["—"])),
                fontsize=8.4, fontweight="bold", color=color, va="center")
    ax.text(0.025, pie_y, _sin_math(textwrap.shorten("ETFs: " + (r.get("etfs") or "—"), 95, placeholder="…")),
            fontsize=7.4, color=COLORS["text_gray"], va="center")
    if r.get("riesgo"):
        ax.text(0.975, pie_y, r["riesgo"], fontsize=7.6, fontweight="bold", color=COLORS["red"], va="center",
                ha="right")


def _make_compras_etf_pages(datos: dict):
    """Páginas finales: primero las compras con gatillo MP, luego las 10 más cercanas al gatillo."""
    compras = (datos or {}).get("compras") or []
    meta = (datos or {}).get("meta") or {}

    # Maquetación: subtítulo al empezar cada grupo; salto de página cuando no cabe.
    paginas, actual, y, grupo_prev = [], [], _ETF_Y0, None
    for r in compras:
        necesita = _ETF_ALTO_FILA + (_ETF_ALTO_SUB if r["grupo"] != grupo_prev else 0)
        if y - necesita < _ETF_Y_MIN:
            paginas.append(actual); actual, y = [], _ETF_Y0
            necesita = _ETF_ALTO_FILA + _ETF_ALTO_SUB
            grupo_prev = None
        if r["grupo"] != grupo_prev:
            actual.append(("sub", r["grupo"], y)); y -= _ETF_ALTO_SUB; grupo_prev = r["grupo"]
        actual.append(("fila", r, y)); y -= _ETF_ALTO_FILA
    paginas.append(actual)

    figuras = []
    for n_pag, elementos in enumerate(paginas, 1):
        fig, ax = plt.subplots(figsize=(8.5, 11))
        fig.subplots_adjust(left=0.03, right=0.97, top=0.985, bottom=0.015)   # página completa: más espacio
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        fig.patch.set_facecolor("white")
        _etf_encabezado(ax, meta, n_pag, len(paginas))
        if meta.get("error"):
            ax.text(0.5, 0.80, meta["error"], ha="center", va="center", fontsize=10, color=COLORS["text_gray"])
        elif not compras:
            ax.text(0.5, 0.75, "Sin compras con gatillo ni acciones cerca del gatillo esta semana.",
                    ha="center", va="center", fontsize=11, color=COLORS["text_gray"])
        for tipo, obj, yy in elementos:
            if tipo == "sub":
                titulo, color = _ETF_GRUPO[obj]
                n = sum(1 for r in compras if r["grupo"] == obj)
                ax.text(0.015, yy - 0.016, f"{titulo}  ·  {n}", fontsize=9.5, fontweight="bold", color=color,
                        va="center")
            else:
                _etf_tarjeta(ax, obj, yy)
        if n_pag == len(paginas) and not meta.get("error"):
            parciales = [c.get("ETF") for c in meta.get("cobertura") or []
                         if "parcial" in str(c.get("Fuente", "")) or "SIN FUENTE" in str(c.get("Fuente", ""))]
            pie = ""
            if meta.get("resto_gatillo"):
                pie += "También con gatillo (no caben en el tope): " + ", ".join(meta["resto_gatillo"]) + ".\n"
            if meta.get("resto_cerca"):
                pie += "También cerca del gatillo: " + ", ".join(meta["resto_cerca"]) + ".\n"
            pie += ("Listas parciales en la foto del universo: " + ", ".join(parciales) + ".  " if parciales else "")
            pie += ("Etiquetas: Calidad = pasó los 4 filtros · Datos parciales = pasó con datos incompletos · "
                    "Especulativa = cupo temático sin utilidades.\nUniverso y fichas: src/universo_etfs.py "
                    "(workflow 'Actualizar universo ETF', trimestral).")
            ax.text(0.02, 0.038, _sin_math("\n".join(textwrap.fill(l, 150) for l in pie.strip().split("\n"))), fontsize=6.5, color=COLORS["text_gray"], va="center", linespacing=1.3)
        figuras.append(fig)
    return figuras
