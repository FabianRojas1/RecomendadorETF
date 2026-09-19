"""
signals.py - Motor de señales LP (largo plazo) + MP (mediano plazo).

Implementa literalmente los checklists del usuario:

  LP  (marco mensual)   : decide SI se tiene el activo.
  MP  (marco semanal,
       contexto mensual): decide CUANDO entrar o salir.

Reglas de combinacion:
  - Se compran tramos LP cuando el MP da gatillo. Si el gatillo no llega en
    4-6 semanas, se compra igual.
  - Salida MP  -> recorte tactico, maximo 25% de la posicion. Nunca vende todo.
  - Salida LP  -> manda la regla LP, sin importar lo que diga el MP.

Este modulo es PURO: recibe un diccionario de valores escalares ya calculados
(ver indicators.py) y devuelve diccionarios. No depende de pandas ni de red,
por lo que se puede probar con datos sinteticos.

Colores del squeeze (vocabulario del checklist, NO el de LazyBear):
  verde_claro   histograma > 0 y subiendo   -> impulso alcista fuerte
  verde_oscuro  histograma > 0 y bajando    -> alcista perdiendo fuerza (corrige)
  rojo_oscuro   histograma < 0 y subiendo   -> bajista recuperandose (corrige)
  rojo_claro    histograma < 0 y bajando    -> bajista acelerando (colapso)
"""
import logging

logger = logging.getLogger(__name__)

# ── Umbrales (configurables desde config.py si se quiere) ─────────────────────
ADX_MIN_MP          = 20.0   # ADX semanal minimo para dar por buena la ubicacion
SOPORTE_ATR_MULT    = 1.0    # "cerca de soporte" = dentro de N x ATR semanal
EXTENSION_ATR_MULT  = 2.0    # "precio extendido" = N x ATR sobre EMA10
INVALIDACION_ATR    = 1.5    # nivel de invalidacion LP = EMA55m - N x ATR mensual
SEMANAS_COMPRA_IGUAL = 4     # si el gatillo MP no llega en N semanas, comprar igual

VERDES = ("verde_claro", "verde_oscuro")
ROJOS  = ("rojo_claro", "rojo_oscuro")


# ── Utilidades ────────────────────────────────────────────────────────────────

def _num(v):
    """Devuelve el valor si es un numero utilizable, si no None."""
    try:
        if v is None:
            return None
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _chk(etiqueta: str, cumple, detalle: str = "") -> dict:
    """Un item de checklist. cumple puede ser True / False / None (sin datos)."""
    return {"item": etiqueta, "cumple": cumple, "detalle": detalle}


def _todos(items) -> bool:
    return all(i["cumple"] is True for i in items)


# =============================================================================
# LP - Largo plazo (marco mensual)
# =============================================================================

