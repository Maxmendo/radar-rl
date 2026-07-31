# radar-rl

Radar de tendencias y alerta editorial de **Refugio Latinoamericano**.

Este archivo es el contexto permanente del proyecto. Está escrito para que cualquier
integrante del equipo entienda qué hace el sistema, por qué está hecho así y qué no
debe hacer nunca. Si algo queda desactualizado, actualizarlo es parte de la tarea.

---

## 1. Qué es Refugio Latinoamericano

Medio digital argentino dedicado al periodismo de migraciones desde una perspectiva
de derechos humanos e interculturalidad. Fundado en noviembre de 2024. Equipo
mayoritariamente voluntario, con red de corresponsales en la región.

**Línea editorial en una frase:** las personas migrantes son sujetos de derecho, no
un problema a administrar ni una amenaza a contener.

Consecuencias para el radar:

- Un cambio normativo que restringe derechos pesa más que su repercusión política.
- El testimonio de una persona migrante nunca es materia prima de un sistema automático.
- La desinformación antimigrante es objeto de cobertura, no material a reproducir.

## 2. Qué hace este repositorio

**Monitorea de forma continua** señales sobre migraciones en América Latina, el Caribe
y Estados Unidos; detecta qué está creciendo en cobertura ahora; y entrega dos cosas:

1. Un **digest diario** a las 06:00 de Argentina, rankeado por relevancia.
2. Una **alerta inmediata** cuando un hecho supera el umbral, fuera de horario.

**Lo que NO hace:** no redacta artículos, no publica, no toma decisiones editoriales,
no notifica por Telegram ni se integra con ningún bot. Su única salida son los archivos
de `datos/` y `docs/`. La capa de distribución que quiera leerlos es un proyecto aparte.
Mantener esa separación es deliberado.

## 3. Cadencia

**Cada 3 horas**, ocho corridas diarias (`cron: 0 */3 * * *`).

La frecuencia no es capricho: **la aceleración solo se puede medir comparando corridas.**
Un feed RSS da una foto de qué hay, no de qué está creciendo. Con una corrida diaria ves
que 22 medios publicaron algo, pero no si fue hoy o a lo largo de tres semanas — y esas
dos situaciones exigen decisiones editoriales opuestas.

Consumo: 8 corridas × 30 días × ~2-3 min = 480-720 minutos de los 2.000 gratuitos.
Se descartó cada 2 horas (54% del cupo, sin margen) y cada 6 horas (demasiado grueso:
entre dos mediciones un tema explota y se apaga).

Ventana de búsqueda: **`when:1d`**, no 3 días. Con ocho corridas diarias, una ventana
de 72 horas trae mayormente material ya visto.

## 4. Memoria persistente: `datos/historico.json`

Sin memoria no hay aceleración posible. Cada corrida lee este archivo, lo actualiza y
lo vuelve a escribir. Se commitea al repositorio: gratis, versionado y auditable.

```json
{
  "actualizado": "2026-07-31T09:00:00Z",
  "hechos": {
    "<hash_del_hecho>": {
      "titulo_canonico": "titulo del item mas completo del grupo",
      "primera_vez": "2026-07-30T18:00:00Z",
      "ultima_vez": "2026-07-31T09:00:00Z",
      "medios": ["dw.com", "elpais.com", "infobae.com"],
      "urls": ["https://..."],
      "mediciones": [
        {"t": "2026-07-30T18:00:00Z", "medios": 3},
        {"t": "2026-07-30T21:00:00Z", "medios": 11},
        {"t": "2026-07-31T00:00:00Z", "medios": 22}
      ],
      "clasificacion": { "...salida del clasificador..." }
    }
  }
}
```

**Retención:** se descartan los hechos sin apariciones en 14 días. Sin esto el archivo
crece sin límite y las corridas se hacen lentas.

**Un hecho no es un item.** Veinte notas sobre el mismo decreto son un hecho con veinte
URLs. La deduplicación agrupa por similitud de título antes de clasificar; cada hecho
se clasifica **una sola vez**, la primera. Después solo se actualizan las métricas.

## 5. Estados: el ciclo de vida de un hecho

El radar **no rankea una lista: ubica cada hecho en su ciclo de vida.** Un puntaje no
le dice a nadie qué hacer; un estado sí.

```
velocidad    = medios DISTINTOS que publicaron el hecho en 24h
aceleracion  = velocidad actual - velocidad de la corrida anterior (3h atras)
```

