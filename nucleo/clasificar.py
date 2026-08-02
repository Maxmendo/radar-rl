"""Clasifica hechos con un modelo de lenguaje, en lotes.

Toma datos/items.json, clasifica los hechos que todavia no lo estan y reescribe
el archivo con los ejes, poblaciones, colectividades, etapa e importancia.

DOS DECISIONES DE DISENO QUE NO CONVIENE ROMPER:

1. EN LOTES, no de a uno. El prompt tiene ~1.500 palabras y la API no tiene
   memoria entre llamadas: mandarlo por cada hecho lo reenvia entero cada vez.
   En lotes de 20 el prompt viaja una vez cada 20 hechos.

2. SOLO LO NUEVO. Un hecho se clasifica una vez, la primera. Despues solo se
   actualizan las metricas de velocidad. Sin esto se reclasificaria lo mismo
   ocho veces por dia sin ningun cambio en el resultado.

Requiere la variable de entorno GEMINI_API_KEY.

Uso:
    python -m nucleo.clasificar
    python -m nucleo.clasificar --lote 10 --max-hechos 40
    python -m nucleo.clasificar --simular      # sin llamar a la API
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.registro import cargar  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ITEMS = RAIZ / "datos" / "items.json"
PROMPT = RAIZ / "prompts" / "clasificacion.md"

# Cascada de modelos: si el primero falla por no existir o por cupo, se pasa al
# siguiente. Los nombres de modelos de Google cambian seguido y las versiones
# viejas se apagan: `gemini-2.5-flash` se apaga el 16/10/2026.
#
# NO usar el alias `gemini-flash-latest`: apunta a modelos experimentales, no
# aptos para produccion y con limites de tasa mas restrictivos.
#
# Flash-Lite va primero a proposito: clasificar titulares es una tarea acotada
# con salida JSON estricta, justo el caso de uso del modelo mas barato.
MODELOS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
]
BASE = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT = 120
LOTE = 20
REINTENTOS = 3
ESPERA_BASE = 5  # segundos; se duplica en cada reintento

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("clasificar")


def cargar_prompt() -> str:
    """Devuelve el prompt de sistema, sin la seccion USER ni el marcador {{ITEM}}."""
    t = PROMPT.read_text(encoding="utf-8")
    if "## SYSTEM" in t:
        t = t.split("## SYSTEM", 1)[1]
    if "## USER" in t:
        t = t.split("## USER", 1)[0]
    return t.strip()


def instruccion_de_lote(n: int) -> str:
    """Adapta el prompt, escrito para un item, al formato de lote."""
    return f"""

---

## FORMATO DE ESTA LLAMADA

Recibis {n} items en un array JSON. Devolves un array JSON con {n} objetos, en
el MISMO ORDEN, uno por item, con el esquema indicado arriba.

Devolves EXCLUSIVAMENTE el array. Sin markdown, sin backticks, sin texto antes
ni despues. Empeza con [ y termina con ].

