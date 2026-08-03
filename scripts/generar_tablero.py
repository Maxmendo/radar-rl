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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nucleo.estados import (estado, normalizar_ejes, potencial,  # noqa: E402
                            puntaje, recalcular_alcance)

RAIZ = Path(__file__).resolve().parent.parent
ENTRADA = RAIZ / "datos" / "items.json"
SALIDA = RAIZ / "docs" / "index.html"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("tablero")


def cruzar_tendencias(items: list[dict]) -> dict:
    """Adjunta a cada hecho su medicion de Google Trends, si la tiene.

    Solo los hechos en estado `interes` fueron consultados: son los unicos donde
    la senal es accionable, y ademas son pocos (2-8 por corrida), lo que permite
    consultar POR HECHO en vez de por un panel grueso de terminos. El resto de
    los hechos queda sin dato, no en cero.

    El puntaje NO entra en el orden del tablero. Google Trends refleja las
    busquedas con retraso y lo que las hace subir suele ser la propia cobertura
    mediatica: rankear con eso contaminaria una metrica que funciona. Se muestra
    como dato y dispara alertas editoriales.
    """
    ruta = RAIZ / "datos" / "tendencias.json"
    if not ruta.exists():
        return {"disponible": False, "servicio": [], "alertas": []}
    try:
        panel = json.loads(ruta.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"disponible": False, "servicio": [], "alertas": []}

    porhecho = panel.get("hechos", {})
    for i in items:
        d = porhecho.get(i.get("id"))
        if d:
            i["trends"] = d["puntaje"]
            i["trends_motivo"] = f"{d['termino']} en {d['geo']}, x{d.get('ratio') or 0}"

    servicio = sorted(
        ({"termino": t, **d} for t, d in panel.get("servicio", {}).items()),
        key=lambda x: -x.get("puntaje", 0))[:6]

    # Consultas en alza sobre migracion, por pais. Son terminos concretos del
    # dia, no una lista fija que ya conocemos de antemano.
    # Los paises se miden por rotacion, asi que cada uno trae la fecha de su
    # ultima medicion. Se muestran del mas reciente al mas viejo.
    audiencia = [{"geo": geo, "consultas": d.get("consultas", []),
                  "medido": d.get("medido", "")}
                 for geo, d in (panel.get("audiencia") or {}).items()
                 if d.get("consultas")]
    audiencia.sort(key=lambda x: x["medido"], reverse=True)

    return {
        "disponible": bool(panel.get("disponible")),
        "generado": panel.get("generado", ""),
        "servicio": servicio,
        "audiencia": audiencia,
        "alertas": panel.get("alertas", [])[:5],
    }


