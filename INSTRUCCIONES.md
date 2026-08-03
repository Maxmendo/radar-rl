# Sistema de borradores del Radar Migratorio — puesta en marcha

Flujo nuevo: apretás **"Generar borrador"** en el dashboard → una Cloudflare
Function redacta el borrador y lo manda por correo. Sin GitHub, sin IDs, sin
descargar artifacts.

Todo vive dentro de `radar-rl`, en la misma infraestructura de Cloudflare que ya
sirve el dashboard.

---

## 1. Sumar la function al repo

Copiá el archivo a la carpeta `functions/` en la raíz de `radar-rl`:

```
radar-rl/
├── functions/
│   └── generar-borrador.js   ← nuevo
├── docs/
│   └── index.html            ← tu dashboard
└── ...
```

En Cloudflare Pages, cualquier archivo dentro de `functions/` se vuelve un
endpoint automáticamente. `functions/generar-borrador.js` queda disponible en
`https://TU-DASHBOARD/generar-borrador`. No hay que configurar rutas.

> Nota: si tu dashboard se sirve desde la subcarpeta `docs/`, confirmá que en la
> configuración de Cloudflare Pages el "build output directory" apunte a la raíz
> del repo (o que `functions/` quede al mismo nivel que el output). Si el sitio
> se sirve desde `docs/`, mové `functions/` de modo que Cloudflare la vea. Si
> algo falla, avisame y lo ajustamos según cómo tengas configurado Pages.

---

## 2. Cargar las variables de entorno en Cloudflare

En el panel de Cloudflare → tu proyecto de Pages → **Settings → Environment
variables**, agregá (como *Secret*):

| Variable              | Para qué                                       | ¿Obligatoria?         |
|-----------------------|------------------------------------------------|-----------------------|
| `GMAIL_CLIENT_ID`     | Autenticar contra Gmail                        | Sí                    |
| `GMAIL_CLIENT_SECRET` | Autenticar contra Gmail                        | Sí                    |
| `GMAIL_REFRESH_TOKEN` | Permite enviar sin que estés presente          | Sí                    |
| `GEMINI_API_KEY`      | Redactar con Gemini (primero en la cascada)    | Al menos una de estas |
| `ANTHROPIC_API_KEY`   | Redactar con Claude (segundo en la cascada)    | tres claves de modelo |
| `GROQ_API_KEY`        | Redactar con Groq (último recurso)             | debe estar cargada    |

La cascada de modelos usa la primera clave que encuentre y cae a la siguiente si
falla. Con una alcanza; cargá las tres para máxima resiliencia.

Las tres credenciales de Gmail se obtienen en el paso 2-bis.

---

## 2-bis. Obtener las credenciales de Gmail (una sola vez)

Como es una cuenta de Gmail común (no Workspace), el envío automático usa OAuth
con un *refresh token*. Se configura una vez y queda andando para siempre.

**a) Crear las credenciales OAuth en Google Cloud (gratis)**

1. Entrá a https://console.cloud.google.com/ con la cuenta
   `refugiolatinoamericano@gmail.com`.
2. Creá un proyecto nuevo (ej. "Radar Borradores").
3. **APIs y servicios → Biblioteca** → buscá **Gmail API** → Habilitar.
4. **APIs y servicios → Pantalla de consentimiento OAuth**:
   - Tipo: **Externo**.
   - Completá nombre de la app y tu correo. Guardá.
   - En **Usuarios de prueba**, agregá `refugiolatinoamericano@gmail.com`.
     (Con la app en modo "prueba" alcanza; no hace falta publicarla.)
5. **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de
   OAuth**:
   - Tipo de aplicación: **Aplicación web**.
   - En **URIs de redireccionamiento autorizados** agregá:
     `https://developers.google.com/oauthplayground`
   - Crear. Anotá el **Client ID** y el **Client Secret**.

**b) Generar el refresh token con OAuth Playground**

1. Entrá a https://developers.google.com/oauthplayground/
2. Arriba a la derecha, ⚙ (Settings) → tildá **Use your own OAuth credentials**
   → pegá tu Client ID y Client Secret.
3. En el panel izquierdo, en "Input your own scopes", pegá:
   `https://www.googleapis.com/auth/gmail.send`
4. **Authorize APIs** → iniciá sesión con `refugiolatinoamericano@gmail.com` y
   aceptá. (Si aparece "Google no verificó esta app", entrá por
   "Configuración avanzada → Ir a la app".)
5. **Exchange authorization code for tokens**.
6. Copiá el **Refresh token** que aparece.

**c) Cargar en Cloudflare** los tres valores como secrets:
`GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`.

> El correo saldrá **desde** `refugiolatinoamericano@gmail.com` (Gmail no permite
> falsear el remitente). Igual llega a las dos casillas de destino, incluida
> `contacto@refugiolatinoamericano.com`.

---

## 3. Poner el botón en el dashboard

En el módulo que genera el HTML de las tarjetas (donde hoy se dibuja el botón
que disparaba GitHub):

1. Reemplazá el botón viejo por uno con clase `btn-borrador` y los datos del
   hecho en atributos `data-*` (título, resumen, país, medios, tags,
   importancia). Ver `boton-dashboard.html`.
2. Pegá el `<script>` una sola vez al final del `<body>`.

Los `data-*` son la clave: el navegador le manda a la function el hecho completo,
así no hace falta ningún almacén compartido ni pasar IDs.

---

## 4. Eliminar el workflow viejo de GitHub

Ya no se usa. Borralo del repo:

```bash
cd radar-rl
git rm .github/workflows/borrador.yml
git commit -m "Elimina borrador.yml: los borradores ahora salen por Cloudflare Function"
git push
```

Con esto desaparece la pestaña "Generar borrador" de la sección Actions de
GitHub. El workflow "Radar migratorio" (`radar.yml`) queda intacto: ese sigue
siendo el que corre las ingestas programadas.

---

## 5. Probar

1. Abrí el dashboard.
2. Apretá "Generar borrador" en cualquier hecho.
3. El botón muestra "Redactando y enviando…" y luego "✓ Enviado por correo".
4. Revisá `refugiolatinoamericano@gmail.com` y
   `contacto@refugiolatinoamericano.com`.

Si algo falla, el botón lo dice y el detalle queda en la consola del navegador
(F12 → Console).

---

## Sumar destinatarios del equipo (cuando la prueba funcione)

Editá la lista `DESTINATARIOS` al inicio de `generar-borrador.js` y agregá los
correos. Nada más.
