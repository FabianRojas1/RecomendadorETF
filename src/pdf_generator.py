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

            # Gráfica del portafolio
            pdf.savefig(_make_portfolio_chart(recommendations), bbox_inches="tight")
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

def _make_portfolio_chart(recs: list):
    """
    Página 2: Vista del portafolio por tipo de acción.
      - Izquierda: donut chart (número de activos)
      - Derecha:   barras horizontales (% del portafolio en COP)
      - Abajo:     tabla de top activos por score absoluto
    """
    ORDER  = ["COMPRA FUERTE", "COMPRA", "MANTENER", "VENTA", "VENTA FUERTE"]
    CLABEL = {"COMPRA FUERTE": "Compra\nFuerte", "COMPRA": "Compra",
              "MANTENER": "Mantener", "VENTA": "Venta", "VENTA FUERTE": "Venta\nFuerte"}

    # Agrupar
    groups: dict[str, list] = {k: [] for k in ORDER}
    for r in recs:
        a = r.get("action", "MANTENER")
        key = a if a in groups else "MANTENER"
        groups[key].append(r)

    labels  = [k for k in ORDER if groups[k]]
    counts  = [len(groups[k]) for k in labels]
    colors  = [COLORS[k] for k in labels]
    total_cop_val = sum(r.get("current_value_cop", 0) or 0 for r in recs) or 1
    pcts    = [
        sum((r.get("current_value_cop", 0) or 0) for r in groups[k]) / total_cop_val * 100
        for k in labels
    ]

    fig = plt.figure(figsize=(8.5, 11))
    fig.patch.set_facecolor("white")

    # ── Encabezado ────────────────────────────────────────────────────────────
    ax_h = fig.add_axes([0, 0.93, 1, 0.07])
    ax_h.axis("off")
    ax_h.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc=COLORS["bg_header"], ec="none"))
    ax_h.text(0.5, 0.55, "Distribución del Portafolio por Señal",
              ha="center", va="center", fontsize=14, fontweight="bold", color="white")
    ax_h.text(0.5, 0.18, f"{len(recs)} activos analizados — {datetime.now().strftime('%d/%m/%Y')}",
              ha="center", va="center", fontsize=9, color="#aaaadd")

    # ── Donut chart (izquierda) ────────────────────────────────────────────────
    ax_d = fig.add_axes([0.02, 0.58, 0.44, 0.33])
    wedges, texts, autotexts = ax_d.pie(
        counts, labels=None, colors=colors,
        autopct=lambda p: f"{p:.0f}%" if p > 5 else "",
        startangle=90, pctdistance=0.75,
        wedgeprops={"width": 0.55, "edgecolor": "white", "linewidth": 1.5},
    )
    for at in autotexts:
        at.set_fontsize(9); at.set_fontweight("bold"); at.set_color("white")
    ax_d.set_title("N.° de activos", fontsize=10, fontweight="bold",
                   color=COLORS["text_dark"], pad=8)

    # Leyenda
    ax_d.legend(
        wedges,
        [f"{CLABEL[k]}  ({len(groups[k])})" for k in labels],
        loc="lower center", bbox_to_anchor=(0.5, -0.18),
        fontsize=8, ncol=2, frameon=False,
    )

    # ── Barras horizontales (derecha) ──────────────────────────────────────────
    ax_b = fig.add_axes([0.52, 0.60, 0.44, 0.28])
    ax_b.set_xlim(0, max(pcts) * 1.15 if pcts else 100)
    ax_b.set_ylim(-0.5, len(labels) - 0.5)
    ax_b.set_yticks(range(len(labels)))
    ax_b.set_yticklabels([CLABEL[k] for k in labels], fontsize=9)
    ax_b.set_xlabel("% del portafolio (COP)", fontsize=8)
    ax_b.set_title("Exposición en COP", fontsize=10, fontweight="bold",
                   color=COLORS["text_dark"])
    ax_b.spines[["top", "right"]].set_visible(False)
    ax_b.tick_params(axis="x", labelsize=8)

    for i, (pct, color) in enumerate(zip(pcts, colors)):
        ax_b.barh(i, pct, color=color, alpha=0.85, height=0.6)
        ax_b.text(pct + 0.5, i, f"{pct:.1f}%", va="center", fontsize=8,
                  color=COLORS["text_dark"], fontweight="bold")

    # ── Tabla: top activos por score absoluto ──────────────────────────────────
    ax_t = fig.add_axes([0.02, 0.08, 0.96, 0.46])
    ax_t.axis("off")
    ax_t.text(0, 0.99, "Ranking de activos por señal (score absoluto):",
              fontsize=10, fontweight="bold", color=COLORS["text_dark"],
              va="top", transform=ax_t.transAxes)

    sorted_recs = sorted(recs, key=lambda x: -abs(x.get("score", 0)))[:20]

    tbl_data   = []
    tbl_colors = []
    for r in sorted_recs:
        act   = r.get("action", "")
        score = r.get("score", 0)
        price = r.get("price_usd", 0) or 0
        val   = r.get("current_value_cop", 0) or 0
        pct_p = r.get("pct_portfolio", "") or ""
        tbl_data.append([
            r.get("ticker", ""),
            act,
            f"{score:+.1f}",
            f"${price:.2f}",
            f"COP {val:,.0f}" if val else "—",
            str(pct_p),
        ])
        rc = COLORS.get(act, COLORS["MANTENER"])
        tbl_colors.append([rc, rc, rc, "#f5f5f5", "#f5f5f5", "#f5f5f5"])

    if tbl_data:
        tbl = ax_t.table(
            cellText=tbl_data,
            colLabels=["Ticker", "Acción", "Score", "Precio USD", "Valor COP", "% Port."],
            loc="upper center", bbox=[0, 0, 1, 0.95],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        tbl.auto_set_column_width([0, 1, 2, 3, 4, 5])
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#2d3a5a")
                cell.set_text_props(fontweight="bold", color="white")
            elif r <= len(tbl_colors):
                cell.set_facecolor(tbl_colors[r - 1][c])
                if c <= 2:
                    cell.set_text_props(color="white", fontweight="bold")

    # ── Footer ────────────────────────────────────────────────────────────────
    ax_f = fig.add_axes([0, 0, 1, 0.04])
    ax_f.axis("off")
    ax_f.add_patch(mpatches.FancyBboxPatch((0, 0), 1, 1,
                   boxstyle="square,pad=0", fc="#f0f0f0", ec="none"))
    ax_f.text(0.5, 0.5,
              "No constituye asesoría financiera. Solo para referencia personal.",
              ha="center", va="center", fontsize=7, color="#999999")
    return fig


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
        pts     = float(comp.get("weighted_score", 0) or 0)
        signal  = str(comp.get("signal", "") or "")
        details = str(comp.get("details", "") or "")
        rows.append([label, f"{pts:+.1f}", signal,
                     textwrap.shorten(details, width=55, placeholder="...")])
        rc = "#e8f5e8" if pts > 0 else "#fde8e8" if pts < 0 else "#f5f5f5"
        row_colors.append([rc, rc, rc, rc])

    if rows:
        # cellColours se aplica manualmente por celda para evitar errores de conteo
        tbl = ax_t.table(
            cellText=rows,
            colLabels=["Indicador", "Pts", "Señal", "Detalle"],
            loc="center", bbox=[0, 0, 1, 0.90],
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8)
        tbl.auto_set_column_width([0, 1, 2, 3])
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#ddddee")
                cell.set_text_props(fontweight="bold")
            elif r <= len(row_colors):
                cell.set_facecolor(row_colors[r - 1][c])

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



