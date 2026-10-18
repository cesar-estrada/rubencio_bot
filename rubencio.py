# -*- coding: utf-8 -*-
"""
Rubencio Bot — Bot de combinaciones de palabras (puns) para Telegram.

Comandos:
    /radd  palabra|combinación   Agrega un pun (admin)
    /rdel  <uuid|palabra>        Elimina un pun (admin)
    /rlist                       Lista paginada de puns
    /rsi   <uuid>                Aprueba un pun (+1 karma)
    /rno   <uuid>                Prohíbe un pun (-1 karma)
    /rset  <1-100>               Probabilidad de responder (admin)
    /roff  <minutos>             Silencia el bot (admin)
    /rchat                       Estado del chat
    /rhelp                       Ayuda

Variables de entorno:
    TOKEN            (requerido) Token de @BotFather
    DBLOCATION       (requerido) Ruta al archivo SQLite
    REQUIRE_ADMIN    (opcional) "0" desactiva la comprobación de admin
"""
from __future__ import annotations

import os
import re
import sys
import time
import uuid
import random
import string
import sqlite3
import logging
import secrets
import unicodedata
from contextlib import contextmanager
from html import escape as html_escape

import telebot

# Timeout de regex (librería opcional pero muy recomendada)
try:
    import regex as regex_engine
    HAS_REGEX_TIMEOUT = True
except ImportError:
    regex_engine = re
    HAS_REGEX_TIMEOUT = False


# ════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ════════════════════════════════════════════════════════════════
VERSION               = "0.9.0"
REQUIRED_VALIDATIONS  = 1
MAX_SILENCE_MINUTES   = 60
MAX_MESSAGE_LENGTH    = 4000
MAX_TRIGGER_LEN       = 50
MAX_PUN_LEN           = 300
MAX_TRIGGERS_PER_CHAT = 100
MAX_LAST_WORD_LEN     = 100
MAX_GROUPS_IN_REGEX   = 5
RATE_WINDOW           = 60         # segundos
RATE_MAX_ADMIN        = 10         # comandos admin por minuto
RATE_MAX_VOTE         = 5          # votos por minuto
REGEX_TIMEOUT         = 0.1        # segundos
DEFAULT_PUNS_DIR      = "./defaultpuns/punsfiles"

ALLOWED_CHARS_PUNS     = string.ascii_letters + " " + string.digits + "áéíóúàèìòùäëïöü"
ALLOWED_CHARS_TRIGGERS = ALLOWED_CHARS_PUNS + "^$.*+?(){}\\[]<>=-"


# ════════════════════════════════════════════════════════════════
# LOGGING
# ════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rubencio")

if not HAS_REGEX_TIMEOUT:
    logger.warning(
        "Librería 'regex' no instalada. Protección ReDoS limitada a heurística. "
        "Instala con: pip install regex"
    )


# ════════════════════════════════════════════════════════════════
# ENTORNO
# ════════════════════════════════════════════════════════════════
def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        logger.critical("Variable de entorno faltante: %s", name)
        sys.exit(1)
    return value


TOKEN         = _require_env("TOKEN")
PUNSDB        = os.path.expanduser(_require_env("DBLOCATION"))
REQUIRE_ADMIN = os.environ.get("REQUIRE_ADMIN", "1") == "1"

bot = telebot.TeleBot(TOKEN)
bot.skip_pending = True


# ════════════════════════════════════════════════════════════════
# UTILIDADES GENERALES
# ════════════════════════════════════════════════════════════════
def safe(text) -> str:
    """Escapa <, >, & para parse_mode='HTML' (no escapa comillas)."""
    return html_escape(str(text), quote=False)


@contextmanager
def db_connect(dbfile: str = PUNSDB):
    conn = sqlite3.connect(dbfile)
    try:
        yield conn
    finally:
        conn.close()


