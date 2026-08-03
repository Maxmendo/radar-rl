// functions/generar-borrador.js
// Cloudflare Pages Function — endpoint POST /generar-borrador
//
// Flujo: el botón "Generar borrador" del dashboard hace fetch a esta ruta
// con los datos del hecho -> se redacta el borrador con la cascada de modelos
// -> se envía por correo a la lista de la etapa de prueba.
//
// No usa GitHub, no expone claves en el navegador (viven en las env vars de
// Cloudflare), no genera artifacts ni IDs para el usuario.

// --- Destinatarios de la etapa de prueba ---
const DESTINATARIOS = [
  "refugiolatinoamericano@gmail.com",
  "contacto@refugiolatinoamericano.com",
];

// Con Gmail común, el correo sale desde la cuenta que autorizó el refresh token.
// Debe ser esa misma dirección (Gmail no deja falsear el remitente).
const REMITENTE = {
  email: "refugiolatinoamericano@gmail.com",
  nombre: "Radar Migratorio",
};

// ---------------------------------------------------------------------------
// Handler principal
// ---------------------------------------------------------------------------
export async function onRequestPost(context) {
  const { request, env } = context;

  // CORS básico por si el dashboard se sirve desde otro subdominio
  const cors = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };

  let hecho;
  try {
    hecho = await request.json();
  } catch {
    return json({ ok: false, error: "Cuerpo inválido" }, 400, cors);
  }

  // El dashboard manda el hecho completo (título, medios, notas, tags, etc.)
  // así no dependemos de ningún almacén compartido.
  const { titulo, resumen, medios, notas, tags, pais, importancia } = hecho || {};
  if (!titulo) {
    return json({ ok: false, error: "Falta el título del hecho" }, 400, cors);
  }

  // 1) Redactar el borrador con la cascada de modelos
  let borrador;
  try {
    borrador = await redactarBorrador(hecho, env);
  } catch (e) {
    return json({ ok: false, error: "Fallo al redactar: " + e.message }, 502, cors);
  }

  // 2) Enviar el borrador por correo
  try {
    await enviarCorreo({
      asunto: `📝 Borrador: ${titulo}`,
      cuerpoHtml: armarHtmlCorreo(titulo, borrador, hecho),
      cuerpoTexto: `${titulo}\n\n${borrador}`,
      env,
    });
  } catch (e) {
    return json({ ok: false, error: "Redactado pero falló el envío: " + e.message }, 502, cors);
  }

  return json({ ok: true, mensaje: "Borrador enviado por correo." }, 200, cors);
}

// Preflight CORS
export async function onRequestOptions() {
  return new Response(null, {
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    },
  });
}

// ---------------------------------------------------------------------------
// Redacción con cascada de modelos: Gemini -> Claude -> Groq
// (mismo orden de preferencia que ya usás; cada uno es opcional según qué
//  claves tengas cargadas en Cloudflare)
// ---------------------------------------------------------------------------
async function redactarBorrador(hecho, env) {
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

  throw new Error("Ningún modelo respondió. " + errores.join(" | "));
}

// Prompt editorial alineado a Refugio + guía ACNUR (no estigmatizante)
function construirPrompt(hecho) {
  const { titulo, resumen, medios, notas, tags, pais } = hecho;
  const listaMedios = Array.isArray(medios) ? medios.join(", ") : (medios || "s/d");
  const listaTags = Array.isArray(tags) ? tags.join(", ") : (tags || "s/d");

  return `Sos redactor/a de Refugio Latinoamericano, medio digital de periodismo migratorio desde una perspectiva de derechos humanos e intercultural.

Redactá un BORRADOR de nota periodística a partir del siguiente hecho detectado por el Radar Migratorio. El borrador es un punto de partida editable para el equipo, no una nota final.

HECHO:
- Título: ${titulo}
- Resumen / ángulo sugerido: ${resumen || "s/d"}
- País principal: ${pais || "s/d"}
- Medios que lo cubrieron: ${listaMedios}
- Ejes temáticos: ${listaTags}

PAUTAS EDITORIALES OBLIGATORIAS:
- Aplicá la guía de ACNUR para cobertura no estigmatizante de la migración.
- No reduzcas a las personas a su condición migratoria ("un migrante", "los ilegales" están prohibidos).
- Enmarcá desde derechos humanos. Nunca criminalices ni deshumanices.
- No inventes datos, cifras ni declaraciones que no estén en el material fuente. Si falta información, indicá "[verificar]" en el texto.
- Señalá al final una lista breve de "Pendientes de verificación" y "Fuentes a consultar".

FORMATO DE SALIDA:
1. Título propuesto (puede diferir del detectado, mejorándolo)
2. Bajada (1-2 oraciones)
3. Cuerpo del borrador (3-5 párrafos)
4. Pendientes de verificación
5. Fuentes a consultar

Escribí en español rioplatense, tono sobrio y riguroso.`;
}

