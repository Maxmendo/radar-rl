"""Envio de correo por SMTP. Alertas editoriales y borradores.

POR QUE SMTP Y NO ISSUES DE GITHUB
-----------------------------------
Los issues notifican solo a colaboradores del repositorio, y eso exige que cada
persona del equipo tenga cuenta de GitHub. Inviable para una redaccion.

Cloudflare Access tampoco sirve: controla quien ENTRA al tablero, pero no lleva
registro de usuarios ni puede enviar nada. Verifica un codigo al momento de
entrar y nada mas.

Un envio SMTP directo no necesita que el destinatario tenga cuenta de ningun
lado: solo un correo.

CONFIGURACION
-------------
Requiere dos secretos en GitHub (Settings > Secrets and variables > Actions):

  CORREO_USUARIO    la casilla desde la que se envia
  CORREO_CLAVE      contrasena de aplicacion, NO la del correo

Con Gmail hay que generar una "contrasena de aplicacion" en la configuracion de
seguridad de la cuenta de Google; la contrasena normal no funciona para SMTP.

Los destinatarios se listan en fuentes.yaml, seccion `correo`. No van en los
secretos porque no son informacion sensible y conviene que se vean y se editen
sin tocar la configuracion del repositorio.

Si faltan las credenciales, el modulo avisa y no falla: el resto del sistema
sigue funcionando.
"""

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate

log = logging.getLogger("correo")

SERVIDOR = "smtp.gmail.com"
PUERTO = 465
REMITENTE = "Radar Migratorio · Refugio Latinoamericano"


def hay_credenciales() -> bool:
    """True si estan las dos variables de entorno necesarias."""
    return bool(os.environ.get("CORREO_USUARIO") and os.environ.get("CORREO_CLAVE"))


def enviar(destinatarios: list[str], asunto: str, texto: str,
           html: str | None = None, servidor: str = SERVIDOR,
           puerto: int = PUERTO) -> bool:
    """Envia un correo. Devuelve True si salio.

    Nunca lanza excepcion: un fallo de correo no debe tumbar la corrida del
    radar. Se registra el motivo y se sigue.
    """
    usuario = os.environ.get("CORREO_USUARIO")
    clave = os.environ.get("CORREO_CLAVE")

    if not usuario or not clave:
        log.warning("   sin credenciales de correo (CORREO_USUARIO / CORREO_CLAVE)")
        return False
    if not destinatarios:
        log.warning("   sin destinatarios configurados")
        return False

    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = formataddr((REMITENTE, usuario))
    msg["To"] = ", ".join(destinatarios)
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")

    try:
        contexto = ssl.create_default_context()
        with smtplib.SMTP_SSL(servidor, puerto, context=contexto, timeout=30) as s:
            s.login(usuario, clave)
            s.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        log.warning("   autenticacion rechazada. Con Gmail hace falta una "
                    "CONTRASENA DE APLICACION, no la del correo.")
        return False
    except Exception as e:
        log.warning("   no se pudo enviar (%s): %s", type(e).__name__, str(e)[:120])
        return False

    log.info("   enviado a %s", ", ".join(destinatarios))
    return True


ESTILO = """
body{font:15px/1.6 -apple-system,'Segoe UI',Roboto,sans-serif;color:#3a2e2e;
  background:#fbf9f8;margin:0;padding:24px}
.caja{max-width:640px;margin:0 auto;background:#fff;border:1px solid #eae3e1;
  border-radius:10px;overflow:hidden}
.cab{background:#ff5f5d;color:#fff;padding:18px 22px}
.cab h1{margin:0;font-size:17px;font-weight:700}
.cab p{margin:2px 0 0;font-size:13px;opacity:.94}
.cuerpo{padding:20px 22px}
h2{font-size:16px;margin:0 0 10px;line-height:1.4}
h2 a{color:#3a2e2e;text-decoration:none}
table{border-collapse:collapse;width:100%;margin:0 0 14px;font-size:13px}
td{padding:5px 0;border-bottom:1px solid #f2ece9;color:#806e6e}
td.v{color:#3a2e2e;font-weight:600;text-align:right}
.angulo{border-left:3px solid #12805c;padding:2px 0 2px 10px;margin:0 0 14px;
  font-size:14px}
.medios{font-size:13px;color:#806e6e;margin:0 0 6px}
.medios a{color:#806e6e}
.aviso{background:#fff6f5;border:1px solid #f3d4d0;border-radius:6px;
  padding:10px 12px;font-size:13px;color:#9a3412;margin:14px 0 0}
.pie{padding:14px 22px;background:#fbf9f8;border-top:1px solid #eae3e1;
  font-size:12px;color:#a2938f;line-height:1.6}
"""


def envoltura(titulo: str, bajada: str, contenido: str, pie: str) -> str:
    """Arma el HTML del correo con la identidad visual de Refugio."""
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><style>{ESTILO}</style>"
            f"</head><body><div class='caja'>"
            f"<div class='cab'><h1>{titulo}</h1><p>{bajada}</p></div>"
            f"<div class='cuerpo'>{contenido}</div>"
            f"<div class='pie'>{pie}</div></div></body></html>")