def evaluar_lp(v: dict) -> dict:
    """
    Checklist LP (Info3). Marco unico mensual, revision al cierre de mes.

    Devuelve:
      estado        : TENER | VIGILAR | NO TENER | SIN DATOS
      confianza_pct : 50 (tendencia cumplida) | 100 (+ zona de compra) | 0
      tendencia     : lista de items de checklist
      zona_compra   : lista de items de checklist
      ventas        : dict con las banderas de venta LP
      invalidacion  : nivel de precio de invalidacion (o None)
      notas         : lista de textos informativos
    """
    close   = _num(v.get("men_close"))
    ema10   = _num(v.get("men_ema10"))
    ema55   = _num(v.get("men_ema55"))
    ema200  = _num(v.get("men_ema200"))
    pend55  = _num(v.get("men_ema55_pendiente"))
    atr     = _num(v.get("men_atr"))
    color   = v.get("men_sqz_color", "desconocido")
    obv_min = v.get("men_obv_min_nuevo")
    proxy   = bool(v.get("men_ema200_proxy", False))
    notas   = []

    if close is None or ema55 is None or ema200 is None:
        return {
            "estado": "SIN DATOS",
            "confianza_pct": 0,
            "tendencia": [],
            "zona_compra": [],
            "ventas": {},
            "invalidacion": None,
            "notas": ["Historial mensual insuficiente para evaluar LP."],
        }

    if proxy:
        notas.append("EMA200 de referencia tomada del marco semanal "
                     "(historial mensual insuficiente).")

    # ── 1. Tendencia de largo plazo ───────────────────────────────────────────
    sobre_200 = close > ema200
    tendencia = [
        _chk("Precio sobre EMA200 mensual", sobre_200,
             f"cierre {close:,.2f} vs EMA200 {ema200:,.2f}"),
        _chk("EMA55 mensual con pendiente positiva",
             (pend55 > 0) if pend55 is not None else None,
             f"pendiente {pend55:+.2f}" if pend55 is not None else "sin datos"),
    ]

    # ── 2. Zona de compra (retroceso sano) ────────────────────────────────────
    if ema10 is not None and atr is not None:
        en_retroceso = (close < ema10) and (close > ema55 - atr)
        det_retro = (f"cierre {close:,.2f} bajo EMA10 {ema10:,.2f} "
                     f"y sobre EMA55-ATR {ema55 - atr:,.2f}")
    else:
        en_retroceso, det_retro = None, "sin datos de EMA10/ATR mensual"

    sqz_corrige = color in ("verde_oscuro", "rojo_oscuro") if color != "desconocido" else None
    obv_sano    = (not obv_min) if obv_min is not None else None

    zona_compra = [
        _chk("Precio en retroceso (bajo EMA10, cerca de EMA55)", en_retroceso, det_retro),
        _chk("SQZ mensual corrigiendo (verde oscuro o rojo oscuro)", sqz_corrige,
             f"SQZ {color}"),
        _chk("OBV mensual sin minimos nuevos", obv_sano,
             "sin distribucion fuerte" if obv_sano else "OBV marca minimo nuevo"),
    ]

    # ── Nivel de invalidacion ─────────────────────────────────────────────────
    invalidacion = (ema55 - INVALIDACION_ATR * atr) if atr is not None else None

    # ── Reglas de venta LP ────────────────────────────────────────────────────
    bajo_invalidacion = invalidacion is not None and close < invalidacion
    ventas = {
        "venta_total": bool((not sobre_200) or bajo_invalidacion),
        "reduccion_50": bool(close < ema55 and color == "rojo_claro"),
        "rebalanceo_parcial": bool(
            ema10 is not None and atr is not None
            and close > ema10 + EXTENSION_ATR_MULT * atr
            and color == "verde_oscuro"
        ),
    }

    # ── Estado ────────────────────────────────────────────────────────────────
    if not sobre_200:
        estado, confianza = "NO TENER", 0
        notas.append("Precio bajo EMA200 mensual: el checklist LP no permite comprar.")
    elif ventas["reduccion_50"]:
        estado, confianza = "VIGILAR", 0
        notas.append("Cierre mensual bajo EMA55 con SQZ en rojo claro: fase de reduccion, no de acumulacion.")
    elif _todos(tendencia):
        if _todos(zona_compra):
            estado, confianza = "TENER", 100
        else:
            estado, confianza = "TENER", 50
    else:
        estado, confianza = "VIGILAR", 0
        notas.append("Sobre EMA200 pero la EMA55 mensual aun no tiene pendiente positiva.")

    return {
        "estado": estado,
        "confianza_pct": confianza,
        "tendencia": tendencia,
        "zona_compra": zona_compra,
        "ventas": ventas,
        "invalidacion": invalidacion,
        "notas": notas,
    }


# =============================================================================
# MP - Mediano plazo (contexto mensual + operativa semanal)
# =============================================================================

