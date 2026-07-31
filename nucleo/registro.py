"""Lectura de fuentes.yaml y armado de URLs. Unica fuente de verdad del registro.

Todo script que necesite saber que fuentes existen o como consultarlas usa este
modulo. Nunca se repite la lista ni la logica de armar URLs en otro lado: fue
exactamente lo que desincronizo a muestrear_feeds.py de fuentes.yaml.
"""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import yaml

RAIZ = Path(__file__).resolve().parent.parent
REGISTRO = RAIZ / "fuentes.yaml"


@dataclass
class Fuente:
    """Una fuente consultable, ya resuelta a una URL concreta."""

    id: str
    url: str
    tipo: str          # google_news | feed | gdelt | social
    prioridad: int
    pais: list[str]
    region: str = ""
    eje_esperado: str = ""

    def __str__(self) -> str:
        return self.id


def cargar() -> dict:
    """Devuelve el contenido crudo de fuentes.yaml."""
    return yaml.safe_load(REGISTRO.read_text(encoding="utf-8"))


def url_google_news(query: str, gl: str, hl: str) -> str:
    """Arma la URL de RSS de Google News. hl define el idioma; gl, la edicion."""
    return (f"https://news.google.com/rss/search?q={quote(query)}"
            f"&hl={hl}&gl={gl}&ceid={gl}:{hl}")


def url_gdelt(query: str, modo: str = "artlist", dias: int = 3) -> str:
    """Arma la URL de la API DOC 2.0 de GDELT."""
    return (f"https://api.gdeltproject.org/api/v2/doc/doc?query={quote(query)}"
            f"&mode={modo}&format=json&maxrecords=50&timespan={dias}d")


def fuentes(prioridad_max: int = 1, solo_verificadas: bool = True) -> list[Fuente]:
    """Devuelve las fuentes consultables hasta la prioridad indicada.

    Es la funcion que usan todos los scripts. Si una fuente no aparece aca,
    no existe para el sistema.
    """
    cfg = cargar()
    salida: list[Fuente] = []

    def pasa(f: dict) -> bool:
        if f.get("prioridad", 9) > prioridad_max:
            return False
        return f.get("verificado", False) or not solo_verificadas

    for f in cfg.get("medios_google_news", []):
        if pasa(f):
            salida.append(Fuente(
                id=f["id"],
                url=url_google_news(f["query"], f.get("gl", "AR"), f.get("hl", "es-419")),
                tipo="google_news",
                prioridad=f["prioridad"],
                pais=f.get("pais", []),
                region=f.get("region", ""),
                eje_esperado=f.get("eje_esperado", ""),
            ))

    for f in cfg.get("organismos", []):
        if pasa(f) and f.get("url_base"):
            salida.append(Fuente(
                id=f["id"],
                url=f["url_base"],
                tipo="feed",
                prioridad=f["prioridad"],
                pais=f.get("pais", []),
                region=f.get("nombre", ""),
            ))

    for f in cfg.get("cobertura_agregada", []):
        if pasa(f) and f.get("query"):
            salida.append(Fuente(
                id=f["id"],
                url=url_gdelt(f["query"], f.get("modo", "artlist")),
                tipo="gdelt",
                prioridad=f["prioridad"],
                pais=["REGIONAL"],
            ))

    return salida


def ejes_activos() -> list[str]:
    """Ids de los ejes marcados como activos. El clasificador solo usa estos."""
    return [e["id"] for e in cargar().get("ejes", []) if e.get("activo")]


def sin_verificar() -> list[tuple[str, str]]:
    """Pares (id, url_base) de fuentes que todavia no fueron verificadas.

    Lo consume descubrir_feeds.py, que no corre a diario sino cuando se agregan
    fuentes nuevas al registro.
    """
    cfg = cargar()
    salida = []
    for grupo in ("normativa", "organismos"):
        for f in cfg.get(grupo, []) or []:
            if f.get("url_base") and not f.get("verificado"):
                salida.append((f["id"], f["url_base"]))
    return salida
