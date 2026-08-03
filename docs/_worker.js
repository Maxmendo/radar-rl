// docs/_worker.js
// Worker en modo "static assets" (el modelo unificado de Cloudflare 2026).
//
// Toma control de TODAS las requests entrantes:
//   - POST /generar-borrador  -> redacta el borrador y lo envía por correo
//   - cualquier otra ruta      -> sirve el dashboard estático (env.ASSETS)
//
// Importante: si no reenviáramos lo demás a env.ASSETS, el dashboard dejaría
// de verse. Por eso el fallback final es obligatorio.

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // --- Endpoint del botón ---
    if (url.pathname === "/generar-borrador") {
      if (request.method === "OPTIONS") return preflight();
      if (request.method === "POST") return manejarBorrador(request, env);
      return json({ ok: false, error: "Método no permitido" }, 405);
    }

    // --- Todo lo demás: el dashboard y sus archivos estáticos ---
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

// Con Gmail común, el remitente debe ser la cuenta que autorizó el token.
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
    return json({ ok: false, error: "Cuerpo inválido" }, 400);
  }

  if (!hecho || !hecho.titulo) {
    return json({ ok: false, error: "Falta el título del hecho" }, 400);
  }

  let borrador;
  try {
    borrador = await redactar(hecho, env);
  } catch (e) {
    return json({ ok: false, error: "Fallo al redactar: " + e.message }, 502);
  }

  try {
    await enviarPorGmail({
      asunto: `📝 Borrador: ${hecho.titulo}`,
      html: armarHtml(hecho, borrador),
      texto: `${hecho.titulo}\n\n${borrador}`,
      env,
    });
  } catch (e) {
    return json({ ok: false, error: "Redactado, pero falló el envío: " + e.message }, 502);
  }

  return json({ ok: true, mensaje: "Borrador enviado por correo." }, 200);
}

// ---------------------------------------------------------------------------
// Redacción con cascada Gemini -> Claude -> Groq (usa las claves que existan)
// ---------------------------------------------------------------------------
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

  throw new Error("Ningún modelo respondió. " + errores.join(" | "));
}

function construirPrompt(h) {
  const medios = Array.isArray(h.medios) ? h.medios.join(", ") : (h.medios || "s/d");
  const ejes = Array.isArray(h.ejes) ? h.ejes.join(", ") : (h.ejes || "s/d");
  const paises = Array.isArray(h.paises) ? h.paises.join(", ") : (h.paises || h.pais || "s/d");

  return `Sos redactor/a de Refugio Latinoamericano, medio digital de periodismo migratorio desde una perspectiva de derechos humanos e intercultural.

Redactá un BORRADOR de nota a partir del siguiente hecho detectado por el Radar Migratorio. Es un punto de partida editable para el equipo, no una nota final.

HECHO:
- Título original: ${h.titulo}
- Ángulo sugerido: ${h.angulo || "s/d"}
- Países: ${paises}
- Región: ${h.region || "s/d"}
- Medios que lo cubrieron: ${medios}
- Ejes temáticos: ${ejes}
- Enlace de referencia: ${h.url || "s/d"}

PAUTAS EDITORIALES OBLIGATORIAS:
- Aplicá la guía de ACNUR para cobertura no estigmatizante de la migración.
- No reduzcas a las personas a su condición migratoria. Prohibido "un migrante", "ilegales".
- Enmarcá desde derechos humanos. No criminalices ni deshumanices.
- No inventes datos, cifras ni declaraciones que no estén en el material fuente. Si falta algo, marcá "[verificar]".
- Cerrá con "Pendientes de verificación" y "Fuentes a consultar".

FORMATO:
1. Título propuesto
2. Bajada (1-2 oraciones)
3. Cuerpo (3-5 párrafos)
4. Pendientes de verificación
5. Fuentes a consultar

Español rioplatense, tono sobrio y riguroso.`;
}

async function viaGemini(prompt, key) {
  const r = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${key}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }] }),
    }
  );
  if (!r.ok) throw new Error("HTTP " + r.status);
  const d = await r.json();
  const txt = d?.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!txt) throw new Error("respuesta vacía");
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
// Envío vía API de Gmail (cuenta común + refresh token OAuth)
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
      <p style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#888;margin:0">Radar Migratorio · Borrador automático</p>
      <h1 style="font-size:22px;margin:8px 0 0">${escapar(h.titulo)}</h1>
    </div>
    ${cuerpo}
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
    <p style="font-size:12px;color:#999">Medios: ${escapar(medios)}${h.url ? ` · <a href="${escapar(h.url)}">enlace de referencia</a>` : ""}</p>
    <p style="font-size:12px;color:#999">Borrador editable generado automáticamente. Verificá antes de publicar.</p>
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
