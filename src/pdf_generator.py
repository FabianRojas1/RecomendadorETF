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
    "COMPRA":        "#2ea82e",
    "COMPRA DEBIL":  "#7ec87e",
    "MANTENER":      "#888888",
    "VENTA DEBIL":   "#e08050",
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
) -> bool:
    """
    Genera el PDF completo del reporte semanal usando matplotlib.
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
        mantener = sorted([r for r in recommendations if "MANTENER" in r.get("action","")],
                          key=lambda x: -abs(x.get("score", 0)))

        with PdfPages(output_path) as pdf:
            # Portada
            pdf.savefig(_make_cover(recommendations, portfolio_total_cop, cop_usd_rate,
                                    len(compras), len(ventas), len(mantener)),
                        bbox_inches="tight")
            plt.close("all")

            # Sección COMPRAS
            if compras:
                pdf.savefig(_make_section_header("COMPRAS", compras, COLORS["COMPRA FUERTE"]),
                            bbox_inches="tight")
                plt.close("all")
                for rec in compras:
                    pdf.savefig(_make_ticker_page(rec), bbox_inches="tight")
                    plt.close("all")

            # Sección VENTAS
            if ventas:
                pdf.savefig(_make_section_header("VENTAS", ventas, COLORS["VENTA FUERTE"]),
                            bbox_inches="tight")
                plt.close("all")
                for rec in ventas:
                    pdf.savefig(_make_ticker_page(rec), bbox_inches="tight")
                    plt.close("all")

            # MANTENER (resumen compacto)
            if mantener:
                pdf.savefig(_make_mantener_page(mantener), bbox_inches="tight")
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
    ax.text(0.5, 0.86, datetime.now().strftime("%A %d de %B de %Y"),
            ha="center", va="center", fontsize=12, color="#aaaadd",
            transform=ax.transAxes)

    # Portfolio summary box
    ax.add_patch(mpatches.FancyBboxPatch((0.05, 0.65), 0.90, 0.14,
                 boxstyle="round,pad=0.01", fc=COLORS["bg_light"], ec="#cccccc"))
    ax.text(0.5, 0.75, f"Portfolio Total:  COP ${total_cop:,.0f}",
            ha="center", va="center", fontsize=13, fontweight="bold",
            color=COLORS["text_dark"], transform=ax.transAxes)
    ax.text(0.5, 0.70, f"Tasa USD/COP: {cop_rate:,.0f}  |  Activos analizados: {len(recs)}",
            ha="center", va="center", fontsize=10, color=COLORS["text_gray"],
            transform=ax.transAxes)

    # Signal summary
    for i, (label, n, color) in enumerate([
        ("COMPRAS", n_comp, COLORS["COMPRA"]),
        ("VENTAS",  n_vent, COLORS["VENTA"]),
        ("MANTENER",n_mant, COLORS["MANTENER"]),
    ]):
        x = 0.18 + i * 0.32
        ax.add_patch(mpatches.FancyBboxPatch((x - 0.12, 0.50), 0.24, 0.12,
                     boxstyle="round,pad=0.01", fc=color, ec="none", alpha=0.9))
        ax.text(x, 0.59, str(n),    ha="center", va="center",
                fontsize=22, fontweight="bold", color="white", transform=ax.transAxes)
        ax.text(x, 0.52, label, ha="center", va="center",
                fontsize=9, color="white", transform=ax.transAxes)

    # Methodology note
    note = (
        "Metodología: EMA 10/55 diario · Squeeze Momentum LazyBear semanal (Trading Latino)\n"
        "ADX 14 semanal · RSI 14 semanal · OBV/VWAP/CMF diario · Noticias NewsAPI\n\n"
        "Señal de COMPRA: Squeeze liberado + histograma verde subiendo + ADX > 25 + DI+ > DI-\n"
        "Señal de VENTA:  Squeeze liberado + histograma rojo bajando  + ADX > 25 + DI- > DI+"
    )
    ax.text(0.5, 0.37, note, ha="center", va="center", fontsize=8.5,
            color=COLORS["text_gray"], transform=ax.transAxes,
            linespacing=1.6, bbox=dict(fc="#f8f8ff", ec="#ddddee", pad=8))

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

    # Mini tabla de resumen
    col_labels = ["Ticker", "Score", "Precio USD", "Target", "Stop Loss"]
    rows = []
    for r in recs[:10]:
        rows.append([
            r.get("ticker", ""),
            f"{r.get('score', 0):+.1f}",
            f"${r.get('price_usd', 0):.2f}",
            f"${r.get('target_usd') or 0:.2f}" if r.get("target_usd") else "—",
            f"${r.get('stop_loss_usd') or 0:.2f}" if r.get("stop_loss_usd") else "—",
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


def _make_ticker_page(rec: dict):
    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    ticker  = rec.get("ticker", "—")
    action  = rec.get("action", "—")
    score   = rec.get("score", 0)
    price   = rec.get("price_usd", 0)
    target  = rec.get("target_usd")
    sl      = rec.get("stop_loss_usd")
    conf    = rec.get("confidence", {})
    comps   = rec.get("score_components", {})
    reasons = rec.get("reasons", [])
    color   = COLORS.get(action, COLORS["MANTENER"])

    # Trading Latino extras
    sq_state   = rec.get("squeeze_state", "")
    sqzm_color = rec.get("sqzm_color", "")
    sqzm_valley= rec.get("sqzm_valley", False)
    sqzm_peak  = rec.get("sqzm_peak",   False)
    adx_v      = rec.get("adx_value", 0)
    rsi_v      = rec.get("rsi_value", 0)

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.91, 1, 0.09])
    ax_h.set_xlim(0, 1); ax_h.set_ylim(0, 1); ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=color, ec="none"))
    ax_h.text(0.03, 0.65, ticker, fontsize=20, fontweight="bold",
              color="white", va="center")
    ax_h.text(0.03, 0.22, action, fontsize=11, color="white", alpha=0.9, va="center")
    ax_h.text(0.97, 0.65, f"Score: {score:+.1f}/40", fontsize=14,
              fontweight="bold", color="white", va="center", ha="right")
    ax_h.text(0.97, 0.22,
              f"Confianza: {conf.get('score',0)}/{conf.get('total',5)}",
              fontsize=9, color="white", alpha=0.85, va="center", ha="right")

    # ── Precios ───────────────────────────────────────────────────────────────
    ax_p = fig.add_axes([0, 0.83, 1, 0.08])
    ax_p.set_xlim(0, 1); ax_p.set_ylim(0, 1); ax_p.axis("off")
    ax_p.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_light"], ec="#cccccc",
                   linewidth=0.5))
    price_str = f"Precio: ${price:.2f} USD"
    if target: price_str += f"   |   Target: ${target:.2f}"
    if sl:     price_str += f"   |   Stop Loss: ${sl:.2f}"
    ax_p.text(0.5, 0.6, price_str, ha="center", va="center",
              fontsize=10.5, fontweight="bold", color=COLORS["text_dark"])

    # ── Bloque Trading Latino ─────────────────────────────────────────────────
    ax_tl = fig.add_axes([0.02, 0.71, 0.96, 0.11])
    ax_tl.set_xlim(0, 1); ax_tl.set_ylim(0, 1); ax_tl.axis("off")
    ax_tl.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                    boxstyle="round,pad=0.02", fc="#fffbe6", ec="#e0c040", linewidth=0.8))
    ax_tl.text(0.5, 0.85, "⚡ Estrategia Trading Latino (semanal)",
               ha="center", va="center", fontsize=9.5, fontweight="bold",
               color="#7a6000")

    # Estado del Squeeze
    sq_label  = {"compressed": "COMPRIMIDO (acumulando presion)",
                 "released":   "LIBERADO (energia en movimiento)",
                 "expanding":  "EXPANDIENDO"}.get(sq_state, sq_state.upper())
    hist_label = {
        "green_strong": "VERDE SUBIENDO  — momentum alcista creciente",
        "green_weak":   "VERDE DEBILITANDO — momentum alcista perdiendo fuerza",
        "red_strong":   "ROJO BAJANDO  — momentum bajista creciente",
        "red_weak":     "ROJO DEBILITANDO  — momentum bajista perdiendo fuerza",
    }.get(sqzm_color, sqzm_color)

    entry_tag = ""
    if sqzm_valley: entry_tag = "  >>> ENTRADA VALLE (señal optima de compra)"
    if sqzm_peak:   entry_tag = "  >>> ENTRADA PICO  (señal optima de venta)"

    tl_line1 = f"Squeeze: {sq_label}"
    tl_line2 = f"Histograma: {hist_label}{entry_tag}"
    tl_line3 = f"ADX: {adx_v:.1f} {'(tendencia fuerte)' if adx_v >= 25 else '(tendencia debil)'}   |   RSI semanal: {rsi_v:.1f}"

    for y, txt, fs in [(0.62, tl_line1, 8.5), (0.40, tl_line2, 8.5), (0.16, tl_line3, 8.5)]:
        ax_tl.text(0.02, y, txt, va="center", fontsize=fs, color="#5a4000")

    # ── Tabla de indicadores ──────────────────────────────────────────────────
    ax_t = fig.add_axes([0.02, 0.38, 0.96, 0.32])
    ax_t.set_xlim(0, 1); ax_t.set_ylim(0, 1); ax_t.axis("off")
    ax_t.text(0, 0.97, "Desglose de indicadores:", fontsize=9.5,
              fontweight="bold", color=COLORS["text_dark"], va="top")

    rows, row_colors = [], []
    for key, comp in comps.items():
        label   = INDICATOR_LABELS.get(key, key)
        pts     = comp.get("weighted_score", 0)
        signal  = comp.get("signal", "—")
        details = comp.get("details", "")
        rows.append([label, f"{pts:+.1f}", signal,
                     textwrap.shorten(details, width=55, placeholder="...")])
        rc = "#e8f5e8" if pts > 0 else "#fde8e8" if pts < 0 else "#f5f5f5"
        row_colors.append([rc, rc, rc, rc])

    if rows:
        tbl = ax_t.table(
            cellText=rows,
            colLabels=["Indicador", "Pts", "Señal", "Detalle"],
            cellColours=row_colors + [["#eeeeee"]*4],
            loc="center", bbox=[0, 0, 1, 0.90],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        tbl.auto_set_column_width([0, 1, 2, 3])
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#ddddee")
                cell.set_text_props(fontweight="bold")

    # ── Razones ───────────────────────────────────────────────────────────────
    if reasons:
        ax_r = fig.add_axes([0.02, 0.18, 0.96, 0.19])
        ax_r.set_xlim(0, 1); ax_r.set_ylim(0, 1); ax_r.axis("off")
        ax_r.text(0, 0.97, "Resumen de señales:", fontsize=9.5,
                  fontweight="bold", color=COLORS["text_dark"], va="top")
        for i, reason in enumerate(reasons[:5]):
            col = COLORS["green"] if reason.startswith("[+]") else \
                  COLORS["red"]   if reason.startswith("[-]") else COLORS["neutral"]
            ax_r.text(0.02, 0.80 - i * 0.18, reason, fontsize=8.5,
                      color=col, va="center")

    # ── Footer ────────────────────────────────────────────────────────────────
    ax_f = fig.add_axes([0, 0, 1, 0.05])
    ax_f.set_xlim(0, 1); ax_f.set_ylim(0, 1); ax_f.axis("off")
    ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#f0f0f0", ec="none"))
    ax_f.text(0.5, 0.5,
              f"Generado {datetime.now().strftime('%d/%m/%Y %H:%M')} | "
              "No constituye asesoría financiera",
              ha="center", va="center", fontsize=7, color="#999999")
    return fig


def _make_mantener_page(mantener: list):
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.add_patch(mpatches.FancyBboxPatch((0, 0.92), 1, 0.08,
                 boxstyle="square,pad=0", fc=COLORS["MANTENER"], ec="none"))
    ax.text(0.5, 0.96, f"MANTENER — {len(mantener)} activos",
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



def _make_news_pages(all_news: list, recommendations: list = None) -> list:
    """
    Paginas de noticias SEPARADAS del analisis tecnico.

    Estructura:
      Pag 1: resumen de sentimiento por ticker (tabla con balance +/-)
      Pag N: titulares de cada ticker, coloreados, con descripcion y fuente

    Nota: son CONTEXTO GEOPOLITICO/MACRO — no modifican el analisis tecnico.
    El score de noticias es independiente de los indicadores tecnicos.
    """
    if recommendations is None:
        recommendations = []

    figs = []

    SENT_COLOR  = {"positive": COLORS["green"], "negative": COLORS["red"],  "neutral": COLORS["neutral"]}
    SENT_MARKER = {"positive": "▲",         "negative": "▼",        "neutral": "●"}

    # ── Agrupar por ticker ────────────────────────────────────────────────────
    by_ticker = {}
    for item in all_news:
        t = item.get("ticker", "MKTG")
        if t not in by_ticker:
            by_ticker[t] = {"pos": 0, "neg": 0, "neu": 0, "items": []}
        s = item.get("sentiment", "neutral")
        if   s == "positive": by_ticker[t]["pos"] += 1
        elif s == "negative": by_ticker[t]["neg"] += 1
        else:                 by_ticker[t]["neu"] += 1
        by_ticker[t]["items"].append(item)

    # ── Pagina resumen ────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(8.5, 11))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    fig.patch.set_facecolor("white")

    ax.add_patch(mpatches.FancyBboxPatch((0, 0.90), 1, 0.10,
                 boxstyle="square,pad=0", fc="#2d4a6e", ec="none"))
    ax.text(0.5, 0.965, "NOTICIAS Y CONTEXTO GEOPOLITICO / MACRO",
            ha="center", va="center", fontsize=13, fontweight="bold",
            color="white", transform=ax.transAxes)
    ax.text(0.5, 0.918,
            "Esta seccion es informacion adicional — no forma parte del analisis tecnico",
            ha="center", va="center", fontsize=8.5, color="#aaccee",
            style="italic", transform=ax.transAxes)

    # Leyenda
    for xi, (sent, lbl) in enumerate([
        ("positive", "▲  Positiva"), ("negative", "▼  Negativa"), ("neutral", "●  Neutral")
    ]):
        xpos = 0.18 + xi * 0.32
        ax.add_patch(mpatches.FancyBboxPatch((xpos - 0.12, 0.838), 0.22, 0.038,
                     boxstyle="round,pad=0.005", fc=SENT_COLOR[sent], ec="none", alpha=0.12))
        ax.text(xpos, 0.857, lbl, ha="center", va="center", fontsize=9,
                fontweight="bold", color=SENT_COLOR[sent], transform=ax.transAxes)

    # Header de tabla
    ax.add_patch(mpatches.FancyBboxPatch((0.01, 0.788), 0.98, 0.040,
                 boxstyle="square,pad=0", fc="#e8eef6", ec="none"))
    for hdr, xp in [("Ticker", 0.08), ("▲ Pos.", 0.30),
                    ("▼ Neg.", 0.50), ("● Neu.", 0.70), ("Balance", 0.88)]:
        ax.text(xp, 0.808, hdr, ha="center", va="center",
                fontsize=8, fontweight="bold", color=COLORS["text_dark"],
                transform=ax.transAxes)

    y = 0.765
    for ticker, data in sorted(by_ticker.items()):
        bal       = data["pos"] - data["neg"]
        bal_color = COLORS["green"] if bal > 0 else COLORS["red"] if bal < 0 else COLORS["neutral"]
        bal_txt   = ("+{}" if bal > 0 else "{}").format(bal)
        row_bg    = "#f4fff4" if bal > 0 else "#fff4f4" if bal < 0 else "white"

        ax.add_patch(mpatches.FancyBboxPatch((0.01, y - 0.015), 0.98, 0.028,
                     boxstyle="square,pad=0", fc=row_bg, ec="#eeeeee"))
        for val, xp, color, fw in [
            (ticker,           0.08, COLORS["text_dark"], "bold"),
            (str(data["pos"]), 0.30, COLORS["green"],     "normal"),
            (str(data["neg"]), 0.50, COLORS["red"],       "normal"),
            (str(data["neu"]), 0.70, COLORS["neutral"],   "normal"),
            (bal_txt,          0.88, bal_color,           "bold"),
        ]:
            ax.text(xp, y, val, ha="center", va="center", fontsize=8,
                    fontweight=fw, color=color, transform=ax.transAxes)
        y -= 0.032
        if y < 0.08:
            break

    ax.text(0.5, 0.03,
            "Fuente: NewsAPI.org  |  Clasificacion automatica por palabras clave  |  "
            "No constituyen consejo de inversion",
            ha="center", va="bottom", fontsize=7, color=COLORS["text_gray"],
            style="italic", transform=ax.transAxes)

    figs.append(fig)

    # ── Una pagina por ticker con sus titulares ───────────────────────────────
    for ticker, data in sorted(by_ticker.items()):
        items = data["items"]
        if not items:
            continue

        fig, ax = plt.subplots(figsize=(8.5, 11))
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        fig.patch.set_facecolor("white")

        bal       = data["pos"] - data["neg"]
        hdr_color = "#1a5c1a" if bal > 0 else "#6a0000" if bal < 0 else "#2d4a6e"
        bal_label = ("Sentimiento POSITIVO" if bal > 0
                     else "Sentimiento NEGATIVO" if bal < 0
                     else "Sentimiento NEUTRAL")

        ax.add_patch(mpatches.FancyBboxPatch((0, 0.90), 1, 0.10,
                     boxstyle="square,pad=0", fc=hdr_color, ec="none"))
        ax.text(0.05, 0.960, f"[NOTICIAS]  {ticker}",
                va="center", fontsize=14, fontweight="bold",
                color="white", transform=ax.transAxes)
        ax.text(0.05, 0.918,
                f"{bal_label}  |  ▲ {data['pos']}  ▼ {data['neg']}  ● {data['neu']}",
                va="center", fontsize=9, color="#dddddd", transform=ax.transAxes)

        # Banner "no es analisis tecnico"
        ax.add_patch(mpatches.FancyBboxPatch((0.01, 0.875), 0.98, 0.018,
                     boxstyle="square,pad=0", fc="#f0f4fa", ec="none"))
        ax.text(0.5, 0.884,
                "Contexto macro/geopolitico — no forma parte del analisis tecnico",
                ha="center", va="center", fontsize=7.5,
                color="#4466aa", style="italic", transform=ax.transAxes)

        y = 0.855
        for item in items:
            sent     = item.get("sentiment", "neutral")
            marker   = SENT_MARKER.get(sent, "●")
            color    = SENT_COLOR.get(sent, COLORS["neutral"])
            title    = item.get("title", "Sin titulo")
            source   = item.get("source", {})
            src_name = source.get("name", "") if isinstance(source, dict) else str(source)
            desc     = (item.get("description") or "")
            date     = (item.get("publishedAt", "") or "")[:10]

            # Barra lateral de sentimiento
            ax.add_patch(mpatches.FancyBboxPatch((0.01, y - 0.060), 0.007, 0.065,
                         boxstyle="square,pad=0", fc=color, ec="none", alpha=0.75))

            # Fuente + fecha
            hdr_line = f"{marker}  {src_name}" if src_name else marker
            ax.text(0.025, y, hdr_line, va="top", fontsize=7.5,
                    fontweight="bold", color=color, transform=ax.transAxes)
            if date:
                ax.text(0.92, y, date, va="top", ha="right", fontsize=7,
                        color=COLORS["text_gray"], transform=ax.transAxes)

            # Titulo (max 2 lineas)
            title_lines = textwrap.fill(title, width=82).split("\n")[:2]
            for li, line in enumerate(title_lines):
                ax.text(0.025, y - 0.018 - li * 0.018, line, va="top",
                        fontsize=8.5, color=COLORS["text_dark"],
                        transform=ax.transAxes)

            # Descripcion (1 linea, en gris)
            if desc:
                short_desc = textwrap.shorten(desc, width=105, placeholder="...")
                ax.text(0.025, y - 0.054, short_desc, va="top", fontsize=7.5,
                        color=COLORS["text_gray"], style="italic",
                        transform=ax.transAxes)

            ax.axhline(y - 0.065, xmin=0.02, xmax=0.98,
                       color="#dddddd", linewidth=0.5)
            y -= 0.076
            if y < 0.04:
                break

        ax.text(0.5, 0.02, "Fuente: NewsAPI.org  |  Clasificacion automatica",
                ha="center", va="bottom", fontsize=7,
                color=COLORS["text_gray"], style="italic", transform=ax.transAxes)

        figs.append(fig)

    return figs
