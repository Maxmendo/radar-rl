// docs/_worker.js
// Worker en modo "static assets" (el modelo unificado de Cloudflare 2026).
//
// Toma control de TODAS las requests entrantes:
//   - POST /generar-borrador  -> redacta el borrador y lo envÃ­a por correo
//   - cualquier otra ruta      -> sirve el dashboard estÃ¡tico (env.ASSETS)
//
// Importante: si no reenviÃ¡ramos lo demÃ¡s a env.ASSETS, el dashboard dejarÃ­a
// de verse. Por eso el fallback final es obligatorio.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // --- Endpoint del botÃ³n ---
    if (url.pathname === "/generar-borrador") {
      if (request.method === "OPTIONS") return preflight();
      if (request.method === "POST") return manejarBorrador(request, env);
      return json({ ok: false, error: "MÃ©todo no permitido" }, 405);
    }

    // --- Todo lo demÃ¡s: el dashboard y sus archivos estÃ¡ticos ---
    return env.ASSETS.fetch(request);
  },
};

// ---------------------------------------------------------------------------
// Destinatarios de la etapa de prueba
// ---------------------------------------------------------------------------
const DESTINATARIOS = [
  "refugiolatinoamericano@gmail.com",
  "contacto@refugiolatinoamericano.com",
];

// Con Gmail comÃºn, el remitente debe ser la cuenta que autorizÃ³ el token.
const REMITENTE = {
  email: "refugiolatinoamericano@gmail.com",
  nombre: "Radar Migratorio",
};

// ---------------------------------------------------------------------------
// Handler del borrador
// ---------------------------------------------------------------------------
async function manejarBorrador(request, env) {
  let hecho;
  try {
    hecho = await request.json();
  } catch {
    return json({ ok: false, error: "Cuerpo invÃ¡lido" }, 400);
  }

  if (!hecho || !hecho.titulo) {
    return json({ ok: false, error: "Falta el tÃ­tulo del hecho" }, 400);
  }

  // El texto pesado de las fuentes no viaja en el payload (inflaria el HTML):
  // se lee aca de items.json, que la ingesta ya enriquecio con fuentes_texto.
  try {
    hecho.fuentes_texto = await leerFuentesTexto(hecho.id, request, env);
  } catch {
    hecho.fuentes_texto = [];           // sin texto -> el prompt hara fallo seguro
  }

  let borrador;
  try {
    borrador = await redactar(hecho, env);
  } catch (e) {
    return json({ ok: false, error: "Fallo al redactar: " + e.message }, 502);
  }

  try {
    await enviarPorGmail({
      asunto: `ðŸ“ Borrador: ${hecho.titulo}`,
      html: armarHtml(hecho, borrador),
      texto: `${hecho.titulo}\n\n${borrador}`,
      env,
    });
  } catch (e) {
    return json({ ok: false, error: "Redactado, pero fallÃ³ el envÃ­o: " + e.message }, 502);
  }

  return json({ ok: true, mensaje: "Borrador enviado por correo." }, 200);
}

// Lee datos/items.json (servido como asset) y devuelve el fuentes_texto del
// hecho pedido. items.json esta en la raiz de los assets como /items.json o
// bajo /datos/; se prueban ambas rutas.
async function leerFuentesTexto(id, request, env) {
  if (!id || !env.ASSETS) return [];
  const base = new URL(request.url).origin;
  for (const ruta of ["/items.json", "/datos/items.json"]) {
    try {
      const r = await env.ASSETS.fetch(new Request(base + ruta));
      if (!r.ok) continue;
      const data = await r.json();
      const items = data.items || [];
      const h = items.find((x) => String(x.id) === String(id));
      if (h && Array.isArray(h.fuentes_texto)) return h.fuentes_texto;
      return [];
    } catch {
      continue;
    }
  }
  return [];
}