def contexto() -> dict:
    """Diccionarios de traduccion que necesita el tablero, desde fuentes.yaml."""
    cfg = yaml.safe_load((RAIZ / "fuentes.yaml").read_text(encoding="utf-8"))
    return {
        "alias": cfg.get("alias_ejes", {}).get("mapa", {}),
        "nombre_eje": {e["id"]: e["nombre"] for e in cfg.get("ejes", [])},
        "macro_de": {eid: m["nombre"] for m in cfg.get("macroareas", {}).values()
                     for eid in m["ejes"]},
        "colectividades": cfg.get("colectividades", {}).get("nombres", {}),
        "regiones": cfg.get("paises_catalogo", {}).get("regiones", []),
    }


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
  /* Semaforo. Senaletica funcional, fuera de la paleta de marca a proposito.
     Se usa solo en puntos de 10px y subrayados, sin invadir la interfaz.
       rojo     trending          -> urgente, publicar ahora
       verde    de interes        -> el punto justo, se llega temprano
       celeste  posibles alertas  -> investigar, posible primicia
       marron   para auditar      -> descarte, control de calidad
       gris     extrarregionales  -> contexto comparado
       amarillo top trend         -> saturado, ya paso                       */
  --sem-rojo:#d92d20; --sem-verde:#12805c; --sem-celeste:#2e90d9;
  --sem-marron:#8a5a33; --sem-amarillo:#b58600;
  --fondo:#fbf9f8; --tarjeta:#fff; --linea:#eae3e1;
  --tinta:#3a2e2e; --suave:#806e6e; --tenue:#a2938f;
}
@media (prefers-color-scheme:dark){
  :root{ --fondo:#211a1a; --tarjeta:#2b2222; --linea:#3d3130;
    --tinta:#f2ebe9; --suave:#bfaeab; --tenue:#8d7a77;
    --sem-rojo:#f97066; --sem-verde:#47cd9a; --sem-celeste:#53b1fd;
    --sem-marron:#c99163; --sem-amarillo:#e5b04a; }
}
*{box-sizing:border-box}
body{margin:0;padding:0 0 4rem;background:var(--fondo);color:var(--tinta);
  font-family:'Barlow',Arial,Helvetica,sans-serif;font-size:16px;line-height:1.6;
  -webkit-font-smoothing:antialiased}
.c{max-width:1180px;margin:0 auto;padding:0 1.1rem}

/* Dos columnas: las noticias mandan, los paneles de busquedas acompanan.
   En pantallas angostas se apilan y los paneles quedan abajo. */
.columnas{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:1.4rem;
  align-items:start}
.lateral{position:sticky;top:1rem;display:flex;flex-direction:column;gap:.9rem}
@media(max-width:880px){
  .columnas{grid-template-columns:1fr}
  .lateral{position:static;order:2}
  main{order:1}
}

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
.semaforo button[aria-pressed="true"]#v-top_trend{border-bottom-color:var(--sem-amarillo)}
.semaforo button[aria-pressed="true"]#v-trending{border-bottom-color:var(--sem-rojo)}
.semaforo button[aria-pressed="true"]#v-interes{border-bottom-color:var(--sem-verde)}
.semaforo button[aria-pressed="true"]#v-emergente{border-bottom-color:var(--sem-celeste)}
.semaforo button[aria-pressed="true"]#v-nadie_lo_mira{border-bottom-color:var(--sem-celeste)}
.semaforo button[aria-pressed="true"]#v-ruido{border-bottom-color:var(--sem-marron)}
.semaforo button[aria-pressed="true"]#v-fuera_alcance{border-bottom-color:var(--tenue)}
.luz{width:10px;height:10px;border-radius:50%;flex:none}
.l-top_trend{background:var(--sem-amarillo)}
.l-trending{background:var(--sem-rojo)}
.l-interes{background:var(--sem-verde)}
.l-emergente{background:var(--sem-celeste)}
.l-nadie_lo_mira{background:var(--sem-celeste)}
.l-ruido{background:var(--sem-marron)}
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
/* Los filtros aplicados se ven siempre, tambien con el panel cerrado: un filtro
   activo e invisible hace parecer que el radar no encontro nada. */
.activos{display:flex;gap:.3rem;flex-wrap:wrap}
.activos button{font:inherit;font-size:.76rem;padding:.22rem .5rem .22rem .62rem;
  cursor:pointer;background:var(--rojo);color:#fff;border:none;border-radius:99px;
  display:flex;align-items:center;gap:.3rem}
.activos button::after{content:"×";font-size:.95rem;line-height:1;opacity:.85}
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

/* Alerta editorial: importante + poco cubierto + busquedas subiendo. */
.alertas{background:var(--tarjeta);border-left:4px solid var(--sem-rojo);border-radius:0 9px 9px 0;
  padding:.85rem 1rem;margin-bottom:1rem}
.alertas .tit{font-size:.71rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--sem-rojo);font-weight:700;margin-bottom:.4rem}
.alertas p{margin:0 0 .6rem;font-size:.82rem;color:var(--suave)}
.alertas ul{list-style:none;margin:0;padding:0}
.alertas li{font-size:.85rem;margin-bottom:.55rem;padding-left:.7rem;
  border-left:2px solid var(--linea);line-height:1.5}
.alertas li b{color:var(--tinta)}
.alertas li a{color:inherit;text-decoration:none}
.alertas li a:hover b{color:var(--sem-rojo);text-decoration:underline}
.alertas .det{color:var(--suave);font-size:.78rem}
.dsc{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.04em;
  padding:.08rem .4rem;border-radius:3px;margin-right:.35rem;white-space:nowrap}
