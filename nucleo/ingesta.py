"""Descarga los feeds, agrupa las notas del mismo hecho y calcula velocidad.

Esta es la ingesta minima: NO clasifica con LLM todavia. Aun asi alcanza para
lo que importa mas, porque el estado del ciclo de vida se calcula con velocidad,
y la velocidad es cuantos MEDIOS DISTINTOS publicaron el mismo hecho.

El eje tematico que se muestra es provisorio: viene de que consulta trajo la
nota (`eje_esperado`), no de un analisis del contenido. Cuando exista la
clasificacion, ese campo lo reemplaza el modelo.

Salida: datos/items.json, que consume scripts/generar_tablero.py

Uso:
    python -m nucleo.ingesta
    python -m nucleo.ingesta --prioridad 2
"""

import argparse
import hashlib
import json
import logging
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.registro import fuentes  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "datos" / "items.json"

TIMEOUT = 25
UA = "radar-rl/0.2 (Refugio Latinoamericano; contacto@refugiolatinoamericano.com)"
VENTANA_HORAS = 30          # margen sobre las 24h para no perder nada del borde

# Alcance del medio: America Latina, el Caribe y Estados Unidos.
# Entra mucha cobertura de la crisis de Ceuta y del Mediterraneo porque la
# prensa en castellano la cubre intensamente. NO se descarta: se marca y va a
# una pestana aparte, para poder auditarla y usarla como contexto comparado
# (Ceuta es el caso testigo de externalizacion de fronteras).
FUERA_DE_ALCANCE = {
    "ceuta", "melilla", "marruecos", "marroquies", "espana", "espanol", "espanola",
    "sanchez", "mediterraneo", "italia", "finlandia", "grecia", "malasia", "myanmar",
    "sudafrica", "ucrania", "canarias", "frontex", "union europea",
}
EN_ALCANCE = {
    "argentina", "argentinos", "milei", "chile", "uruguay", "paraguay", "bolivia",
    "peru", "ecuador", "colombia", "venezuela", "brasil", "mexico", "guatemala",
    "honduras", "salvador", "nicaragua", "costa rica", "panama", "dominicana",
    "haiti", "cuba", "estados unidos", "eeuu", "ice", "trump", "darien",
    "latinoamerica", "america latina", "migraciones",
}
SIMILITUD_MINIMA = 0.35     # umbral para considerar que dos notas son el mismo hecho
MINIMO_COMPARTIDO = 2       # palabras significativas en comun, como piso
LARGO_RAIZ = 6              # truncado de palabras para unificar formas flexionadas

# Palabras sin valor discriminante al comparar titulos.
VACIAS = {
    "de", "la", "el", "los", "las", "un", "una", "unos", "unas", "y", "o", "a", "en",
    "por", "para", "con", "sin", "que", "del", "al", "se", "su", "sus", "es", "son",
    "lo", "le", "les", "mas", "pero", "como", "the", "of", "to", "in", "and", "for",
    "on", "at", "is", "are", "da", "do", "das", "dos", "em", "com", "nao", "ao",
}

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("ingesta")


def sin_acentos(t: str) -> str:
    """Quita tildes y dieresis para comparar titulos de forma robusta."""
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def separar_medio(titulo: str) -> tuple[str, str]:
    """Google News agrega ' - Medio' al final del titulo. Lo separa."""
    partes = titulo.rsplit(" - ", 1)
    if len(partes) == 2 and 2 < len(partes[1]) < 45:
        return partes[0].strip(), partes[1].strip()
    return titulo.strip(), ""


def dominio(url: str) -> str:
    """Dominio limpio de una URL, sin www."""
    try:
        d = urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except ValueError:
        return ""


