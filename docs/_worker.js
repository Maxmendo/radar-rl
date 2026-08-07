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

    // --- DIAGNOSTICO TEMPORAL: probar si Cloudflare puede bajar una fuente ---
    // Uso: /probar-fuente?url=<url de Google News>
    // Devuelve la URL real resuelta, el dominio y cuantos caracteres bajo.
    // Sacar este bloque una vez confirmado.
    if (url.pathname === "/probar-fuente") {
      const objetivo = url.searchParams.get("url");
      if (!objetivo) return json({ ok: false, error: "falta ?url=" }, 400);
      try {
        const { urlReal, dominio, texto } = await bajarUnaFuente(objetivo);
        return json({
          ok: true,
          url_original: objetivo,
          url_real: urlReal,
          dominio: dominio,
          caracteres: texto ? texto.length : 0,
          muestra: texto ? texto.slice(0, 300) : "",
        }, 200);
      } catch (e) {
        return json({ ok: false, error: (e && e.message) || "fallo",
                      tipo: (e && e.name) || "" }, 200);
      }
    }

    // --- Todo lo demás: el dashboard y sus archivos estáticos ---
    return env.ASSETS.fetch(request);
  },
};

// ---------------------------------------------------------------------------
// Descarga de fuentes desde el Worker (IP de Cloudflare)
// ---------------------------------------------------------------------------
// Portado de nucleo/textos.py. Resuelve la URL de Google News y baja el texto.
// La resolucion de las URLs CBMi requiere pedir dos tokens y llamar a
// batchexecute; si falla, se intenta extraer la URL directa del HTML.
const UA_NAV = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";
const HDRS = {
  "User-Agent": UA_NAV,
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
};

async function resolverGoogleNews(gurl) {
  if (!/news\.google\.com/.test(gurl)) return gurl;
  const r = await fetch(gurl, { headers: HDRS, redirect: "follow" });
  const finalUrl = r.url || gurl;
  if (!/news\.google\.com/.test(finalUrl)) return finalUrl;  // ya redirigio
  const html = await r.text();

  // Tokens para batchexecute.
  const sig = html.match(/data-n-a-sg="([^"]+)"/);
  const ts = html.match(/data-n-a-ts="([^"]+)"/);
  const id = html.match(/data-n-a-id="([^"]+)"/);
  if (!sig || !ts) {
    const m = html.match(/https?:\/\/(?!news\.google\.com|www\.google\.com)[^"'\s<>\\]+/);
    return m ? m[0] : gurl;
  }
  const artId = id ? id[1] : gurl.split("/").pop().split("?")[0];
  const inner = JSON.stringify(["garturlreq",
    [["X", "X", ["X", "X"], null, null, 1, 1, "US:en", null, 1, null, null, null,
      null, null, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, null, 0, 0, null, 0],
    artId, ts[1], sig[1]]);
  const body = "f.req=" + encodeURIComponent(JSON.stringify([[["Fbv4je", inner]]]));
  const r2 = await fetch("https://news.google.com/_/DotsSplashUi/data/batchexecute", {
    method: "POST", body,
    headers: { ...HDRS, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
  });
  const txt = await r2.text();
  const m = txt.match(/https?:\/\/(?!news\.google\.com)[^"'\s\\]+/);
  return m ? m[0] : gurl;
}

function dominioDe(u) {
  try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return ""; }
}

function extraerTextoJS(html) {
  if (!html) return "";
  let h = html.replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<!--[\s\S]*?-->/g, " ");
  const art = h.match(/<article[\s\S]*?<\/article>/i);
  if (art) h = art[0];
  const parrafos = [...h.matchAll(/<p[^>]*>([\s\S]*?)<\/p>/gi)]
    .map((m) => m[1].replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim())
    .filter((p) => p.length > 40);
  let texto = parrafos.join("\n\n");
  if (!texto) texto = h.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  return texto.slice(0, 4000);
}

async function bajarUnaFuente(gurl) {
  const real = await resolverGoogleNews(gurl);
  if (/news\.google\.com/.test(real)) {
    return { urlReal: real, dominio: "", texto: "" };  // no se resolvio
  }
  const r = await fetch(real, { headers: HDRS, redirect: "follow" });
  const html = await r.text();
  return { urlReal: real, dominio: dominioDe(real), texto: extraerTextoJS(html) };
}


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
      asunto: `Borrador: ${hecho.titulo}`,
      html: armarHtml(hecho, borrador),
      texto: `${hecho.titulo}\n\n${borrador}`,
      env,
    });
  } catch (e) {
    return json({ ok: false, error: "Redactado, pero falló el envío: " + e.message }, 502);
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
// Redacción con cascada Gemini -> Claude -> Groq (usa las claves que existan)
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

  throw new Error("Ningún modelo respondió. " + errores.join(" | "));
}