def evaluar_mp(v: dict) -> dict:
    """
    Checklist MP (Info2). Contexto mensual + ubicacion y gatillo semanales.

    Confianza: 30% contexto -> 60% + ubicacion -> 100% + gatillo.

    Devuelve:
      estado        : ENTRAR AHORA | ESPERAR GATILLO | SALIR | MANTENER | SIN DATOS
      confianza_pct : 0 | 30 | 60 | 100
      contexto / ubicacion / gatillo : listas de items de checklist
      ventas        : dict con banderas de venta MP
      media_posicion: True si el contexto solo admite media posicion
      notas         : lista de textos informativos
    """
    s_close = _num(v.get("sem_close"))
    s_e10   = _num(v.get("sem_ema10"))
    s_e55   = _num(v.get("sem_ema55"))
    s_e200  = _num(v.get("sem_ema200"))
    s_adx   = _num(v.get("sem_adx"))
    s_atr   = _num(v.get("sem_atr"))
    s_min12 = _num(v.get("sem_min_12"))
    s_color = v.get("sem_sqz_color", "desconocido")
    s_prev  = v.get("sem_sqz_color_prev", "desconocido")
    s_obv   = v.get("sem_obv_sobre_ema20")
    s_obvd  = v.get("sem_obv_divergencia", "ninguna")
    s_rsid  = v.get("sem_rsi_divergencia", "ninguna")

    m_close = _num(v.get("men_close"))
    m_e55   = _num(v.get("men_ema55"))
    m_e200  = _num(v.get("men_ema200"))
    m_color = v.get("men_sqz_color", "desconocido")

    notas = []

    if s_close is None or s_e10 is None or s_atr is None:
        return {
            "estado": "SIN DATOS",
            "confianza_pct": 0,
            "contexto": [], "ubicacion": [], "gatillo": [],
            "ventas": {}, "media_posicion": False, "stop_mp": None,
            "notas": ["Historial semanal insuficiente para evaluar MP."],
        }

    # ── 1. Contexto (mensual) ─────────────────────────────────────────────────
    media_posicion = False
    if m_close is not None and m_e55 is not None:
        sobre_e55m = m_close > m_e55
        if not sobre_e55m and m_e200 is not None and m_close > m_e200:
            media_posicion = True
            notas.append("Bajo EMA55 mensual pero sobre EMA200: solo media posicion.")
        det_ctx = f"cierre mensual {m_close:,.2f} vs EMA55m {m_e55:,.2f}"
        ctx_precio = sobre_e55m or media_posicion
    else:
        sobre_e55m, ctx_precio, det_ctx = None, None, "sin datos mensuales"

    ctx_sqz = (m_color != "rojo_claro") if m_color != "desconocido" else None

    contexto = [
        _chk("Precio sobre EMA55 mensual", ctx_precio, det_ctx),
        _chk("SQZ mensual no esta en rojo claro", ctx_sqz, f"SQZ mensual {m_color}"),
    ]
    contexto_ok = _todos(contexto)

    # ── 2. Ubicacion (semanal) ────────────────────────────────────────────────
    soportes = [("EMA55 semanal", s_e55), ("EMA200 semanal", s_e200),
                ("minimo de 12 semanas", s_min12)]
    tolerancia = SOPORTE_ATR_MULT * s_atr
    cercanos = [(nombre, nivel) for nombre, nivel in soportes
                if nivel is not None and abs(s_close - nivel) <= tolerancia]
    cerca_soporte = len(cercanos) > 0
    det_soporte = (", ".join(n for n, _ in cercanos) if cercanos
                   else f"sin soporte dentro de 1 ATR ({tolerancia:,.2f})")

    adx_ok = (s_adx > ADX_MIN_MP) if s_adx is not None else None
    if adx_ok is False and cerca_soporte:
        notas.append(f"ADX {s_adx:.1f} lateral: valido solo para acumular, no para impulso.")

    # Stop sugerido segun el checklist: soporte - 2 x ATR semanal.
    # Se toma el soporte relevante mas alto que quede por debajo del precio;
    # si no hay ninguno, se usa la EMA55 semanal como referencia.
    niveles = [n for _, n in soportes if n is not None]
    debajo  = [n for n in niveles if n <= s_close]
    base_stop = max(debajo) if debajo else (min(niveles) if niveles else None)
    stop_mp = (base_stop - 2.0 * s_atr) if base_stop is not None else None

    ubicacion = [
        _chk("Precio cerca de soporte (1 ATR semanal)", cerca_soporte, det_soporte),
        _chk(f"ADX semanal > {ADX_MIN_MP:.0f}", adx_ok,
             f"ADX {s_adx:.1f}" if s_adx is not None else "sin datos"),
    ]
    ubicacion_ok = _todos(ubicacion)

    # ── 3. Gatillo (semanal) ──────────────────────────────────────────────────
    sqz_gira   = (s_prev == "rojo_oscuro") and (s_color in VERDES)
    sobre_e10  = s_close > s_e10
    g_precio   = bool(sqz_gira or sobre_e10)
    det_gatillo = []
    if sqz_gira:
        det_gatillo.append("SQZ paso de rojo oscuro a verde")
    if sobre_e10:
        det_gatillo.append(f"cierre {s_close:,.2f} sobre EMA10 {s_e10:,.2f}")
    if not det_gatillo:
        det_gatillo.append(f"SQZ {s_color} y cierre bajo EMA10")

    g_obv = None
    if s_obv is not None or s_obvd != "ninguna":
        g_obv = bool(s_obv) or (s_obvd == "alcista")
    det_obv = ("OBV sobre su EMA20" if s_obv else
               "divergencia alcista de OBV" if s_obvd == "alcista" else
               "OBV bajo su EMA20")

    gatillo = [
        _chk("SQZ gira a verde o cierre sobre EMA10 semanal", g_precio,
             " | ".join(det_gatillo)),
        _chk("OBV sobre su EMA20 o divergencia alcista", g_obv, det_obv),
    ]
    gatillo_ok = _todos(gatillo)

    # ── Confianza acumulativa ─────────────────────────────────────────────────
    if not contexto_ok:
        confianza = 0
    elif not ubicacion_ok:
        confianza = 30
    elif not gatillo_ok:
        confianza = 60
    else:
        confianza = 100

    # ── Reglas de venta MP ────────────────────────────────────────────────────
    extendido = s_close > s_e10 + EXTENSION_ATR_MULT * s_atr
    sqz_techo = (s_prev == "verde_claro") and (s_color == "verde_oscuro")
    div_baj   = (s_rsid == "bajista") or (s_obvd == "bajista")
    bajo_e10  = s_close < s_e10
    bajo_e55  = (s_e55 is not None) and (s_close < s_e55)
    stop_tesis = (m_close is not None and m_e55 is not None
                  and m_close < m_e55 and m_color == "rojo_claro")

    ventas = {
        "parcial": bool(extendido or sqz_techo or div_baj),
        "trailing_ema10": bool(bajo_e10),
        "trailing_ema55": bool(bajo_e55),
        "stop_tesis": bool(stop_tesis),
        "motivos": [m for m, activo in (
            ("precio extendido >2 ATR sobre EMA10", extendido),
            ("SQZ paso de verde claro a verde oscuro", sqz_techo),
            ("divergencia bajista en RSI u OBV", div_baj),
            ("cierre semanal bajo EMA10", bajo_e10),
            ("cierre semanal bajo EMA55", bajo_e55),
            ("cierre mensual bajo EMA55 con SQZ rojo claro", stop_tesis),
        ) if activo],
    }

    # ── Estado ────────────────────────────────────────────────────────────────
    hay_venta = ventas["parcial"] or ventas["trailing_ema55"] or ventas["stop_tesis"]

    if confianza == 100 and not div_baj:
        estado = "ENTRAR AHORA"
    elif hay_venta:
        estado = "SALIR"
    elif contexto_ok:
        estado = "ESPERAR GATILLO"
    else:
        estado = "MANTENER"

    return {
        "estado": estado,
        "confianza_pct": confianza,
        "contexto": contexto,
        "ubicacion": ubicacion,
        "gatillo": gatillo,
        "ventas": ventas,
        "media_posicion": media_posicion,
        "stop_mp": stop_mp,
        "notas": notas,
    }


