"""Prueba si `related_queries` de Google Trends sirve para vincular hechos.

POR QUE ESTE SCRIPT EXISTE
--------------------------
Vincular Google Trends con noticias individuales fallo dos veces:

  1. Terminos especificos ("ICE detenciones Miami"): sin volumen, series vacias.
  2. Terminos generales ("deportaciones"): tienen volumen, pero todos los hechos
     del mismo eje comparten termino y reciben identico puntaje. El cruce deja
     de distinguir entre noticias.

`related_queries` invierte la pregunta: en vez de "¿esta subiendo ESTE termino?",
pregunta "¿que se esta buscando sobre deportaciones AHORA?". Si entre las
consultas en alza aparece algo que coincide con un titular, ese hecho queda
vinculado con evidencia concreta.

Este script NO modifica nada del radar. Solo consulta y reporta, para decidir
con datos si vale la pena construirlo.

Uso:
    python scripts/probar_related.py
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ITEMS = RAIZ / "datos" / "items.json"
SALIDA = RAIZ / "datos" / "prueba_related.txt"

# Terminos amplios, uno por eje, con el pais donde tiene sentido medirlos.
PRUEBAS = [
    ("deportaciones", "US"),
    ("deportaciones", "MX"),
    ("migrantes", "AR"),
    ("migrantes", "CL"),
    ("asilo", "US"),
    ("refugiados", "CO"),
]

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("probar")


def filas(df, tope: int = 10) -> list[tuple[str, str]]:
    """Extrae (consulta, valor) de un DataFrame de trendspy, tolerando formatos."""
    if df is None or getattr(df, "empty", True):
        return []
    try:
        cols = list(df.columns)
        c_query = next((c for c in cols if "quer" in str(c).lower()), cols[0])
        c_val = next((c for c in cols if str(c).lower() in ("value", "valor")), cols[-1])
        return [(str(r[c_query]), str(r[c_val]))
                for _, r in df.head(tope).iterrows()]
    except Exception as e:
        log.warning("      no se pudo leer el DataFrame: %s", type(e).__name__)
        return []


def titulares_de_interes() -> list[str]:
    """Titulares de los hechos que hoy estan en estado `interes`."""
    if not ITEMS.exists():
        return []
    sys.path.insert(0, str(RAIZ))
    from nucleo.estados import estado, normalizar_ejes
    datos = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = datos.get("items", [])
    normalizar_ejes(items)
    return [i["titulo_original"] for i in items if estado(i) == "interes"]


def main() -> int:
    try:
        from trendspy import Trends
        cliente = Trends(hl="es", tz=180, request_delay=2.0)
    except Exception as e:
        log.error("trendspy no disponible: %s", type(e).__name__)
        return 1

    lineas = [f"PRUEBA DE related_queries — {datetime.now(timezone.utc).isoformat(timespec='seconds')}", ""]

    titulares = titulares_de_interes()
    lineas.append(f"Titulares en estado `interes` hoy: {len(titulares)}")
    for t in titulares:
        lineas.append(f"   {t[:100]}")
    lineas.append("")
    lineas.append("=" * 70)

    exitos = fallos = 0

    for termino, geo in PRUEBAS:
        log.info("\n%s / %s", termino, geo)
        lineas.append(f"\n{termino}  ({geo})")
        lineas.append("-" * 40)
        try:
            r = cliente.related_queries(termino, timeframe="today 3-m", geo=geo)
        except Exception as e:
            log.warning("   FALLA: %s: %s", type(e).__name__, str(e)[:80])
            lineas.append(f"   FALLA: {type(e).__name__}: {str(e)[:120]}")
            fallos += 1
            time.sleep(3)
            continue

        if not isinstance(r, dict):
            lineas.append(f"   formato inesperado: {type(r).__name__}")
            fallos += 1
            time.sleep(3)
            continue

        hubo = False
        for clave in ("rising", "top"):
            datos = filas(r.get(clave))
            if not datos:
                continue
            hubo = True
            etiqueta = "EN ALZA" if clave == "rising" else "MAS BUSCADAS"
            lineas.append(f"   {etiqueta}:")
            for consulta, valor in datos:
                lineas.append(f"      {valor:>8}  {consulta}")
                log.info("      [%s] %-8s %s", clave, valor, consulta)

        if hubo:
            exitos += 1
        else:
            lineas.append("   sin datos")
            fallos += 1
        time.sleep(3)

    lineas.append("")
    lineas.append("=" * 70)
    lineas.append(f"RESULTADO: {exitos} consultas con datos, {fallos} sin datos")
    lineas.append("")
    if exitos:
        lineas.append("related_queries FUNCIONA. Comparar las consultas en alza de arriba")
        lineas.append("contra los titulares del principio: si hay coincidencias de palabras,")
        lineas.append("el vinculo por hecho es viable y vale la pena construirlo.")
    else:
        lineas.append("related_queries NO devuelve datos. El vinculo por hecho no es viable")
        lineas.append("con Google Trends: el valor queda en los paneles de atencion publica")
        lineas.append("y demanda de servicio, que si funcionan.")

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text("\n".join(lineas), encoding="utf-8")

    log.info("\n%s", "=" * 60)
    log.info("%d consultas con datos, %d sin datos", exitos, fallos)
    log.info("Escrito %s", SALIDA.relative_to(RAIZ))
    log.info("")
    for l in lineas[-4:]:
        log.info("%s", l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
