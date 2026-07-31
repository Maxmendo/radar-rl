"""Genera docs/index.html: el tablero que lee la redaccion.

Un unico archivo HTML con los datos incrustados. Sin servidor, sin conexion,
sin dependencias: se abre con doble clic y se puede mandar por mail o WhatsApp
a alguien que no sepa que es GitHub.

Lee datos/items.json, que produce nucleo/ingesta.py

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


def estado(item: dict) -> str:
    """Ubica un hecho en su ciclo de vida segun cuantos medios lo publicaron.

    La aceleracion puede promover de estado: cinco medios subiendo de a cuatro
    cada tres horas valen mas que ocho estancados. Sin clasificacion por LLM
    todavia no hay importancia, asi que `nadie_lo_mira` y `ruido` no se pueden
    separar: todo lo de baja cobertura va a `emergente`.
    """
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
    """Orden dentro de cada estado. Sin importancia, manda velocidad y frescura."""
    imp = item.get("importancia") or 5
    vel = item.get("velocidad") or 0
    acel = max(0, item.get("aceleracion") or 0)
    return round(imp * frescura(item.get("horas")) * (vel + acel * 2), 1)


PLANTILLA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Radar migratorio | Refugio Latinoamericano</title>
<style>
:root { --tinta:#1a1a1a; --suave:#6b6b6b; --tenue:#9a9890; --linea:#e4e2db;
  --fondo:#faf9f6; --tarjeta:#fff; --acento:#1d5e4a; --alerta:#9a3412; }
@media (prefers-color-scheme: dark) {
  :root { --tinta:#e8e6e0; --suave:#9c9a92; --tenue:#6f6e68; --linea:#33322e;
    --fondo:#16150f; --tarjeta:#1e1d18; --acento:#5dcaa5; --alerta:#f0997b; } }
* { box-sizing:border-box; }
body { margin:0; padding:1.5rem 1rem 4rem; background:var(--fondo); color:var(--tinta);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif; }
.c { max-width:880px; margin:0 auto; }
h1 { font-size:1.35rem; font-weight:600; margin:0 0 .2rem; }
.meta { color:var(--suave); font-size:.84rem; margin:0 0 1.2rem; }
.aviso { background:var(--tarjeta); border-left:3px solid var(--alerta); padding:.7rem .9rem;
  margin-bottom:1.3rem; font-size:.85rem; color:var(--suave); }
.vistas { display:flex; flex-wrap:wrap; gap:.3rem; margin-bottom:.6rem;
  border-bottom:1px solid var(--linea); }
.vistas button { font:inherit; font-size:.87rem; font-weight:600; padding:.5rem .85rem;
  cursor:pointer; background:transparent; color:var(--suave); border:none;
  border-bottom:2px solid transparent; margin-bottom:-1px; }
.vistas button[aria-pressed="true"] { color:var(--acento); border-bottom-color:var(--acento); }
.vistas .n { font-weight:400; opacity:.65; }
.explica { font-size:.83rem; color:var(--suave); margin:.7rem 0 1rem; }
.filtros { display:flex; flex-wrap:wrap; gap:.35rem; margin-bottom:1.2rem; }
.filtros button { font:inherit; font-size:.78rem; padding:.3rem .7rem; cursor:pointer;
  background:var(--tarjeta); color:var(--suave); border:1px solid var(--linea);
  border-radius:99px; }
.filtros button[aria-pressed="true"] { background:var(--acento); color:var(--fondo);
  border-color:var(--acento); }
.item { background:var(--tarjeta); border:1px solid var(--linea); border-radius:10px;
  padding:.95rem 1.05rem; margin-bottom:.7rem; }
.item h2 { font-size:1rem; font-weight:600; margin:0 0 .45rem; line-height:1.42; }
.item h2 a { color:inherit; text-decoration:none; }
.item h2 a:hover { text-decoration:underline; }
.datos { display:flex; gap:1rem; flex-wrap:wrap; font-size:.79rem; color:var(--suave);
  margin-bottom:.4rem; }
.datos b { color:var(--tinta); font-weight:600; }
.medios { font-size:.76rem; color:var(--tenue); margin:.35rem 0 0; line-height:1.5; }
.etiquetas { display:flex; gap:.3rem; flex-wrap:wrap; margin-top:.5rem; }
.et { font-size:.7rem; padding:.12rem .5rem; border-radius:4px; border:1px solid var(--linea);
  color:var(--suave); }
.vacio { text-align:center; color:var(--suave); padding:2.5rem 1rem; }
footer { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--linea);
  color:var(--suave); font-size:.77rem; line-height:1.7; }
</style>
</head>
<body>
<div class="c">
<h1>Radar migratorio</h1>
<p class="meta">Refugio Latinoamericano &middot; __GENERADO__ &middot; __RESUMEN__</p>
__AVISO__
<div class="vistas" id="vistas"></div>
<p class="explica" id="explica"></p>
<div class="filtros" id="filtros"></div>
<div id="lista"></div>
<footer>
<b>Cómo leerlo.</b> Cada fila es un <i>hecho</i>, no una nota: si veinte medios publican
sobre el mismo decreto, es un hecho con veinte medios. La cantidad de medios distintos
es la <i>velocidad</i>, y es lo que define en qué estado está.<br>
El radar propone. La decisión editorial es humana.
</footer>
</div>
<script>
const ITEMS = __ITEMS__;
let vista = null, ejeActivo = null, regionActiva = null;

const ESTADOS = {
  interes:   { n:'De interés',   d:'3 o más medios. EL PUNTO JUSTO: todavía se llega temprano. Si escala, la nota ya está publicada.' },
  trending:  { n:'Trending',     d:'8 o más medios. Publicar ya, o buscar el ángulo que nadie tomó.' },
  top_trend: { n:'Top trend',    d:'20 o más medios. No correrla: cubrir solo con ángulo propio o dato nuevo.' },
  emergente: { n:'Emergente',    d:'1 o 2 medios. Puede ser una primicia o puede ser irrelevante: sin clasificación todavía no se distingue. Es donde hay que mirar a mano.' },
  nadie_lo_mira:{ n:'Nadie lo mira', d:'Importante y casi sin cobertura. Investigar: posible primicia.' },
  ruido:     { n:'Ruido',        d:'Poca cobertura y poca importancia. Visible para auditar el descarte.' }
};
const ORDEN = ['top_trend','trending','interes','emergente','nadie_lo_mira','ruido'];

function esc(s){ const d=document.createElement('div'); d.textContent=s||''; return d.innerHTML; }

function armarVistas(){
  const cont = document.getElementById('vistas');
  ORDEN.forEach(id => {
    const n = ITEMS.filter(i => i.estado===id).length;
    if (!n) return;
    if (!vista) vista = id;
    const b = document.createElement('button');
    b.innerHTML = ESTADOS[id].n + ' <span class="n">' + n + '</span>';
    b.id = 'v-'+id;
    b.onclick = () => cambiar(id);
    cont.appendChild(b);
  });
}

function armarFiltros(){
  const cont = document.getElementById('filtros');
  const ejes = [...new Set(ITEMS.flatMap(i => i.ejes||[]))].sort();
  const regs = [...new Set(ITEMS.map(i => i.region).filter(Boolean))].sort();
  const grupo = (vals, tipo) => vals.forEach(v => {
    const b = document.createElement('button');
    b.textContent = v;
    b.dataset.tipo = tipo; b.dataset.valor = v;
    b.setAttribute('aria-pressed','false');
    b.onclick = () => {
      if (tipo==='eje') ejeActivo = ejeActivo===v ? null : v;
      else regionActiva = regionActiva===v ? null : v;
      dibujar();
    };
    cont.appendChild(b);
  });
  grupo(ejes,'eje'); grupo(regs,'region');
}

function cambiar(v){
  vista = v;
  ORDEN.forEach(id => { const b=document.getElementById('v-'+id);
    if (b) b.setAttribute('aria-pressed', String(id===v)); });
  document.getElementById('explica').textContent = ESTADOS[v].d;
  dibujar();
}

function dibujar(){
  document.querySelectorAll('#filtros button').forEach(b => {
    const act = b.dataset.tipo==='eje' ? ejeActivo : regionActiva;
    b.setAttribute('aria-pressed', String(b.dataset.valor===act));
  });
  const vis = ITEMS
    .filter(i => i.estado===vista)
    .filter(i => !ejeActivo || (i.ejes||[]).includes(ejeActivo))
    .filter(i => !regionActiva || i.region===regionActiva)
    .sort((a,b) => b.puntaje - a.puntaje);
  const l = document.getElementById('lista');
  if (!vis.length){ l.innerHTML='<p class="vacio">Sin resultados con estos filtros.</p>'; return; }
  l.innerHTML = vis.map(i => `
    <article class="item">
      <h2><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.titulo_original)}</a></h2>
      <div class="datos">
        <span><b>${i.velocidad}</b> ${i.velocidad===1?'medio':'medios'}</span>
        ${i.notas>1?`<span>${i.notas} notas</span>`:''}
        ${i.horas!=null?`<span>hace ${i.horas<1?'menos de 1 h':Math.round(i.horas)+' h'}</span>`:''}
        ${i.aceleracion>0?`<span style="color:var(--alerta);font-weight:600">+${i.aceleracion} en 3h</span>`:''}
      </div>
      ${i.medios&&i.medios.length?`<p class="medios">${esc(i.medios.slice(0,10).join(' · '))}${i.medios.length>10?' · …':''}</p>`:''}
      <div class="etiquetas">
        ${(i.ejes||[]).map(e=>`<span class="et">${esc(e)}</span>`).join('')}
        ${i.region?`<span class="et">${esc(i.region)}</span>`:''}
        ${(i.paises||[]).slice(0,4).map(p=>`<span class="et">${esc(p)}</span>`).join('')}
      </div>
    </article>`).join('');
}

armarVistas();
armarFiltros();
cambiar(vista || 'emergente');
</script>
</body>
</html>
"""