// ---------------------------------------------------------------------------
// RedacciÃ³n con cascada Gemini -> Claude -> Groq (usa las claves que existan)
// ---------------------------------------------------------------------------
// El texto de las fuentes lo baja la INGESTA (Python, robusto) y llega ya listo
// en hecho.fuentes_texto. El Worker no resuelve URLs en vivo: solo redacta.
async function redactar(hecho, env) {
  const prompt = construirPrompt(hecho);
  const errores = [];

  if (env.GEMINI_API_KEY) {
    try { return await viaGemini(prompt, env.GEMINI_API_KEY); }
    catch (e) { errores.push("Gemini: " + e.message); }
  }
  if (env.ANTHROPIC_API_KEY) {
    try { return await viaClaude(prompt, env.ANTHROPIC_API_KEY); }
    catch (e) { errores.push("Claude: " + e.message); }
  }
  if (env.GROQ_API_KEY) {
    try { return await viaGroq(prompt, env.GROQ_API_KEY); }
    catch (e) { errores.push("Groq: " + e.message); }
  }

  throw new Error("NingÃºn modelo respondiÃ³. " + errores.join(" | "));
}

function construirPrompt(h) {
  const ejes = Array.isArray(h.ejes) ? h.ejes.join(", ") : (h.ejes || "s/d");
  const paises = Array.isArray(h.paises) ? h.paises.join(", ") : (h.paises || h.pais || "s/d");
  const pobl = Array.isArray(h.poblaciones) ? h.poblaciones.join(", ") : "";

  const fuentes = Array.isArray(h.fuentes_texto) ? h.fuentes_texto : [];
  const conTexto = fuentes.filter((f) => f && f.ok && f.texto);
  const sinTexto = fuentes.filter((f) => !f || !f.ok || !f.texto);

  const AGENCIAS = ["reuters", "apnews", "afp", "efe", "dpa"];
  const catDe = (dom) => {
    dom = (dom || "").toLowerCase();
    if (AGENCIAS.some((a) => dom.includes(a))) return "A (agencia)";
    return "B (medio de referencia)";
  };

  const material = conTexto
    .map((f, i) => `--- FUENTE ${i + 1}: ${f.medio} [${catDe(f.dominio)}] (${f.dominio || "dominio s/d"})
URL: ${f.url}
TEXTO:
${f.texto}`)
    .join("\n\n");

  if (conTexto.length < 3) {
    return `Sos redactor/a de Refugio Latinoamericano. El Radar detecto este hecho, pero NO se pudo acceder al texto de al menos 3 fuentes (se accedio a ${conTexto.length}). NO inventes una nota.

HECHO: ${h.titulo}
Paises: ${paises} | Region: ${h.region || "s/d"} | Ejes: ${ejes}
Fuentes con texto: ${conTexto.map((f) => f.medio).join(", ") || "ninguna"}
Fuentes sin acceso: ${sinTexto.map((f) => f.medio).join(", ") || "-"}

Responde SOLO con este unico bloque, sin ningun otro:

NOTA INCOMPLETA - INFORMACION INSUFICIENTE
En texto corrido y sin vinetas, en 2 o 3 parrafos: (1) que se sabe del hecho por el titular y el material disponible; (2) que datos centrales faltan para responder las 7W; (3) que fuentes convendria consultar. No agregues nada mas.`;
  }

  return `ROL
Sos periodista de Refugio Latinoamericano, medio de periodismo migratorio con perspectiva de derechos humanos e intercultural. Redactas un BORRADOR de nota como informe: original, verificado, narrativamente cohesionado. Es un punto de partida editable para el equipo, no la nota final.

MATERIAL (texto real de las fuentes principales del hecho; es tu materia prima exclusiva):
${material}

DATOS DEL RADAR (contexto ya clasificado; respetalo, no lo redefinas):
- Titulo detectado: ${h.titulo}
- Angulo sugerido: ${h.angulo || "s/d"}
- Paises donde ocurre: ${paises}
- Region: ${h.region || "s/d"}
- Ejes tematicos: ${ejes}${pobl ? `
- Poblaciones mencionadas: ${pobl}` : ""}
${sinTexto.length ? `
FUENTES SIN ACCESO (no uses su contenido, solo mencionalas como pendientes): ${sinTexto.map((f) => f.medio).join(", ")}` : ""}

TAREA
1. Extrae de cada fuente los hechos centrales: que paso, datos duros (cifras, fechas, nombres, cargos), declaraciones textuales, contexto.
2. Contrasta entre las fuentes: coincidencias (dato en 2+ fuentes = establecido), divergencias (si discrepan, prevalece la mayoritaria y se menciona la discrepancia con atribucion), vacios (dato en una sola fuente, se incorpora con su atribucion).
3. Sintetiza UNA pieza original. No copies frases ni la estructura de las fuentes.

REGLAS DE REDACCION
- El LEAD (primer parrafo) debe responder las 7W: quien, que, cuando, donde, por que, como y con que consecuencias. Puede extenderse a dos parrafos si hace falta.
- Atribui cada dato a su fuente en el texto: "segun EFE", "de acuerdo con Infobae", "declaro ante Reuters". Toda declaracion con nombre y cargo completos.
- No inventes datos, cifras, cargos ni declaraciones que no esten en el MATERIAL. Si un dato clave falta, marcalo "[a verificar por el equipo]".
- No opines. Solo informas hechos constatados en el material.
- Subtitulos internos declarativos y autocontenidos (oraciones completas con informacion), no metaforicos ni interrogativos.
- Parrafos cortos (max 4 lineas). Ninguna linea empieza con guion, asterisco, numero+punto ni vineta. Sin tablas.
- Respeta la categoria legal que ya fijo el Radar (migrante, refugiado, solicitante de asilo, desplazado): no la cambies.
- PROHIBIDO generar, sintetizar o parafrasear testimonios de personas migrantes. Si una fuente cita un testimonio, podes referirlo con atribucion, nunca recrearlo.

FACT CHECKING
No tenes acceso a web en vivo: NO verifiques contra fuentes externas. En el bloque de fact-checking, lista los datos centrales con su fuente y marcalos "a verificar por el equipo".

FORMATO DE SALIDA (exactamente estos bloques, en este orden, sin texto antes ni despues):

TITULO PROPUESTO
Informativo, voz activa, sin infinitivo ni signos de interrogacion/exclamacion. Max 12 palabras.

BAJADA
Una oracion que amplia el titulo con un dato clave. 20-35 palabras. No repite palabras del titulo.

LEAD
Primer parrafo con las 7W. Presenta el hecho central, no el contexto.

CUERPO
Prosa periodistica continua con subtitulos declarativos. Causas, impacto, contexto, perspectivas. Toda afirmacion atribuida.

FACT CHECKING - A VERIFICAR POR EL EQUIPO
Una linea por dato central: [dato] - [fuente] - a verificar por el equipo. Sin vinetas ni tablas.

PENDIENTES Y FUENTES A CONSULTAR
Que falta para completar la nota y que fuentes adicionales convendria sumar (inclui las fuentes sin acceso, si las hay).

Espanol rioplatense, tono sobrio, riguroso y humanizador, sin sensacionalismo.`;
}


