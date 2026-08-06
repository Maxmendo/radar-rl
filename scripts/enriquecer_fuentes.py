"""Baja el texto de las fuentes para los hechos que califican para borrador.

Corre DESPUES de clasificar (necesita `importancia`) y ANTES de generar el
tablero. Para cada hecho que cumple los minimos de borrador, resuelve las URLs
de Google News de sus 3 fuentes principales y guarda el texto en la cobertura,
para que el Worker redacte con contenido real y no con el titular.

Es deliberadamente acotado: solo toca los hechos que YA muestran el boton de
borrador (pocos por corrida), no las ~280 notas. Nunca falla la corrida: si una
fuente no se puede bajar, queda con texto vacio y se sigue.

Uso:
    python scripts/enriquecer_fuentes.py
"""

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.textos import enriquecer_fuentes  # noqa: E402

try:
    import yaml
except ImportError:
    yaml = None

RAIZ = Path(__file__).resolve().parent.parent
ITEMS = RAIZ / "datos" / "items.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("enriquecer")


def _jerarquia(medio: str) -> int:
    """Mismo orden que el tablero: agencias 0, legacy 1, resto 2."""
    n = (medio or "").lower()
    agencias = ("efe", "reuters", "afp", "associated press", "europa press",
                "télam", "telam", "ansa", "dpa", "notimex", "bloomberg", "xinhua")
    legacy = ("la nación", "la nacion", "clarín", "clarin", "infobae", "página 12",
              "pagina 12", "el país", "el pais", "el mundo", "el observador",
              "la vanguardia", "abc", "el cronista", "ámbito", "ambito", "perfil",
              "el universal", "el tiempo", "el espectador", "el comercio", "milenio",
              "proceso", "la tercera", "la república", "la republica", "el nacional",
              "semana", "el heraldo", "la prensa", "o globo", "folha", "bbc", "cnn",
              "univision", "telemundo", "france 24", "telesur", "euronews")
    if any(a in n for a in agencias):
        return 0
    if any(a in n for a in legacy):
        return 1
    return 2


def _califica(hecho: dict, vel_min: int, imp_min: int) -> bool:
    return bool(
        hecho.get("clasificado") and hecho.get("es_migratorio") is not False
        and not hecho.get("fuera_de_alcance")
        and (hecho.get("velocidad") or 0) >= vel_min
        and (hecho.get("importancia") or 0) >= imp_min)


def main() -> int:
    if not ITEMS.exists():
        log.error("No existe %s. Correr antes la ingesta y el clasificador.", ITEMS)
        return 1

    vel_min, imp_min = 3, 7
    if yaml:
        try:
            cfg = yaml.safe_load((RAIZ / "fuentes.yaml").read_text(encoding="utf-8"))
            b = cfg.get("borrador", {})
            vel_min = b.get("medios_minimos", 3)
            imp_min = b.get("importancia_minima", 7)
        except Exception:
            pass

    datos = json.loads(ITEMS.read_text(encoding="utf-8"))
    items = datos.get("items", [])
    por_id = {h.get("id"): h for h in items}

    # Candidatos por importancia/velocidad (los que muestran el boton en el listado).
    candidatos = [h for h in items if _califica(h, vel_min, imp_min)]
    ids = {h.get("id") for h in candidatos}

    # Sumar los hechos que estan en ALERTA editorial: tambien muestran boton de
    # borrador, pero se eligen por otra logica (busquedas subiendo) y su id puede
    # no calificar por importancia/velocidad. Sin esto, el borrador de una alerta
    # daba "No se encontro el hecho" porque su texto no se habia bajado.
    tend = RAIZ / "datos" / "tendencias.json"
    if tend.exists():
        try:
            alertas = json.loads(tend.read_text(encoding="utf-8")).get("alertas", [])
            for a in alertas:
                idh = a.get("id_hecho")
                if idh and idh in por_id and idh not in ids:
                    candidatos.append(por_id[idh])
                    ids.add(idh)
        except Exception:
            pass

    log.info("Hechos a enriquecer (califican + en alerta): %d de %d",
             len(candidatos), len(items))

    total_ok = 0
    for h in candidatos:
        cob = h.get("coberturas", [])
        # Ordenar por jerarquia de medio (agencias y legacy primero), estable.
        ordenadas = sorted(enumerate(cob),
                           key=lambda t: (_jerarquia(t[1].get("medio", "")), t[0]))
        ordenadas = [c for _, c in ordenadas]

        fuentes = enriquecer_fuentes(ordenadas, tope=3, espera=1.0)
        h["fuentes_texto"] = fuentes
        ok = sum(1 for f in fuentes if f.get("ok"))
        total_ok += ok
        estado = "  ".join(
            f"{f['medio'][:18]}:{'OK' if f.get('ok') else 'sin texto'}" for f in fuentes)
        log.info("   [%s medios, imp %s] %s", h.get("velocidad"), h.get("importancia"),
                 h.get("titulo_original", "")[:44])
        log.info("      %s", estado or "(sin fuentes con URL)")

    datos["items"] = items
    ITEMS.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    log.info("")
    log.info("Fuentes con texto bajado: %d (de %d hechos candidatos)",
             total_ok, len(candidatos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
