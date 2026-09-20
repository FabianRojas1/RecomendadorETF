"""
ia_sintesis.py - Sintesis cualitativa del regimen de mercado.

Principios de diseño, en orden de importancia:

1. EL BOT NUNCA DEPENDE DE UN PROVEEDOR. Si no hay API key, si la API falla,
   si responde basura o si cambia de terminos, se usa el respaldo en Python y
   el reporte sale igual. Ninguna excepcion sube de este modulo.
2. LAS FECHAS NO LAS PONE EL MODELO. Se calculan en calendario.py. Aqui se le
   prohibe explicitamente inventarlas.
3. LOS NUMEROS DUROS NO LOS PONE EL MODELO. Los indicadores se calculan en
   Python; el modelo solo interpreta.
4. TODO LO QUE DEVUELVE SE VALIDA. Estados de una lista cerrada, probabilidades
   enteras que suman 100, catalizadores acotados y deduplicados.

Cambiar de proveedor = escribir otra funcion _llamar_<proveedor> y apuntar
PROVEEDOR. El resto del bot no se entera.
"""
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

PROVEEDOR   = os.getenv("LLM_PROVEEDOR", "groq")
GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"

# Lista de modelos en orden de preferencia. Groq retira y renombra modelos sin
# avisar, y el catalogo depende del plan de la cuenta: si el primero responde
# 404 model_not_found se intenta el siguiente, y el reporte sale con IA igual.
# LLM_MODELO acepta un nombre o varios separados por coma y reemplaza la lista.
GROQ_MODELOS = [m.strip() for m in os.getenv(
    "LLM_MODELO",
    "llama3-70b-8192,"
    "llama-3.3-70b-versatile,"
    "llama-3.1-8b-instant,"
    "openai/gpt-oss-20b"
).split(",") if m.strip()]

GROQ_MODELO_USADO = None        # lo fija _llamar_groq con el que si respondio
TIMEOUT_S   = 30

ESTADOS = ("BULL", "BEAR", "RANGO")
CATEGORIAS = ("geopolitica", "materias_primas")
MAX_POR_CATEGORIA = 2

_PALABRAS = {
    "geopolitica": ("guerra", "war", "conflicto", "arancel", "tariff", "sancion",
                    "sanction", "eleccion", "election", "china", "iran", "russia",
                    "rusia", "ukraine", "ucrania", "israel", "taiwan", "otan", "nato"),
    "materias_primas": ("petroleo", "oil", "crudo", "opec", "opep", "gas", "oro",
                        "gold", "inventario", "inventories", "ormuz", "hormuz",
                        "barril", "barrel", "cobre", "copper"),
}


# =============================================================================
# Entrada unica
# =============================================================================

def sintetizar(contexto: dict) -> dict:
    """
    Devuelve la sintesis cualitativa. Nunca lanza excepcion.

    contexto = {
      "acciones": {"bull_pct": float, "signals": [...], "macro": {...}},
      "cripto":   {"indicadores": {...}},
      "titulares": [{"title": str, "description": str}, ...],
    }
    """
    try:
        if PROVEEDOR == "groq" and os.getenv("GROQ_API_KEY"):
            cruda = _llamar_groq(_construir_prompt(contexto))
            if cruda:
                datos = _validar(cruda, contexto)
                if datos:
                    datos["fuente"] = "groq"
                    datos["modelo"] = GROQ_MODELO_USADO
                    logger.info("Sintesis generada por IA (%s)", GROQ_MODELO_USADO)
                    return datos
            logger.warning("La IA no devolvio una sintesis utilizable: se usa el respaldo.")
        else:
            logger.info("Sin proveedor de IA configurado: se usa el respaldo en Python.")
    except Exception as e:                      # jamas debe tumbar el reporte
        logger.warning("Fallo la sintesis por IA (%s): se usa el respaldo.", e)

    datos = _respaldo(contexto)
    datos["fuente"] = "fallback"
    return datos


# =============================================================================
# Proveedor
# =============================================================================

