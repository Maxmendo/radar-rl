"""Consulta Google Trends SOLO para los hechos que estan en estado `interes`.

POR QUE SOLO ESOS
-----------------
`interes` es el estado donde una redaccion chica todavia puede llegar primero:
3 o mas medios, pero el tema no explotó. Son entre 2 y 8 hechos por corrida, no
los ~100 del total, asi que se puede consultar POR HECHO en vez de por un panel
grueso de terminos.

Y la senal ahi es predictiva: un hecho con 3 medios Y busquedas subiendo esta por
escalar. Uno con 3 medios y busquedas planas probablemente se quede donde esta.
Eso es justo lo que la velocidad sola no distingue.

En cambio NO se usa para ordenar el tablero: Google Trends refleja las busquedas
con retraso y lo que las hace subir suele ser la propia cobertura mediatica.
Sumarlo al ranking contaminaria una metrica que funciona con una senal
correlacionada. Sirve para DISPARAR ALERTAS, no para rankear.

SEGUNDA FUNCION: ATENCION PUBLICA POR PAIS
------------------------------------------
Terminos amplios ("migrantes", "extranjeros", "remesas") medidos en cada pais.
No miden demanda de tramite: miden cuanto esta la migracion en la cabeza de la
gente. Un pico en Chile significa que algo esta pasando alli aunque no haya
llegado a los medios que monitoreamos.

La geografia va en el parametro `geo`, NO en el termino. Consultar "migrantes"
con geo=AR ES "cuanto buscan los argentinos sobre migrantes"; escribir "migrantes
en argentina" seria una frase sin volumen suficiente para medir.

TERCERA FUNCION: DEMANDA DE SERVICIO
------------------------------------
Un panel fijo de terminos de tramite ("turno migraciones", "residencia precaria")
que no cruza con noticias. Son busquedas de gente resolviendo un problema, no de
gente leyendo. Un pico ahi señala una demora o un cambio de tramite que
probablemente ningun medio cubrio: es la senal mas independiente del sistema.

Salida: datos/tendencias.json

Uso:
    python -m nucleo.tendencias
    python -m nucleo.tendencias --forzar
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.estados import estado, normalizar_ejes  # noqa: E402
from nucleo.registro import cargar  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
ITEMS = RAIZ / "datos" / "items.json"
SALIDA = RAIZ / "datos" / "tendencias.json"

LOTE = 5              # tope de terminos por consulta que admite Google Trends
BIBLIOTECA = "trendspy"   # pytrends esta archivado desde abril de 2025
ESPERA = 3            # segundos entre consultas
FALLOS_SEGUIDOS = 3   # si tantas fallan seguidas, se abandona en vez de gastar minutos
MAX_HECHOS = 15       # tope de seguridad si `interes` creciera mucho

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("tendencias")


def vacio(motivo: str) -> dict:
    """Estructura minima para que el resto del sistema siga funcionando."""
    return {
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disponible": False,
        "motivo": motivo,
        "hechos": {},
        "general": {},
        "servicio": {},
        "alertas": [],
    }


def rotacion(previo: dict | None, geos: list[str], por_corrida: int) -> tuple[list[str], int]:
    """Elige que paises tocan en esta corrida y devuelve el puntero siguiente.

    Consultar los 27 paises de una vez agoto la cuota de Google en el sexto
    pedido (verificado el 2026-08-03). Repartirlos entre las ocho corridas
    diarias mantiene el volumen bajo sin resignar cobertura: cada pais se
    actualiza cada pocas corridas, que para una serie de 90 dias alcanza.
    """
    if not geos:
        return [], 0
    desde = (previo or {}).get("proximo_pais", 0) % len(geos)
    elegidos = [geos[(desde + i) % len(geos)] for i in range(min(por_corrida, len(geos)))]
    return elegidos, (desde + len(elegidos)) % len(geos)


def cache_vigente(horas: int) -> dict | None:
    """Devuelve el panel guardado si todavia es reciente."""
    if not SALIDA.exists():
        return None
    try:
        d = json.loads(SALIDA.read_text(encoding="utf-8"))
        gen = datetime.fromisoformat(d["generado"].replace("Z", "+00:00"))
    except (json.JSONDecodeError, KeyError, ValueError):
        return None
    return d if datetime.now(timezone.utc) - gen < timedelta(hours=horas) else None


def puntuar(serie, umbrales: dict) -> tuple[int, dict]:
    """Convierte una serie temporal en un puntaje 0-10 de cuanto esta subiendo.

    Compara el interes de la ultima semana contra la media del periodo. Un
    termino con interes absoluto bajo se ignora aunque suba mucho: pasar de 2 a 6
    es ruido estadistico, no una senal.
    """
    valores = [v for v in serie if v is not None]
    if len(valores) < 8:
        return 0, {}

    reciente = sum(valores[-7:]) / 7
    base = sum(valores) / len(valores)

    if base <= 0 or reciente < umbrales["interes_minimo"]:
        return 0, {"reciente": round(reciente, 1), "base": round(base, 1), "ratio": None}

    ratio = reciente / base
    lo, hi = umbrales["ratio_minimo"], umbrales["ratio_maximo"]
    if ratio < lo:
        p = 0
    elif ratio >= hi:
        p = 10
    else:
        p = round((ratio - lo) / (hi - lo) * 10)

    return int(p), {"reciente": round(reciente, 1), "base": round(base, 1),
                    "ratio": round(ratio, 2)}


# `related_queries` tiene una cuota mucho mas estricta que `interest_over_time`.
# La propia biblioteca sugiere cambiar el referer del pedido como primer remedio;
# es gratis y no requiere proxy. Se prueban varios en orden.
REFERERS = [
    {"referer": "https://www.google.com/"},
    {"referer": "https://trends.google.com/trends/explore"},
    None,
]


def consultas_relacionadas(cliente, semilla: str, geo: str, ventana: str,
                           tope: int = 6) -> list[dict]:
    """Que se esta buscando SOBRE la semilla en ese pais, ahora.

    Responde algo distinto que interest_over_time: no "cuanto se busca
    `migrantes`" sino "que consultas sobre migrantes estan subiendo". El
    resultado son terminos concretos y del dia, no una lista fija que ya
    sabemos de antemano.

    Prioriza `rising` sobre `top`: lo que sube dice mas que lo mas buscado,
    que suele ser siempre lo mismo.
    """
    r = None
    for cabeceras in REFERERS:
        try:
            r = (cliente.related_queries(semilla, timeframe=ventana, geo=geo,
                                         headers=cabeceras)
                 if cabeceras else
                 cliente.related_queries(semilla, timeframe=ventana, geo=geo))
            break
        except Exception as e:
            nombre = type(e).__name__
            if "Quota" in nombre and cabeceras is not REFERERS[-1]:
                continue          # se reintenta con otro referer
            log.warning("      %s / %s: %s", geo, semilla, nombre)
            return []
    if not isinstance(r, dict):
        return []

    salida = []
    for clave in ("rising", "top"):
        df = r.get(clave)
        if df is None or getattr(df, "empty", True):
            continue
        try:
            cols = list(df.columns)
            c_q = next((c for c in cols if "quer" in str(c).lower()), cols[0])
            c_v = next((c for c in cols if str(c).lower() in ("value", "valor")), cols[-1])
            for _, fila in df.head(tope).iterrows():
                consulta = str(fila[c_q]).strip()
                if consulta and not any(x["consulta"] == consulta for x in salida):
                    salida.append({"consulta": consulta, "valor": str(fila[c_v]),
                                   "tipo": clave})
        except Exception as e:
            log.warning("      %s: no se pudo leer %s (%s)", geo, clave, type(e).__name__)
        if len(salida) >= tope:
            break
    return salida[:tope]


def consultar(cliente, terminos: list[str], geo: str, ventana: str,
              umbrales: dict) -> dict:
    """Consulta un lote de terminos para un pais y los puntua."""
    try:
        df = cliente.interest_over_time(terminos, timeframe=ventana, geo=geo)
    except Exception as e:
        log.warning("      %s / %s: %s: %s", geo, ", ".join(terminos)[:34],
                    type(e).__name__, str(e)[:60])
        return {}
    if df is None or getattr(df, "empty", True):
        return {}

    salida = {}
    for t in terminos:
        # trendspy puede devolver la columna con el termino tal cual o
        # normalizado: se busca sin distinguir mayusculas ni espacios.
        col = next((c for c in df.columns
                    if str(c).strip().lower() == t.strip().lower()), None)
        if col is None:
            continue
        p, d = puntuar(df[col].tolist(), umbrales)
        salida[t] = {"puntaje": p, **d}
    return salida


def hechos_de_interes(limite: int) -> list[dict]:
    """Los hechos en estado `interes` que tienen termino de busqueda asignado."""
    if not ITEMS.exists():
        return []
    datos = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = datos.get("items", [])
    normalizar_ejes(items)

    sel = [i for i in items
           if estado(i) == "interes" and (i.get("termino_busqueda") or "").strip()]
    sel.sort(key=lambda x: -(x.get("importancia") or 0))
    return sel[:limite]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forzar", action="store_true", help="ignora el cache")
    args = ap.parse_args()

    cfg = cargar().get("tendencias", {})
    if not cfg.get("activo"):
        log.info("Tendencias desactivado en fuentes.yaml")
        SALIDA.write_text(json.dumps(vacio("desactivado"), ensure_ascii=False, indent=1),
                          encoding="utf-8")
        return 0

    if not args.forzar:
        previo = cache_vigente(cfg.get("horas_de_cache", 20))
        if previo:
            log.info("Panel en cache, generado %s. Nada que hacer.", previo["generado"])
            return 0

    seleccion = hechos_de_interes(cfg.get("max_hechos", MAX_HECHOS))
    servicio = cfg.get("terminos_servicio", [])

    log.info("Hechos en `interes` con termino de busqueda: %d", len(seleccion))
    for h in seleccion:
        log.info("   [%s] %s", h["termino_busqueda"], h["titulo_original"][:56])

    if not seleccion and not servicio:
        SALIDA.write_text(json.dumps(vacio("nada que consultar"), ensure_ascii=False,
                                     indent=1), encoding="utf-8")
        return 0

    try:
        from trendspy import Trends
        cliente = Trends(hl="es", tz=180, request_delay=2.0)
    except Exception as e:
        log.warning("trendspy no disponible (%s); panel vacio", type(e).__name__)
        SALIDA.write_text(json.dumps(vacio(f"trendspy: {type(e).__name__}"),
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        return 0

    global FALLOS_SEGUIDOS, ESPERA
    FALLOS_SEGUIDOS = cfg.get("fallos_seguidos_antes_de_abandonar", FALLOS_SEGUIDOS)
    ESPERA = cfg.get("espera_entre_consultas", ESPERA)

    ventana = cfg.get("ventana", "today 3-m")
    umbrales = cfg.get("umbrales", {"ratio_minimo": 1.2, "ratio_maximo": 3.0,
                                    "interes_minimo": 15})
    geo_servicio = cfg.get("geo_servicio", "AR")
    seguidos = 0

    # --- Hechos de interes: un termino por hecho, agrupados por pais ---------
    por_geo: dict = {}
    for h in seleccion:
        geo = (h.get("paises") or ["AR"])[0]
        por_geo.setdefault(geo, []).append(h)

    resultados: dict = {}
    for geo, grupo in por_geo.items():
        if seguidos >= FALLOS_SEGUIDOS:
            break
        terminos = [h["termino_busqueda"] for h in grupo]
        for i in range(0, len(terminos), LOTE):
            if seguidos >= FALLOS_SEGUIDOS:
                break
            lote = terminos[i:i + LOTE]
            res = consultar(cliente, lote, geo, ventana, umbrales)
            seguidos = 0 if res else seguidos + 1
            for h in grupo:
                d = res.get(h["termino_busqueda"])
                if d:
                    resultados[h["id"]] = {
                        "termino": h["termino_busqueda"], "geo": geo,
                        "titulo": h["titulo_original"], "importancia": h.get("importancia"),
                        "velocidad": h.get("velocidad"), **d,
                    }
            time.sleep(ESPERA)

    # --- Que lee la audiencia: paises rotando, pocos por corrida ------------
    # No se consultan todos de una vez: eso agoto la cuota de Google. Se rotan
    # dos por corrida y, con ocho corridas diarias, cada pais se actualiza a
    # diario sin concentrar los pedidos.
    semilla = cfg.get("semilla_audiencia", "migrantes")
    geos_aud = cfg.get("geos_audiencia", [])
    por_corrida = cfg.get("paises_por_corrida", 2)
    previo = cache_vigente(24 * 30)          # solo para leer el puntero anterior
    toca, proximo = rotacion(previo, geos_aud, por_corrida)

    # Lo medido en corridas anteriores se conserva: la rotacion actualiza de a
    # poco, no borra lo que ya sabemos.
    atencion: dict = dict((previo or {}).get("audiencia", {}))
    sin_datos: list[str] = []

    if toca and seguidos < FALLOS_SEGUIDOS:
        log.info("")
        log.info("Audiencia: «%s» en %s  (rotan %d de %d por corrida)",
                 semilla, " ".join(toca), por_corrida, len(geos_aud))
        for geo in toca:
            if seguidos >= FALLOS_SEGUIDOS:
                log.warning("   %d consultas seguidas sin respuesta: se abandona.", seguidos)
                break
            rel = consultas_relacionadas(cliente, semilla, geo, ventana)
            if rel:
                seguidos = 0
                atencion[geo] = {"consultas": rel,
                                 "medido": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                log.info("   %-4s %s", geo, " · ".join(x["consulta"] for x in rel[:3]))
            else:
                seguidos += 1
                sin_datos.append(geo)
                log.info("   %-4s sin datos", geo)
            time.sleep(ESPERA)

    # --- Demanda de servicio: tramites concretos, senal independiente -------
    demanda: dict = dict((previo or {}).get("servicio", {}))
    if seguidos < FALLOS_SEGUIDOS:
        for i in range(0, len(servicio), LOTE):
            res = consultar(cliente, servicio[i:i + LOTE], geo_servicio, ventana, umbrales)
            seguidos = 0 if res else seguidos + 1
            for t, d in res.items():
                if d["puntaje"] > 0:
                    demanda[t] = {"geo": geo_servicio, **d}
            time.sleep(ESPERA)
            if seguidos >= FALLOS_SEGUIDOS:
                break

    # --- Alertas: importante + poco cubierto + busquedas subiendo -----------
    umbral_alerta = cfg.get("umbral_alerta", 5)
    imp_minima = cfg.get("importancia_minima_alerta", 7)
    alertas = [
        d for d in resultados.values()
        if d["puntaje"] >= umbral_alerta and (d.get("importancia") or 0) >= imp_minima
    ]
    alertas.sort(key=lambda x: -x["puntaje"])

    disponible = bool(resultados or demanda or atencion)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps({
        "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "disponible": disponible,
        "motivo": "" if disponible else "sin respuesta de Google Trends",
        "ventana": ventana,
        "hechos": resultados,
        "audiencia": atencion,
        "proximo_pais": proximo,
        "paises_sin_datos": sin_datos,
        "servicio": demanda,
        "alertas": alertas,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    log.info("")
    log.info("Hechos consultados: %d | paises acumulados: %d | servicio en alza: %d",
             len(resultados), len(atencion), len(demanda))
    log.info("Proxima corrida arranca por: %s",
             geos_aud[proximo] if geos_aud else "-")
    log.info("Escrito %s", SALIDA.relative_to(RAIZ))

    if alertas:
        log.info("")
        log.info("ALERTA EDITORIAL: importante, poco cubierto y con busquedas en alza")
        for a in alertas:
            log.info("   x%.2f  imp %s  %d medios  |  %s",
                     a.get("ratio") or 0, a.get("importancia"), a.get("velocidad") or 0,
                     a["titulo"][:58])
    if atencion:
        log.info("")
        log.info("QUE LEE LA AUDIENCIA, POR PAIS (acumulado de varias corridas):")
        for geo, d in atencion.items():
            log.info("   %-4s %s", geo,
                     " · ".join(x["consulta"] for x in d["consultas"][:4]))

    if demanda:
        log.info("")
        log.info("DEMANDA DE SERVICIO EN ALZA (gente buscando, prensa todavia no):")
        for t, d in demanda.items():
            log.info("   %-28s %s  interes %.0f contra base %.0f",
                     t, d["geo"], d["reciente"], d["base"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