def tokens(titulo: str) -> set[str]:
    """Raices de las palabras significativas de un titulo, para comparar.

    El truncado a LARGO_RAIZ caracteres unifica formas flexionadas sin
    necesidad de un lematizador: expulsara / expulsar / expulsion -> expuls,
    argentina / argentinos -> argent, modificacion / modifica -> modifi.
    Es tosco pero suficiente, y no agrega dependencias.
    """
    limpio = sin_acentos(titulo.lower())
    palabras = re.findall(r"[a-z0-9]{3,}", limpio)
    return {p[:LARGO_RAIZ] for p in palabras if p not in VACIAS}


def pesos_por_rareza(items: list[dict]) -> dict[str, float]:
    """Peso de cada palabra segun su rareza en el conjunto (IDF).

    Compartir "Milei" o "migraciones" es evidencia fuerte de que dos titulos
    hablan del mismo hecho. Compartir "para" no dice nada. Sin este peso, un
    Jaccard plano no agrupa notas del mismo hecho escritas con otras palabras.
    """
    n = max(len(items), 1)
    frecuencia: Counter = Counter()
    for it in items:
        frecuencia.update(it["_tokens"])
    return {p: math.log(n / f) + 1 for p, f in frecuencia.items()}


def parecido(a: set[str], b: set[str], pesos: dict[str, float]) -> float:
    """Solapamiento ponderado por rareza. 1.0 = uno contiene al otro.

    Se usa solapamiento y no Jaccard porque los titulos del mismo hecho tienen
    largos muy distintos, y Jaccard penaliza esa asimetria.
    """
    if not a or not b:
        return 0.0
    comunes = a & b
    if len(comunes) < MINIMO_COMPARTIDO:
        return 0.0
    peso = lambda s: sum(pesos.get(p, 1.0) for p in s)
    return peso(comunes) / max(min(peso(a), peso(b)), 1e-9)


def fuera_de_alcance(titulo: str) -> bool:
    """True si el hecho parece ocurrir fuera de America Latina, el Caribe o EEUU.

    Heuristica deliberadamente conservadora: solo marca cuando hay senal de otra
    region Y ninguna del alcance propio. Ante la duda, deja el hecho adentro.
    """
    t = sin_acentos(titulo.lower())
    hay_fuera = any(p in t for p in FUERA_DE_ALCANCE)
    hay_dentro = any(p in t for p in EN_ALCANCE)
    return hay_fuera and not hay_dentro


def fecha_de(entrada) -> datetime | None:
    """Fecha de publicacion en UTC, o None si el feed no la trae."""
    t = entrada.get("published_parsed") or entrada.get("updated_parsed")
    return datetime(*t[:6], tzinfo=timezone.utc) if t else None