def _llamar_groq(prompt: str) -> dict:
    """Intenta los modelos de GROQ_MODELOS en orden hasta que uno responda."""
    global GROQ_MODELO_USADO
    import requests

    cabeceras = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}",
                 "Content-Type": "application/json"}

    for modelo in GROQ_MODELOS:
        r = requests.post(
            GROQ_URL,
            headers=cabeceras,
            json={
                "model": modelo,
                "messages": [
                    {"role": "system",
                     "content": "Eres un analista macro. Respondes SOLO con JSON valido, "
                                "en español, sin texto adicional."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 2000,
                "response_format": {"type": "json_object"},
            },
            timeout=TIMEOUT_S,
        )

        if r.status_code == 200:
            GROQ_MODELO_USADO = modelo
            texto = r.json()["choices"][0]["message"]["content"]
            return _extraer_json(texto)

        detalle = r.text[:200]
        if _modelo_no_disponible(r.status_code, detalle):
            logger.warning("Modelo %s no disponible en esta cuenta: se prueba el siguiente.",
                           modelo)
            continue

        # 401 (key mala), 429 (cuota) o 5xx: cambiar de modelo no arregla nada.
        logger.warning("Groq respondio %s con %s: %s", r.status_code, modelo, detalle)
        return {}

    logger.warning("Ningun modelo de la lista esta disponible: %s",
                   ", ".join(GROQ_MODELOS))
    return {}


def _modelo_no_disponible(status: int, detalle: str) -> bool:
    """True si el error es 'este modelo no existe / no lo tienes', no otra falla."""
    if status not in (400, 404):
        return False
    d = (detalle or "").lower()
    return ("model_not_found" in d or "does not exist" in d
            or "decommissioned" in d or "has been deprecated" in d)


def _extraer_json(texto: str) -> dict:
    try:
        return json.loads(texto)
    except Exception:
        pass
    m = re.search(r"\{.*\}", texto or "", re.S)     # por si envuelve el JSON en prosa
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return {}


# =============================================================================
# Prompt
# =============================================================================

def _construir_prompt(contexto: dict) -> str:
    acc = contexto.get("acciones", {}) or {}
    cri = contexto.get("cripto", {}) or {}

    lineas_acc = [f"- {s.get('name')}: {s.get('value')} ({s.get('signal')})"
                  for s in (acc.get("signals") or [])]
    lineas_macro = [f"- {d.get('name')}: {d.get('value')} (previo {d.get('prev')}, {d.get('dir')})"
                    for d in (acc.get("macro") or {}).values()
                    if d.get("value") not in (None, "N/D")]
    lineas_cri = [f"- {k}: {v}" for k, v in (cri.get("indicadores") or {}).items()]
    titulares = [f"- {t.get('title', '')}" for t in (contexto.get("titulares") or [])[:15]]

    return f"""Analiza el regimen de mercado con estos datos ya calculados.

ACCIONES EE.UU. — señales tecnicas:
{chr(10).join(lineas_acc) or "- sin datos"}

ACCIONES EE.UU. — macro:
{chr(10).join(lineas_macro) or "- sin datos"}

CRIPTO — indicadores:
{chr(10).join(lineas_cri) or "- sin datos"}

TITULARES DE LA SEMANA:
{chr(10).join(titulares) or "- sin titulares"}

REGLAS DE ANALISIS:
1. El rango es el estado por defecto. Solo declara BULL o BEAR si hay
   convergencia de al menos tres condiciones independientes.
2. El precio manda, la macro explica. Si se contradicen, clasifica por el
   precio y reporta la divergencia como riesgo.
3. Las señales de deterioro exigen menos confirmacion que las de mejora.
4. Cripto se analiza por separado, no se hereda el estado de acciones.
5. Para cada horizonte, las tres probabilidades deben sumar exactamente 100.
6. Incluye siempre que invalidaria tu lectura.

PROHIBIDO:
- Inventar fechas de publicaciones o reuniones. NO escribas ninguna fecha.
- Inventar cifras que no esten arriba.
- Recomendar comprar o vender.

Para los catalizadores: elige como maximo 2 de categoria "geopolitica" y 2 de
"materias_primas", ordenados por impacto esperado en un portafolio agresivo de
acciones EE.UU., cripto, oro y emergentes. Si un evento geopolitico ya explica
su impacto en petroleo u oro, NO lo repitas en materias_primas. Si no hay nada
relevante en una categoria, devuelve menos elementos.

Responde SOLO este JSON:
{{
  "acciones_usa": {{
    "estado": "BULL|BEAR|RANGO",
    "resumen": "una frase con el dato que sostiene la lectura",
    "probabilidades": {{"3m": {{"bull": 0, "bear": 0, "rango": 0}},
                       "6m": {{"bull": 0, "bear": 0, "rango": 0}}}},
    "que_paso": ["hecho reciente 1", "hecho reciente 2"],
    "que_invalidaria": "condicion concreta"
  }},
  "cripto": {{ ...misma estructura... }},
  "catalizadores": [
    {{"titulo": "...", "categoria": "geopolitica|materias_primas",
      "riesgo": "alto|medio|bajo", "que_paso": "una linea",
      "impacto": "una linea sobre el portafolio",
      "palabras_clave": ["...", "..."]}}
  ],
  "noticias": [{{"titular": "...", "relacion": "por que se relaciona con el regimen"}}]
}}"""


# =============================================================================
# Validacion
# =============================================================================

def _texto(v, largo=220) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:largo]


def _normalizar_probabilidades(d) -> dict:
    """Enteros, sin negativos y sumando exactamente 100."""
    base = {}
    for k in ("bull", "bear", "rango"):
        try:
            base[k] = max(0, int(round(float((d or {}).get(k, 0)))))
        except (TypeError, ValueError):
            base[k] = 0
    total = sum(base.values())
    if total == 0:
        return {"bull": 25, "bear": 25, "rango": 50}
    escalado = {k: int(round(v * 100 / total)) for k, v in base.items()}
    escalado["rango"] += 100 - sum(escalado.values())   # cuadra el redondeo
    return escalado


def _validar_bloque(b) -> dict:
    b = b or {}
    estado = str(b.get("estado", "")).upper().strip()
    if estado not in ESTADOS:
        estado = "RANGO"
    probs = b.get("probabilidades") or {}
    lista = [_texto(x, 160) for x in (b.get("que_paso") or []) if _texto(x)]
    return {
        "estado": estado,
        "resumen": _texto(b.get("resumen")),
        "probabilidades": {"3m": _normalizar_probabilidades(probs.get("3m")),
                           "6m": _normalizar_probabilidades(probs.get("6m"))},
        "que_paso": lista[:3],
        "que_invalidaria": _texto(b.get("que_invalidaria")),
    }


def _validar_catalizadores(lista) -> list:
    salida, por_categoria = [], {c: 0 for c in CATEGORIAS}
    vistos = set()
    for c in (lista or []):
        if not isinstance(c, dict):
            continue
        cat = str(c.get("categoria", "")).lower().strip()
        if cat not in CATEGORIAS or por_categoria[cat] >= MAX_POR_CATEGORIA:
            continue
        titulo = _texto(c.get("titulo"), 60)
        if not titulo or titulo.lower() in vistos:
            continue
        riesgo = str(c.get("riesgo", "medio")).lower().strip()
        claves = [_texto(k, 30).lower() for k in (c.get("palabras_clave") or [])][:6]
        salida.append({
            "titulo": titulo,
            "categoria": cat,
            "riesgo": riesgo if riesgo in ("alto", "medio", "bajo") else "medio",
            "que_paso": _texto(c.get("que_paso"), 150),
            "impacto": _texto(c.get("impacto"), 150),
            "palabras_clave": [k for k in claves if k],
        })
        vistos.add(titulo.lower())
        por_categoria[cat] += 1
    return salida


def _validar(cruda: dict, contexto: dict) -> dict:
    if not isinstance(cruda, dict) or "acciones_usa" not in cruda:
        return {}
    return {
        "acciones_usa": _validar_bloque(cruda.get("acciones_usa")),
        "cripto": _validar_bloque(cruda.get("cripto")),
        "catalizadores": _validar_catalizadores(cruda.get("catalizadores")),
        "noticias": [{"titular": _texto(n.get("titular"), 130),
                      "relacion": _texto(n.get("relacion"), 130)}
                     for n in (cruda.get("noticias") or [])[:3]
                     if isinstance(n, dict) and _texto(n.get("titular"))],
    }


# =============================================================================
# Respaldo 100% Python (sin IA)
# =============================================================================

def _estado_por_pct(pct: float) -> str:
    if pct is None:
        return "RANGO"
    return "BULL" if pct >= 0.65 else "BEAR" if pct <= 0.35 else "RANGO"


def _probabilidades_por_pct(pct: float, horizonte_meses: int) -> dict:
    """
    Reparto determinista. A mayor horizonte, mas peso a los extremos: cuanto mas
    lejos se mira, menos probable es seguir exactamente en el mismo rango.
    """
    pct = 0.5 if pct is None else max(0.0, min(1.0, pct))
    rango = 50 if horizonte_meses <= 3 else 40
    resto = 100 - rango
    bull = int(round(resto * pct))
    bear = resto - bull
    return {"bull": bull, "bear": bear, "rango": rango}


def _hechos_macro(macro: dict) -> list:
    """Cambios recientes visibles en los datos, sin interpretar de mas."""
    hechos = []
    for d in (macro or {}).values():
        if d.get("value") in (None, "N/D") or d.get("dir") not in ("↑", "↓"):
            continue
        flecha = "subio" if d["dir"] == "↑" else "bajo"
        hechos.append(f"{d.get('name')} {flecha} a {d.get('value')} (previo {d.get('prev')})")
    return hechos[:3]


def _clasificar_titulares(titulares: list) -> tuple:
    """Clasificacion por palabras clave: lo que se puede hacer sin modelo."""
    catalizadores, noticias, por_categoria = [], [], {c: 0 for c in CATEGORIAS}
    for t in (titulares or [])[:20]:
        titulo = _texto((t or {}).get("title"), 110)
        if not titulo:
            continue
        bajo = titulo.lower()
        for cat, claves in _PALABRAS.items():
            if por_categoria[cat] >= MAX_POR_CATEGORIA:
                continue
            encontradas = [k for k in claves if k in bajo]
            if not encontradas:
                continue
            catalizadores.append({
                "titulo": titulo[:60],
                "categoria": cat,
                "riesgo": "medio",
                "que_paso": titulo,
                "impacto": "Sin analisis de IA esta semana: revisar el titular directamente.",
                "palabras_clave": encontradas[:4],
            })
            noticias.append({"titular": titulo,
                             "relacion": f"Coincide con terminos de {cat.replace('_', ' ')}"})
            por_categoria[cat] += 1
            break
    return catalizadores, noticias[:3]


def _respaldo(contexto: dict) -> dict:
    acc = contexto.get("acciones", {}) or {}
    pct = acc.get("bull_pct")
    estado = _estado_por_pct(pct)
    hechos = _hechos_macro(acc.get("macro"))
    catalizadores, noticias = _clasificar_titulares(contexto.get("titulares"))

    pct_txt = f"{pct * 100:.0f}%" if pct is not None else "sin datos"
    bloque_acc = {
        "estado": estado,
        "resumen": f"{pct_txt} de las señales tecnicas y macro son alcistas.",
        "probabilidades": {"3m": _probabilidades_por_pct(pct, 3),
                           "6m": _probabilidades_por_pct(pct, 6)},
        "que_paso": hechos,
        "que_invalidaria": ("Que el S&P pierda su media de 200 dias con el VIX sobre 25."
                            if estado != "BEAR" else
                            "Que el S&P recupere su media de 200 dias y el VIX baje de 20."),
    }

    # Sin modelo no se interpreta cripto: se declara rango y se dice por que.
    bloque_cri = {
        "estado": "RANGO",
        "resumen": "Sin sintesis de IA esta semana: lectura tecnica unicamente.",
        "probabilidades": {"3m": {"bull": 25, "bear": 25, "rango": 50},
                           "6m": {"bull": 30, "bear": 30, "rango": 40}},
        "que_paso": [],
        "que_invalidaria": "Que BTC pierda su media de 200 semanas.",
    }

    return {"acciones_usa": bloque_acc, "cripto": bloque_cri,
            "catalizadores": catalizadores, "noticias": noticias}


# =============================================================================
# Cruce catalizador <-> ticker
# =============================================================================
#
# La relacion no se mantiene a mano: se infiere cruzando las palabras clave que
# ya existen por ticker en config.NEWS_KEYWORDS (mas su tipo de activo) contra
# las palabras clave del catalizador de la semana.
#
# El puente bilingue existe porque los catalizadores vienen en español y las
# palabras clave del config estan en ingles.

_SINONIMOS = {
    "petroleo":        {"oil", "crude", "brent", "wti", "energy", "energia", "gas"},
    "crudo":           {"oil", "crude", "brent", "wti"},
    "ormuz":           {"oil", "crude", "energy"},
    "opep":            {"oil", "crude", "opec"},
    "oro":             {"gold", "safe", "haven", "hedge"},
    "semiconductores": {"semiconductor", "chip", "chips", "tsmc", "intel", "nvidia", "taiwan"},
    "chips":           {"semiconductor", "chip", "tsmc", "intel", "nvidia"},
    "aranceles":       {"tariff", "tariffs", "trade"},
    "china":           {"china", "chinese", "brics", "emerging"},
    "emergentes":      {"emerging", "brics", "developing", "china"},
    "cripto":          {"crypto", "bitcoin", "btc", "ethereum", "eth", "blockchain"},
    "tasas":           {"rate", "rates", "fed", "fomc", "treasury"},
    "inflacion":       {"inflation", "cpi", "hedge"},
    "guerra":          {"war", "defense", "defence", "aerospace"},
    "defensa":         {"defense", "defence", "aerospace"},
}

_ORDEN_RIESGO = {"alto": 0, "medio": 1, "bajo": 2}


def _tokens(textos) -> set:
    salida = set()
    for t in textos or []:
        for palabra in re.split(r"[^\wáéíóúñ]+", str(t).lower()):
            if len(palabra) >= 3:
                salida.add(palabra)
    return salida


def _expandir(tokens: set) -> set:
    ampliado = set(tokens)
    for t in tokens:
        ampliado |= _SINONIMOS.get(t, set())
    return ampliado


def catalizador_para_ticker(catalizadores, ticker, asset_type="", palabras_ticker=None):
    """
    Devuelve el catalizador de la semana que afecta a este activo, o None.

    Es informativo: no puntua ni cambia ninguna señal de compra o venta.
    """
    if not catalizadores:
        return None

    propios = _tokens([ticker, asset_type] + list(palabras_ticker or []))
    candidatos = []

    for cat in catalizadores:
        if not isinstance(cat, dict):
            continue
        ajenos = _expandir(_tokens(list(cat.get("palabras_clave") or []) + [cat.get("titulo", "")]))

        coincide = bool(propios & ajenos)

        # Reglas por categoria, para lo que las palabras no alcanzan a cubrir
        if not coincide and cat.get("categoria") == "materias_primas" \
                and asset_type == "Materias Primas":
            coincide = True
        if not coincide and asset_type == "Emergentes" \
                and ajenos & {"china", "emerging", "brics", "developing"}:
            coincide = True

        if coincide:
            candidatos.append(cat)

    if not candidatos:
        return None
    candidatos.sort(key=lambda c: _ORDEN_RIESGO.get(c.get("riesgo", "medio"), 1))
    return candidatos[0]