Cada objeto debe incluir el campo "id" exactamente como lo recibiste. Si un item
te resulta imposible de clasificar, igual devolves su objeto con es_migratorio
en false, importancia 1 y una nota que explique por que.
"""


def resumir(hecho: dict) -> dict:
    """Reduce un hecho a lo que el clasificador necesita ver.

    Mandar el objeto completo desperdicia tokens en campos que el modelo no usa
    (urls, coberturas, metricas) y aumenta el riesgo de que se confunda.
    """
    return {
        "id": hecho["id"],
        "titulo": hecho["titulo_original"],
        "medios_que_lo_publicaron": hecho.get("velocidad", 0),
        "horas_desde_la_primera_publicacion": hecho.get("horas"),
        "otros_titulares_del_mismo_hecho": [
            c["medio"] for c in hecho.get("coberturas", [])[1:4]
        ],
    }


def extraer_json(texto: str) -> list[dict]:
    """Parsea la respuesta del modelo, tolerando backticks o texto alrededor."""
    t = texto.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        datos = json.loads(t)
    except json.JSONDecodeError:
        # Ultimo recurso: quedarse con el primer array balanceado del texto.
        i, j = t.find("["), t.rfind("]")
        if i < 0 or j <= i:
            raise
        datos = json.loads(t[i:j + 1])
    return datos if isinstance(datos, list) else [datos]


def llamar_modelo(clave: str, modelo: str, cuerpo: dict) -> tuple[list[dict], str]:
    """Intenta un modelo. Devuelve (resultado, motivo_de_fallo).

    El motivo distingue fallos que justifican pasar al siguiente modelo
    ("inexistente", "cupo") de los que no ("config").
    """
    url = f"{BASE}/{modelo}:generateContent"

    for intento in range(1, REINTENTOS + 1):
        try:
            r = requests.post(url, params={"key": clave}, json=cuerpo, timeout=TIMEOUT)
        except requests.RequestException as e:
            log.warning("      red (%s), intento %d/%d", type(e).__name__, intento, REINTENTOS)
            time.sleep(ESPERA_BASE * intento)
            continue

        if r.status_code == 404:
            return [], "inexistente"
        if r.status_code == 429:
            if intento == REINTENTOS:
                return [], "cupo"
            espera = ESPERA_BASE * (2 ** intento)
            log.warning("      limite de tasa; espero %ds (%d/%d)", espera, intento, REINTENTOS)
            time.sleep(espera)
            continue
        if r.status_code in (400, 401, 403):
            log.warning("      HTTP %s: %s", r.status_code, r.text[:200])
            return [], "config"
        if r.status_code != 200:
            log.warning("      HTTP %s, intento %d/%d", r.status_code, intento, REINTENTOS)
            time.sleep(ESPERA_BASE * intento)
            continue

        try:
            texto = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return extraer_json(texto), ""
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            log.warning("      respuesta ilegible (%s), intento %d/%d",
                        type(e).__name__, intento, REINTENTOS)
            time.sleep(ESPERA_BASE * intento)

    return [], "agotado"


def llamar(clave: str, sistema: str, lote: list[dict], modelos: list[str]) -> list[dict]:
    """Recorre la cascada de modelos hasta obtener una respuesta utilizable."""
    cuerpo = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        "contents": [{"parts": [{"text": json.dumps(lote, ensure_ascii=False)}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }

    for modelo in modelos:
        log.info("   modelo: %s", modelo)
        resultado, motivo = llamar_modelo(clave, modelo, cuerpo)
        if resultado:
            return resultado
        if motivo == "config":
            log.error("   error de configuracion; revisar la clave de API")
            return []
        log.warning("   %s no sirvio (%s); paso al siguiente", modelo, motivo or "sin datos")

    log.error("   ningun modelo de la cascada respondio")
    return []


CAMPOS = ("es_migratorio", "ejes", "poblaciones", "colectividades", "actores",
          "etapa", "paises", "tipo", "importancia", "cobertura", "confianza",
          "tiene_fuente_primaria", "contiene_datos_personales",
          "requiere_verificacion", "terminologia_problematica",
          "termino_busqueda", "angulo_sugerido", "nota")


def validar(obj: dict, vocab: dict) -> dict:
    """Descarta valores fuera del vocabulario y normaliza rangos.

    Un modelo puede inventar un eje que no existe. Si eso entra al archivo, el
    tablero muestra filtros fantasma y el vocabulario deja de ser confiable.
    """
    limpio = {k: obj.get(k) for k in CAMPOS}

    limpio["ejes"] = [e for e in (limpio.get("ejes") or []) if e in vocab["ejes"]][:3]
    limpio["poblaciones"] = [p for p in (limpio.get("poblaciones") or [])
                             if p in vocab["poblaciones"]]
    limpio["actores"] = [a for a in (limpio.get("actores") or []) if a in vocab["actores"]]
    limpio["colectividades"] = [c for c in (limpio.get("colectividades") or [])
                                if c in vocab["colectividades"]]
    if limpio.get("etapa") not in vocab["etapas"]:
        limpio["etapa"] = None

    for campo in ("es_migratorio", "tiene_fuente_primaria",
                  "contiene_datos_personales", "requiere_verificacion"):
        limpio[campo] = bool(limpio.get(campo))

    for campo, tope in (("importancia", 10), ("cobertura", 10)):
        v = limpio.get(campo)
        if isinstance(v, (int, float)):
            limpio[campo] = max(1, min(tope, int(v)))
        else:
            limpio[campo] = None

    c = limpio.get("confianza")
    limpio["confianza"] = round(max(0.0, min(1.0, float(c))), 2) if isinstance(c, (int, float)) else None

    v = limpio.get("terminologia_problematica")
    limpio["terminologia_problematica"] = v if isinstance(v, list) else []

    # Google Trends no acepta frases largas: se acota a 3 palabras.
    tb = limpio.get("termino_busqueda")
    limpio["termino_busqueda"] = " ".join(str(tb).split()[:3]) if tb else None

    limpio["clasificado"] = True
    return limpio


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lote", type=int, default=LOTE)
    ap.add_argument("--max-hechos", type=int, default=200,
                    help="tope de seguridad por corrida")
    ap.add_argument("--modelo", help="fuerza un modelo en vez de usar la cascada")
    ap.add_argument("--simular", action="store_true",
                    help="arma los lotes y muestra el plan, sin llamar a la API")
    ap.add_argument("--reclasificar", action="store_true",
                    help="vuelve a clasificar TODO, ignorando lo ya hecho. Usarlo "
                         "solo cuando cambia el criterio del prompt: cuesta una "
                         "corrida completa de la API.")
    args = ap.parse_args()

    if not ITEMS.exists():
        log.error("No existe %s. Correr antes: python -m nucleo.ingesta",
                  ITEMS.relative_to(RAIZ))
        return 1

    datos = json.loads(ITEMS.read_text(encoding="utf-8"))
    hechos = datos.get("items", [])

    # Fuera de alcance no se clasifica: gastar tokens en Ceuta no tiene sentido.
    pendientes = [h for h in hechos
                  if (args.reclasificar or not h.get("clasificado"))
                  and not h.get("fuera_de_alcance")]
    if args.reclasificar:
        log.info("RECLASIFICANDO TODO: se ignora lo ya clasificado.")
    pendientes = pendientes[:args.max_hechos]

    log.info("Hechos totales: %d | ya clasificados: %d | pendientes: %d",
             len(hechos), sum(1 for h in hechos if h.get("clasificado")), len(pendientes))

    if not pendientes:
        log.info("Nada que clasificar.")
        return 0

    lotes = [pendientes[i:i + args.lote] for i in range(0, len(pendientes), args.lote)]
    log.info("Lotes: %d de hasta %d hechos", len(lotes), args.lote)

    if args.simular:
        log.info("\nSIMULACION. No se llama a la API.")
        log.info("Prompt de sistema: %d palabras", len(cargar_prompt().split()))
        log.info("Cascada de modelos: %s", " -> ".join(MODELOS))
        log.info("\nPrimeros hechos del primer lote:")
        for h in lotes[0][:3]:
            log.info("   %s", json.dumps(resumir(h), ensure_ascii=False)[:150])
        return 0

    clave = os.environ.get("GEMINI_API_KEY")
    if not clave:
        log.error("Falta GEMINI_API_KEY. En local: $env:GEMINI_API_KEY='...'")
        log.error("En GitHub: Settings > Secrets and variables > Actions")
        return 1

    cfg = cargar()
    vocab = {
        "ejes": {e["id"] for e in cfg.get("ejes", []) if e.get("activo")},
        "poblaciones": {p["id"] for p in cfg.get("poblaciones", [])},
        "actores": {a["id"] for a in cfg.get("actores", [])},
        "etapas": {e["id"] for e in cfg.get("etapas", [])},
        "colectividades": set(cfg.get("colectividades", {}).get("valores", [])),
    }

    modelos = [args.modelo] if args.modelo else MODELOS
    log.info("Cascada de modelos: %s", " -> ".join(modelos))
    sistema = cargar_prompt() + instruccion_de_lote(args.lote)
    por_id = {h["id"]: h for h in hechos}
    ok = fallidos = 0

    for n, lote in enumerate(lotes, 1):
        log.info("Lote %d/%d (%d hechos)...", n, len(lotes), len(lote))
        respuesta = llamar(clave, sistema, [resumir(h) for h in lote], modelos)

        if not respuesta:
            log.warning("   sin respuesta utilizable; quedan pendientes para la proxima")
            fallidos += len(lote)
            continue

        for obj in respuesta:
            h = por_id.get(obj.get("id"))
            if h:
                h.update(validar(obj, vocab))
                ok += 1

        if n < len(lotes):
            time.sleep(2)   # respiro entre lotes

    datos["clasificado"] = all(h.get("clasificado") for h in hechos
                               if not h.get("fuera_de_alcance"))
    ITEMS.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    log.info("\nClasificados: %d | fallidos: %d", ok, fallidos)

    nuevos = [h for h in hechos if h.get("clasificado") and h.get("importancia")]
    if nuevos:
        migratorios = [h for h in nuevos if h.get("es_migratorio")]
        log.info("Marcados como NO migratorios: %d de %d",
                 len(nuevos) - len(migratorios), len(nuevos))
        log.info("\nLos de mayor importancia:")
        for h in sorted(migratorios, key=lambda x: -(x.get("importancia") or 0))[:5]:
            log.info("   imp %2d | %-28s | %s", h["importancia"],
                     ",".join(h.get("ejes") or [])[:28], h["titulo_original"][:52])
    return 0


if __name__ == "__main__":
    sys.exit(main())
