# radar-rl

Radar de tendencias y monitoreo editorial de **Refugio Latinoamericano**.

Este archivo es el contexto permanente del proyecto. Está escrito para que cualquier
integrante del equipo —no solo quien lo desarrolló— entienda qué hace el sistema,
por qué está hecho así y qué no debe hacer nunca. Si algo de lo que sigue queda
desactualizado, actualizarlo es parte de la tarea.

---

## 1. Qué es Refugio Latinoamericano

Medio digital argentino dedicado al periodismo de migraciones desde una perspectiva
de derechos humanos e interculturalidad. Fundado en noviembre de 2024. Equipo
mayoritariamente voluntario, con una red de corresponsales en crecimiento en la región.

Sitio: refugiolatinoamericano.com (WordPress).

**Línea editorial en una frase:** las personas migrantes son sujetos de derecho, no
un problema a administrar ni una amenaza a contener.

Esto tiene consecuencias concretas para el radar:

- Un cambio normativo que restringe derechos es más relevante que su repercusión política.
- El testimonio de una persona migrante nunca es materia prima de un sistema automático.
- La desinformación antimigrante es objeto de cobertura, no material a reproducir.

## 2. Qué hace este repositorio

Ingesta, clasifica y prioriza señales sobre migraciones en América Latina, y entrega
un digest diario al equipo editorial para que la decisión sobre qué cubrir se tome
con datos y no por lo que apareció en el timeline.

Flujo: fuentes → normalización → clasificación (LLM) → deduplicación → scoring →
digest en Telegram + base histórica en Google Sheets.

**Lo que este repositorio NO hace:** no redacta artículos, no publica nada en ningún
lado, no toma decisiones editoriales. Propone. Decide una persona.

## 3. Reglas de gobernanza (no negociables)

1. **Nada se publica automáticamente.** Ningún componente de este sistema tiene
   permiso de escritura sobre el sitio publicado. Si en el futuro se integra WordPress,
   es exclusivamente con `status: draft`.
2. **Etiquetado.** Todo contenido que llegue a publicarse con asistencia de este
   sistema debe indicarlo de forma visible al lector.
3. **Prohibido generar, sintetizar o parafrasear testimonios** de personas migrantes.
   El sistema puede señalar que existe un testimonio y dónde está; no lo reescribe.
4. **Uso opcional.** El radar es una herramienta de apoyo. Nadie está obligado a
   tomar temas de ahí.

Reglas técnicas derivadas:

- No almacenar datos personales de personas migrantes identificables. Si una fuente
  los trae, el pipeline los descarta antes de persistir.
- El discurso de odio se clasifica y se cuantifica; no se guarda el texto completo
  ni se reproduce en el digest. Se guarda la URL y una descripción del patrón.
- Ninguna clave o secreto en el repositorio. Todo por variables de entorno,
  documentadas en `.env.example`.

## 4. Convenciones de código

Este proyecto lo mantiene un equipo chico y no técnico en su mayoría. La prioridad
es que se pueda leer y arreglar dentro de seis meses, no que sea elegante.

- Python 3.11+.
- **Un archivo por fuente de ingesta**, en `fuentes/`. Cada uno expone una única
  función `obtener() -> list[dict]` que devuelve items normalizados. Si una fuente
  se rompe, se arregla o se borra ese archivo y nada más.
- Funciones cortas, con un solo propósito. Nombres explícitos, en castellano cuando
  el concepto es del dominio editorial (`puntuar_relevancia`, `es_normativa`) y en
  inglés cuando es técnico (`fetch`, `parse`, `retry`).
- Sin abstracciones prematuras. No crear una clase base de fuentes hasta tener al
  menos seis fuentes funcionando y ver qué comparten de verdad.
- Toda llamada de red con timeout explícito y manejo de excepción. Una fuente caída
  nunca debe tumbar la corrida completa: se registra el fallo y se sigue.
- Logging a stdout con nivel. Nada de `print` suelto.
- Docstring de una línea en toda función pública, en castellano.

## 5. Esquema del item normalizado

Todas las fuentes devuelven diccionarios con esta forma. Los campos de clasificación
los completa la etapa siguiente, no la fuente.

```python
{
    "id": str,              # hash estable de url + titulo
    "titulo": str,
    "resumen": str,         # texto plano, máx 1000 caracteres
    "url": str,
    "fuente": str,          # identificador de la fuente, ej. "boletin_oficial_ar"
    "tipo_fuente": str,     # normativa | organismo | medio | tendencia | social
    "fecha": str,           # ISO 8601 UTC
    "pais": list[str],      # códigos ISO, ej. ["AR", "BO"]
    "obtenido_en": str,     # ISO 8601 UTC
}
```

## 6. Estructura

```
radar-rl/
├── CLAUDE.md
├── fuentes.yaml            # registro de fuentes, editable sin tocar código
├── prompts/
│   └── clasificacion.md    # prompt de clasificación (versionado)
├── fuentes/                # un módulo por fuente
├── nucleo/                 # normalización, dedup, scoring, persistencia
├── salidas/                # digest Telegram, escritura en Sheets
├── scripts/
│   └── validar_fuentes.py  # verifica que las fuentes de fuentes.yaml respondan
└── .github/workflows/      # scheduler
```

## 7. Modelos

Cascada, igual criterio que el resto de los proyectos de Refugio:

- **Clasificación en volumen:** modelo rápido y barato (Gemini Flash). Cientos de
  items por corrida, tarea acotada, salida JSON estricta.
- **Síntesis del digest y casos ambiguos:** modelo más capaz (Claude), pocos llamados
  por corrida.
- Fallback a un tercer proveedor ante error, sin reintentar indefinidamente.

Todo prompt vive en `prompts/` como archivo versionado. **Nunca embebido en el código.**
Es la lección del caso ScribNews: el prompt centralizado y versionado es lo que
permite controlar el criterio editorial a escala.

## 8. Estado actual

Fase 1 en desarrollo: ingesta y validación de fuentes. Sin clasificación, sin Sheets,
sin Telegram todavía. La salida de esta fase es un JSON local que se revisa a mano
para ajustar los ejes de clasificación con datos reales.