async function viaGemini(prompt, key) {
  const r = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key=${key}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: { maxOutputTokens: 4000, temperature: 0.4 },
      }),
    }
  );
  if (!r.ok) throw new Error("HTTP " + r.status);
  const d = await r.json();
  const txt = d?.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!txt) throw new Error("respuesta vacÃ­a");
  return txt;
}

async function viaClaude(prompt, key) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": key,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: "claude-opus-4-8",
      max_tokens: 4000,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const d = await r.json();
  const txt = d?.content?.map((b) => b.text || "").join("").trim();
  if (!txt) throw new Error("respuesta vacÃ­a");
  return txt;
}

async function viaGroq(prompt, key) {
  const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + key,
    },
    body: JSON.stringify({
      model: "llama-3.3-70b-versatile",
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const d = await r.json();
  const txt = d?.choices?.[0]?.message?.content;
  if (!txt) throw new Error("respuesta vacÃ­a");
  return txt;
}

// ---------------------------------------------------------------------------
// EnvÃ­o vÃ­a API de Gmail (cuenta comÃºn + refresh token OAuth)
// Secrets: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
// ---------------------------------------------------------------------------
async function enviarPorGmail({ asunto, html, texto, env }) {
  if (!env.GMAIL_CLIENT_ID || !env.GMAIL_CLIENT_SECRET || !env.GMAIL_REFRESH_TOKEN) {
    throw new Error("Faltan credenciales de Gmail en las variables de Cloudflare");
  }

  const accessToken = await obtenerAccessToken(env);
  const raw = construirMime(asunto, html, texto);

  const r = await fetch(
    "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + accessToken,
      },
      body: JSON.stringify({ raw }),
    }
  );
  if (!r.ok) {
    const detalle = await r.text().catch(() => "");
    throw new Error("Gmail HTTP " + r.status + " " + detalle.slice(0, 200));
  }
}

