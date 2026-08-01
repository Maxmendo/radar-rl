"""Genera docs/index.html: el tablero que lee la redaccion.

Un unico archivo HTML con los datos incrustados. Sin servidor, sin dependencias:
se abre con doble clic y se puede mandar por mail o WhatsApp a alguien que no
sepa que es GitHub.

Identidad visual segun el manual de marca de Refugio Latinoamericano:
  - Rojo principal  #ff5f5d   - Marron oscuro  #554242
  - Secundarios     #806e6e   #a97776   #d47270
  - Tipografia principal Barlow, secundaria Arial (asi lo indica el manual)
  - Elemento grafico: lineas oblicuas del simbolo (arraigo)

Lee datos/items.json, que produce nucleo/ingesta.py

Uso:
    python scripts/generar_tablero.py
"""

import json
import logging
import sys

import yaml
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "datos" / "items.json"
SALIDA = RAIZ / "docs" / "index.html"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("tablero")


def mapa_macroareas() -> dict:
    """Devuelve {macroarea: {"nombre":..., "ejes":[...]}} desde fuentes.yaml."""
    cfg = yaml.safe_load((RAIZ / "fuentes.yaml").read_text(encoding="utf-8"))
    return {mid: {"nombre": m["nombre"], "ejes": m["ejes"]}
            for mid, m in cfg.get("macroareas", {}).items()}


