"""Verifica que las fuentes declaradas en fuentes.yaml respondan y con qué formato.

No implementa ingesta. Solo responde: ¿esta URL existe, responde, y qué devuelve?
Se corre antes de escribir cualquier módulo de fuente.

Uso:
    python scripts/validar_fuentes.py
    python scripts/validar_fuentes.py --prioridad 1
"""

import argparse
import logging
import sys
from pathlib import Path
from urllib.parse import quote

import requests
import yaml

TIMEOUT = 15
UA = "radar-rl/0.1 (Refugio Latinoamericano; contacto@refugiolatinoamericano.com)"
RAIZ = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("validar")


def probar_url(url: str) -> dict:
    """Hace un GET y describe qué respondió, sin interpretar el contenido."""
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    except requests.RequestException as e:
        return {"ok": False, "detalle": f"{type(e).__name__}: {e}"}

    ctype = r.headers.get("Content-Type", "").split(";")[0].strip()
    muestra = r.text[:300].replace("\n", " ") if r.text else ""
    return {
        "ok": r.status_code == 200,
        "status": r.status_code,
        "content_type": ctype,
        "formato": inferir_formato(ctype, muestra),
        "bytes": len(r.content),
        "muestra": muestra,
    }


def inferir_formato(ctype: str, muestra: str) -> str:
    """Adivina el formato a partir del content-type y los primeros bytes."""
    if "json" in ctype:
        return "json"
    if "xml" in ctype or "rss" in ctype:
        return "rss/xml"
    if muestra.lstrip().startswith("<?xml") or "<rss" in muestra[:200]:
        return "rss/xml"
    if muestra.lstrip().startswith("{") or muestra.lstrip().startswith("["):
        return "json"
    if "html" in ctype:
        return "html"
    return "desconocido"


def url_google_news(query: str, gl: str) -> str:
    """Arma la URL de RSS de Google News para una consulta."""
    return (
        f"https://news.google.com/rss/search?q={quote(query)}"
        f"&hl=es-419&gl={gl}&ceid={gl}:es-419"
    )


def url_gdelt(query: str, modo: str) -> str:
    """Arma la URL de la API DOC 2.0 de GDELT."""
    return (
        f"https://api.gdeltproject.org/api/v2/doc/doc?query={quote(query)}"
        f"&mode={modo}&format=json&maxrecords=10&timespan=3d"
    )


def recolectar_pruebas(cfg: dict, prioridad_max: int) -> list[tuple[str, str]]:
    """Devuelve pares (id, url) a probar, a partir del yaml."""
    pruebas = []

    for grupo in ("normativa", "organismos"):
        for f in cfg.get(grupo, []):
            if f.get("prioridad", 9) > prioridad_max or not f.get("url_base"):
                continue
            pruebas.append((f["id"], f["url_base"]))

    for f in cfg.get("medios_google_news", []):
        if f.get("prioridad", 9) <= prioridad_max:
            pruebas.append((f["id"], url_google_news(f["query"], f.get("gl", "AR"))))

    for f in cfg.get("cobertura_agregada", []):
        if f.get("prioridad", 9) <= prioridad_max and f.get("query"):
            pruebas.append((f["id"], url_gdelt(f["query"], f.get("modo", "artlist"))))

    for f in cfg.get("social", []):
        if f.get("prioridad", 9) > prioridad_max:
            continue
        if f["id"] == "bluesky_migracion":
            pruebas.append((f["id"], f"{f['endpoint']}?q=migrantes&limit=5"))

    return pruebas


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prioridad", type=int, default=1)
    args = ap.parse_args()

    cfg = yaml.safe_load((RAIZ / "fuentes.yaml").read_text(encoding="utf-8"))
    pruebas = recolectar_pruebas(cfg, args.prioridad)

    log.info("Probando %d fuentes (prioridad <= %d)\n", len(pruebas), args.prioridad)

    vivas, muertas = [], []
    for fid, url in pruebas:
        r = probar_url(url)
        if r["ok"]:
            vivas.append(fid)
            log.info("OK    %-32s %-9s %d bytes", fid, r["formato"], r["bytes"])
        else:
            muertas.append((fid, r.get("detalle") or f"HTTP {r.get('status')}"))
            log.warning("FALLA %-32s %s", fid, muertas[-1][1])

    print(f"\n{len(vivas)} vivas / {len(pruebas)} probadas")
    if muertas:
        print("\nRevisar en fuentes.yaml:")
        for fid, motivo in muertas:
            print(f"  - {fid}: {motivo}")
        print("\nCorregir la URL o dar de baja la fuente. No implementar módulos")
        print("de ingesta para fuentes que no validan.")

    return 0 if not muertas else 1


if __name__ == "__main__":
    sys.exit(main())