def strip_accents(text: str) -> str:
    """Elimina diacríticos: 'camión' -> 'camion'."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def is_valid_regex(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _extract_arg(message) -> str:
    """Devuelve el argumento de un comando (soporta /cmd@bot)."""
    if not message.text:
        return ""
    parts = message.text.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


# ─── Rate limiting en memoria ───────────────────────────────────
_rate_limit: dict[int, list[float]] = {}


def rate_limit_ok(user_id: int, max_calls: int, window: int = RATE_WINDOW) -> bool:
    """True si el usuario puede hacer otra llamada. Limpia entradas viejas."""
    now = time.time()
    entries = [t for t in _rate_limit.get(user_id, []) if now - t < window]
    if len(entries) >= max_calls:
        _rate_limit[user_id] = entries
        return False
    entries.append(now)
    _rate_limit[user_id] = entries
    return True


# ─── Comprobación de admin ──────────────────────────────────────
def is_admin(chat_id: int, user_id: int) -> bool:
    if not REQUIRE_ADMIN:
        return True
    if chat_id > 0:              # chat privado: el usuario es "admin" de su chat
        return True
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except Exception as exc:
        logger.warning("Error verificando admin (chat=%s, user=%s): %s",
                       chat_id, user_id, exc)
        return False


# ─── Miembros del chat (compatibilidad) ─────────────────────────
def get_member_count(chat_id: int) -> int:
    for name in ("get_chat_member_count", "get_chat_members_count"):
        method = getattr(bot, name, None)
        if method is None:
            continue
        try:
            return method(chat_id)
        except Exception:
            continue
    return 0


# ════════════════════════════════════════════════════════════════
# REGEX SEGURO
# ════════════════════════════════════════════════════════════════
from functools import lru_cache


@lru_cache(maxsize=512)
def _compile_pattern(pattern: str):
    """Compila y cachea un patrón. Devuelve None si es inválido."""
    try:
        if HAS_REGEX_TIMEOUT:
            return regex_engine.compile(pattern)
        return re.compile(pattern)
    except Exception:
        return None


def check_regex_safety(pattern: str) -> tuple[bool, str]:
    """Heurística anti-ReDoS. Devuelve (seguro, razón)."""
    if not pattern:
        return False, "vacío"
    if len(pattern) > MAX_TRIGGER_LEN:
        return False, f"más de {MAX_TRIGGER_LEN} caracteres"
    if not is_valid_regex(pattern):
        return False, "regex inválido"
    if pattern.count("(") != pattern.count(")"):
        return False, "paréntesis desbalanceados"
    if pattern.count("[") != pattern.count("]"):
        return False, "corchetes desbalanceados"
    if pattern.count("(") > MAX_GROUPS_IN_REGEX:
        return False, f"más de {MAX_GROUPS_IN_REGEX} grupos"
    # Cuantificadores anidados: (X+)+, (X*){2,}, (X{1,2})*, etc.
    if re.search(r"\([^()]*(?:[+*]|\{\d+,\d*\})[^()]*\)[+*{]", pattern):
        return False, "cuantificadores anidados (riesgo ReDoS)"
    return True, ""


def safe_regex_match(pattern: str, text: str) -> bool:
    """Matchea con timeout si regex está disponible. Nunca lanza excepción."""
    compiled = _compile_pattern(pattern)
    if compiled is None:
        return False
    try:
        if HAS_REGEX_TIMEOUT:
            return compiled.fullmatch(text, timeout=REGEX_TIMEOUT) is not None
        return compiled.fullmatch(text) is not None
    except Exception:
        return False


# ════════════════════════════════════════════════════════════════
# BASE DE DATOS
# ════════════════════════════════════════════════════════════════
def db_setup(dbfile: str = PUNSDB) -> None:
    with db_connect(dbfile) as conn:
        cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS puns (
                           uuid   TEXT,
                           chatid INTEGER,
                           trigger TEXT,
                           pun    TEXT)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS validations (
                           punid  TEXT,
                           chatid INTEGER,
                           userid TEXT,
                           karma  INTEGER)""")
        cur.execute("""CREATE TABLE IF NOT EXISTS chatoptions (
                           chatid     INTEGER,
                           silence    INTEGER,
                           efectivity INTEGER,
                           UNIQUE(chatid))""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_puns_chatid  ON puns(chatid)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_puns_trigger ON puns(trigger)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_valid_punid  ON validations(punid, chatid)")
        conn.commit()

    if os.path.isdir(DEFAULT_PUNS_DIR):
        for fname in sorted(os.listdir(DEFAULT_PUNS_DIR)):
            load_default_puns(dbfile, os.path.join(DEFAULT_PUNS_DIR, fname))


def load_default_puns(dbfile: str, punsfile: str) -> None:
    if not os.path.isfile(punsfile):
        logger.warning("Archivo de puns por defecto no encontrado: %s", punsfile)
        return

    with db_connect(dbfile) as conn, open(punsfile, "r", encoding="utf-8") as fh:
        for number, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line or line.lstrip().startswith("#"):
                continue

            parts = line.split("|", 1)
            if len(parts) != 2:
                logger.warning("Línea %s incorrecta en %s", number, punsfile)
                continue

            trigger, pun = parts[0].strip(), parts[1].strip()

            if not trigger or not pun:
                logger.warning("Línea %s vacía en %s", number, punsfile)
                continue
            if len(trigger) > MAX_TRIGGER_LEN or len(pun) > MAX_PUN_LEN:
                logger.warning("Línea %s excede longitud máxima en %s", number, punsfile)
                continue

            safe_ok, reason = check_regex_safety(trigger)
            if not safe_ok:
                logger.warning("Trigger inseguro '%s' (línea %s): %s", trigger, number, reason)
                continue

            exists = conn.execute(
                "SELECT 1 FROM puns WHERE pun = ? AND trigger = ? AND chatid = 0 LIMIT 1",
                (pun, trigger),
            ).fetchone()
            if exists:
                continue

            conn.execute(
                "INSERT INTO puns(uuid, chatid, trigger, pun) VALUES(?, ?, ?, ?)",
                (str(uuid.uuid4()), 0, trigger, pun),
            )
            conn.commit()
            logger.info("Default pun añadido (trigger=%s)", trigger)


# ─── Opciones de chat ───────────────────────────────────────────
def load_chat_options(chatid) -> dict:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT silence, efectivity FROM chatoptions WHERE chatid = ?",
            (chatid,),
        ).fetchone()
    return {
        "chatid":     chatid,
        "silence":    row[0] if row and row[0] is not None else None,
        "efectivity": row[1] if row and row[1] is not None else None,
    }


def set_chat_options(options: dict) -> None:
    with db_connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO chatoptions(chatid, silence, efectivity) VALUES(?, ?, ?)",
            (options["chatid"], options["silence"], options["efectivity"]),
        )
        conn.commit()


def is_chat_silenced(chat_id) -> bool:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT silence FROM chatoptions WHERE chatid = ?", (chat_id,)
        ).fetchone()
    silence = int(row[0]) if row and row[0] is not None else 0
    return silence > time.time()


def silence_until(chat_id) -> str:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT silence FROM chatoptions WHERE chatid = ?", (chat_id,)
        ).fetchone()
    if row and row[0] is not None and time.time() < int(row[0]):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(row[0])))
    return "--"


def efectivity(chat_id) -> int:
    with db_connect() as conn:
        row = conn.execute(
            "SELECT efectivity FROM chatoptions WHERE chatid = ?", (chat_id,)
        ).fetchone()
    return int(row[0]) if row and row[0] is not None else 100


def is_efective(chat_id) -> bool:
    # secrets.randbelow(101) devuelve 0..100 uniformemente
    return secrets.randbelow(101) <= efectivity(chat_id)


def count_chat_triggers(chat_id) -> int:
    with db_connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM puns WHERE chatid = ?", (chat_id,)
        ).fetchone()[0]


# ─── Búsqueda de puns ───────────────────────────────────────────
def find_pun(message) -> str | None:
    if not message.text:
        return None

    clean_text = "".join(
        c for c in message.text.lower() if c in ALLOWED_CHARS_PUNS
    ).split()
    if not clean_text:
        return None

    last_word = strip_accents(clean_text[-1])
    if len(last_word) > MAX_LAST_WORD_LEN:
        return None

    chat_id = message.chat.id
    enough  = get_member_count(chat_id) >= REQUIRED_VALIDATIONS

    with db_connect() as conn:
        triggers = conn.execute(
            "SELECT trigger FROM puns WHERE chatid = ? OR chatid = 0 ORDER BY chatid DESC",
            (chat_id,),
        ).fetchall()

        candidates: list[str] = []

        for (trigger,) in triggers:
            normalized = strip_accents(trigger)
            pattern = "^" + normalized + "$"

            if not safe_regex_match(pattern, last_word):
                continue

            rows = conn.execute(
                "SELECT uuid, pun, chatid FROM puns "
                "WHERE trigger = ? AND (chatid = ? OR chatid = 0) "
                "ORDER BY chatid DESC",
                (trigger, chat_id),
            ).fetchall()

            for pun_uuid, pun_text, pun_chatid in rows:
                if not pun_text or not pun_text.split():
                    continue
                if strip_accents(pun_text.split()[-1]) == last_word:
                    continue

                if pun_chatid == 0:
                    candidates.append(pun_text)
                    continue

                karma = conn.execute(
                    "SELECT SUM(karma) FROM validations WHERE punid = ? AND chatid = ?",
                    (pun_uuid, chat_id),
                ).fetchone()[0] or 0

                if enough:
                    if karma >= REQUIRED_VALIDATIONS:
                        candidates.append(pun_text)
                elif karma > 0:
                    candidates.append(pun_text)

        return random.choice(candidates) if candidates else None


# ════════════════════════════════════════════════════════════════
# COMANDOS
# ════════════════════════════════════════════════════════════════
@bot.message_handler(commands=["rhelp", "help"])
def cmd_help(message):
    text = (
        "<b>Comandos disponibles</b>\n"
        "/radd  palabra|combinación  — Agregar combinación (admin)\n"
        "/rdel  &lt;uuid|palabra&gt;       — Eliminar combinación (admin)\n"
        "/rlist                      — Listar combinaciones\n"
        "/rsi   &lt;uuid&gt;               — Aprobar combinación\n"
        "/rno   &lt;uuid&gt;               — Prohibir combinación\n"
        "/rset  &lt;1-100&gt;              — Probabilidad de responder (admin)\n"
        "/roff  &lt;minutos&gt;            — Silenciar el bot (admin)\n"
        "/rchat                      — Estado del chat\n\n"
        f"Las combinaciones se habilitan cuando el karma supera {REQUIRED_VALIDATIONS} "
        f"en grupos con más de {REQUIRED_VALIDATIONS} personas.\n"
        "  · En grupos más pequeños, basta con karma positivo.\n\n"
        f"Versión del bot: {VERSION}"
    )
    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(commands=["rchat"])
def cmd_status(message):
    text = (
        "<b>Estado del chat</b>\n\n"
        f"  · Rubencio silenciado hasta: {safe(silence_until(message.chat.id))}\n"
        f"  · Probabilidad de responder: {efectivity(message.chat.id)}%\n"
        f"  · Karma requerido: {REQUIRED_VALIDATIONS}"
    )
    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(commands=["radd"])
def cmd_add(message):
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "Solo administradores pueden usar /radd.")
        return

    if not rate_limit_ok(message.from_user.id, RATE_MAX_ADMIN):
        bot.reply_to(message, "Demasiadas solicitudes. Espera un momento.")
        return

    quote = _extract_arg(message)
    if "|" not in quote:
        bot.reply_to(message, "Sintaxis no válida. Uso: /radd palabra|combinación")
        return

    trigger, pun = (p.strip() for p in quote.split("|", 1))
    if not trigger or not pun:
        bot.reply_to(message, "Sintaxis no válida. Uso: /radd palabra|combinación")
        return

    if len(trigger) > MAX_TRIGGER_LEN:
        bot.reply_to(message, f"El trigger no puede superar {MAX_TRIGGER_LEN} caracteres.")
        return
    if len(pun) > MAX_PUN_LEN:
        bot.reply_to(message, f"La combinación no puede superar {MAX_PUN_LEN} caracteres.")
        return
    if "\n" in trigger or "\r" in trigger or "\n" in pun or "\r" in pun:
        bot.reply_to(message, "No se permiten saltos de línea.")
        return

    for ch in trigger:
        if ch not in ALLOWED_CHARS_TRIGGERS:
            bot.reply_to(
                message,
                f"Carácter inválido '{ch}' en la palabra. Solo letras y números.",
            )
            return

    safe_ok, reason = check_regex_safety(trigger)
    if not safe_ok:
        bot.reply_to(message, f"Trigger rechazado: {reason}")
        return

    if count_chat_triggers(message.chat.id) >= MAX_TRIGGERS_PER_CHAT:
        bot.reply_to(
            message,
            f"Este chat alcanzó el límite de {MAX_TRIGGERS_PER_CHAT} combinaciones.",
        )
        return

    with db_connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM puns WHERE trigger = ? AND chatid = ? AND pun = ? LIMIT 1",
            (trigger, message.chat.id, pun),
        ).fetchone()
        if exists:
            bot.reply_to(message, "Ya existe una palabra con esta combinación")
            return

        pun_uuid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO puns(uuid, chatid, trigger, pun) VALUES(?, ?, ?, ?)",
            (pun_uuid, message.chat.id, trigger, pun),
        )
        conn.execute(
            "INSERT INTO validations(punid, chatid, userid, karma) VALUES(?, ?, ?, 1)",
            (pun_uuid, message.chat.id, message.from_user.id),
        )
        conn.commit()

    safe_trigger = safe(trigger)
    safe_uuid    = safe(pun_uuid)

    if get_member_count(message.chat.id) >= REQUIRED_VALIDATIONS:
        msg = (
            f"Combinación <b>{safe_trigger}</b> agregada. "
            f"UUID: <code>{safe_uuid}</code>\n"
            f"Necesita {REQUIRED_VALIDATIONS} aprobaciones de personas distintas."
        )
    else:
        msg = (
            f"Combinación <b>{safe_trigger}</b> agregada. "
            f"UUID: <code>{safe_uuid}</code>\n"
            "Se requiere karma positivo para habilitarla."
        )

    bot.reply_to(message, msg, parse_mode="HTML")
    logger.info("Pun añadido al chat %s por usuario %s",
                message.chat.id, message.from_user.id)


@bot.message_handler(commands=["rd"])
def cmd_delete(message):
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "Solo administradores pueden usar /rdel.")
        return

    if not rate_limit_ok(message.from_user.id, RATE_MAX_ADMIN):
        bot.reply_to(message, "Demasiadas solicitudes. Espera un momento.")
        return

    quote = _extract_arg(message)
    if not quote:
        bot.reply_to(message, "Falta el UUID. Uso: /rdel <uuid|palabra>")
        return

    with db_connect() as conn:
        row = None
        if is_valid_uuid(quote):
            row = conn.execute(
                "SELECT uuid FROM puns WHERE chatid = ? AND uuid = ?",
                (message.chat.id, quote),
            ).fetchone()
        if row is None:                          # fallback por trigger exacto
            row = conn.execute(
                "SELECT uuid FROM puns WHERE chatid = ? AND trigger = ?",
                (message.chat.id, quote),
            ).fetchone()

        if row is None:
            bot.reply_to(message, "Combinación no encontrada")
            return

        pun_uuid = row[0]
        conn.execute(
            "DELETE FROM puns WHERE chatid = ? AND uuid = ?",
            (message.chat.id, pun_uuid),
        )
        conn.execute(
            "DELETE FROM validations WHERE chatid = ? AND punid = ?",
            (message.chat.id, pun_uuid),
        )
        conn.commit()

    bot.reply_to(message, "Combinación eliminada")
    logger.info("Pun %s eliminado del chat %s por usuario %s",
                pun_uuid, message.chat.id, message.from_user.id)


def _vote(message, pun_uuid: str, karma: int, action: str) -> None:
    """Lógica común para /rsi y /rno."""
    with db_connect() as conn:
        row = conn.execute(
            "SELECT trigger FROM puns WHERE chatid = ? AND uuid = ?",
            (message.chat.id, pun_uuid),
        ).fetchone()
        if row is None:
            bot.reply_to(message, "UUID no encontrado en este chat")
            return

        trigger = row[0]
        already = conn.execute(
            "SELECT 1 FROM validations "
            "WHERE chatid = ? AND punid = ? AND userid = ? AND karma = ? LIMIT 1",
            (message.chat.id, pun_uuid, message.from_user.id, karma),
        ).fetchone()

        if already:
            bot.reply_to(
                message,
                f"Ya has {action} esta combinación. Solo se permite una vez por usuario.",
            )
            return

        conn.execute(
            "INSERT INTO validations(punid, chatid, userid, karma) VALUES(?, ?, ?, ?)",
            (pun_uuid, message.chat.id, message.from_user.id, karma),
        )
        conn.commit()

        total = conn.execute(
            "SELECT SUM(karma) FROM validations WHERE chatid = ? AND punid = ?",
            (message.chat.id, pun_uuid),
        ).fetchone()[0] or 0

    bot.reply_to(message, f"Gracias por elegir esta combinación. El karma es {total}")


@bot.message_handler(commands=["rsi"])
def cmd_approve(message):
    if not rate_limit_ok(message.from_user.id, RATE_MAX_VOTE):
        bot.reply_to(message, "Demasiadas solicitudes. Espera un momento.")
        return

    pun_uuid = _extract_arg(message)
    if not pun_uuid:
        bot.reply_to(message, "Falta el UUID. Uso: /rsi <uuid>")
        return
    if not is_valid_uuid(pun_uuid):
        bot.reply_to(message, "UUID no válido.")
        return
    _vote(message, pun_uuid, karma=1, action="aprobado")


@bot.message_handler(commands=["rno"])
def cmd_ban(message):
    if not rate_limit_ok(message.from_user.id, RATE_MAX_VOTE):
        bot.reply_to(message, "Demasiadas solicitudes. Espera un momento.")
        return

    pun_uuid = _extract_arg(message)
    if not pun_uuid:
        bot.reply_to(message, "Falta el UUID. Uso: /rno <uuid>")
        return
    if not is_valid_uuid(pun_uuid):
        bot.reply_to(message, "UUID no válido.")
        return
    _vote(message, pun_uuid, karma=-1, action="prohibido")


@bot.message_handler(commands=["roff"])
def cmd_silence(message):
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "Solo administradores pueden usar /roff.")
        return

    if not rate_limit_ok(message.from_user.id, RATE_MAX_ADMIN):
        bot.reply_to(message, "Demasiadas solicitudes. Espera un momento.")
        return

    quote = _extract_arg(message)
    if not quote.isdigit():
        bot.reply_to(message, "Sintaxis no válida. Uso: /roff <minutos>")
        return

    minutes = int(quote)
    if minutes <= 0:
        bot.reply_to(message, "El tiempo debe ser mayor a 0")
        return
    if minutes > MAX_SILENCE_MINUTES:
        bot.reply_to(message, "Desactivar a Rubencio durante más de una hora no es divertido ☹️")
        return

    options = load_chat_options(message.chat.id)
    now     = int(time.time())
    current = int(options["silence"]) if options["silence"] else 0
    base    = current if current > now else now
    new_end = base + minutes * 60

    if new_end - now > MAX_SILENCE_MINUTES * 60:
        bot.reply_to(message, "Desactivar a Rubencio durante más de una hora no es divertido ☹️")
        return

    options["silence"] = new_end
    set_chat_options(options)
    bot.reply_to(
        message,
        "Rubencio se silenciará hasta "
        + time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(new_end)),
    )


@bot.message_handler(commands=["rset"])
def cmd_set(message):
    if not is_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "Solo administradores pueden usar /rset.")
        return

    if not rate_limit_ok(message.from_user.id, RATE_MAX_ADMIN):
        bot.reply_to(message, "Demasiadas solicitudes. Espera un momento.")
        return

    quote = _extract_arg(message)
    if not quote.isdigit() or not (0 <= int(quote) <= 100):
        bot.reply_to(message, "Probabilidad no válida. Uso: /rset <1-100>")
        return

    value = int(quote)
    if value == 0:
        bot.reply_to(
            message,
            "La probabilidad no puede ser 0. Para deshabilitar temporalmente usa /roff",
        )
        return

    options = load_chat_options(message.chat.id)
    options["efectivity"] = value
    set_chat_options(options)
    bot.reply_to(message, f"Rubencio detectará las combinaciones el {value}% del tiempo")


@bot.message_handler(commands=["rl"])
def cmd_list(message):
    header = "| uuid | status (karma) | trigger | pun\n"

    with db_connect() as conn:
        rows = conn.execute(
            "SELECT uuid, chatid, trigger, pun FROM puns "
            "WHERE chatid = ? OR chatid = 0 ORDER BY chatid",
            (message.chat.id,),
        ).fetchall()
        enough = get_member_count(message.chat.id) >= REQUIRED_VALIDATIONS

        lines: list[str] = []
        for pun_uuid, pun_chatid, trigger, pun in rows:
            if pun_chatid == 0:
                lines.append(f"| default pun | always enabled | {trigger} | {pun}")
                continue

            karma = conn.execute(
                "SELECT SUM(karma) FROM validations WHERE punid = ? AND chatid = ?",
                (pun_uuid, message.chat.id),
            ).fetchone()[0] or 0

            if enough:
                status = (
                    f"enabled ({karma}/{REQUIRED_VALIDATIONS})"
                    if karma >= REQUIRED_VALIDATIONS
                    else f"disabled ({karma}/{REQUIRED_VALIDATIONS})"
                )
            else:
                status = f"enabled ({karma})" if karma > 0 else f"disabled ({karma})"

            lines.append(f"| {pun_uuid} | {status} | {trigger} | {pun}")

    # Paginación (sin parse_mode → texto plano, no hace falta escapar)
    chunk = header
    for line in lines:
        candidate = chunk + line + "\n"
        if len(candidate) > MAX_MESSAGE_LENGTH and chunk != header:
            bot.reply_to(message, chunk)
            chunk = header + line + "\n"
        else:
            chunk = candidate
    if chunk != header:
        bot.reply_to(message, chunk)


@bot.message_handler(commands=["start"])
def cmd_start(message):
    bot.reply_to(message, "Vamos a divertirnos un rato. Usa /rhelp para obtener ayuda.")


@bot.message_handler(func=lambda m: True)
def echo_all(message):
    if not message.text:
        return
    if is_chat_silenced(message.chat.id):
        return
    if not is_efective(message.chat.id):
        return

    rima = find_pun(message)
    if rima is not None:
        # Sin parse_mode → el pun se muestra tal cual
        bot.reply_to(message, rima)


# ════════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════════
def main() -> None:
    db_setup(dbfile=PUNSDB)
    logger.info("Rubencio %s listo para los puns!", VERSION)
    try:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=25)
        except AttributeError:
            bot.polling(none_stop=True)
    except KeyboardInterrupt:
        logger.info("Detenido por el usuario")

if __name__ == "__main__":
    main()