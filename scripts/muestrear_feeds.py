"""Muestra qué hay realmente adentro de cada feed: cuántas entradas, de qué fecha, qué títulos.

Un feed puede responder OK y traer cinco entradas de 2019. Esto lo detecta antes
de que escribamos código de ingesta que dependa de él.

Uso:
    python scripts/muestrear_feeds.py
"""

import logging
import sys
from datetime import datetime, timezone

import feedparser
import requests

TIMEOUT = 25
UA = "radar-rl/0.1 (Refugio Latinoamericano; contacto@refugiolatinoamericano.com)"

# Feeds confirmados por descubrir_feeds.py.
# Se listan acá y no en fuentes.yaml a propósito: primero verificamos que sirvan,
# después los promovemos al registro oficial.
CANDIDATOS = [
    ("infoleg_ar", "https://www.infoleg.gob.ar/?feed=rss2"),
    ("cels", "https://www.cels.org.ar/feed"),
    ("ippdh_mercosur", "https://www.ippdh.mercosur.int/feed"),
    ("diario_oficial_cl", "https://www.diariooficial.interior.gob.cl/feed"),
    ("gnews_politica_migratoria_ar",
     "https://news.google.com/rss/search?q=%22pol%C3%ADtica+migratoria%22+OR+%22decreto+migratorio%22+OR+%22Migraciones%22+Argentina+when:3d&hl=es-419&gl=AR&ceid=AR:es-419"),
    ("gnews_radicacion_ar",
     "https://news.google.com/rss/search?q=%22radicaci%C3%B3n%22+OR+%22residencia+precaria%22+OR+%22expulsi%C3%B3n%22+migrantes+Argentina+when:3d&hl=es-419&gl=AR&ceid=AR:es-419"),
    ("gnews_xenofobia_regional",
     "https://news.google.com/rss/search?q=xenofobia+OR+%22discurso+de+odio%22+migrantes+when:3d&hl=es-419&gl=AR&ceid=AR:es-419"),
    ("gnews_migracion_bolivia_peru",
     "https://news.google.com/rss/search?q=migrantes+bolivianos+OR+peruanos+OR+venezolanos+Argentina+when:7d&hl=es-419&gl=AR&ceid=AR:es-419"),
]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("muestrear")


def antiguedad_en_dias(entrada) -> int | None:
    """Días transcurridos desde la publicación de una entrada, o None si no trae fecha."""
    t = entrada.get("published_parsed") or entrada.get("updated_parsed")
    if not t:
        return None
    fecha = datetime(*t[:6], tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fecha).days


def recortar(texto: str, largo: int = 90) -> str:
    """Acorta un texto para que entre en una línea de log."""
    limpio = " ".join(texto.split())
    return limpio[:largo] + ("..." if len(limpio) > largo else "")


def muestrear(fid: str, url: str) -> None:
    """Descarga un feed e informa volumen, frescura y una muestra de títulos."""
    log.info("\n%s\n%s", fid, "-" * len(fid))

    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        r.raise_for_status()
    except requests.RequestException as e:
        log.info("   no se pudo descargar: %s", type(e).__name__)
        return

    d = feedparser.parse(r.content)
    entradas = d.entries

    if not entradas:
        log.info("   FEED VACIO. Responde pero no trae entradas. Descartar.")
        return

    edades = [a for a in (antiguedad_en_dias(e) for e in entradas) if a is not None]
    log.info("   entradas: %d", len(entradas))

    if edades:
        log.info("   mas reciente: hace %d dias  |  mas vieja: hace %d dias",
                 min(edades), max(edades))
        if min(edades) > 30:
            log.info("   ATENCION: nada nuevo en mas de un mes. Probablemente inservible.")
    else:
        log.info("   sin fechas legibles en las entradas")

    log.info("   ultimos titulos:")
    for e in entradas[:4]:
        dias = antiguedad_en_dias(e)
        marca = f"[{dias}d]" if dias is not None else "[s/f]"
        log.info("      %s %s", marca, recortar(e.get("title", "(sin titulo)")))


def main() -> int:
    log.info("Muestreando %d feeds\n%s", len(CANDIDATOS), "=" * 60)
    for fid, url in CANDIDATOS:
        muestrear(fid, url)
    log.info("\n%s", "=" * 60)
    log.info("Criterio: sirve si trae entradas, tiene fechas y hay algo de la ultima semana.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
