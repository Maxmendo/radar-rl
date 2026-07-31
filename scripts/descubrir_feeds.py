"""Busca el feed RSS/Atom de los sitios que devolvieron HTML en la validación.

Dos estrategias, en orden:
  1. Autodescubrimiento: leer las etiquetas <link rel="alternate"> del HTML,
     que es donde los sitios declaran su feed por convención.
  2. Rutas convencionales: probar /feed, /rss, etc. Solo si lo anterior no dio nada.

No adivina ni inventa URLs: solo reporta lo que el propio sitio declara o lo que
responde con contenido de feed verificable.

Uso:
    python scripts/descubrir_feeds.py
"""

import logging
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml

TIMEOUT = 20
UA = "radar-rl/0.1 (Refugio Latinoamericano; contacto@refugiolatinoamericano.com)"
RAIZ = Path(__file__).resolve().parent.parent

TIPOS_FEED = ("application/rss+xml", "application/atom+xml", "application/feed+json")
RUTAS_COMUNES = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml")

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("descubrir")


class BuscadorDeFeeds(HTMLParser):
    """Extrae las URLs de feed declaradas en las etiquetas <link> del head."""

    def __init__(self):
        super().__init__()
        self.encontrados = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = dict(attrs)
        if a.get("type", "").lower() in TIPOS_FEED and a.get("href"):
            self.encontrados.append((a["href"], a.get("title", "")))


def bajar(url: str) -> requests.Response | None:
    """GET tolerante: devuelve None ante cualquier problema, sin cortar la corrida."""
    try:
        return requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    except requests.RequestException as e:
        log.info("      error de red: %s", type(e).__name__)
        return None


def parece_feed(r: requests.Response) -> bool:
    """Confirma que la respuesta sea realmente un feed y no una página de error."""
    if r.status_code != 200:
        return False
    ctype = r.headers.get("Content-Type", "").lower()
    if "json" in ctype:
        return True
    cabeza = r.text[:600].lower()
    return "<rss" in cabeza or "<feed" in cabeza or "rdf:rdf" in cabeza


def por_autodescubrimiento(url_base: str, html: str) -> list[str]:
    """Devuelve los feeds que el sitio declara en su propio HTML."""
    p = BuscadorDeFeeds()
    try:
        p.feed(html)
    except Exception:
        return []
    return [urljoin(url_base, href) for href, _ in p.encontrados]


def por_rutas_comunes(url_base: str) -> list[str]:
    """Prueba las rutas de feed más habituales. Solo confirma las que responden."""
    hallados = []
    for ruta in RUTAS_COMUNES:
        candidata = url_base.rstrip("/") + ruta
        r = bajar(candidata)
        if r and parece_feed(r):
            hallados.append(candidata)
    return hallados


def revisar(fid: str, url_base: str) -> None:
    """Analiza una fuente e imprime el resultado."""
    log.info("\n%s\n   %s", fid, url_base)

    r = bajar(url_base)
    if r is None:
        return
    if r.status_code != 200:
        log.info("   HTTP %s — el sitio no responde bien. Revisar a mano.", r.status_code)
        return

    if parece_feed(r):
        log.info("   Ya es un feed. Nada que hacer.")
        return

    declarados = por_autodescubrimiento(url_base, r.text)
    if declarados:
        log.info("   Feeds declarados por el sitio:")
        for u in declarados:
            v = bajar(u)
            estado = "responde OK" if v and parece_feed(v) else "declarado pero no responde"
            log.info("      %s  (%s)", u, estado)
        return

    log.info("   No declara feed. Probando rutas convencionales...")
    hallados = por_rutas_comunes(url_base)
    if hallados:
        for u in hallados:
            log.info("      %s  (responde OK)", u)
    else:
        log.info("      Sin feed. Opciones: buscar una API oficial, o dar de baja.")


def main() -> int:
    cfg = yaml.safe_load((RAIZ / "fuentes.yaml").read_text(encoding="utf-8"))

    pendientes = []
    for grupo in ("normativa", "organismos"):
        for f in cfg.get(grupo, []):
            if f.get("url_base") and not f.get("verificado"):
                pendientes.append((f["id"], f["url_base"]))

    log.info("Buscando feeds en %d sitios\n%s", len(pendientes), "=" * 60)
    for fid, url in pendientes:
        revisar(fid, url)

    log.info("\n%s", "=" * 60)
    log.info("Copiar las URLs que digan 'responde OK' a fuentes.yaml,")
    log.info("reemplazando url_base y poniendo verificado: true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
