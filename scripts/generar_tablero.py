"""Genera el tablero HTML que GitHub Pages publica.

Lee datos/items.json y escribe docs/index.html con los datos incrustados.
Sin dependencias de red ni build: un unico archivo que se abre y funciona.

Si datos/items.json no existe todavia, usa datos de ejemplo y lo avisa en el
tablero con un cartel visible. Eso permite disenar y revisar la interfaz antes
de que el pipeline de ingesta este escrito.

CONTRATO DE DATOS
-----------------
datos/items.json debe tener esta forma:

    {
      "generado": "2026-07-31T11:00:00Z",
      "items": [
        {
          "id": str,
          "titulo_original": str,      # sin traducir
          "idioma": "es|pt|en",
          "url": str,
          "fuente": str,               # id de fuentes.yaml
          "region": str,
          "fecha": str,                # ISO 8601
          "ejes": [str],
          "paises": [str],             # ISO 2 letras
          "tipo": str,
          "importancia": int,          # 1-10
          "cobertura": int | null,     # 1-10, null si no se pudo medir
          "confianza": float,          # 0-1
          "tiene_fuente_primaria": bool,
          "angulo_sugerido": str | null,
          "nota": str,
          "duplicados": int            # cuantas notas del mismo hecho se agruparon
        }
      ]
    }

Uso:
    python scripts/generar_tablero.py
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "datos" / "items.json"
SALIDA = RAIZ / "docs" / "index.html"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("tablero")

EJEMPLO = {
    "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "items": [
        {"id": "e1", "titulo_original": "El Gobierno prohibira el ingreso y expulsara a extranjeros que expresen mensajes de odio",
         "idioma": "es", "url": "https://example.org/1", "fuente": "gnews_cono_sur_normativa",
         "region": "Cono Sur", "fecha": "2026-07-30T18:00:00Z", "ejes": ["normativa", "derechos"],
         "paises": ["AR"], "tipo": "normativa", "importancia": 10, "cobertura": 9, "confianza": 0.95,
         "tiene_fuente_primaria": True, "angulo_sugerido": "Que organo define que es un mensaje de odio y con que recurso",
         "nota": "DNU que habilita expulsion por expresiones. Muy cubierto: el valor esta en el analisis juridico.",
         "duplicados": 23, "medios": 23, "velocidad": 23, "aceleracion": 11, "trends": 9, "horas": 4},
        {"id": "e2", "titulo_original": "Migrantes en Cordoba se pronunciaron tras el DNU contra extranjeros",
         "idioma": "es", "url": "https://example.org/2", "fuente": "gnews_cono_sur_derechos",
         "region": "Cono Sur", "fecha": "2026-07-30T12:00:00Z", "ejes": ["derechos", "odio"],
         "paises": ["AR"], "tipo": "caso", "importancia": 8, "cobertura": 2, "confianza": 0.85,
         "tiene_fuente_primaria": False, "angulo_sugerido": "Contactar a las organizaciones que convocaron",
         "nota": "Respuesta organizada de las comunidades. Casi sin cobertura nacional.",
         "duplicados": 1, "medios": 1, "velocidad": 1, "aceleracion": 0, "trends": 1, "horas": 14},
        {"id": "e3", "titulo_original": "ICE raid at meatpacking plant detains 200",
         "idioma": "en", "url": "https://example.org/3", "fuente": "gnews_eeuu_es_derechos",
         "region": "Estados Unidos", "fecha": "2026-07-29T20:00:00Z", "ejes": ["derechos"],
         "paises": ["US"], "tipo": "caso", "importancia": 9, "cobertura": 6, "confianza": 0.9,
         "tiene_fuente_primaria": False, "angulo_sugerido": "Cuantos detenidos tenian proceso de asilo abierto",
         "nota": "Detencion masiva que afecta debido proceso.", "duplicados": 7, "medios": 7, "velocidad": 7, "aceleracion": 5, "trends": 4, "horas": 9},
        {"id": "e4", "titulo_original": "Republica Dominicana amplia el operativo de deportaciones en la frontera",
         "idioma": "es", "url": "https://example.org/4", "fuente": "gnews_caribe_derechos",
         "region": "Caribe", "fecha": "2026-07-29T09:00:00Z", "ejes": ["derechos", "normativa"],
         "paises": ["DO", "HT"], "tipo": "evento", "importancia": 9, "cobertura": 1, "confianza": 0.8,
         "tiene_fuente_primaria": False, "angulo_sugerido": "Cifras oficiales versus registros de organizaciones haitianas",
         "nota": "Alta importancia y practicamente sin cobertura regional. Prioridad editorial.",
         "duplicados": 2, "medios": 2, "velocidad": 2, "aceleracion": 1, "trends": 0, "horas": 30},
    ],
}


def frescura(horas: float | None) -> float:
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


def estado(item: dict) -> str:
    """Ubica un hecho en su ciclo de vida segun cuantos medios lo publicaron.

    La aceleracion puede promover de estado: cinco medios subiendo de a cuatro
    cada tres horas vale mas que ocho estancados. Sin eso, un tema que arranca
    fuerte quedaria clasificado por su numero absoluto y se llegaria tarde.
    """
    vel = item.get("velocidad") or 0
    acel = item.get("aceleracion") or 0
    imp = item.get("importancia") or 0

    if vel >= 20:
        return "top_trend"
    if vel >= 8 or (vel >= 5 and acel >= 4):
        return "trending"
    if vel >= 3 or (vel >= 2 and acel >= 2):
        return "interes"
    return "nadie_lo_mira" if imp >= 7 else "ruido"


def puntaje_alerta(item: dict) -> float:
    """Ranking 'Ahora': que esta creciendo en cobertura en este momento.

    La aceleracion pesa doble a proposito. Un tema que paso de 3 a 15 medios en
    tres horas importa mas que uno estable en 20: al primero todavia se llega.
    """
    imp = item.get("importancia") or 0
    vel = item.get("velocidad") or 0
    acel = max(0, item.get("aceleracion") or 0)
    tr = item.get("trends") or 0
    return round(imp * frescura(item.get("horas")) * (vel + acel * 2 + tr), 1)


def puntaje_subcobertura(item: dict) -> float:
    """Ranking 'Nadie lo mira': alta importancia con poca cobertura.

    Es el diferencial frente a un medio grande: en velocidad pura, una redaccion
    de 470 periodistas gana siempre.
    """
    imp = item.get("importancia") or 0
    vel = item.get("velocidad") or 0
    return round(imp + (10 - min(vel, 10)) * 0.4, 1)


def cargar() -> tuple[dict, bool]:
    """Devuelve los datos y si son de ejemplo."""
    if not ENTRADA.exists():
        log.info("No existe %s. Usando datos de ejemplo.", ENTRADA.relative_to(RAIZ))
        return EJEMPLO, True
    datos = json.loads(ENTRADA.read_text(encoding="utf-8"))
    log.info("Cargados %d items de %s", len(datos.get("items", [])), ENTRADA.name)
    return datos, False


PLANTILLA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Radar migratorio | Refugio Latinoamericano</title>
<style>
:root {
  --tinta: #1a1a1a; --suave: #6b6b6b; --linea: #e2e0da;
  --fondo: #faf9f6; --tarjeta: #fff; --acento: #1d5e4a; --alerta: #9a3412;
}
@media (prefers-color-scheme: dark) {
  :root { --tinta:#e8e6e0; --suave:#9c9a92; --linea:#33322e;
          --fondo:#16150f; --tarjeta:#1e1d18; --acento:#5dcaa5; --alerta:#f0997b; }
}
* { box-sizing: border-box; }
body { margin:0; padding:1.5rem 1rem 4rem; background:var(--fondo); color:var(--tinta);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }
.contenedor { max-width: 860px; margin: 0 auto; }
h1 { font-size:1.4rem; font-weight:600; margin:0 0 .25rem; }
.meta { color:var(--suave); font-size:.85rem; margin-bottom:1.5rem; }
.aviso { background:var(--alerta); color:#fff; padding:.7rem 1rem; border-radius:8px;
  margin-bottom:1.5rem; font-size:.9rem; }
.vistas { display:flex; gap:.5rem; margin-bottom:.75rem; }
.vistas { flex-wrap:wrap; }
.vistas button { font:inherit; font-size:.88rem; font-weight:600; padding:.45rem .9rem;
  cursor:pointer; background:transparent; color:var(--suave); border:none;
  border-bottom:2px solid transparent; }
.vistas button[aria-pressed="true"] { color:var(--acento); border-bottom-color:var(--acento); }
.vistas .cuenta { font-weight:400; opacity:.7; }
.chip { font-size:.7rem; font-weight:600; padding:.15rem .5rem; border-radius:4px;
  text-transform:uppercase; letter-spacing:.03em; }
.e-top_trend { background:#f4c0d1; color:#72243e; }
.e-trending { background:#fac775; color:#633806; }
.e-interes { background:#9fe1cb; color:#085041; }
.e-nadie_lo_mira { background:#b5d4f4; color:#0c447c; }
.e-ruido { background:#d3d1c7; color:#444441; }
.explica { font-size:.82rem; color:var(--suave); margin:0 0 1rem; }
.filtros { display:flex; flex-wrap:wrap; gap:.4rem; margin-bottom:1.25rem; }
.filtros button { font:inherit; font-size:.82rem; padding:.35rem .8rem; cursor:pointer;
  background:var(--tarjeta); color:var(--tinta); border:1px solid var(--linea); border-radius:99px; }
.filtros button[aria-pressed="true"] { background:var(--acento); color:var(--fondo);
  border-color:var(--acento); }
.item { background:var(--tarjeta); border:1px solid var(--linea); border-radius:10px;
  padding:1rem 1.1rem; margin-bottom:.75rem; }
.item h2 { font-size:1rem; font-weight:600; margin:0 0 .5rem; line-height:1.4; }
.item h2 a { color:inherit; text-decoration:none; }
.item h2 a:hover { text-decoration:underline; }
.puntajes { display:flex; gap:1.2rem; flex-wrap:wrap; font-size:.8rem;
  color:var(--suave); margin-bottom:.5rem; }
.puntajes b { color:var(--tinta); font-weight:600; }
.destacado { color:var(--acento); font-weight:600; }
.sube { color:var(--alerta); font-weight:600; }
.etiquetas { display:flex; gap:.35rem; flex-wrap:wrap; margin-bottom:.5rem; }
.etiqueta { font-size:.72rem; padding:.15rem .55rem; border-radius:4px;
  border:1px solid var(--linea); color:var(--suave); }
.nota { font-size:.85rem; color:var(--suave); margin:0; }
.angulo { font-size:.85rem; margin:.5rem 0 0; padding-left:.7rem;
  border-left:2px solid var(--acento); }
.vacio { text-align:center; color:var(--suave); padding:3rem 1rem; }
footer { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--linea);
  color:var(--suave); font-size:.78rem; }
</style>
</head>
<body>
<div class="contenedor">
<h1>Radar migratorio</h1>
<p class="meta">Refugio Latinoamericano &middot; actualizado __GENERADO__</p>
__AVISO__
<div class="vistas" id="vistas"></div>
<p class="explica" id="explica"></p>
<div class="filtros" id="filtros"></div>
<div id="lista"></div>
<footer>
Monitoreo cada 3 horas. La velocidad se mide en medios distintos, no en cantidad de notas.<br>
La aceleracion puede promover de estado: 5 medios subiendo rapido valen mas que 8 estancados.<br>
Este tablero propone. La decision editorial es humana.
</footer>
</div>
<script>
const ITEMS = __ITEMS__;
let ejeActivo = null, regionActiva = null, vista = 'interes';

const ESTADOS = {
  interes:       { nombre: 'De interes',   accion: 'EL PUNTO JUSTO. 3+ medios o acelerando. Publicar temprano: si escala, la nota ya esta.' },
  trending:      { nombre: 'Trending',     accion: '8+ medios, o 5+ creciendo rapido. Publicar ya, o buscar el angulo que nadie tomo.' },
  top_trend:     { nombre: 'Top trend',    accion: '20+ medios. No correrla: cubrir solo con angulo propio o dato nuevo.' },
  nadie_lo_mira: { nombre: 'Nadie lo mira', accion: 'Importante y casi sin cobertura. Investigar: posible primicia. Requiere reporteria propia.' },
  ruido:         { nombre: 'Ruido',        accion: 'Poca cobertura y poca importancia. Visible para auditar que se esta descartando.' }
};
const ORDEN = ['interes', 'trending', 'top_trend', 'nadie_lo_mira', 'ruido'];

function armarVistas() {
  const cont = document.getElementById('vistas');
  ORDEN.forEach(id => {
    const n = ITEMS.filter(i => i.estado === id).length;
    const b = document.createElement('button');
    b.innerHTML = `${ESTADOS[id].nombre} <span class="cuenta">${n}</span>`;
    b.onclick = () => cambiarVista(id);
    b.id = 'v-' + id;
    cont.appendChild(b);
  });
}

function cambiarVista(v) {
  vista = v;
  ORDEN.forEach(id => {
    const b = document.getElementById('v-' + id);
    if (b) b.setAttribute('aria-pressed', String(id === v));
  });
  document.getElementById('explica').textContent = ESTADOS[v].accion;
  dibujar();
}

function armarFiltros() {
  const ejes = [...new Set(ITEMS.flatMap(i => i.ejes))].sort();
  const regiones = [...new Set(ITEMS.map(i => i.region))].sort();
  const cont = document.getElementById('filtros');
  const grupo = (valores, tipo) => valores.map(v => {
    const b = document.createElement('button');
    b.textContent = v;
    b.setAttribute('aria-pressed', 'false');
    b.onclick = () => {
      if (tipo === 'eje') ejeActivo = (ejeActivo === v) ? null : v;
      else regionActiva = (regionActiva === v) ? null : v;
      dibujar();
    };
    b.dataset.tipo = tipo; b.dataset.valor = v;
    return b;
  });
  [...grupo(ejes, 'eje'), ...grupo(regiones, 'region')].forEach(b => cont.appendChild(b));
}

function dibujar() {
  document.querySelectorAll('#filtros button').forEach(b => {
    const act = b.dataset.tipo === 'eje' ? ejeActivo : regionActiva;
    b.setAttribute('aria-pressed', String(b.dataset.valor === act));
  });
  const visibles = ITEMS
    .filter(i => i.estado === vista)
    .filter(i => !ejeActivo || i.ejes.includes(ejeActivo))
    .filter(i => !regionActiva || i.region === regionActiva)
    .sort((a, b) => vista === 'nadie_lo_mira' || vista === 'ruido'
      ? b.subcobertura - a.subcobertura
      : b.alerta - a.alerta);
  const lista = document.getElementById('lista');
  if (!visibles.length) { lista.innerHTML = '<p class="vacio">Sin resultados con estos filtros.</p>'; return; }
  lista.innerHTML = visibles.map(i => `
    <article class="item">
      <h2><a href="${i.url}" target="_blank" rel="noopener">${escapar(i.titulo_original)}</a></h2>
      <div class="puntajes">
        <span class="chip e-${i.estado}">${ESTADOS[i.estado].nombre}</span>
        <span>importancia <b>${i.importancia}</b></span>
        <span>medios <b>${i.velocidad ?? 's/d'}</b></span>
        ${i.aceleracion > 0 ? `<span class="sube">+${i.aceleracion} en 3h</span>` : ''}
        ${i.horas != null ? `<span>hace ${i.horas}h</span>` : ''}
        ${i.tiene_fuente_primaria ? '<span>fuente primaria</span>' : ''}
      </div>
      <div class="etiquetas">
        ${i.ejes.map(e => `<span class="etiqueta">${e}</span>`).join('')}
        ${i.paises.map(p => `<span class="etiqueta">${p}</span>`).join('')}
        <span class="etiqueta">${i.idioma}</span>
      </div>
      <p class="nota">${escapar(i.nota || '')}</p>
      ${i.angulo_sugerido ? `<p class="angulo">${escapar(i.angulo_sugerido)}</p>` : ''}
    </article>`).join('');
}

function escapar(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

armarVistas();
armarFiltros();
cambiarVista('interes');
</script>
</body>
</html>
"""


def main() -> int:
    datos, es_ejemplo = cargar()

    items = datos.get("items", [])
    for i in items:
        i["alerta"] = puntaje_alerta(i)
        i["subcobertura"] = puntaje_subcobertura(i)
        i["estado"] = estado(i)

    aviso = ""
    if es_ejemplo:
        aviso = ('<p class="aviso">Datos de ejemplo. El pipeline de ingesta todavia no '
                 'esta implementado, asi que estos items son ficticios y sirven solo para '
                 'revisar el diseno del tablero.</p>')

    generado = datos.get("generado", "")
    try:
        generado = datetime.fromisoformat(generado.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M UTC")
    except ValueError:
        pass

    html = (PLANTILLA
            .replace("__GENERADO__", generado)
            .replace("__AVISO__", aviso)
            .replace("__ITEMS__", json.dumps(items, ensure_ascii=False)))

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(html, encoding="utf-8")
    log.info("Escrito %s (%d items, %d KB)", SALIDA.relative_to(RAIZ), len(items), len(html) // 1024)
    return 0


if __name__ == "__main__":
    sys.exit(main())
