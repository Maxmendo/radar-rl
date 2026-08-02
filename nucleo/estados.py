"""Reglas del ciclo de vida de un hecho. Fuente unica.

Vivian dentro de generar_tablero.py, pero ahora tambien las necesita
nucleo/tendencias.py, que consulta Google Trends SOLO para los hechos que estan
en `interes`. Duplicar las reglas en dos archivos garantiza que en algun momento
se desincronicen, que fue el bug de muestrear_feeds.py en julio de 2026.
"""

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent

# Umbral propio para hechos de otras regiones que llegan a Top trend.
# Mas alto que el regional (20) porque la cobertura del Mediterraneo en prensa
# hispana es estructuralmente mas voluminosa que la de un decreto argentino.
UMBRAL_EXTRARREGIONAL = 30


def estado(item: dict) -> str:
    """Ubica un hecho en su ciclo de vida segun cuantos medios lo publicaron."""
    if item.get("fuera_de_alcance"):
        # Excepcion deliberada: un hecho extrarregional con cobertura masiva
        # entra a `top_trend` para mostrar cual es la conversacion dominante
        # sobre movilidad humana en el mundo. Queda marcado y siempre ordenado
        # DEBAJO de los hechos regionales.
        if (item.get("velocidad") or 0) >= UMBRAL_EXTRARREGIONAL:
            return "top_trend"
        return "fuera_alcance"

    if item.get("clasificado") and item.get("es_migratorio") is False:
        return "ruido"

    vel = item.get("velocidad") or 0
    acel = item.get("aceleracion") or 0
    imp = item.get("importancia")

    if vel >= 20:
        return "top_trend"
    if vel >= 8 or (vel >= 5 and acel >= 4):
        return "trending"
    if vel >= 3 or (vel >= 2 and acel >= 2):
        return "interes"
    if imp is None:
        return "emergente"
    return "nadie_lo_mira" if imp >= 7 else "ruido"


def frescura(horas) -> float:
    """Peso por antiguedad: lo que recien arranca vale mas que lo que ya paso."""
    if horas is None:
        return 0.4
    if horas < 6:
        return 1.0
    if horas < 12:
        return 0.7
    if horas < 24:
        return 0.4
    return 0.1


def puntaje(item: dict) -> float:
    """Desempate dentro de una misma importancia.

    El orden principal del tablero es por IMPORTANCIA. Este puntaje solo ordena
    los hechos que la comparten: ahi mandan velocidad y frescura.

    NOTA: `trends` NO entra en esta formula. Google Trends refleja las busquedas
    con retraso y lo que las hace subir suele ser la propia cobertura mediatica,
    asi que sumarlo aca contaminaria el ranking con una senal correlacionada.
    Se usa para disparar alertas, no para ordenar.
    """
    imp = item.get("importancia") or 5
    vel = item.get("velocidad") or 0
    acel = max(0, item.get("aceleracion") or 0)
    return round(imp * frescura(item.get("horas")) * (vel + acel * 2), 1)


def potencial(item: dict) -> float:
    """Se conserva SOLO para poder comparar hipotesis de orden con datos reales.

    NO se usa para ordenar el tablero. Se probó ordenar `interes` por
    importancia x frescura x (medios + trends x 2) y se descartó por tres
    razones:

      1. La multiplicacion amplificaba de mas: hechos editorialmente cercanos
         quedaban con puntajes al triple, magnificando cualquier error en la
         importancia, que es un juicio del modelo y no un hecho.
      2. Hizo falta un piso arbitrario de importancia 6 para que un hecho menor
         muy buscado no desplazara a uno grave poco buscado. Un parche, no un
         criterio.
      3. Sumaba cosas incomparables: "4 medios" es un conteo y "trends 8" es un
         ratio convertido a escala inventada. El peso relativo entre ambos no
         tenia fundamento.

    DECISION: el orden lo da la IMPORTANCIA EDITORIAL, que tiene fundamento.
    Google Trends se muestra como dato al lado, y la persona decide combinando
    ambas cosas. La decision editorial queda donde tiene que estar.

    El valor se sigue calculando y guardando para que, con dos semanas de datos
    reales, se pueda comparar los dos ordenes y decidir con evidencia.
    """
    imp = item.get("importancia") or 5
    vel = item.get("velocidad") or 0
    tr = item.get("trends") or 0
    return round(imp * frescura(item.get("horas")) * (vel + tr * 2), 1)


def alias_ejes() -> dict:
    """Mapa de IDs de vocabulario anterior al vigente."""
    cfg = yaml.safe_load((RAIZ / "fuentes.yaml").read_text(encoding="utf-8"))
    return cfg.get("alias_ejes", {}).get("mapa", {})


def normalizar_ejes(items: list[dict], alias: dict | None = None) -> None:
    """Traduce ejes de versiones anteriores al vocabulario vigente."""
    alias = alias if alias is not None else alias_ejes()
    for i in items:
        i["ejes"] = list(dict.fromkeys(alias.get(e, e) for e in (i.get("ejes") or [])))