async function obtenerAccessToken(env) {
  const r = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env.GMAIL_CLIENT_ID,
      client_secret: env.GMAIL_CLIENT_SECRET,
      refresh_token: env.GMAIL_REFRESH_TOKEN,
      grant_type: "refresh_token",
    }),
  });
  if (!r.ok) {
    const detalle = await r.text().catch(() => "");
    throw new Error("OAuth HTTP " + r.status + " " + detalle.slice(0, 200));
  }
  const d = await r.json();
  if (!d.access_token) throw new Error("No se obtuvo access_token");
  return d.access_token;
}

function construirMime(asunto, html, texto) {
  const limite = "limite_refugio_" + Date.now();
  const asuntoEnc = "=?UTF-8?B?" + base64(utf8(asunto)) + "?=";

  const mensaje =
    `From: ${REMITENTE.nombre} <${REMITENTE.email}>\r\n` +
    `To: ${DESTINATARIOS.join(", ")}\r\n` +
    `Subject: ${asuntoEnc}\r\n` +
    `MIME-Version: 1.0\r\n` +
    `Content-Type: multipart/alternative; boundary="${limite}"\r\n\r\n` +
    `--${limite}\r\n` +
    `Content-Type: text/plain; charset="UTF-8"\r\n` +
    `Content-Transfer-Encoding: base64\r\n\r\n` +
    `${base64(utf8(texto))}\r\n\r\n` +
    `--${limite}\r\n` +
    `Content-Type: text/html; charset="UTF-8"\r\n` +
    `Content-Transfer-Encoding: base64\r\n\r\n` +
    `${base64(utf8(html))}\r\n\r\n` +
    `--${limite}--`;

  return base64(utf8(mensaje))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function armarHtml(h, borrador) {
  const medios = Array.isArray(h.medios) ? h.medios.join(", ") : (h.medios || "s/d");
  const cuerpo = borrador
    .split("\n")
    .map((l) => (l.trim() ? `<p style="margin:0 0 12px">${escapar(l)}</p>` : ""))
    .join("");

  return `<div style="font-family:Georgia,serif;max-width:640px;margin:auto;color:#1a1a1a">
    <div style="border-left:4px solid #c0392b;padding-left:16px;margin-bottom:24px">
      <p style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#888;margin:0">Radar Migratorio Â· Borrador automÃ¡tico</p>
      <h1 style="font-size:22px;margin:8px 0 0">${escapar(h.titulo)}</h1>
    </div>
    ${cuerpo}
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
    <p style="font-size:12px;color:#999">Medios: ${escapar(medios)}${h.url ? ` Â· <a href="${escapar(h.url)}">enlace de referencia</a>` : ""}</p>
    <p style="font-size:12px;color:#999">Borrador editable generado automÃ¡ticamente. VerificÃ¡ antes de publicar.</p>
  </div>`;
}

function escapar(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function utf8(str) { return new TextEncoder().encode(str); }
function base64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function json(obj, status) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    },
  });
}
function preflight() {
  return new Response(null, {
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}
