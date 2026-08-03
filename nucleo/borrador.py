"""Genera un borrador editorial para UN hecho, a pedido.

NO CORRE SOLO. Se ejecuta cuando alguien lo pide desde el tablero, y el tablero
solo ofrece el boton si el hecho cumple los requisitos.

REQUISITOS (definidos en fuentes.yaml, seccion `borrador`)
----------------------------------------------------------
  - 3 o mas medios cubriendo el hecho
  - importancia editorial >= 7
  - que sea migratorio y este dentro del alcance regional

Un hecho con una sola fuente no da para un borrador: da para reportear.

QUE HACE DISTINTO A "RESUMIR TITULARES"
---------------------------------------
Descarga el CONTENIDO de las notas, no solo los titulos. Un texto armado con ocho
titulares es un resumen de resumenes. Con las notas completas a la vista, el
borrador puede hacer lo que ninguna de ellas hace por separado: contrastar cifras,
detectar contradicciones y marcar que falta.

Ese contraste es lo unico que justifica generarlo.

LIMITES
-------
El borrador NUNCA se publica: sale a datos/borradores/ para curaduria humana.
Y sigue prohibido generar, sintetizar o parafrasear testimonios de personas
migrantes: esa regla no se modifico.

Uso:
    python -m nucleo.borrador --id <id_del_hecho>
    python -m nucleo.borrador --id <id> --simular   # sin llamar a la API
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.clasificar import BASE, MODELOS, extraer_json  # noqa: E402
from nucleo.estados import estado  # noqa: E402
from nucleo.correo import enviar, envoltura, hay_credenciales  # noqa: E402
from nucleo.registro import cargar  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ITEMS = RAIZ / "datos" / "items.json"
PROMPT = RAIZ / "prompts" / "borrador.md"
SALIDA = RAIZ / "datos" / "borradores"

TIMEOUT = 180
TIMEOUT_NOTA = 20
MAX_NOTAS = 6           # tope de notas a descargar por hecho
MAX_CARACTERES = 6000   # por nota, para no desbordar el contexto
UA = "radar-rl/0.3 (Refugio Latinoamericano; contacto@refugiolatinoamericano.com)"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("borrador")


def texto_de_html(html: str) -> str:
    """Extrae el texto legible de una pagina, sin dependencias externas.

    Es tosco: saca script, style y etiquetas, y colapsa espacios. Alcanza para
    que el modelo lea el contenido; no reconstruye la estructura del articulo.
    """
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html,
                  flags=re.S | re.I)
    html = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>", "\n", html, flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'),
                 ("&#39;", "'"), ("&lt;", "<"), ("&gt;", ">")):
        texto = texto.replace(a, b)
    lineas = [l.strip() for l in texto.split("\n")]
    # Descarta lineas cortas: suelen ser menu, pie y botones de compartir.
    return "\n".join(l for l in lineas if len(l) > 60)


def descargar_nota(url: str) -> str:
    """Baja una nota y devuelve su texto. Cadena vacia si no se pudo."""
    try:
        r = requests.get(url, timeout=TIMEOUT_NOTA, headers={"User-Agent": UA})
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("      no se pudo bajar (%s)", type(e).__name__)
        return ""
    t = texto_de_html(r.text)
    return t[:MAX_CARACTERES]


def material(hecho: dict) -> dict:
    """Arma lo que ve el modelo: analisis del radar y contenido de las notas."""
    log.info("Descargando notas...")
    fuentes = []
    for c in (hecho.get("coberturas") or [])[:MAX_NOTAS]:
        log.info("   %s", c["medio"])
        texto = descargar_nota(c["url"])
        if texto:
            fuentes.append({"medio": c["medio"], "url": c["url"], "texto": texto})
        time.sleep(1)

    return {
        "titulo_del_hecho": hecho["titulo_original"],
        "analisis_del_radar": {
            "importancia": hecho.get("importancia"),
            "medios_que_lo_publicaron": hecho.get("velocidad"),
            "ejes": hecho.get("ejes"),
            "poblaciones": hecho.get("poblaciones"),
            "colectividades": hecho.get("colectividades"),
            "actores": hecho.get("actores"),
            "paises": hecho.get("paises_nombres") or hecho.get("paises"),
            "etapa": hecho.get("etapa"),
            "angulo_sugerido": hecho.get("angulo_sugerido"),
            "terminologia_problematica_en_la_cobertura": hecho.get("terminologia_problematica"),
            "requiere_verificacion": hecho.get("requiere_verificacion"),
        },
        "notas": fuentes,
        "medios_sin_texto": [c["medio"] for c in (hecho.get("coberturas") or [])[:MAX_NOTAS]
                             if not any(f["medio"] == c["medio"] for f in fuentes)],
    }


def apto(hecho: dict, cfg: dict) -> tuple[bool, str]:
    """Verifica los requisitos. Devuelve (apto, motivo si no lo es)."""
    if not hecho.get("clasificado"):
        return False, "todavia no fue clasificado"
    if hecho.get("es_migratorio") is False:
        return False, "el clasificador determino que no trata de personas en movilidad"
    if hecho.get("fuera_de_alcance"):
        return False, "ocurre fuera de America Latina, el Caribe y Estados Unidos"

    vel_min = cfg.get("medios_minimos", 3)
    imp_min = cfg.get("importancia_minima", 7)
    if (hecho.get("velocidad") or 0) < vel_min:
        return False, (f"solo {hecho.get('velocidad', 0)} medio(s); hacen falta "
                       f"{vel_min}. Con una sola fuente no hay con que contrastar")
    if (hecho.get("importancia") or 0) < imp_min:
        return False, f"importancia {hecho.get('importancia')}; el minimo es {imp_min}"
    return True, ""


def llamar(clave: str, sistema: str, mat: dict) -> tuple[str, list[dict]]:
    """Pide el borrador con busqueda web habilitada.

    El fact checking del prompt es obligatorio y exige URLs recuperadas en la
    sesion. Sin la herramienta de busqueda, el prompt devuelve
    "INSUFICIENCIA DE VERIFICACION" y no redacta nada: por eso se activa
    `google_search`.

    Devuelve (texto, fuentes_consultadas). Google exige mostrar las fuentes
    cuando se usa grounding, asi que se extraen de la respuesta y se guardan.
    """
    cuerpo = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        "contents": [{"parts": [{"text": json.dumps(mat, ensure_ascii=False)}]}],
        "generationConfig": {"temperature": 0.4},
        # Habilita el fact checking. No se puede combinar con herramientas que
        # no sean de busqueda, y por eso tampoco se fija responseMimeType.
        "tools": [{"google_search": {}}],
    }
    for modelo in MODELOS:
        log.info("   modelo: %s", modelo)
        try:
            r = requests.post(f"{BASE}/{modelo}:generateContent",
                              params={"key": clave}, json=cuerpo, timeout=TIMEOUT)
        except requests.RequestException as e:
            log.warning("      red: %s", type(e).__name__)
            continue
        if r.status_code == 404:
            continue
        if r.status_code != 200:
            log.warning("      HTTP %s: %s", r.status_code, r.text[:150])
            continue
        try:
            cand = r.json()["candidates"][0]
            partes = cand["content"]["parts"]
            texto = "".join(p.get("text", "") for p in partes)
            return texto, fuentes_consultadas(cand)
        except (KeyError, IndexError):
            log.warning("      respuesta ilegible")
    return "", []


def fuentes_consultadas(candidato: dict) -> list[dict]:
    """Extrae las paginas que el modelo consulto durante el fact checking.

    Google exige mostrar las fuentes cuando se usa grounding con busqueda.
    Ademas sirve para auditar: si el reporte de fact checking cita una URL que
    no esta aca, el modelo la invento.
    """
    meta = candidato.get("groundingMetadata") or {}
    salida = []
    for chunk in meta.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        if web.get("uri"):
            salida.append({"titulo": web.get("title", ""), "url": web["uri"]})
    return salida


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="id del hecho")
    ap.add_argument("--simular", action="store_true",
                    help="arma el material y muestra el plan, sin llamar a la API")
    args = ap.parse_args()

    if not ITEMS.exists():
        log.error("No existe datos/items.json")
        return 1

    datos = json.loads(ITEMS.read_text(encoding="utf-8"))
    hecho = next((h for h in datos.get("items", []) if h["id"] == args.id), None)
    if not hecho:
        log.error("No se encontro el hecho %s", args.id)
        return 1

    cfg = cargar().get("borrador", {})
    ok, motivo = apto(hecho, cfg)
    log.info("%s", hecho["titulo_original"][:70])
    log.info("   estado: %s | %d medios | importancia %s",
             estado(hecho), hecho.get("velocidad", 0), hecho.get("importancia"))

    if not ok:
        log.error("")
        log.error("No cumple los requisitos: %s", motivo)
        return 1

    mat = material(hecho)
    if not mat["notas"]:
        log.error("No se pudo descargar el texto de ninguna nota.")
        log.error("Sin contenido, el borrador seria un resumen de titulares.")
        return 1

    log.info("")
    log.info("Notas con texto: %d de %d", len(mat["notas"]),
             len(hecho.get("coberturas") or [])[:MAX_NOTAS] if False else
             min(MAX_NOTAS, len(hecho.get("coberturas") or [])))
    if mat["medios_sin_texto"]:
        log.info("Sin texto: %s", ", ".join(mat["medios_sin_texto"]))

    if args.simular:
        log.info("\nSIMULACION. No se llama a la API.")
        log.info("Prompt: %d palabras", len(PROMPT.read_text(encoding='utf-8').split()))
        for n in mat["notas"]:
            log.info("   %-24s %d caracteres", n["medio"], len(n["texto"]))
        return 0

    clave = os.environ.get("GEMINI_API_KEY")
    if not clave:
        log.error("Falta GEMINI_API_KEY")
        return 1

    sistema = PROMPT.read_text(encoding="utf-8")
    if "## SYSTEM" in sistema:
        sistema = sistema.split("## SYSTEM", 1)[1]
    if "## USER" in sistema:
        sistema = sistema.split("## USER", 1)[0]

    log.info("")
    log.info("Generando borrador con fact checking...")
    texto, fuentes = llamar(clave, sistema.strip(), mat)
    if not texto:
        log.error("No se pudo generar.")
        return 1

    if texto.lstrip().startswith("⛔"):
        log.warning("")
        log.warning("El modelo devolvio INSUFICIENCIA. No hay borrador:")
        log.warning("%s", texto[:400])

    if fuentes:
        log.info("   paginas consultadas en el fact checking: %d", len(fuentes))

    ahora = datetime.now(timezone.utc)
    cabecera = (
        f"<!-- BORRADOR GENERADO POR IA — NO PUBLICAR SIN CURADURIA HUMANA\n"
        f"     hecho: {args.id}\n"
        f"     generado: {ahora.isoformat(timespec='seconds')}\n"
        f"     notas leidas: {', '.join(n['medio'] for n in mat['notas'])}\n"
        f"     Verificar fuentes y datos antes de publicar. Si se publica, debe\n"
        f"     indicarse de forma visible que hubo asistencia de IA. -->\n\n"
    )
    if fuentes:
        # Google exige mostrar las fuentes del grounding. Y sirve para auditar:
        # si el bloque 8 cita una URL que no esta aca, el modelo la invento.
        cabecera += ("<!-- PAGINAS CONSULTADAS EN EL FACT CHECKING\n"
                     + "\n".join(f"     {f['titulo'][:60]} — {f['url']}"
                                  for f in fuentes)
                     + "\n-->\n\n")
    SALIDA.mkdir(parents=True, exist_ok=True)
    ruta = SALIDA / f"{ahora.strftime('%Y%m%d-%H%M')}-{args.id}.md"
    ruta.write_text(cabecera + texto, encoding="utf-8")

    log.info("")
    log.info("Escrito %s (%d palabras)", ruta.relative_to(RAIZ), len(texto.split()))

    # --- Correo -------------------------------------------------------------
    # Los borradores van a MENOS gente que las alertas: es material de trabajo
    # sin curaduria, no una nota. Que circule de mas es peor que que circule de
    # menos.
    correo_cfg = cargar().get("correo", {})
    destinos = correo_cfg.get("borradores", []) if correo_cfg.get("activo") else []
    if destinos and hay_credenciales():
        cuerpo_html = (
            "<h2>" + hecho["titulo_original"] + "</h2>"
            "<div class='aviso'><b>Es un borrador generado por IA.</b> No publicar sin "
            "verificar fuentes y datos. Si se publica, debe indicarse de forma visible "
            "al lector que hubo asistencia de IA.</div>"
            "<p class='medios'><b>Fuentes leídas:</b> "
            + ", ".join(n["medio"] for n in mat["notas"]) + "</p>"
            "<hr style='border:none;border-top:1px solid #eae3e1;margin:16px 0'>"
            "<pre style='white-space:pre-wrap;font:14px/1.65 -apple-system,sans-serif;"
            "margin:0'>" + texto.replace("<", "&lt;") + "</pre>")
        pie = ("Este borrador se generó a pedido, leyendo las notas completas de "
               f"{len(mat['notas'])} medios. Queda en el repositorio, en "
               f"datos/borradores/<br><br>"
               "Radar Migratorio · Una herramienta de Refugio Latinoamericano")
        log.info("")
        log.info("Enviando por correo...")
        enviar(destinos,
               f"Borrador: {hecho['titulo_original'][:65]}",
               f"BORRADOR GENERADO POR IA — NO PUBLICAR SIN CURADURIA\n\n{texto}",
               envoltura("Borrador editorial",
                         "Generado a pedido · requiere curaduría humana",
                         cuerpo_html, pie))
    elif destinos:
        log.warning("Faltan las credenciales de correo; el borrador quedo solo en el repo.")

    log.info("")
    log.info("RECORDATORIO: es un borrador. Verificar fuentes y datos antes de")
    log.info("publicar, y etiquetar la asistencia de IA de forma visible al lector.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