def estado(item: dict) -> str:
    """Ubica un hecho en su ciclo de vida segun cuantos medios lo publicaron.

    Sin clasificacion por LLM no hay importancia, asi que `nadie_lo_mira` y
    `ruido` no se pueden separar: todo lo de baja cobertura va a `emergente`.
    """
    if item.get("fuera_de_alcance"):
        return "fuera_alcance"
    # El clasificador ya evaluo que no trata de personas en movilidad.
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
    """Orden dentro de cada estado.

    Con clasificacion, la importancia editorial pondera. Sin ella, el 5 neutro
    hace que manden velocidad y frescura.
    """
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
<title>Radar Migratorio | Refugio Latinoamericano</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<style>
/* Paleta del manual de marca de Refugio Latinoamericano */
:root{
  --rojo:#ff5f5d; --marron:#554242; --marron-med:#806e6e;
  --rosa:#a97776; --rosa-claro:#d47270;
  /* Semaforo. Codigo de color universal, deliberadamente fuera de la paleta
     de marca: es senaletica funcional, no identidad. Se usa solo en puntos
     de 10px, sin invadir el resto de la interfaz.
       rojo    top trend  -> saturado, ya paso
       amarillo trending  -> instalado, publicar ya
       verde   de interes -> el punto justo, se llega temprano
       celeste emergente  -> sin confirmar, mirar a mano                     */
  --sem-rojo:#d92d20; --sem-amarillo:#e5a000; --sem-verde:#12805c;
  --sem-celeste:#2e90d9;
  --fondo:#fbf9f8; --tarjeta:#fff; --linea:#eae3e1;
  --tinta:#3a2e2e; --suave:#806e6e; --tenue:#a2938f;
}
@media (prefers-color-scheme:dark){
  :root{ --fondo:#211a1a; --tarjeta:#2b2222; --linea:#3d3130;
    --tinta:#f2ebe9; --suave:#bfaeab; --tenue:#8d7a77;
    --sem-rojo:#f97066; --sem-amarillo:#fdb022; --sem-verde:#47cd9a;
    --sem-celeste:#53b1fd; }
}
*{box-sizing:border-box}
body{margin:0;padding:0 0 4rem;background:var(--fondo);color:var(--tinta);
  font-family:'Barlow',Arial,Helvetica,sans-serif;font-size:16px;line-height:1.6;
  -webkit-font-smoothing:antialiased}
.c{max-width:900px;margin:0 auto;padding:0 1.1rem}

/* Cabecera: franja roja con las lineas oblicuas del simbolo (arraigo) */
header{background:var(--rojo);color:#fff;padding:1.9rem 0 1.6rem;margin-bottom:1.6rem;
  position:relative;overflow:hidden}
header .trama{position:absolute;right:-30px;top:0;height:100%;width:210px;opacity:.22}
header h1{font-size:1.75rem;font-weight:800;margin:0;letter-spacing:-.015em;
  position:relative;z-index:1}
header .bajada{font-size:1rem;font-weight:400;margin:.15rem 0 0;opacity:.94;
  position:relative;z-index:1}
header .marca{font-size:.82rem;font-weight:600;margin:.75rem 0 0;opacity:.9;
  position:relative;z-index:1;display:flex;align-items:center;gap:.45rem}
header .marca::before{content:"";width:16px;height:9px;flex:none;
  background:repeating-linear-gradient(105deg,#fff 0 2px,transparent 2px 4px)}
.meta{color:var(--suave);font-size:.82rem;margin:0 0 1rem}

.aviso{background:var(--tarjeta);border-left:3px solid var(--rosa-claro);
  padding:.7rem .95rem;margin-bottom:1.4rem;font-size:.85rem;color:var(--suave);
  border-radius:0 6px 6px 0}
.aviso b{color:var(--tinta)}

/* Semaforo */
.semaforo{display:flex;flex-wrap:wrap;gap:.3rem;margin-bottom:.5rem}
.semaforo button{font:inherit;font-size:.87rem;font-weight:600;padding:.5rem .8rem;
  cursor:pointer;background:transparent;color:var(--suave);border:none;
  border-bottom:2px solid transparent;display:flex;align-items:center;gap:.42rem}
.semaforo button:hover{color:var(--tinta)}
.semaforo button[aria-pressed="true"]{color:var(--tinta)}
.semaforo button[aria-pressed="true"]#v-top_trend{border-bottom-color:var(--sem-rojo)}
.semaforo button[aria-pressed="true"]#v-trending{border-bottom-color:var(--sem-amarillo)}
.semaforo button[aria-pressed="true"]#v-interes{border-bottom-color:var(--sem-verde)}
.semaforo button[aria-pressed="true"]#v-emergente{border-bottom-color:var(--sem-celeste)}
.semaforo button[aria-pressed="true"]#v-nadie_lo_mira{border-bottom-color:var(--sem-verde)}
.semaforo button[aria-pressed="true"]#v-ruido{border-bottom-color:var(--tenue)}
.semaforo button[aria-pressed="true"]#v-fuera_alcance{border-bottom-color:var(--tenue)}
.luz{width:10px;height:10px;border-radius:50%;flex:none}
.l-top_trend{background:var(--sem-rojo)}
.l-trending{background:var(--sem-amarillo)}
.l-interes{background:var(--sem-verde)}
.l-emergente{background:var(--sem-celeste)}
.l-nadie_lo_mira{background:var(--sem-verde)}
.l-ruido{background:var(--tenue)}
.l-fuera_alcance{background:var(--tenue)}
.semaforo .n{font-weight:400;opacity:.62}
.accion{font-size:.85rem;color:var(--suave);margin:.55rem 0 1.1rem;
  padding-left:.7rem;border-left:3px solid var(--linea);transition:border-color .15s}

/* Filtros: colapsados por defecto para que las noticias tengan la portada */
.barra{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin:0 0 1rem}
.abrir{font:inherit;font-size:.8rem;font-weight:600;padding:.34rem .8rem;cursor:pointer;
  background:var(--tarjeta);color:var(--suave);border:1px solid var(--linea);
  border-radius:99px;display:flex;align-items:center;gap:.35rem}
.abrir::after{content:"▾";font-size:.7rem;transition:transform .15s}
.abrir[aria-expanded="true"]{color:var(--rojo);border-color:var(--rosa-claro)}
.abrir[aria-expanded="true"]::after{transform:rotate(180deg)}
.abrir #cuenta:not(:empty){background:var(--rojo);color:#fff;border-radius:99px;
  padding:0 .38rem;font-size:.72rem}
.limpiar{font:inherit;font-size:.78rem;padding:.3rem .7rem;cursor:pointer;
  background:transparent;color:var(--rojo);border:none;text-decoration:underline}
.resultado{font-size:.79rem;color:var(--tenue);margin-left:auto}
.filtros{margin:0 0 1.3rem;padding:.9rem 1rem;background:var(--tarjeta);
  border:1px solid var(--linea);border-radius:9px}
.filtros[hidden]{display:none}
.grupo{display:flex;align-items:baseline;gap:.5rem;flex-wrap:wrap;margin-bottom:.4rem}
.rotulo{font-size:.69rem;text-transform:uppercase;letter-spacing:.06em;
  color:var(--tenue);font-weight:600;min-width:132px;line-height:1.35}
.grupo button{font:inherit;font-size:.78rem;padding:.24rem .68rem;cursor:pointer;
  background:var(--tarjeta);color:var(--suave);border:1px solid var(--linea);
  border-radius:99px}
.grupo button[aria-pressed="true"]{background:var(--rojo);color:#fff;border-color:var(--rojo)}
.nota-filtro{font-size:.74rem;color:var(--tenue);margin:.45rem 0 0;font-style:italic}

.item{background:var(--tarjeta);border:1px solid var(--linea);border-radius:9px;
  padding:1rem 1.1rem;margin-bottom:.75rem}
.item h2{font-size:1.03rem;font-weight:600;margin:0 0 .5rem;line-height:1.4}
.item h2 a{color:inherit;text-decoration:none}
.item h2 a:hover{color:var(--rojo)}
.datos{display:flex;gap:.9rem;flex-wrap:wrap;font-size:.79rem;color:var(--suave);
  align-items:center}
.datos .vel{font-weight:700;color:var(--tinta)}
.sube{color:var(--rojo);font-weight:700}

.fuentes{margin:.6rem 0 0;padding:.55rem 0 0;border-top:1px solid var(--linea)}
.fuentes .tit{font-size:.71rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--tenue);font-weight:600;margin-bottom:.3rem}
.fuentes ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.3rem}
.fuentes a{font-size:.77rem;padding:.16rem .55rem;border-radius:4px;
  background:var(--fondo);border:1px solid var(--linea);color:var(--suave);
  text-decoration:none;white-space:nowrap}
.fuentes a:hover{color:var(--rojo);border-color:var(--rosa-claro)}

.etiquetas{display:flex;gap:.28rem;flex-wrap:wrap;margin-top:.55rem}
.et{font-size:.7rem;padding:.1rem .48rem;border-radius:3px;
  border:1px solid var(--linea);color:var(--tenue)}
.et.inferido{border-style:dashed;opacity:.7}
.et.eje{border-color:var(--rosa-claro);color:var(--rosa)}
.et.pobl{background:var(--fondo);border-color:var(--marron-med);color:var(--marron-med)}
.et.actor{border-style:dotted;color:var(--suave)}
.alerta-mini{font-size:.7rem;padding:.05rem .42rem;border-radius:3px;
  background:var(--fondo);border:1px solid var(--sem-amarillo);color:var(--sem-amarillo);
  font-weight:600}
.imp{background:var(--fondo);padding:.05rem .42rem;border-radius:3px;
  border:1px solid var(--linea)}
.imp b{color:var(--rojo)}
.angulo{font-size:.85rem;margin:.5rem 0 0;padding-left:.7rem;
  border-left:2px solid var(--sem-verde);color:var(--tinta)}
.termino{font-size:.78rem;margin:.45rem 0 0;color:var(--sem-rojo)}
.vacio{text-align:center;color:var(--suave);padding:2.5rem 1rem}
footer{margin-top:2.5rem;padding-top:1.1rem;border-top:1px solid var(--linea);
  color:var(--suave);font-size:.78rem;line-height:1.75}
footer b{color:var(--tinta)}
.slogan{color:var(--rojo);font-weight:600;margin-top:.8rem;display:flex;
  align-items:center;gap:.4rem}
.slogan::before{content:"";width:14px;height:8px;flex:none;
  background:repeating-linear-gradient(105deg,var(--rojo) 0 2px,transparent 2px 4px)}
@media(max-width:560px){
  header h1{font-size:1.4rem} .rotulo{min-width:100%}
}
</style>
</head>
<body>
<header>
  <svg class="trama" viewBox="0 0 120 100" preserveAspectRatio="none" aria-hidden="true">
    <g fill="#fff">
      <path d="M14 0h11L11 100H0z"/><path d="M38 0h11L35 100H24z"/>
      <path d="M62 0h11L59 100H48z"/><path d="M86 0h11L83 100H72z"/>
      <path d="M110 0h11L107 100H96z"/>
    </g>
  </svg>
  <div class="c">
    <h1>Radar Migratorio</h1>
    <p class="bajada">Alertas de noticias sobre movilidad humana</p>
    <p class="marca">Una herramienta de Refugio Latinoamericano</p>
  </div>
</header>

<div class="c">
<p class="meta">__GENERADO__ &middot; __RESUMEN__</p>
__AVISO__
<div class="semaforo" id="semaforo"></div>
<p class="accion" id="accion"></p>
<div class="barra">
  <button class="abrir" id="abrir" aria-expanded="false">Filtros <span id="cuenta"></span></button>
  <button class="limpiar" id="limpiar" hidden>Quitar filtros</button>
  <span class="resultado" id="resultado"></span>
</div>
<div class="filtros" id="filtros" hidden></div>
<div id="lista"></div>
<footer>
<b>Cómo leerlo.</b> Cada fila es un <i>hecho</i>, no una nota: si veinte medios publican
sobre el mismo decreto, es un hecho con veinte medios. La cantidad de medios distintos
es la <b>velocidad</b>, y define en qué luz del semáforo está.<br>
Cada medio listado abajo del título es un enlace directo a su publicación, para chequear
cualquiera de las fuentes.<br>
Los países con <span class="et inferido">borde punteado</span> son inferidos de la
búsqueda, no del titular: menos confiables.<br>
El radar propone. La decisión editorial es humana.
<p class="slogan">periodismo sin fronteras</p>
</footer>
</div>

<script>
const ITEMS = __ITEMS__;
const CLASIFICADO = __CLASIFICADO__;
const MACRO = __MACRO__;
let vista=null, ejeActivo=null, regionActiva=null, poblActiva=null, actorActivo=null;

const ESTADOS = {
  trending:{n:'Trending', a:'8 o más medios. Ya está instalado: publicar ahora, o buscar el ángulo que nadie tomó.'},
  interes:{n:'De interés', a:'3 o más medios. EL PUNTO JUSTO: todavía se llega temprano. Si el tema escala, la nota ya está publicada.'},
  top_trend:{n:'Top trend', a:'20 o más medios. Saturado: no correrla. Cubrir solo con ángulo propio o dato nuevo.'},
  emergente:{n:'Emergente', a:'1 o 2 medios. Puede ser una primicia o puede ser irrelevante: sin clasificación todavía no se distingue. Es donde hay que mirar a mano.'},
  nadie_lo_mira:{n:'Posibles alertas', a:'Posible noticia de impacto. Para investigar. Alta importancia editorial y casi sin cobertura: si se confirma, es una primicia.'},
  ruido:{n:'Para auditar', a:'Baja cobertura y baja importancia, o el clasificador determinó que no trata de personas en movilidad. Visible para controlar qué se está descartando.'},
  fuera_alcance:{n:'Noticias extrarregionales', a:'Noticias sobre migración de otros continentes, para contexto comparado. Ceuta, por ejemplo, es el caso testigo de externalización de fronteras.'}
};
const ORDEN=['top_trend','trending','interes','emergente','nadie_lo_mira','ruido','fuera_alcance'];

function esc(s){const d=document.createElement('div');d.textContent=s||'';return d.innerHTML}

function armarSemaforo(){
  const c=document.getElementById('semaforo');
  ORDEN.forEach(id=>{
    const n=ITEMS.filter(i=>i.estado===id).length;
    if(!n) return;
    if(!vista && id!=='fuera_alcance') vista=id;
    const b=document.createElement('button');
    b.innerHTML='<span class="luz l-'+id+'"></span>'+ESTADOS[id].n+' <span class="n">'+n+'</span>';
    b.id='v-'+id; b.onclick=()=>cambiar(id);
    c.appendChild(b);
  });
}

function armarFiltros(){
  const c=document.getElementById('filtros');
  const ejes=[...new Set(ITEMS.flatMap(i=>i.ejes||[]))].sort();
  const pobls=[...new Set(ITEMS.flatMap(i=>i.poblaciones||[]))].sort();
  const ORDEN_REG=['Cono Sur','Region Andina','Brasil','Mexico y Centroamerica',
                   'Caribe','Estados Unidos','Regional','Sin determinar'];
  const regs=[...new Set(ITEMS.map(i=>i.region).filter(Boolean))]
    .sort((a,b)=>ORDEN_REG.indexOf(a)-ORDEN_REG.indexOf(b));
  const grupo=(rotulo,vals,tipo)=>{
    if(!vals.length) return;
    const d=document.createElement('div'); d.className='grupo';
    const r=document.createElement('span'); r.className='rotulo'; r.textContent=rotulo;
    d.appendChild(r);
    vals.forEach(v=>{
      const b=document.createElement('button');
      b.textContent=v; b.dataset.tipo=tipo; b.dataset.valor=v;
      b.setAttribute('aria-pressed','false');
      b.onclick=()=>{
        if(tipo==='eje') ejeActivo=ejeActivo===v?null:v;
        else if(tipo==='pobl') poblActiva=poblActiva===v?null:v;
        else if(tipo==='actor') actorActivo=actorActivo===v?null:v;
        else regionActiva=regionActiva===v?null:v;
        dibujar(); };
      d.appendChild(b);
    });
    c.appendChild(d);
  };
  if(CLASIFICADO){
    // Un grupo por macroarea, solo con los ejes que aparecen en esta corrida.
    Object.values(MACRO).forEach(m=>{
      const presentes=m.ejes.filter(e=>ejes.includes(e));
      if(presentes.length) grupo(m.nombre,presentes,'eje');
    });
    // Ejes que no pertenecen a ninguna macroarea: quedaron de una version
    // anterior del vocabulario. Se muestran aparte para poder detectarlos.
    const sueltos=ejes.filter(e=>!Object.values(MACRO).some(m=>m.ejes.includes(e)));
    if(sueltos.length) grupo('Vocabulario viejo',sueltos,'eje');
    if(pobls.length) grupo('Población',pobls,'pobl');
    const actores=[...new Set(ITEMS.flatMap(i=>i.actores||[]))].sort();
    if(actores.length) grupo('Actor',actores,'actor');
  } else {
    grupo('Tema · provisorio',ejes,'eje');
  }
  grupo('Dónde ocurre',regs,'region');
  const n=document.createElement('p'); n.className='nota-filtro';
  n.innerHTML=(CLASIFICADO
    ?'Los <b>ejes</b> están agrupados por macroárea y los asigna el clasificador leyendo cada titular.<br>'
    :'Los <b>temas</b> son provisorios: indican qué búsqueda trajo la nota, no un análisis de su contenido.<br>')+
    'El <b>dónde</b> sale de los países que menciona el titular. «Regional» es un hecho '+
    'que cruza más de un bloque; «Sin determinar», uno cuyo titular no nombra ningún país.';
  c.appendChild(n);
}

function activos(){
  return [ejeActivo,poblActiva,actorActivo,regionActiva].filter(Boolean).length;
}

function refrescarBarra(n){
  const c=activos();
  document.getElementById('cuenta').textContent=c?c:'';
  document.getElementById('limpiar').hidden=!c;
  document.getElementById('resultado').textContent=
    n===null?'':`${n} ${n===1?'hecho':'hechos'}`;
}

function alternarFiltros(){
  const caja=document.getElementById('filtros'), b=document.getElementById('abrir');
  const abierto=b.getAttribute('aria-expanded')==='true';
  b.setAttribute('aria-expanded',String(!abierto));
  caja.hidden=abierto;
}

function limpiarFiltros(){
  ejeActivo=poblActiva=actorActivo=regionActiva=null;
  dibujar();
}

function cambiar(v){
  vista=v;
  ORDEN.forEach(id=>{const b=document.getElementById('v-'+id);
    if(b) b.setAttribute('aria-pressed',String(id===v))});
  const acc=document.getElementById('accion');
  acc.textContent=ESTADOS[v].a;
  acc.style.borderLeftColor=getComputedStyle(
    document.querySelector('.l-'+v)||document.body).backgroundColor;
  dibujar();
}

function dibujar(){
  document.querySelectorAll('.grupo button').forEach(b=>{
    const T=b.dataset.tipo;
    const act=T==='eje'?ejeActivo:(T==='pobl'?poblActiva:(T==='actor'?actorActivo:regionActiva));
    b.setAttribute('aria-pressed',String(b.dataset.valor===act));
  });
  const vis=ITEMS.filter(i=>i.estado===vista)
    .filter(i=>!ejeActivo||(i.ejes||[]).includes(ejeActivo))
    .filter(i=>!poblActiva||(i.poblaciones||[]).includes(poblActiva))
    .filter(i=>!actorActivo||(i.actores||[]).includes(actorActivo))
    .filter(i=>!regionActiva||i.region===regionActiva)
    .sort((a,b)=>b.puntaje-a.puntaje);
  refrescarBarra(vis.length);
  const l=document.getElementById('lista');
  if(!vis.length){l.innerHTML='<p class="vacio">Sin resultados con estos filtros.</p>';return}
  l.innerHTML=vis.map(i=>{
    const cob=i.coberturas||[];
    return `<article class="item">
      <h2><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.titulo_original)}</a></h2>
      <div class="datos">
        ${i.importancia?`<span class="imp" title="Importancia editorial, 1 a 10">imp <b>${i.importancia}</b></span>`:''}
        ${i.requiere_verificacion?`<span class="alerta-mini" title="El titular afirma cifras o hechos sin citar fuente">verificar</span>`:''}
        ${i.contiene_datos_personales?`<span class="alerta-mini" title="Identifica a una persona migrante concreta">dato personal</span>`:''}
        <span><span class="vel">${i.velocidad}</span> ${i.velocidad===1?'medio':'medios'}</span>
        ${i.notas>1?`<span>${i.notas} notas</span>`:''}
        ${i.horas!=null?`<span>hace ${i.horas<1?'menos de 1 h':Math.round(i.horas)+' h'}</span>`:''}
        ${i.aceleracion>0?`<span class="sube">+${i.aceleracion} en 3 h</span>`:''}
      </div>
      ${i.angulo_sugerido?`<p class="angulo">${esc(i.angulo_sugerido)}</p>`:''}
      ${(i.terminologia_problematica||[]).length?`<p class="termino">Lenguaje a revisar en la cobertura: ${
        i.terminologia_problematica.map(x=>esc(x)).join(', ')}</p>`:''}
      ${cob.length?`<div class="fuentes"><div class="tit">Publicado por</div><ul>${
        cob.map(c=>`<li><a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.medio)}</a></li>`).join('')
      }</ul></div>`:''}
      <div class="etiquetas">
        ${(i.ejes||[]).map(e=>`<span class="et eje">${esc(e)}</span>`).join('')}
        ${(i.poblaciones||[]).map(x=>`<span class="et pobl">${esc(x)}</span>`).join('')}
        ${(i.actores||[]).map(x=>`<span class="et actor">${esc(x)}</span>`).join('')}
        ${i.etapa?`<span class="et">${esc(i.etapa)}</span>`:''}
        ${i.region?`<span class="et">${esc(i.region)}</span>`:''}
        ${(i.paises||[]).slice(0,4).map(p=>`<span class="et${i.pais_inferido?' inferido':''}">${esc(p)}</span>`).join('')}
      </div>
    </article>`}).join('');
}

document.getElementById('abrir').onclick=alternarFiltros;
document.getElementById('limpiar').onclick=limpiarFiltros;
armarSemaforo();
armarFiltros();
cambiar(vista||'emergente');
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
        generado = datetime.fromisoformat(
            generado.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M UTC")
    except ValueError:
        pass

    en_alcance = sum(1 for i in items if not i.get("fuera_de_alcance"))
    resumen = (f"{en_alcance} hechos en la región, de {datos.get('notas_totales', 0)} "
               f"notas relevadas")

    aviso = ""
    if not datos.get("clasificado"):
        aviso = ('<p class="aviso"><b>Clasificación pendiente.</b> Los datos son reales, '
                 'pero todavía sin análisis por IA: no hay puntaje de importancia ni ejes '
                 'temáticos analizados. La aceleración necesita al menos dos corridas de '
                 'historial.</p>')

    html = (PLANTILLA
            .replace("__GENERADO__", generado)
            .replace("__RESUMEN__", resumen)
            .replace("__AVISO__", aviso)
            .replace("__CLASIFICADO__", "true" if datos.get("clasificado") else "false")
            .replace("__MACRO__", json.dumps(mapa_macroareas(), ensure_ascii=False))
            .replace("__ITEMS__", json.dumps(items, ensure_ascii=False)))

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(html, encoding="utf-8")

    c = Counter(i["estado"] for i in items)
    log.info("Escrito %s  (%d hechos, %d KB)",
             SALIDA.relative_to(RAIZ), len(items), len(html) // 1024)
    for e in ORDEN_LOG:
        if c[e]:
            log.info("   %-16s %d", e, c[e])
    return 0


ORDEN_LOG = ("top_trend", "trending", "interes", "emergente",
             "nadie_lo_mira", "ruido", "fuera_alcance")


if __name__ == "__main__":
    sys.exit(main())
