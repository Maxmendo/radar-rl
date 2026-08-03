"""Abre un issue en el repositorio cuando se dispara una alerta editorial.

POR QUE UN ISSUE Y NO OTRA COSA
-------------------------------
La alerta vive en el tablero, pero si nadie entra no se entera nadie. Un issue de
GitHub notifica por mail y por push a la app del celular, sin credenciales
externas, sin costo y sin sumar infraestructura. Ademas queda registro: cada
alerta es un issue con fecha, que se cierra cuando se cubrio o se descarto.

A QUIEN LE LLEGA
----------------
A quienes esten como colaboradores del repositorio Y tengan las notificaciones
activadas. Para sumar a alguien: Settings > Collaborators > Add people. Si el
equipo crece o no todos quieren cuenta de GitHub, conviene evaluar un envio por
mail directo, pero eso requiere credenciales de un servicio de correo.

Se puede mencionar gente en el cuerpo del issue con @usuario para que reciba
notificacion aunque no siga el repositorio: se configura en fuentes.yaml,
`alertas_mencionar`.

Requiere GH_TOKEN (el GITHUB_TOKEN que provee Actions alcanza) y permiso
`issues: write` en el workflow.

Uso:
    python -m nucleo.alertar
    python -m nucleo.alertar --simular    # muestra que abriria, sin abrir nada
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.registro import cargar  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
TENDENCIAS = RAIZ / "datos" / "tendencias.json"
ITEMS = RAIZ / "datos" / "items.json"
REGISTRO = RAIZ / "datos" / "alertados.json"

API = "https://api.github.com"
TIMEOUT = 30

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("alertar")


def ya_alertados() -> dict:
    """Hechos que ya generaron un issue. Evita repetir la misma alerta."""
    if not REGISTRO.exists():
        return {}
    try:
        return json.loads(REGISTRO.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def cuerpo(alerta: dict, hecho: dict | None, mencionar: list[str]) -> str:
    """Arma el texto del issue. Todo lo necesario para decidir sin abrir el tablero."""
    l = []
    if mencionar:
        l.append(" ".join(f"@{u}" for u in mencionar))
        l.append("")

    l.append(f"**{alerta['titulo']}**")
    l.append("")
    l.append("| | |")
    l.append("|---|---|")
    l.append(f"| Importancia editorial | **{alerta.get('importancia', '?')}/10** |")
    l.append(f"| Medios que lo publicaron | {alerta.get('velocidad', '?')} |")
    l.append(f"| Búsquedas en Google | «{alerta['termino']}» ×{alerta.get('ratio', '?')} "
             f"en {alerta['geo']} |")

    if hecho:
        if hecho.get("horas") is not None:
            l.append(f"| Antigüedad | {round(hecho['horas'])} h |")
        if hecho.get("ejes"):
            l.append(f"| Ejes | {', '.join(hecho['ejes'])} |")
        if hecho.get("paises_nombres") or hecho.get("paises"):
            l.append(f"| Dónde | {', '.join(hecho.get('paises_nombres') or hecho['paises'])} |")
    l.append("")

    if hecho and hecho.get("angulo_sugerido"):
        l.append(f"> **Ángulo sugerido:** {hecho['angulo_sugerido']}")
        l.append("")

    if hecho and hecho.get("coberturas"):
        l.append("**Publicado por**")
        l.append("")
        for c in hecho["coberturas"][:12]:
            l.append(f"- [{c['medio']}]({c['url']})")
        l.append("")

    if hecho and hecho.get("terminologia_problematica"):
        l.append(f"⚠️ Lenguaje a revisar en la cobertura: "
                 f"{', '.join(hecho['terminologia_problematica'])}")
        l.append("")
    if hecho and hecho.get("requiere_verificacion"):
        l.append("⚠️ El titular afirma cifras o hechos sin citar fuente.")
        l.append("")

    l.append("---")
    l.append("")
    l.append("Por qué llega esta alerta: el hecho tiene importancia editorial alta, "
             "todavía pocos medios cubriéndolo, y las búsquedas en Google están "
             "subiendo. Está por escalar: si se publica ahora, se llega primero.")
    l.append("")
    l.append("*Cerrar este issue cuando se cubrió o se descartó.*")
    return "\n".join(l)


def abrir_issue(repo: str, token: str, titulo: str, texto: str,
                etiquetas: list[str]) -> str | None:
    """Crea el issue y devuelve su URL, o None si fallo."""
    try:
        r = requests.post(
            f"{API}/repos/{repo}/issues",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"title": titulo, "body": texto, "labels": etiquetas},
            timeout=TIMEOUT)
    except requests.RequestException as e:
        log.warning("   error de red: %s", type(e).__name__)
        return None

    if r.status_code == 201:
        return r.json().get("html_url")
    log.warning("   HTTP %s: %s", r.status_code, r.text[:200])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", action="store_true",
                    help="muestra que issues abriria, sin abrirlos")
    args = ap.parse_args()

    if not TENDENCIAS.exists():
        log.info("No hay datos de tendencias. Nada que alertar.")
        return 0

    try:
        panel = json.loads(TENDENCIAS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("tendencias.json ilegible.")
        return 0

    alertas = panel.get("alertas", [])
    if not alertas:
        log.info("Sin alertas en esta corrida.")
        return 0

    hechos = {}
    if ITEMS.exists():
        try:
            hechos = {h["id"]: h
                      for h in json.loads(ITEMS.read_text(encoding="utf-8")).get("items", [])}
        except json.JSONDecodeError:
            pass

    cfg = cargar().get("tendencias", {})
    mencionar = cfg.get("alertas_mencionar", [])
    tope = cfg.get("max_alertas_por_corrida", 3)

    previos = ya_alertados()
    # Solo las que nunca se avisaron: una alerta persiste 12 horas en el tablero,
    # pero el mail se manda una sola vez.
    nuevas = [a for a in alertas if a["id_hecho"] not in previos][:tope]

    log.info("Alertas en el panel: %d | ya avisadas: %d | a avisar ahora: %d",
             len(alertas), len(alertas) - len(nuevas), len(nuevas))

    if not nuevas:
        return 0

    if args.simular:
        for a in nuevas:
            log.info("\n%s", "=" * 62)
            log.info("TITULO: Alerta editorial: %s", a["titulo"][:60])
            log.info("%s", cuerpo(a, hechos.get(a["id_hecho"]), mencionar))
        return 0

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        log.error("Faltan GH_TOKEN o GITHUB_REPOSITORY. Solo funciona dentro de Actions.")
        log.error("Para probar localmente: python -m nucleo.alertar --simular")
        return 0

    abiertos = 0
    for a in nuevas:
        titulo = f"Alerta editorial: {a['titulo'][:80]}"
        url = abrir_issue(repo, token, titulo,
                          cuerpo(a, hechos.get(a["id_hecho"]), mencionar),
                          ["alerta-editorial"])
        if url:
            previos[a["id_hecho"]] = {
                "titulo": a["titulo"], "issue": url,
                "avisada": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            abiertos += 1
            log.info("   abierto: %s", url)

    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(previos, ensure_ascii=False, indent=1), encoding="utf-8")

    log.info("")
    log.info("Issues abiertos: %d", abiertos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
