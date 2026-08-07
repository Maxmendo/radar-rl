"""Resuelve URLs de Google News y baja el texto de los articulos.

POR QUE EXISTE
--------------
El borrador necesita el TEXTO de las notas, no solo el titular, para redactar
con datos, nombres y citas reales. Pero las URLs que trae el feed son de Google
News (news.google.com/rss/articles/CBMi...), que NO son la nota: son un
redireccionador que hay que resolver.

Las URLs modernas (formato CBMi) no se resuelven decodificando base64: requieren
pedir dos tokens a Google y hacer una segunda llamada a su endpoint interno
`batchexecute`. Es el metodo que usan las librerias del rubro; es estable pero
depende de que Google no cambie el formato, asi que TODO esto degrada con
gracia: si una URL no se resuelve o el medio bloquea, se devuelve texto vacio y
el que llama sigue con lo que tenga.

Se corre SOLO para las 3 fuentes principales de los hechos que califican para
borrador (no para las ~280 notas de cada corrida): bajar todo seria lento y
gastaria de mas. La ingesta decide a cuales.

Uso:
    from nucleo.textos import bajar_texto
    real, dominio, texto = bajar_texto(url_google_news)
"""

import json
import logging
import re
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("textos")

TIMEOUT = 20
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
# Headers de navegador real: algunos medios rechazan pedidos sin estos.
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
MAX_CARACTERES = 4000       # por nota: alcanza para lead 7W y datos duros


def _dominio(url: str) -> str:
    try:
        return urlparse(url).hostname.replace("www.", "") or ""
    except Exception:
        return ""


def resolver_google_news(url: str, sesion: requests.Session = None) -> str:
    """Devuelve la URL real del medio a partir de una URL de Google News.

    Google envuelve cada enlace en un redireccionador (CBMi...) que SOLO se
    resuelve ejecutando JavaScript: las peticiones HTTP planas reciben la pagina
    de "trafico inusual" (captcha). Por eso se usa Playwright, un navegador
    headless real que Google trata como una visita legitima. Es el metodo que
    usan las librerias del rubro (gnews, etc.) para esto.

    Si Playwright no esta instalado o la resolucion falla, devuelve la URL
    original: el que llama vera que sigue siendo news.google.com y sabra que no
    se pudo resolver. Nunca lanza.
    """
    if "news.google.com" not in url:
        return url                      # ya es una URL directa

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright no instalado; no se puede resolver Google News")
        return url

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=True,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"])
            try:
                ctx = navegador.new_context(user_agent=UA)
                pagina = ctx.new_page()
                pagina.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Google redirige (via JS) a la URL real del medio: se espera a
                # que la URL de la pagina deje de ser news.google.com.
                try:
                    pagina.wait_for_url(
                        lambda u: "news.google.com" not in u, timeout=30000)
                except Exception:
                    pass
                final = pagina.url
                return final if "news.google.com" not in final else url
            finally:
                navegador.close()
    except Exception as e:
        log.debug("playwright no resolvio %s: %s", url[:60], type(e).__name__)
        return url


def _extraer_texto(html: str) -> str:
    """Texto legible del HTML: quita scripts/estilos, prioriza <article>/<p>."""
    if not html:
        return ""
    h = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    h = re.sub(r"<style[\s\S]*?</style>", " ", h, flags=re.I)
    h = re.sub(r"<!--[\s\S]*?-->", " ", h)

    art = re.search(r"<article[\s\S]*?</article>", h, flags=re.I)
    if art:
        h = art.group(0)

    parrafos = re.findall(r"<p[^>]*>([\s\S]*?)</p>", h, flags=re.I)
    limpios = []
    for p in parrafos:
        t = re.sub(r"<[^>]+>", " ", p)
        t = re.sub(r"\s+", " ", t).strip()
        if len(t) > 40:                 # descartar migas, pies de foto, menus
            limpios.append(t)
    texto = "\n\n".join(limpios)

    if not texto:                       # fallback: todo el texto plano
        texto = re.sub(r"<[^>]+>", " ", h)
        texto = re.sub(r"\s+", " ", texto).strip()

    return texto[:MAX_CARACTERES]


def bajar_texto(url: str, sesion: requests.Session | None = None) -> tuple[str, str, str]:
    """Resuelve la URL de Google News y baja el texto del articulo.

    Devuelve (url_real, dominio, texto). Si algo falla en cualquier paso,
    devuelve el texto que haya podido juntar (posiblemente vacio) sin lanzar:
    el que llama decide que hacer con una fuente sin texto.
    """
    propia = sesion is None
    if propia:
        sesion = requests.Session()
    try:
        real = resolver_google_news(url, sesion)
        if "news.google.com" in real:
            return real, "", ""          # no se pudo resolver
        try:
            r = sesion.get(real, timeout=TIMEOUT, headers=HEADERS)
            r.raise_for_status()
            return real, _dominio(real), _extraer_texto(r.text)
        except Exception as e:
            log.debug("no se bajo %s: %s", real[:60], type(e).__name__)
            return real, _dominio(real), ""
    finally:
        if propia:
            sesion.close()