| Estado | Condición | Acción editorial |
|---|---|---|
| `top_trend` | velocidad >= 20 | No correrla. Solo con ángulo propio o dato nuevo |
| `trending` | velocidad >= 8, **o** >= 5 con aceleración >= 4 | Publicar ya, o buscar el ángulo que nadie tomó |
| `interes` | velocidad >= 3, **o** >= 2 con aceleración >= 2 | **El punto justo.** Publicar temprano: si escala, la nota ya está |
| `nadie_lo_mira` | velocidad <= 2 **e** importancia >= 7 | Investigar. Posible primicia. Requiere reportería propia |
| `ruido` | velocidad <= 2 e importancia <= 6 | Oculto por defecto. Visible para auditar el descarte |

**Tres reglas de diseño que no hay que romper:**

1. **Los estados van sobre velocidad; la importancia es otra dimensión.** Si
   `nadie_lo_mira` fuera solo "poca cobertura", ahí caería toda la basura sin cobertura.
   Por eso exige importancia >= 7, y existe `ruido` como destino del resto.

2. **La aceleración puede promover de estado.** Cinco medios subiendo de a cuatro cada
   tres horas valen más que ocho estancados. Sin esta regla, un tema que arranca fuerte
   quedaría clasificado por su número absoluto y se llegaría tarde.

3. **`interes` es la vista por defecto.** Es el estado donde una redacción chica todavía
   puede llegar primero. `top_trend` es donde ya perdió.

Ordenamiento dentro de cada estado: por `alerta` en los tres de arriba, por
`subcobertura` en `nadie_lo_mira` y `ruido`.

```
frescura     = 1.0 si primera_vez < 6h | 0.7 < 12h | 0.4 < 24h | 0.1 despues
trends       = 0-10, senal de Google Trends para los terminos del hecho
alerta       = importancia x frescura x (velocidad + aceleracion x 2 + trends)
subcobertura = importancia + (10 - velocidad) x 0.4
```

Los umbrales viven en `fuentes.yaml`, sección `estados`. **Son provisorios**: hay que
calibrarlos con datos reales de las primeras semanas. Cambiarlos no requiere tocar código.

## 6. Alertas: se disparan por ascenso de estado

**No por puntaje alto.** El momento que importa es cuando algo importante entra en
`interes`: ahí todavía se puede llegar primero. Un umbral absoluto avisaría cuando ya
es `top_trend`, o sea tarde.

- Dispara al **ascender** a `interes` o a `trending`, con importancia >= 7.
- Un hecho alerta **una sola vez por estado**. Registro en `datos/alertados.json`.
- Máximo 3 por corrida. Si se superan, algo está mal calibrado y es preferible no inundar.
- Mecanismo: el workflow **abre un issue en este repositorio**. GitHub notifica por mail
  y por push a la app del celular, sin credenciales ni servicios externos, y cada alerta
  queda registrada con fecha para cerrarla cuando se cubrió o descartó.

## 7. Reglas de gobernanza (no negociables)

1. **Nada se publica automáticamente.** Ningún componente tiene permiso de escritura
   sobre el sitio publicado.
2. **Etiquetado.** Todo contenido publicado con asistencia de este sistema debe
   indicarlo de forma visible al lector.
3. **Prohibido generar, sintetizar o parafrasear testimonios** de personas migrantes.
   El sistema señala que existe un testimonio y dónde está; no lo reescribe.
4. **Uso opcional.** El radar propone. La decisión editorial es humana.

Derivadas técnicas:

- No almacenar datos personales de personas migrantes identificables.
- El discurso de odio se clasifica y se cuantifica; no se guarda el texto completo ni
  se reproduce en el digest. Se guarda la URL y una descripción del patrón.
- Ninguna clave en el repositorio. Todo por variables de entorno, documentadas en
  `.env.example`.

## 8. Regla de oro para las consultas

**Consulta corta o Google News ignora `when:`.**

Verificado el 2026-07-31: las consultas de más de ~120 caracteres devolvieron 100
entradas con material de hasta 15 años de antigüedad, ignorando la ventana temporal.
Las de menos de 100 caracteres respetaron los 3 días.

- Máximo 4 términos `OR` por consulta.
- Sin ancla geográfica de texto: `gl` y `hl` ya sesgan la edición.
- Nunca términos ambiguos sueltos: `visa` trae la tarjeta de crédito, `regularizacion`
  trae cooperativas. Siempre calificados.