def descargar(f) -> list[dict]:
    """Baja un feed y devuelve sus entradas normalizadas. Tolera fallos."""
    try:
        r = requests.get(f.url, timeout=TIMEOUT, headers={"User-Agent": UA})
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("   %-32s fallo: %s", f.id, type(e).__name__)
        return []

    corte = datetime.now(timezone.utc) - timedelta(hours=VENTANA_HORAS)
    salida = []

    for e in feedparser.parse(r.content).entries:
        fecha = fecha_de(e)
        if fecha and fecha < corte:
            continue

        crudo = e.get("title", "").strip()
        if not crudo:
            continue

        titulo, medio_titulo = separar_medio(crudo)
        url = e.get("link", "")
        # El nombre que declara el feed es mas confiable que el dominio, porque
        # las URLs de Google News son redirecciones a news.google.com.
        medio = (e.get("source", {}).get("title") or medio_titulo or dominio(url)).strip()

        salida.append({
            "id": hashlib.sha1((url or titulo).encode()).hexdigest()[:12],
            "titulo": titulo,
            "url": url,
            "medio": medio or "desconocido",
            "fuente": f.id,
            "region": f.region,
            "eje_esperado": f.eje_esperado,
            "pais": f.pais,
            "fecha": (fecha or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
            "_tokens": tokens(titulo),
        })

    log.info("   %-32s %3d entradas", f.id, len(salida))
    return salida


def agrupar(items: list[dict]) -> list[dict]:
    """Agrupa notas del mismo hecho comparando palabras del titulo.

    Un hecho no es una nota: veinte notas sobre el mismo decreto son UN hecho
    con veinte URLs. La velocidad se mide en medios distintos por hecho.

    Enlace simple: si A se parece a B y B a C, los tres van al mismo grupo
    aunque A y C no se parezcan directamente. Los titulos del mismo hecho
    forman cadenas de reformulaciones.
    """
    pesos = pesos_por_rareza(items)
    grupos: list[list[dict]] = []

    # De mas largo a mas corto: los titulos largos hacen mejores centros de grupo.
    for it in sorted(items, key=lambda x: -len(x["_tokens"])):
        for g in grupos:
            if any(parecido(it["_tokens"], o["_tokens"], pesos) >= SIMILITUD_MINIMA
                   for o in g):
                g.append(it)
                break
        else:
            grupos.append([it])

    hechos = []
    for g in grupos:
        # Un medio, un enlace. Se guarda emparejado para que el tablero pueda
        # linkear cada fuente y el equipo chequee cualquiera de ellas.
        vistos: dict[str, dict] = {}
        for i in sorted(g, key=lambda x: x["fecha"]):
            if i["medio"] != "desconocido" and i["medio"] not in vistos:
                vistos[i["medio"]] = {"medio": i["medio"], "url": i["url"], "fecha": i["fecha"]}
        coberturas = sorted(vistos.values(), key=lambda x: x["medio"].lower())
        medios = [c["medio"] for c in coberturas]
        fechas = sorted(i["fecha"] for i in g)
        ejes = [i["eje_esperado"] for i in g if i["eje_esperado"]]
        regiones = sorted({i["region"] for i in g})
        paises = sorted({p for i in g for p in i["pais"]})

        primera = datetime.fromisoformat(fechas[0])
        horas = round((datetime.now(timezone.utc) - primera).total_seconds() / 3600, 1)

        hechos.append({
            "id": g[0]["id"],
            "titulo_original": g[0]["titulo"],
            "url": g[0]["url"],
            "medios": medios,
            "coberturas": coberturas,
            "velocidad": len(medios),
            "aceleracion": None,          # requiere historico entre corridas
            "trends": None,
            "horas": horas,
            "notas": len(g),
            "otras_urls": [i["url"] for i in g[1:8]],
            "ejes": [e for e, _ in Counter(ejes).most_common(2)],
            "regiones": regiones,
            "region": regiones[0] if regiones else "",
            "paises": paises,
            "fuera_de_alcance": fuera_de_alcance(g[0]["titulo"]),
            "importancia": None,          # requiere clasificacion por LLM
            "clasificado": False,
        })

    return hechos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prioridad", type=int, default=1)
    args = ap.parse_args()

    lista = [f for f in fuentes(args.prioridad) if f.tipo in ("google_news", "feed")]
    log.info("Descargando %d fuentes\n%s", len(lista), "=" * 58)

    items = [x for f in lista for x in descargar(f)]
    log.info("%s\nNotas descargadas: %d", "=" * 58, len(items))

    hechos = agrupar(items)
    hechos.sort(key=lambda h: (-h["velocidad"], h["horas"]))

    for h in hechos:
        h.pop("_tokens", None)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "clasificado": False,
        "notas_totales": len(items),
        "items": hechos,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    fuera = sum(1 for h in hechos if h["fuera_de_alcance"])
    log.info("Hechos unicos: %d  (reduccion del %d%%)",
             len(hechos), round((1 - len(hechos) / max(len(items), 1)) * 100))
    log.info("Fuera del alcance geografico: %d  (van a pestana aparte, no se descartan)", fuera)
    log.info("")
    log.info("Los cinco de mayor velocidad dentro del alcance:")
    for h in [x for x in hechos if not x["fuera_de_alcance"]][:5]:
        log.info("   %2d medios | %5.1fh | %s", h["velocidad"], h["horas"], h["titulo_original"][:60])
    log.info("")
    log.info("Escrito %s", SALIDA.relative_to(RAIZ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