# =============================================================================
# Combinacion LP + MP (Info1)
# =============================================================================

def combinar(lp: dict, mp: dict, semanas_en_estado=None, tiene_posicion=False) -> dict:
    """
    Cruza el veredicto LP con el MP segun las reglas de Info1.

    semanas_en_estado: semanas que lleva activa la señal combinada (o None).
    tiene_posicion   : si el activo ya esta en el portafolio.

    Devuelve: accion, horizonte, texto, confianza_pct, avisos.
    """
    e_lp = lp.get("estado", "SIN DATOS")
    e_mp = mp.get("estado", "SIN DATOS")
    v_lp = lp.get("ventas", {}) or {}
    v_mp = mp.get("ventas", {}) or {}
    avisos = []

    if mp.get("media_posicion"):
        avisos.append("Contexto mensual admite solo media posicion.")

    # 1. La regla LP manda sobre cualquier lectura de MP.
    if v_lp.get("venta_total"):
        return {
            "accion": "VENTA TOTAL",
            "horizonte": "LP",
            "confianza_pct": 100,
            "texto": "Venta total en LP: precio bajo EMA200 mensual o bajo el nivel de invalidacion.",
            "avisos": avisos + ["La regla LP manda sin importar lo que diga el MP."],
        }

    if v_lp.get("reduccion_50"):
        return {
            "accion": "REDUCIR 50%",
            "horizonte": "LP",
            "confianza_pct": 100,
            "texto": "Reduccion LP del 50%: cierre mensual bajo EMA55 con SQZ mensual en rojo claro.",
            "avisos": avisos,
        }

    if e_lp == "NO TENER":
        return {
            "accion": "NO TENER",
            "horizonte": "LP",
            "confianza_pct": 0,
            "texto": "El checklist LP no permite mantener ni abrir posicion (precio bajo EMA200 mensual).",
            "avisos": avisos,
        }

    if e_lp == "SIN DATOS":
        return {
            "accion": "SIN DATOS",
            "horizonte": "-",
            "confianza_pct": 0,
            "texto": "Historial insuficiente para un veredicto de largo plazo.",
            "avisos": avisos,
        }

    # 2. Rebalanceo por extension (venta parcial LP, no cambia la tesis).
    if v_lp.get("rebalanceo_parcial"):
        avisos.append("Precio muy extendido sobre EMA10 mensual: considerar recorte de 20-30% por rebalanceo.")

    # 3. LP vigente -> el MP decide el momento.
    if e_lp == "TENER":
        if e_mp == "ENTRAR AHORA":
            texto = "Compra en LP con respaldo en MP."
            if not tiene_posicion:
                texto += " Señal de entrada al 100% (aplica si aun no has ingresado)."
            return {"accion": "COMPRAR", "horizonte": "LP+MP", "confianza_pct": 100,
                    "texto": texto, "avisos": avisos}

        if e_mp == "ESPERAR GATILLO":
            texto = "Compra en LP, a la espera de gatillo en MP."
            conf = mp.get("confianza_pct", 30)
            texto += f" Seguridad de entrada {conf}% (aplica si aun no has ingresado)."
            if semanas_en_estado is not None and semanas_en_estado >= SEMANAS_COMPRA_IGUAL:
                avisos.append(
                    f"El gatillo de MP no llega hace {semanas_en_estado} semanas: "
                    "segun tu regla, comprar el tramo LP de todas formas."
                )
            return {"accion": "COMPRAR (LP)", "horizonte": "LP", "confianza_pct": conf,
                    "texto": texto, "avisos": avisos}

        if e_mp == "SALIR":
            motivos = ", ".join(v_mp.get("motivos", [])) or "señal de salida semanal"
            return {"accion": "RECORTE TACTICO", "horizonte": "MP", "confianza_pct": 100,
                    "texto": f"Mantener la tesis LP y recortar como maximo 25% por MP ({motivos}).",
                    "avisos": avisos + ["Una salida de MP nunca vende toda la posicion."]}

        return {"accion": "MANTENER", "horizonte": "LP", "confianza_pct": lp.get("confianza_pct", 50),
                "texto": "Tesis LP vigente. Sin señal de entrada ni de salida en MP.",
                "avisos": avisos}

    # 4. LP en vigilancia -> solo lecturas tacticas.
    if e_mp == "SALIR":
        motivos = ", ".join(v_mp.get("motivos", [])) or "señal de salida semanal"
        return {"accion": "RECORTE TACTICO", "horizonte": "MP", "confianza_pct": 100,
                "texto": f"Recorte tactico por MP ({motivos}). El LP aun no confirma tendencia.",
                "avisos": avisos}

    if e_mp == "ENTRAR AHORA":
        return {"accion": "ENTRADA TACTICA", "horizonte": "MP", "confianza_pct": 100,
                "texto": "Entrada tactica de MP. El LP todavia no confirma tendencia de largo plazo.",
                "avisos": avisos + ["Sin respaldo de LP: tratar como posicion de mediano plazo."]}

    return {"accion": "VIGILAR", "horizonte": "LP", "confianza_pct": 0,
            "texto": "Sobre EMA200 mensual pero sin tendencia LP confirmada. Sin accion.",
            "avisos": avisos}


def evaluar(v: dict, semanas_en_estado=None, tiene_posicion=False) -> dict:
    """Punto de entrada unico: devuelve lp, mp y la recomendacion combinada."""
    lp = evaluar_lp(v)
    mp = evaluar_mp(v)
    return {"lp": lp, "mp": mp, "combinada": combinar(lp, mp, semanas_en_estado, tiene_posicion)}