def main() -> int:
    if not ENTRADA.exists():
        log.error("No existe %s. Correr antes: python -m nucleo.ingesta",
                  ENTRADA.relative_to(RAIZ))
        return 1

    datos = json.loads(ENTRADA.read_text(encoding="utf-8"))
    items = datos.get("items", [])

    for i in items:
        i["estado"] = estado(i)
        i["puntaje"] = puntaje(i)

    generado = datos.get("generado", "")
    try:
        dt = datetime.fromisoformat(generado.replace("Z", "+00:00"))
        local = dt.astimezone(timezone(datetime.now().astimezone().utcoffset() or
                                       -datetime.now().astimezone().utcoffset()))
        generado = dt.strftime("%d/%m/%Y %H:%M UTC")
    except ValueError:
        pass

    resumen = f"{len(items)} hechos de {datos.get('notas_totales', 0)} notas"

    aviso = ""
    if not datos.get("clasificado"):
        aviso = ('<p class="aviso"><b>Clasificación pendiente.</b> Estos son datos reales, '
                 'pero todavía sin análisis por IA: no hay puntaje de importancia ni ejes '
                 'temáticos analizados. El eje que se muestra viene de qué búsqueda trajo la '
                 'nota. La aceleración necesita al menos dos corridas de historial.</p>')

    html = (PLANTILLA
            .replace("__GENERADO__", generado)
            .replace("__RESUMEN__", resumen)
            .replace("__AVISO__", aviso)
            .replace("__ITEMS__", json.dumps(items, ensure_ascii=False)))

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(html, encoding="utf-8")

    from collections import Counter
    c = Counter(i["estado"] for i in items)
    log.info("Escrito %s  (%d hechos, %d KB)", SALIDA.relative_to(RAIZ), len(items), len(html) // 1024)
    for e in ("top_trend", "trending", "interes", "emergente"):
        if c[e]:
            log.info("   %-12s %d", e, c[e])
    return 0


if __name__ == "__main__":
    sys.exit(main())