function construirPrompt(h) {
  const ejes = Array.isArray(h.ejes) ? h.ejes.join(", ") : (h.ejes || "s/d");
  const paises = Array.isArray(h.paises) ? h.paises.join(", ") : (h.paises || h.pais || "s/d");
  const pobl = Array.isArray(h.poblaciones) ? h.poblaciones.join(", ") : "";

  const fuentes = Array.isArray(h.fuentes_texto) ? h.fuentes_texto : [];
  const conTexto = fuentes.filter((f) => f && f.ok && f.texto);
  const sinTexto = fuentes.filter((f) => !f || !f.ok || !f.texto);

  const AGENCIAS = ["reuters", "apnews", "afp", "efe", "dpa", "europapress", "ansa"];
  const LEGACY = ["infobae", "clarin", "lanacion", "pagina12", "eltiempo", "elpais",
    "elmundo", "abc.es", "lavanguardia", "milenio", "eluniversal", "proceso",
    "latercera", "semana", "elespectador", "bbc", "cnn", "univision", "telemundo",
    "france24", "dw.com", "aljazeera", "nytimes", "washingtonpost", "theguardian",
    "abc7", "elcomercio", "oglobo", "folha", "elnuevoherald"];
  const nivelDe = (f) => {
    const d = ((f.dominio || "") + " " + (f.medio || "")).toLowerCase().replace(/\s/g, "");
    if (AGENCIAS.some((a) => d.includes(a))) return 0;   // agencia
    if (LEGACY.some((a) => d.includes(a))) return 1;     // legacy / referencia
    return 2;                                            // otro
  };
  const catDe = (f) => (nivelDe(f) === 0 ? "A (agencia)"
    : nivelDe(f) === 1 ? "B (medio de referencia)" : "C (otro medio)");

  const material = conTexto
    .map((f, i) => `--- FUENTE ${i + 1}: ${f.medio} [${catDe(f)}] (${f.dominio || "dominio s/d"})
URL: ${f.url}
TEXTO:
${f.texto}`)
    .join("\n\n");

  // Umbral: basta con 3 fuentes con texto para redactar (criterio editorial:
  // el fact-check y la evaluacion de confiabilidad los hace el equipo). Menos de
  // 3 no da material para contrastar, asi que ahi si va nota incompleta.
  const suficiente = conTexto.length >= 3;

  if (!suficiente) {
    return `Sos redactor/a de Refugio Latinoamericano. El Radar detecto este hecho, pero solo se accedio al texto de ${conTexto.length} fuente(s), menos de las 3 necesarias para contrastar. NO inventes una nota.

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

PENDIENTES DE VERIFICACION
Que datos faltan para completar la nota y que fuentes oficiales o adicionales convendria consultar (por ejemplo organismos, voceros, o las fuentes que quedaron sin acceso). NO listes aca los medios que ya usaste: de eso se encarga el sistema aparte. En prosa, sin vinetas.

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
      max_tokens: 4000,
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

  // Rotulos de bloque que devuelve el prompt: se muestran como encabezados.
  const ROTULOS = [
    "TITULO PROPUESTO", "BAJADA", "LEAD", "CUERPO",
    "FACT CHECKING - A VERIFICAR POR EL EQUIPO", "FACT CHECKING",
    "PENDIENTES DE VERIFICACION", "PENDIENTES Y FUENTES A CONSULTAR", "PENDIENTES",
    "NOTA INCOMPLETA - INFORMACION INSUFICIENTE", "NOTA INCOMPLETA",
  ];
  const esRotulo = (l) => {
    const t = l.trim().replace(/[:.]+$/, "").toUpperCase();
    return ROTULOS.includes(t);
  };

  const cuerpo = borrador
    .split("\n")
    .map((l) => {
      const t = l.trim();
      if (!t) return "";
      if (esRotulo(t)) {
        return `<h2 style="font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#c0392b;margin:22px 0 6px;font-family:Arial,sans-serif">${escapar(t.replace(/[:.]+$/, ""))}</h2>`;
      }
      return `<p style="margin:0 0 12px;line-height:1.55">${escapar(t)}</p>`;
    })
    .join("");

  // Fuentes efectivamente usadas (las que bajaron texto), ordenadas por
  // jerarquia (agencia > legacy > resto), cada una con su enlace real.
  const AGEN = ["reuters", "apnews", "afp", "efe", "dpa", "europapress", "ansa"];
  const LEG = ["infobae", "clarin", "lanacion", "pagina12", "eltiempo", "elpais",
    "elmundo", "abc.es", "lavanguardia", "milenio", "eluniversal", "proceso",
    "latercera", "semana", "elespectador", "bbc", "cnn", "univision", "telemundo",
    "france24", "dw.com", "aljazeera", "nytimes", "washingtonpost", "theguardian",
    "abc7", "elcomercio", "oglobo", "folha", "elnuevoherald", "rionegro"];
  const nivel = (f) => {
    const d = ((f.dominio || "") + " " + (f.medio || "")).toLowerCase().replace(/\s/g, "");
    if (AGEN.some((a) => d.includes(a))) return 0;
    if (LEG.some((a) => d.includes(a))) return 1;
    return 2;
  };
  const usadas = (Array.isArray(h.fuentes_texto) ? h.fuentes_texto : [])
    .filter((f) => f && f.ok && f.texto)
    .sort((a, b) => nivel(a) - nivel(b));
  const listaFuentes = usadas.length
    ? `<p style="font-size:13px;color:#555;margin:0 0 6px"><strong>Fuentes utilizadas</strong> (por jerarquía):</p>
       <ol style="font-size:13px;color:#555;margin:0 0 12px;padding-left:20px">${
         usadas.map((f) => `<li style="margin:0 0 4px"><a href="${escapar(f.url)}" style="color:#c0392b">${escapar(f.medio)}</a></li>`).join("")
       }</ol>`
    : `<p style="font-size:12px;color:#999">Medios: ${escapar(medios)}</p>`;

  return `<div style="font-family:Georgia,serif;max-width:640px;margin:auto;color:#1a1a1a">
    <div style="border-left:4px solid #c0392b;padding-left:16px;margin-bottom:24px">
      <p style="font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#888;margin:0">Radar Migratorio · Borrador automático</p>
      <h1 style="font-size:22px;margin:8px 0 0">${escapar(h.titulo)}</h1>
    </div>
    ${cuerpo}
    <hr style="border:none;border-top:1px solid #eee;margin:24px 0">
    ${listaFuentes}
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
