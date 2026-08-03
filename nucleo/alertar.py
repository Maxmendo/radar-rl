"""Abre un issue en el repositorio cuando se dispara una alerta editorial.

COMO LLEGA
----------
Por CORREO, a la lista de fuentes.yaml > correo > alertas. No requiere que los
destinatarios tengan cuenta de nada.

Opcionalmente tambien puede abrir un issue en el repositorio, pero eso queda
desactivado por defecto: los issues solo notifican a colaboradores, y eso exige
cuenta de GitHub a cada persona del equipo. Se activa con
fuentes.yaml > tendencias > alertas_por_issue.

Cada alerta se avisa UNA sola vez, aunque persista 12 horas en el tablero. El
registro esta en datos/alertados.json

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
from nucleo.correo import enviar, envoltura, hay_credenciales  # noqa: E402
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


def html_alerta(alerta: dict, hecho: dict | None) -> str:
    """Version en HTML del aviso, para el correo."""
    c = []
    url = alerta.get("url") or (hecho or {}).get("url") or ""
    titulo = alerta["titulo"]
    c.append(f"<h2>{f'<a href=\'{url}\'>{titulo}</a>' if url else titulo}</h2>")

    c.append("<table>")
    c.append(f"<tr><td>Importancia editorial</td>"
             f"<td class='v'>{alerta.get('importancia','?')}/10</td></tr>")
    c.append(f"<tr><td>Medios que lo publicaron</td>"
             f"<td class='v'>{alerta.get('velocidad','?')}</td></tr>")
    c.append(f"<tr><td>Búsquedas en Google</td>"
             f"<td class='v'>«{alerta['termino']}» ×{alerta.get('ratio','?')} "
             f"en {alerta['geo']}</td></tr>")
    if hecho and hecho.get("horas") is not None:
        c.append(f"<tr><td>Antigüedad</td>"
                 f"<td class='v'>{round(hecho['horas'])} h</td></tr>")
    if hecho and hecho.get("ejes"):
        c.append(f"<tr><td>Ejes</td><td class='v'>{', '.join(hecho['ejes'])}</td></tr>")
    c.append("</table>")

    if hecho and hecho.get("angulo_sugerido"):
        c.append(f"<p class='angulo'><b>Ángulo sugerido:</b> {hecho['angulo_sugerido']}</p>")

    if hecho and hecho.get("coberturas"):
        enlaces = " · ".join(f"<a href='{x['url']}'>{x['medio']}</a>"
                             for x in hecho["coberturas"][:10])
        c.append(f"<p class='medios'><b>Publicado por</b><br>{enlaces}</p>")

    avisos = []
    if hecho and hecho.get("terminologia_problematica"):
        avisos.append("Lenguaje a revisar en la cobertura: "
                      + ", ".join(hecho["terminologia_problematica"]))
    if hecho and hecho.get("requiere_verificacion"):
        avisos.append("El titular afirma cifras o hechos sin citar fuente.")
    if avisos:
        c.append("<div class='aviso'>" + "<br>".join(avisos) + "</div>")

    return "".join(c)


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

    correo_cfg = cargar().get("correo", {})
    destinatarios = correo_cfg.get("alertas", []) if correo_cfg.get("activo") else []

    if args.simular:
        log.info("Se enviaria a: %s", ", ".join(destinatarios) or "(nadie)")
        for a in nuevas:
            log.info("\n%s", "=" * 62)
            log.info("ASUNTO: Alerta editorial: %s", a["titulo"][:60])
            log.info("%s", cuerpo(a, hechos.get(a["id_hecho"]), mencionar))
        return 0

    # --- Correo: la via principal ------------------------------------------
    enviados = 0
    if destinatarios and hay_credenciales():
        for a in nuevas:
            h = hechos.get(a["id_hecho"])
            asunto = f"Alerta editorial: {a['titulo'][:70]}"
            plano = cuerpo(a, h, [])
            pie = ("Esta alerta llega porque el hecho tiene importancia editorial alta, "
                   "todavía pocos medios cubriéndolo, y las búsquedas en Google están "
                   "subiendo. Está por escalar: si se publica ahora, se llega primero."
                   "<br><br>Radar Migratorio · Una herramienta de Refugio Latinoamericano")
            html = envoltura("Alerta editorial",
                             "Importante, poco cubierto y con las búsquedas subiendo",
                             html_alerta(a, h), pie)
            log.info("Enviando: %s", a["titulo"][:56])
            if enviar(destinatarios, asunto, plano, html):
                enviados += 1
    elif destinatarios:
        log.warning("Hay destinatarios pero faltan las credenciales de correo.")
        log.warning("Cargar CORREO_USUARIO y CORREO_CLAVE como secretos del repositorio.")

    # --- Issue: respaldo opcional, desactivado por defecto ------------------
    abiertos = 0
    por_issue = cargar().get("tendencias", {}).get("alertas_por_issue", False)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")

    for a in (nuevas if por_issue and token and repo else []):
        titulo = f"Alerta editorial: {a['titulo'][:80]}"
        url = abrir_issue(repo, token, titulo,
                          cuerpo(a, hechos.get(a["id_hecho"]), mencionar),
                          ["alerta-editorial"])
        if url:
            abiertos += 1
            log.info("   issue: %s", url)

    # Se registran como avisadas aunque el envio haya fallado: reintentar cada
    # tres horas convertiria un problema de credenciales en una avalancha de
    # correos el dia que se arregle.
    ahora_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for a in nuevas:
        previos[a["id_hecho"]] = {"titulo": a["titulo"], "avisada": ahora_iso}

    REGISTRO.parent.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text(json.dumps(previos, ensure_ascii=False, indent=1), encoding="utf-8")

    log.info("")
    log.info("Correos enviados: %d | issues abiertos: %d", enviados, abiertos)
    return 0


if __name__ == "__main__":
    sys.exit(main())
