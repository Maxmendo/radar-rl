"""Muestra que hay realmente adentro de cada feed: cuantas entradas, de que fecha, que titulos.

Un feed puede responder OK y traer cinco entradas de 2019. Esto lo detecta antes
de que escribamos codigo de ingesta que dependa de el.

Lee las fuentes de fuentes.yaml a traves de nucleo.registro. No mantiene ninguna
lista propia: eso fue lo que lo desincronizo del registro en la version anterior.

Uso:
    python scripts/muestrear_feeds.py
    python scripts/muestrear_feeds.py --prioridad 2
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.registro import fuentes  # noqa: E402

TIMEOUT = 25
UA = "radar-rl/0.1 (Refugio Latinoamericano; contacto@refugiolatinoamericano.com)"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("muestrear")


def antiguedad_en_dias(entrada) -> int | None:
    """Dias transcurridos desde la publicacion de una entrada, o None si no trae fecha."""
    t = entrada.get("published_parsed") or entrada.get("updated_parsed")
    if not t:
        return None
    fecha = datetime(*t[:6], tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - fecha).days


def recortar(texto: str, largo: int = 88) -> str:
    """Acorta un texto para que entre en una linea de log."""
    limpio = " ".join(texto.split())
    return limpio[:largo] + ("..." if len(limpio) > largo else "")


def muestrear(f) -> dict:
    """Descarga un feed e informa volumen, frescura y una muestra de titulos."""
    log.info("\n%s", f.id)
    log.info("%s", "-" * len(f.id))

    try:
        r = requests.get(f.url, timeout=TIMEOUT, headers={"User-Agent": UA})
        r.raise_for_status()
    except requests.RequestException as e:
        log.info("   no se pudo descargar: %s", type(e).__name__)
        return {"id": f.id, "entradas": 0, "sirve": False}

    entradas = feedparser.parse(r.content).entries
    if not entradas:
        log.info("   FEED VACIO. Responde pero no trae entradas.")
        return {"id": f.id, "entradas": 0, "sirve": False}

    edades = [a for a in (antiguedad_en_dias(e) for e in entradas) if a is not None]
    log.info("   entradas: %d", len(entradas))

    sirve = True
    if edades:
        log.info("   mas reciente: hace %d dias  |  mas vieja: hace %d dias",
                 min(edades), max(edades))
        if min(edades) > 30:
            log.info("   ATENCION: nada nuevo en mas de un mes. Probablemente inservible.")
            sirve = False
    else:
        log.info("   sin fechas legibles en las entradas")

    log.info("   ultimos titulos:")
    for e in entradas[:3]:
        dias = antiguedad_en_dias(e)
        marca = f"[{dias}d]" if dias is not None else "[s/f]"
        log.info("      %s %s", marca, recortar(e.get("title", "(sin titulo)")))

    return {"id": f.id, "entradas": len(entradas), "sirve": sirve}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prioridad", type=int, default=1)
    args = ap.parse_args()

    # GDELT devuelve JSON, no un feed: queda fuera de este muestreo.
    lista = [f for f in fuentes(args.prioridad) if f.tipo != "gdelt"]

    log.info("Muestreando %d feeds (prioridad <= %d)\n%s",
             len(lista), args.prioridad, "=" * 60)

    resultados = [muestrear(f) for f in lista]

    total = sum(r["entradas"] for r in resultados)
    utiles = [r for r in resultados if r["sirve"] and r["entradas"]]
    flojos = [r["id"] for r in resultados if not r["sirve"]]

    log.info("\n%s", "=" * 60)
    log.info("RESUMEN")
    log.info("   feeds utiles: %d de %d", len(utiles), len(resultados))
    log.info("   entradas totales en esta corrida: %d", total)
    log.info("   volumen estimado por dia: ~%d entradas (ventana de 3 dias)", total // 3)
    if flojos:
        log.info("   revisar: %s", ", ".join(flojos))
    log.info("")
    log.info("El total importa: cada item que sobrevive a la deduplicacion")
    log.info("cuesta una llamada al modelo en la etapa de clasificacion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
