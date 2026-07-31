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
         "duplicados": 23},
        {"id": "e2", "titulo_original": "Migrantes en Cordoba se pronunciaron tras el DNU contra extranjeros",
         "idioma": "es", "url": "https://example.org/2", "fuente": "gnews_cono_sur_derechos",
         "region": "Cono Sur", "fecha": "2026-07-30T12:00:00Z", "ejes": ["derechos", "odio"],
         "paises": ["AR"], "tipo": "caso", "importancia": 8, "cobertura": 2, "confianza": 0.85,
         "tiene_fuente_primaria": False, "angulo_sugerido": "Contactar a las organizaciones que convocaron",
         "nota": "Respuesta organizada de las comunidades. Casi sin cobertura nacional.",
         "duplicados": 1},
        {"id": "e3", "titulo_original": "ICE raid at meatpacking plant detains 200",
         "idioma": "en", "url": "https://example.org/3", "fuente": "gnews_eeuu_es_derechos",
         "region": "Estados Unidos", "fecha": "2026-07-29T20:00:00Z", "ejes": ["derechos"],
         "paises": ["US"], "tipo": "caso", "importancia": 9, "cobertura": 6, "confianza": 0.9,
         "tiene_fuente_primaria": False, "angulo_sugerido": "Cuantos detenidos tenian proceso de asilo abierto",
         "nota": "Detencion masiva que afecta debido proceso.", "duplicados": 7},
        {"id": "e4", "titulo_original": "Republica Dominicana amplia el operativo de deportaciones en la frontera",
         "idioma": "es", "url": "https://example.org/4", "fuente": "gnews_caribe_derechos",
         "region": "Caribe", "fecha": "2026-07-29T09:00:00Z", "ejes": ["derechos", "normativa"],
         "paises": ["DO", "HT"], "tipo": "evento", "importancia": 9, "cobertura": 1, "confianza": 0.8,
         "tiene_fuente_primaria": False, "angulo_sugerido": "Cifras oficiales versus registros de organizaciones haitianas",
         "nota": "Alta importancia y practicamente sin cobertura regional. Prioridad editorial.",
         "duplicados": 2},
    ],
}


def prioridad_editorial(item: dict) -> float:
    """Importancia ponderada por subcobertura: lo grave que nadie cubre vale mas."""
    imp = item.get("importancia") or 0
    cob = item.get("cobertura")
    if cob is None:
        return float(imp)
    return round(imp + (10 - cob) * 0.4, 1)


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
<div class="filtros" id="filtros"></div>
<div id="lista"></div>
<footer>
Ordenado por prioridad editorial: importancia ponderada por subcobertura.
Un hecho grave que nadie cubre vale mas que uno grave que cubren todos.<br>
Este tablero propone. La decision editorial es humana.
</footer>
</div>
<script>
const ITEMS = __ITEMS__;
let ejeActivo = null, regionActiva = null;

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
    .filter(i => !ejeActivo || i.ejes.includes(ejeActivo))
    .filter(i => !regionActiva || i.region === regionActiva)
    .sort((a, b) => b.prioridad - a.prioridad);
  const lista = document.getElementById('lista');
  if (!visibles.length) { lista.innerHTML = '<p class="vacio">Sin resultados con estos filtros.</p>'; return; }
  lista.innerHTML = visibles.map(i => `
    <article class="item">
      <h2><a href="${i.url}" target="_blank" rel="noopener">${escapar(i.titulo_original)}</a></h2>
      <div class="puntajes">
        <span>prioridad <b class="destacado">${i.prioridad}</b></span>
        <span>importancia <b>${i.importancia}</b></span>
        <span>cobertura <b>${i.cobertura ?? 's/d'}</b></span>
        ${i.duplicados > 1 ? `<span>${i.duplicados} notas agrupadas</span>` : ''}
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

armarFiltros();
dibujar();
</script>
</body>
</html>
"""


def main() -> int:
    datos, es_ejemplo = cargar()

    items = datos.get("items", [])
    for i in items:
        i["prioridad"] = prioridad_editorial(i)

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