- **Si una consulta devuelve exactamente 100 entradas, sospechar.** El muestreador
  dispara una ALERTA automática en ese caso.

## 9. Convenciones de código

Este proyecto lo mantiene un equipo chico y no técnico en su mayoría. La prioridad es
que se pueda leer y arreglar dentro de seis meses, no que sea elegante.

- Python 3.11+.
- **`nucleo/registro.py` es la única fuente de verdad** sobre qué fuentes existen y cómo
  consultarlas. Nunca repetir la lista ni la lógica de armar URLs en otro lado: eso fue
  lo que desincronizó a `muestrear_feeds.py` en julio de 2026.
- **Un archivo por fuente de ingesta**, en `fuentes/`, con una única función
  `obtener() -> list[dict]`. Si una fuente se rompe, se arregla o se borra ese archivo.
- Funciones cortas, con un solo propósito. Nombres explícitos, en castellano cuando el
  concepto es del dominio editorial y en inglés cuando es técnico.
- Sin abstracciones prematuras.
- Toda llamada de red con timeout explícito y manejo de excepción. Una fuente caída
  nunca debe tumbar la corrida: se registra el fallo y se sigue.
- Logging a stdout con nivel. Nada de `print` suelto.
- Docstring de una línea en toda función pública, en castellano.

## 10. Esquema del item normalizado

```python
{
    "id": str,              # hash estable de url + titulo
    "titulo": str,
    "resumen": str,         # texto plano, max 1000 caracteres
    "url": str,
    "medio": str,           # dominio del medio, ej. "elpais.com"
    "fuente": str,          # id de fuentes.yaml
    "tipo_fuente": str,     # google_news | feed | gdelt | social | trends
    "fecha": str,           # ISO 8601 UTC
    "pais": list[str],
    "obtenido_en": str,     # ISO 8601 UTC
}
```

El campo `medio` es nuevo y **es crítico**: la velocidad se mide en medios distintos,
no en cantidad de notas. Se extrae del dominio de la URL.

## 11. Modelos

- **Clasificación en volumen:** modelo rápido y barato (Gemini Flash). **En lotes de 20
  items por llamada**, no uno por llamada: el prompt tiene ~1.500 palabras y reenviarlo
  por item multiplica el costo y choca contra los límites de tasa del nivel gratuito.
- **Síntesis del digest y casos ambiguos:** modelo más capaz (Claude), pocas llamadas.
- Fallback a un tercer proveedor ante error, sin reintentar indefinidamente.

Todo prompt vive en `prompts/` como archivo versionado. **Nunca embebido en el código.**

## 12. Estructura

```
radar-rl/
├── CLAUDE.md
├── fuentes.yaml              # registro de fuentes y vocabulario
├── prompts/clasificacion.md
├── nucleo/
│   ├── registro.py           # LISTO. Fuente de verdad de las fuentes
│   ├── normalizar.py         # PENDIENTE
│   ├── deduplicar.py         # PENDIENTE. Agrupa items en hechos
│   ├── velocidad.py          # PENDIENTE. Lee y actualiza historico.json
│   ├── clasificar.py         # PENDIENTE. Lotes de 20
│   └── alertar.py            # PENDIENTE. Abre issues sobre el umbral
├── fuentes/                  # PENDIENTE. Un modulo por fuente
├── scripts/
│   ├── validar_fuentes.py    # LISTO
│   ├── muestrear_feeds.py    # LISTO
│   ├── descubrir_feeds.py    # LISTO. No corre a diario
│   └── generar_tablero.py    # LISTO
├── datos/
│   ├── historico.json        # PENDIENTE. Memoria entre corridas
│   ├── items.json            # PENDIENTE. Salida de la ultima corrida
│   └── alertados.json        # PENDIENTE. Para no repetir alertas
└── docs/index.html           # tablero, dos vistas
```

## 13. Estado actual

**Funcionando:** monitoreo de 24 fuentes verificadas, validación, muestreo con métrica
de ventana temporal, y generación del tablero con datos de ejemplo.

**Pendiente (fase 2):** ingesta, deduplicación en hechos, memoria persistente, cálculo
de velocidad y aceleración, clasificación por lotes, digest y alertas.

**Orden sugerido de construcción:** ingesta → deduplicación → memoria y velocidad →
clasificación → tablero con datos reales → alertas. Cada etapa tiene que funcionar y
verse antes de pasar a la siguiente.