.d-vig{background:var(--sem-verde);color:#fff}
.d-esc{background:var(--sem-amarillo);color:#fff}
.d-frio{background:var(--tenue);color:#fff}

/* Atencion publica por pais: donde esta instalado el tema. */
.atencion{background:var(--tarjeta);border:1px solid var(--sem-celeste);border-radius:9px;
  padding:.75rem .85rem}
.atencion .tit{font-size:.71rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--sem-celeste);font-weight:700;margin-bottom:.4rem}
.atencion p{margin:0 0 .5rem;font-size:.82rem;color:var(--suave)}
.atencion .pais{margin-bottom:.6rem}
.atencion .pais b{font-size:.78rem;color:var(--tinta);display:block;margin-bottom:.2rem}
.atencion ul{list-style:none;margin:0;padding:0}
.atencion li{font-size:.76rem;color:var(--suave);line-height:1.5;padding-left:.55rem;
  border-left:2px solid var(--linea)}
.atencion .sube{color:var(--sem-verde);font-weight:600;font-size:.7rem}
.atencion .var{font-size:.65rem;color:var(--tenue);border:1px solid var(--linea);
  padding:0 .25rem;border-radius:3px}
.atencion .cuando{font-size:.65rem;font-weight:400;color:var(--tenue);
  float:right;text-transform:none;letter-spacing:0}
.atencion .pie{font-size:.7rem;color:var(--tenue);margin:.5rem 0 0;line-height:1.45}

/* Demanda de busqueda: lo que la gente busca antes de que sea noticia. */
.demanda{background:var(--tarjeta);border:1px solid var(--sem-verde);border-radius:9px;
  padding:.75rem .85rem}
.demanda .tit{font-size:.71rem;text-transform:uppercase;letter-spacing:.07em;
  color:var(--sem-verde);font-weight:700;margin-bottom:.4rem}
.demanda p{margin:0 0 .5rem;font-size:.82rem;color:var(--suave)}
.demanda ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:.35rem}
.demanda ul{flex-direction:column;gap:.25rem}
.demanda li{font-size:.76rem;padding:.14rem .5rem;border-radius:4px;
  background:var(--fondo);border:1px solid var(--linea);color:var(--tinta)}
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
.et.cole{border-color:var(--rosa);color:var(--rosa)}
.trend{font-size:.7rem;padding:.05rem .42rem;border-radius:3px;
  background:var(--fondo);border:1px solid var(--sem-verde);color:var(--sem-verde);
  font-weight:600}
.trend.plano{border-color:var(--linea);color:var(--tenue)}
.trend.nomedido{border-style:dashed;border-color:var(--linea);color:var(--tenue);
  font-weight:400}
.tardia{font-size:.7rem;padding:.05rem .42rem;border-radius:3px;
  background:var(--fondo);border:1px solid var(--marron-med);color:var(--marron-med);
  font-weight:600}
.extrarreg{font-size:.7rem;padding:.05rem .42rem;border-radius:3px;
  background:var(--fondo);border:1px solid var(--linea);color:var(--tenue);
  font-weight:600;text-transform:uppercase;letter-spacing:.03em}
.alerta-mini{font-size:.7rem;padding:.05rem .42rem;border-radius:3px;
  background:var(--fondo);border:1px solid var(--rosa-claro);color:var(--rosa);
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
  <span class="activos" id="activos"></span>
  <button class="limpiar" id="limpiar" hidden>Quitar filtros</button>
  <span class="resultado" id="resultado"></span>
</div>
<div class="filtros" id="filtros" hidden></div>
<div id="alertas"></div>
<div class="columnas">
  <main id="lista"></main>
  <aside class="lateral">
    <div id="atencion"></div>
    <div id="demanda"></div>
  </aside>
</div>
<footer>
<b>Cómo leerlo.</b> Cada fila es un <i>hecho</i>, no una nota: si veinte medios publican
sobre el mismo decreto, es un hecho con veinte medios. La cantidad de medios distintos
es la <b>velocidad</b>, y define en qué luz del semáforo está.<br>
Cada medio listado abajo del título es un enlace directo a su publicación, para chequear
cualquiera de las fuentes.<br>
Los países con <span class="et inferido">borde punteado</span> son inferidos de la
búsqueda, no del titular: menos confiables.<br>
Cada hecho de la región muestra el dato de <b>búsquedas</b> en Google, de 0 a 10:
↑ si están subiendo, → si se mueven poco, — si están planas, <i>s/d</i> si todavía no
se midió (Google limita las consultas por día). <b>No altera el orden</b>, que lo da la
importancia editorial.<br>
La marca <b>cobertura tardía</b> señala que el titular retoma un hecho de días
anteriores en vez de informar algo nuevo: no es una primicia aunque tenga pocos medios.<br>
El radar propone. La decisión editorial es humana.
<p class="slogan">periodismo sin fronteras</p>
</footer>
</div>

<script>
const ITEMS = __ITEMS__;
const CLASIFICADO = __CLASIFICADO__;
const CTX = __CTX__;
let vista=null, regionActiva=null, paisActivo=null;

const ESTADOS = {
  trending:{n:'Trending', a:'8 o más medios. Ya está instalado: publicar ahora, o buscar el ángulo que nadie tomó.'},
  interes:{n:'De interés', a:'3 o más medios. EL PUNTO JUSTO: todavía se llega temprano. Ordenado por importancia editorial; el dato de búsquedas en Google va al lado de cada hecho, para que la decisión combine ambas cosas.'},
  top_trend:{n:'Top trend', a:'La conversación dominante del momento: 20 o más medios en la región, 30 o más fuera de ella. Saturado, no correrla; cubrir solo con ángulo propio. Los hechos extrarregionales aparecen abajo, marcados, para ver de qué se habla globalmente.'},
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

function nombresPais(i){
  // Respaldo a codigos ISO si el hecho viene de una corrida anterior a que la
  // ingesta empezara a guardar nombres legibles.
  return (i.paises_nombres && i.paises_nombres.length) ? i.paises_nombres : (i.paises||[]);
}

function armarFiltros(){
  const c=document.getElementById('filtros');

  const ORDEN_REG=[...(CTX.regiones||[]),'Regional','Sin determinar'];
  const regs=[...new Set(ITEMS.map(i=>i.region).filter(Boolean))]
    .sort((a,b)=>{
      const ia=ORDEN_REG.indexOf(a), ib=ORDEN_REG.indexOf(b);
      return (ia<0?99:ia)-(ib<0?99:ib);
    });
  const paises=[...new Set(ITEMS.flatMap(nombresPais))].filter(Boolean)
    .sort((a,b)=>a.localeCompare(b,'es'));

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
        if(tipo==='pais') paisActivo = paisActivo===v ? null : v;
        else regionActiva = regionActiva===v ? null : v;
        dibujar();
      };
      d.appendChild(b);
    });
    c.appendChild(d);
  };

  // El usuario filtra SOLO por region y pais. Ejes, poblaciones, actores y
  // colectividades se muestran como etiquetas en cada titular: ocho filas de
  // filtros hacian que las categorias predominaran sobre las noticias.
  grupo('Región',regs,'region');
  grupo('País',paises,'pais');

  const n=document.createElement('p'); n.className='nota-filtro';
  n.innerHTML='La región y el país salen de lo que menciona el titular. «Regional» es un hecho '+
    'que cruza más de una región; «Sin determinar», uno cuyo titular no nombra ningún lugar.<br>'+
    'Los ejes temáticos, poblaciones y actores aparecen como etiquetas debajo de cada titular.';
  c.appendChild(n);
}