// --- Gemini ---
async function viaGemini(prompt, key) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${key}`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const d = await r.json();
  const txt = d?.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!txt) throw new Error("respuesta vacía");
  return txt;
}

// --- Claude ---
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
      max_tokens: 2000,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!r.ok) throw new Error("HTTP " + r.status);
  const d = await r.json();
  const txt = d?.content?.map((b) => b.text || "").join("").trim();
  if (!txt) throw new Error("respuesta vacía");
  return txt;
}

// --- Groq ---
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
  if (!txt) throw new Error("respuesta vacía");
  return txt;
}

// ---------------------------------------------------------------------------
// Envío de correo vía API de Gmail (cuenta Gmail común + OAuth refresh token).
//
// Necesita tres secrets en Cloudflare:
//   GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN
// El correo sale desde la cuenta que autorizó el refresh token.
// ---------------------------------------------------------------------------
async function enviarCorreo({ asunto, cuerpoHtml, cuerpoTexto, env }) {
  if (!env.GMAIL_CLIENT_ID || !env.GMAIL_CLIENT_SECRET || !env.GMAIL_REFRESH_TOKEN) {
    throw new Error("Faltan credenciales de Gmail (CLIENT_ID / CLIENT_SECRET / REFRESH_TOKEN) en Cloudflare");
  }

  // 1) Intercambiar el refresh token por un access token de corta vida
  const accessToken = await obtenerAccessToken(env);

  // 2) Construir el mensaje MIME (multipart: texto + html)
  const raw = construirMimeBase64(asunto, cuerpoHtml, cuerpoTexto);

  // 3) Enviar vía Gmail API
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

// Canjea el refresh token por un access token vigente
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

// Arma el mensaje MIME y lo codifica en base64url (formato que pide Gmail API)
function construirMimeBase64(asunto, cuerpoHtml, cuerpoTexto) {
  const limite = "limite_refugio_" + Date.now();
  // Asunto codificado para soportar acentos/emoji (RFC 2047)
  const asuntoEnc = "=?UTF-8?B?" + base64(utf8Bytes(asunto)) + "?=";

  const mensaje =
    `From: ${REMITENTE.nombre} <${REMITENTE.email}>\r\n` +
    `To: ${DESTINATARIOS.join(", ")}\r\n` +
    `Subject: ${asuntoEnc}\r\n` +
    `MIME-Version: 1.0\r\n` +
    `Content-Type: multipart/alternative; boundary="${limite}"\r\n\r\n` +
    `--${limite}\r\n` +
    `Content-Type: text/plain; charset="UTF-8"\r\n` +
    `Content-Transfer-Encoding: base64\r\n\r\n` +
    `${base64(utf8Bytes(cuerpoTexto))}\r\n\r\n` +
    `--${limite}\r\n` +
    `Content-Type: text/html; charset="UTF-8"\r\n` +
    `Content-Transfer-Encoding: base64\r\n\r\n` +
    `${base64(utf8Bytes(cuerpoHtml))}\r\n\r\n` +
    `--${limite}--`;

  // base64url (Gmail lo exige: +/ -> -_ y sin padding)
  return base64(utf8Bytes(mensaje))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

// Helpers de codificación (el runtime de Workers no tiene Buffer)
function utf8Bytes(str) {
  return new TextEncoder().encode(str);
}
function base64(bytes) {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function armarHtmlCorreo(titulo, borrador, hecho) {
  const medios = Array.isArray(hecho.medios) ? hecho.medios.join(", ") : (hecho.medios || "s/d");
  const cuerpo = borrador
    .split("\n")
    .map((l) => (l.trim() ? `<p style="margin:0 0 12px">${escapar(l)}</p>` : ""))
    .join("");

  return `<div style="font-family:Georgia,serif;max-width:640px;margin:auto;color:#1a1a1a">
    <div style="border-left:4px solid #c0392b;padding-left:16px;margin-bottom:24px">
      <p style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#888;margin:0">Radar Migratorio · Borrador automático</p>
      <h1 style="font-size:22px;margin:8px 0 0">${escapar(titulo)}</h1>
    </div>
    ${cuerpo}
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
    <p style="font-size:12px;color:#999">Hecho detectado · Medios: ${escapar(medios)}</p>
    <p style="font-size:12px;color:#999">Este es un borrador editable generado automáticamente. Verificá antes de publicar.</p>
  </div>`;
}

function escapar(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function json(obj, status, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...extraHeaders },
  });
}
