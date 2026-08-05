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
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
MAX_CARACTERES = 4000       # por nota: alcanza para lead 7W y datos duros


def _dominio(url: str) -> str:
    try:
        return urlparse(url).hostname.replace("www.", "") or ""
    except Exception:
        return ""


def resolver_google_news(url: str, sesion: requests.Session) -> str:
    """Devuelve la URL real del medio a partir de una URL de Google News.

    Metodo para el formato CBMi (2026): se pide la pagina del articulo, se
    extraen los tokens `signature` y `timestamp` incrustados en el HTML, y con
    ellos se llama a `batchexecute`, que responde la URL de destino.

    Si algo falla, devuelve la URL original: el que llama vera que sigue siendo
    news.google.com y sabra que no se pudo resolver.
    """
    if "news.google.com" not in url:
        return url                      # ya es una URL directa

    try:
        # 1) Traer la pagina del articulo para extraer los tokens.
        r = sesion.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
        r.raise_for_status()
        html = r.text

        # Los tokens vienen en un div con data-n-a-sg (signature) y data-n-a-ts
        # (timestamp), o embebidos en un JSON del HTML.
        sig = re.search(r'data-n-a-sg="([^"]+)"', html)
        ts = re.search(r'data-n-a-ts="([^"]+)"', html)
        art = re.search(r'data-n-a-id="([^"]+)"', html)

        if not (sig and ts):
            # Formato alternativo: buscar la URL directa ya presente en el HTML.
            m = re.search(r'https?://(?!news\.google\.com|www\.google\.com)'
                          r'[^\s"\'<>]+', html)
            return m.group(0) if m else url

        # 2) Armar el payload de batchexecute con los tokens.
        art_id = art.group(1) if art else url.rsplit("/", 1)[-1].split("?")[0]
        payload = [
            "Fbv4je",
            f'["garturlreq",[["X","X",["X","X"],null,null,1,1,'
            f'"US:en",null,1,null,null,null,null,null,0,1],'
            f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{art_id}","{ts.group(1)}","{sig.group(1)}"]',
        ]
        body = "f.req=" + requests.utils.quote(json.dumps([[payload]]))

        r2 = sesion.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=body, timeout=TIMEOUT,
            headers={"User-Agent": UA,
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        r2.raise_for_status()
        # La respuesta es JSON con basura antes; se busca la URL directa.
        m = re.search(r'https?://(?!news\.google\.com)[^\s"\\]+', r2.text)
        return m.group(0) if m else url

    except Exception as e:
        log.debug("no se resolvio %s: %s", url[:60], type(e).__name__)
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
            r = sesion.get(real, timeout=TIMEOUT, headers={"User-Agent": UA})
            r.raise_for_status()
            return real, _dominio(real), _extraer_texto(r.text)
        except Exception as e:
            log.debug("no se bajo %s: %s", real[:60], type(e).__name__)
            return real, _dominio(real), ""
    finally:
        if propia:
            sesion.close()


def enriquecer_fuentes(coberturas: list[dict], tope: int = 3,
                       espera: float = 1.0) -> list[dict]:
    """Baja el texto de las `tope` primeras coberturas (ya vienen ordenadas por
    importancia desde la ingesta). Devuelve una lista de dicts listos para el
    borrador. Nunca lanza: las que fallan quedan con texto vacio y ok=False.
    """
    sesion = requests.Session()
    salida = []
    try:
        for c in coberturas[:tope]:
            url = c.get("url", "")
            if not url:
                continue
            real, dom, texto = bajar_texto(url, sesion)
            salida.append({
                "medio": c.get("medio", "") or dom or "fuente",
                "dominio": dom,
                "url": real,
                "texto": texto,
                "ok": bool(texto and len(texto) > 200),
            })
            time.sleep(espera)          # cortesia con los servidores
    finally:
        sesion.close()
    return salida