function refrescarBarra(n){
  const puestos=[['region',regionActiva],['pais',paisActivo]].filter(x=>x[1]);
  document.getElementById('cuenta').textContent=puestos.length?puestos.length:'';
  document.getElementById('limpiar').hidden=!puestos.length;
  document.getElementById('resultado').textContent=
    n===null?'':`${n} ${n===1?'hecho':'hechos'}`;

  const caja=document.getElementById('activos');
  caja.innerHTML='';
  puestos.forEach(([tipo,valor])=>{
    const b=document.createElement('button');
    b.textContent=valor;
    b.title='Quitar este filtro';
    b.onclick=()=>{ if(tipo==='pais') paisActivo=null; else regionActiva=null; dibujar(); };
    caja.appendChild(b);
  });
}

function alternarFiltros(){
  const caja=document.getElementById('filtros'), b=document.getElementById('abrir');
  const abierto=b.getAttribute('aria-expanded')==='true';
  b.setAttribute('aria-expanded',String(!abierto));
  caja.hidden=abierto;
}

function limpiarFiltros(){
  regionActiva=paisActivo=null;
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
    const act=b.dataset.tipo==='pais'?paisActivo:regionActiva;
    b.setAttribute('aria-pressed',String(b.dataset.valor===act));
  });
  const vis=ITEMS.filter(i=>i.estado===vista)
    .filter(i=>!regionActiva||i.region===regionActiva)
    .filter(i=>!paisActivo||nombresPais(i).includes(paisActivo))
    // Orden: primero lo regional, despues lo extrarregional. Dentro de cada
    // bloque, IMPORTANCIA de mayor a menor y el puntaje desempata.
    // Google Trends NO ordena: se muestra como dato al lado de cada hecho para
    // que la decision editorial combine ambas cosas. Ver nucleo/estados.py.
    .sort((a,b)=>
      (a.fuera_de_alcance?1:0)-(b.fuera_de_alcance?1:0) ||
      (b.importancia||0)-(a.importancia||0) ||
      b.puntaje-a.puntaje);
  refrescarBarra(vis.length);
  const l=document.getElementById('lista');
  if(!vis.length){l.innerHTML='<p class="vacio">Sin resultados con estos filtros.</p>';return}
  l.innerHTML=vis.map(i=>{
    const cob=i.coberturas||[];
    return `<article class="item">
      <h2><a href="${esc(i.url)}" target="_blank" rel="noopener">${esc(i.titulo_original)}</a></h2>
      <div class="datos">
        ${i.importancia?`<span class="imp" title="Importancia editorial, 1 a 10">Importancia <b>${i.importancia}</b></span>`:''}
        ${i.cobertura_tardia?`<span class="tardia" title="El titular retoma un hecho de días anteriores, no informa algo nuevo">cobertura tardía</span>`:''}
        ${i.fuera_de_alcance?`<span class="extrarreg" title="Ocurre fuera de America Latina, el Caribe y Estados Unidos">extrarregional</span>`:''}
        ${!i.fuera_de_alcance?(i.trends!=null
            ?`<span class="trend${i.trends>=5?'':' plano'}" title="${esc(i.trends_motivo||'')}">búsquedas ${i.trends>=5?'↑':(i.trends>0?'→':'—')} ${i.trends}/10</span>`
            :`<span class="trend nomedido" title="Google Trends limita las consultas por día: este hecho no se midió todavía">búsquedas s/d</span>`):''}
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
function armarAlertas(){
  const t=CTX.tendencias;
  const c=document.getElementById('alertas');
  if(!t || !(t.alertas||[]).length) return;
  const DESENLACE={
    vigente:{t:'sigue abierto',c:'d-vig'},
    escalo:{t:'ya escaló',c:'d-esc'},
    se_enfrio:{t:'se enfrió',c:'d-frio'}
  };
  const cuando=h=>!h?'ahora':(h<1?'hace minutos':`hace ${Math.round(h)} h`);
  c.innerHTML='<div class="alertas"><div class="tit">Alertas editoriales</div>'+
    '<p>Temas importantes, poco cubiertos y con las búsquedas subiendo. '+
    'Se conservan 12 horas aunque el tema cambie de estado, con lo que pasó después.</p><ul>'+
    t.alertas.map(a=>{
      const d=DESENLACE[a.desenlace]||DESENLACE.vigente;
      return `<li><span class="dsc ${d.c}">${d.t}</span> `+
        `${a.url?`<a href="${esc(a.url)}" target="_blank" rel="noopener"><b>${esc(a.titulo)}</b></a>`
                :`<b>${esc(a.titulo)}</b>`}<br>`+
        `<span class="det">búsquedas de «${esc(a.termino)}» ×${a.ratio} en ${esc(a.geo)} · `+
        `importancia ${a.importancia} · ${a.velocidad} medios · ${cuando(a.horas)}</span></li>`;
    }).join('')+
    '</ul></div>';
}

const NOMBRE_PAIS={AR:'Argentina',BO:'Bolivia',BR:'Brasil',CL:'Chile',CO:'Colombia',
  EC:'Ecuador',GY:'Guyana',PY:'Paraguay',PE:'Perú',SR:'Surinam',UY:'Uruguay',
  VE:'Venezuela',BZ:'Belice',CR:'Costa Rica',SV:'El Salvador',GT:'Guatemala',
  HN:'Honduras',NI:'Nicaragua',PA:'Panamá',MX:'México',US:'Estados Unidos',
  CA:'Canadá',CU:'Cuba',DO:'Rep. Dominicana',HT:'Haití',PR:'Puerto Rico',
  JM:'Jamaica',TT:'Trinidad y Tobago',
  // Espana entra por audiencia, no por alcance editorial: segun Analytics es uno
  // de los paises donde mas leen a Refugio.
  ES:'España'};

function armarAtencion(){
  const t=CTX.tendencias;
  const c=document.getElementById('atencion');
  if(!t || !(t.audiencia||[]).length) return;
  const dias=iso=>{
    if(!iso) return '';
    const h=(Date.now()-new Date(iso).getTime())/36e5;
    return h<24?'hoy':(h<48?'ayer':`hace ${Math.round(h/24)} días`);
  };
  c.innerHTML='<div class="atencion"><div class="tit">Qué busca nuestra audiencia</div>'+
    '<p>Consultas sobre migración en los países donde más nos leen. '+
    'Argentina siempre, más un país rotando. Las variantes de un mismo tema '+
    'se agrupan: <span class="var">+3</span> significa tres búsquedas parecidas.</p>'+
    t.audiencia.map(p=>`<div class="pais"><b>${esc(NOMBRE_PAIS[p.geo]||p.geo)}`+
      `<span class="cuando">${esc(dias(p.medido))}</span></b>`+
      `<ul>${p.consultas.map(q=>`<li>${esc(q.consulta)}`+
        `${q.variantes>0?` <span class="var">+${q.variantes}</span>`:''}`+
        `${q.valor?` <span class="sube">${esc(q.valor)}</span>`:''}</li>`).join('')}</ul>`+
      `</div>`).join('')+
    '</div>';
}

function armarDemanda(){
  const t=CTX.tendencias;
  const c=document.getElementById('demanda');
  if(!t || !(t.servicio||[]).length) return;
  c.innerHTML='<div class="demanda"><div class="tit">Trámites en alza · Argentina</div>'+
    '<p>Búsquedas de trámite por encima de lo habitual. Quien las escribe está '+
    'resolviendo un problema, no leyendo noticias: un pico acá suele señalar una '+
    'demora o un cambio de requisito que ningún medio cubrió.</p>'+
    '<ul>'+t.servicio.map(x=>`<li>${esc(x.termino)} · ${esc(x.geo)} · ×${x.ratio}</li>`).join('')+
    '</ul></div>';
}

armarSemaforo();
armarAlertas();
armarAtencion();
armarDemanda();
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

    ctx = contexto()
    normalizar_ejes(items, ctx["alias"])

    # Los paises que asigna el clasificador son mucho mas confiables que los que
    # infiere la ingesta por coincidencia de palabras. Sin este recalculo, un
    # hecho de Reino Unido podia quedar como `Sudamerica` y aparecer en `interes`.
    movidos = recalcular_alcance(items)
    if movidos:
        log.info("Alcance recalculado con los paises del clasificador: %d hechos cambiaron",
                 movidos)
    ctx["tendencias"] = cruzar_tendencias(items)
    for i in items:
        i["estado"] = estado(i)
        i["puntaje"] = puntaje(i)
        i["potencial"] = potencial(i)

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
            .replace("__CTX__", json.dumps(ctx, ensure_ascii=False))
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