def _resolver_lote(urls: list[str]) -> dict:
    """Resuelve varias URLs de Google News en UNA sola sesion de navegador.

    Abrir Playwright es caro; abrirlo una vez y reusar la pagina para todas las
    URLs del hecho es mucho mas rapido que un navegador por URL. Devuelve un dict
    {url_original: url_real}. Las que no se resuelven quedan con su valor original.
    """
    salida = {u: u for u in urls}
    gnews = [u for u in urls if "news.google.com" in u]
    if not gnews:
        return salida

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("playwright no instalado; no se resuelven URLs de Google News")
        return salida

    try:
        with sync_playwright() as p:
            navegador = p.chromium.launch(
                headless=True,
                args=["--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage"])
            try:
                ctx = navegador.new_context(user_agent=UA)
                for u in gnews:
                    try:
                        pagina = ctx.new_page()
                        pagina.goto(u, wait_until="domcontentloaded", timeout=30000)
                        try:
                            pagina.wait_for_url(
                                lambda x: "news.google.com" not in x, timeout=30000)
                        except Exception:
                            pass
                        final = pagina.url
                        if "news.google.com" not in final:
                            salida[u] = final
                        pagina.close()
                    except Exception as e:
                        log.debug("no resolvio %s: %s", u[:50], type(e).__name__)
            finally:
                navegador.close()
    except Exception as e:
        log.warning("playwright fallo: %s", type(e).__name__)
    return salida


def enriquecer_fuentes(coberturas: list[dict], tope: int = 3,
                       espera: float = 1.0, max_intentos: int = 8) -> list[dict]:
    """Baja el texto de las coberturas hasta juntar `tope` con texto util.

    Las coberturas vienen ordenadas por jerarquia (agencias y legacy primero).
    Primero se resuelven TODAS las URLs de Google News en una sola sesion de
    navegador (Playwright), luego se baja el texto de cada medio por HTTP. Se
    recorren en orden e se intenta hasta juntar `tope` con texto o agotar
    `max_intentos`: si una fuente grande falla, sigue con las siguientes.

    Devuelve TODAS las intentadas (con y sin texto), para que el borrador vea
    tanto el material como que fuentes quedaron sin acceso. Nunca lanza.
    """
    # Excluir redes sociales y agregadores: no son fuentes periodisticas y no
    # dan texto util (facebook, x/twitter, youtube, etc.). Se filtran por el
    # nombre del medio (antes de resolver) y por el dominio real (despues).
    REDES = ("facebook", "twitter", "x.com", "instagram", "tiktok", "youtube",
             "youtu.be", "t.me", "telegram", "whatsapp", "reddit", "linkedin",
             "threads")
    def _es_red(texto):
        t = (texto or "").lower().replace(" ", "")
        return any(r in t for r in REDES)

    candidatas = [c for c in coberturas[:max_intentos]
                  if c.get("url") and not _es_red(c.get("medio", ""))]
    # Paso 1: resolver todas las URLs de una, con un solo navegador.
    reales = _resolver_lote([c["url"] for c in candidatas])

    # Paso 2: bajar el texto de cada medio por HTTP (esto no lo bloquea Google).
    # Se deduplica por dominio: dos URLs del mismo medio (p.ej. infobae.com/america
    # e infobae.com/peru) NO son fuentes independientes; cuentan como una y se
    # sigue buscando otra distinta, para que el borrador tenga contraste real.
    sesion = requests.Session()
    salida = []
    con_texto = 0
    dominios_usados = set()
    try:
        for c in candidatas:
            real = reales.get(c["url"], c["url"])
            texto, dom = "", ""
            if "news.google.com" not in real:      # se resolvio
                dom = _dominio(real)
                if _es_red(dom):
                    continue                       # dominio real es red social
                # Normalizar el dominio para comparar (sacar subdominios comunes).
                base = ".".join(dom.split(".")[-2:]) if dom else ""
                if base and base in dominios_usados:
                    continue                       # mismo medio ya usado: saltear
                try:
                    r = sesion.get(real, timeout=TIMEOUT, headers=HEADERS)
                    r.raise_for_status()
                    texto = _extraer_texto(r.text)
                except Exception as e:
                    log.debug("no se bajo %s: %s", real[:60], type(e).__name__)
            ok = bool(texto and len(texto) > 200)
            salida.append({
                "medio": c.get("medio", "") or dom or "fuente",
                "dominio": dom,
                "url": real,
                "texto": texto,
                "ok": ok,
            })
            if ok:
                con_texto += 1
                base = ".".join(dom.split(".")[-2:]) if dom else ""
                if base:
                    dominios_usados.add(base)
            if con_texto >= tope:
                break
    finally:
        sesion.close()
    return salida
