import os
import re
import glob
import uuid
import time
import copy
import html
import hashlib
import hmac
import ipaddress
import itertools
import logging
import signal
import socket
import shutil
import stat
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Full, PriorityQueue
from threading import Event, Lock, Thread
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
import telebot
import yt_dlp
import subprocess
import json
from yt_dlp.version import __version__ as YT_DLP_VERSION

try:
    import curl_cffi
    from curl_cffi import requests as curl_requests
    CURL_CFFI_VERSION = getattr(curl_cffi, "__version__", "instalado")
    TIKTOK_IMPERSONATION_DISPONIVEL = True
except ImportError:
    curl_requests = None
    CURL_CFFI_VERSION = None
    TIKTOK_IMPERSONATION_DISPONIVEL = False

from telebot import types
from pymongo import MongoClient, ReturnDocument
from requests.exceptions import RequestException, Timeout

# =========================================
# CONFIGURAÇÕES
# =========================================
def get_env_required(name):
    value = os.environ.get(name)
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Variável de ambiente obrigatória ausente: {name}")
    return value.strip()


def get_first_env(names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value is not None and str(value).strip() != "":
            return value.strip()
    return default


def get_env_int(name, default, minimo=None, maximo=None):
    value = os.environ.get(name, default)
    try:
        value = int(value)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"Variável {name} precisa ser um número inteiro") from e

    if minimo is not None and value < minimo:
        raise RuntimeError(f"Variável {name} precisa ser maior ou igual a {minimo}")
    if maximo is not None and value > maximo:
        raise RuntimeError(f"Variável {name} precisa ser menor ou igual a {maximo}")
    return value


TOKEN_TELEGRAM = get_env_required("TOKEN_TELEGRAM")
MONGO_URI = get_env_required("MONGO_URI")
MONGO_DB_NAME = get_env_required("MONGO_DB_NAME")
ADMIN_ID = int(get_env_required("ADMIN_ID"))

# Chave local e estável para referências anônimas nos logs. Ela não é gravada
# nem exibida e não exige uma nova variável na Railway.
LOG_ANONYMIZATION_KEY = hashlib.sha256(
    f"baixar-videos-hd:logs:v1:{TOKEN_TELEGRAM}".encode("utf-8")
).digest()

# Contato público oficial. Mantê-lo no código evita que uma variável antiga
# da Railway continue enviando usuários para o suporte anterior.
SUPORTE_USERNAME = "@suportebaixarvideoshd"
LINK_SUPORTE = f"https://t.me/{SUPORTE_USERNAME.lstrip('@')}"

# Vendas exclusivamente por Pix manual. Nenhuma integração de checkout ou
# cartão é carregada pelo bot. Os dados ficam somente nas variáveis do Railway.
PIX_KEY = get_env_required("PIX_KEY")
PIX_RECEIVER_NAME = get_env_required("PIX_RECEIVER_NAME")
PIX_RECEIVER_BANK = get_env_required("PIX_RECEIVER_BANK")

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads_temp")
PRIVATE_DIR = os.path.join(DOWNLOAD_DIR, "private")
PRIVATE_COOKIES_DIR = os.path.join(PRIVATE_DIR, "cookies")
PRIVATE_BACKUPS_DIR = os.path.join(PRIVATE_DIR, "backups")
TZ = ZoneInfo("America/Sao_Paulo")

SERVICE_NAME = get_first_env(
    ["SERVICE_NAME", "RAILWAY_SERVICE_NAME"],
    default="bot-downloads-vip"
)
ENVIRONMENT_NAME = get_first_env(
    ["RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT", "ENVIRONMENT"],
    default="production"
)
APP_STARTED_AT = datetime.now(TZ).isoformat()
APP_INSTANCE_ID = uuid.uuid4().hex

FREE_DAILY_LIMIT = 3
MAX_DURATION_SECONDS = 90
MAX_URL_LENGTH = get_env_int("MAX_URL_LENGTH", 2048, 256, 8192)
MAX_SOURCE_FILE_MB = get_env_int("MAX_SOURCE_FILE_MB", 100, 10, 500)
MAX_OUTPUT_FILE_MB = get_env_int("MAX_OUTPUT_FILE_MB", 50, 5, 200)
MAX_SOURCE_FILE_BYTES = MAX_SOURCE_FILE_MB * 1024 * 1024
MAX_OUTPUT_FILE_BYTES = MAX_OUTPUT_FILE_MB * 1024 * 1024
MIN_DISK_FREE_MB = get_env_int("MIN_DISK_FREE_MB", 300, 100, 10000)
MIN_DISK_FREE_BYTES = MIN_DISK_FREE_MB * 1024 * 1024
FFPROBE_TIMEOUT_SECONDS = get_env_int("FFPROBE_TIMEOUT_SECONDS", 30, 5, 120)
FFMPEG_TIMEOUT_SECONDS = get_env_int("FFMPEG_TIMEOUT_SECONDS", 300, 30, 1800)
DOWNLOAD_TIMEOUT_SECONDS = get_env_int("DOWNLOAD_TIMEOUT_SECONDS", 240, 30, 1800)
FFMPEG_THREADS = get_env_int("FFMPEG_THREADS", 2, 1, 8)
WORKER_STALL_TIMEOUT_SECONDS = get_env_int(
    "WORKER_STALL_TIMEOUT_SECONDS",
    max(900, DOWNLOAD_TIMEOUT_SECONDS + 60, FFMPEG_TIMEOUT_SECONDS + 60),
    300,
    7200,
)
WORKER_WATCHDOG_INTERVAL_SECONDS = get_env_int(
    "WORKER_WATCHDOG_INTERVAL_SECONDS", 30, 10, 300
)
WORKER_RESTART_GRACE_SECONDS = get_env_int(
    "WORKER_RESTART_GRACE_SECONDS", 300, 60, 1800
)
WORKER_MAX_RESTARTS_PER_HOUR = get_env_int(
    "WORKER_MAX_RESTARTS_PER_HOUR", 2, 1, 10
)
WORKER_RESTART_RETRY_SECONDS = get_env_int(
    "WORKER_RESTART_RETRY_SECONDS", 300, 60, 1800
)
WORKER_RESTART_EXIT_CODE = 70
VIDEO_CRF = get_env_int("VIDEO_CRF", 27, 18, 35)
AUDIO_BITRATE = os.environ.get("AUDIO_BITRATE", "80k").strip() or "80k"
MEDIA_CACHE_DAYS = get_env_int("MEDIA_CACHE_DAYS", 180, 1, 365)
DOWNLOAD_COOLDOWN_SECONDS = get_env_int(
    "DOWNLOAD_COOLDOWN_SECONDS", 5, 0, 60
)
MAX_DOWNLOADS_PER_USER_HOUR = get_env_int(
    "MAX_DOWNLOADS_PER_USER_HOUR", 30, 3, 1000
)
MAX_DOWNLOADS_GLOBAL_HOUR = get_env_int(
    "MAX_DOWNLOADS_GLOBAL_HOUR", 300, 20, 10000
)
GLOBAL_RATE_LIMIT_WINDOW_SECONDS = 3600
GLOBAL_RATE_LIMIT_DOCUMENT_TTL_HOURS = 2
GLOBAL_RATE_LIMIT_DOCUMENT_ID = "downloads_rolling_hour"
USER_RATE_LIMIT_DOCUMENT_TTL_HOURS = 2
DOWNLOAD_QUEUE_MAX = get_env_int("DOWNLOAD_QUEUE_MAX", 10, 1, 50)
DOWNLOAD_RESERVATION_TTL_SECONDS = max(
    7200,
    DOWNLOAD_QUEUE_MAX * (DOWNLOAD_TIMEOUT_SECONDS + FFMPEG_TIMEOUT_SECONDS),
)
RAILWAY_DRAINING_CONFIGURED = bool(
    os.environ.get("RAILWAY_DEPLOYMENT_DRAINING_SECONDS", "").strip()
)
SHUTDOWN_DRAIN_SECONDS = get_env_int(
    "RAILWAY_DEPLOYMENT_DRAINING_SECONDS", 120, 10, 1800
)
SHUTDOWN_SAFETY_MARGIN_SECONDS = min(
    15,
    max(5, SHUTDOWN_DRAIN_SECONDS // 8),
)
QUEUE_RECOVERY_TTL_HOURS = get_env_int(
    "QUEUE_RECOVERY_TTL_HOURS", 24, 1, 168
)
QUEUE_RECOVERY_DELAY_SECONDS = min(
    1800,
    SHUTDOWN_DRAIN_SECONDS + 15,
)
PIX_ORDER_EXPIRATION_HOURS = get_env_int(
    "PIX_ORDER_EXPIRATION_HOURS", 24, 1, 168
)
VIP_EXPIRATION_NOTICE_CHECK_SECONDS = get_env_int(
    "VIP_EXPIRATION_NOTICE_CHECK_SECONDS", 3600, 300, 86400
)
VIP_EXPIRATION_NOTICE_INITIAL_DELAY_SECONDS = 60
PIX_PENDING_PAGE_SIZE = 8
TIKWM_REQUEST_TIMEOUT_SECONDS = get_env_int(
    "TIKWM_REQUEST_TIMEOUT_SECONDS", 12, 5, 30
)
TIKWM_TOTAL_TIMEOUT_SECONDS = get_env_int(
    "TIKWM_TOTAL_TIMEOUT_SECONDS", 35, 10, 90
)
TIKWM_CIRCUIT_FAILURES = get_env_int("TIKWM_CIRCUIT_FAILURES", 3, 1, 10)
TIKWM_CIRCUIT_COOLDOWN_SECONDS = get_env_int(
    "TIKWM_CIRCUIT_COOLDOWN_SECONDS", 300, 30, 1800
)
MONITOR_FAILURE_THRESHOLD = get_env_int(
    "MONITOR_FAILURE_THRESHOLD", 3, 2, 10
)
MONITOR_FAILURE_WINDOW_SECONDS = get_env_int(
    "MONITOR_FAILURE_WINDOW_SECONDS", 900, 60, 3600
)
MONITOR_ALERT_COOLDOWN_SECONDS = get_env_int(
    "MONITOR_ALERT_COOLDOWN_SECONDS", 3600, 300, 86400
)
MONITOR_SUCCESS_LOG_INTERVAL_SECONDS = 900
MEDIA_PROFILE_VERSION = (
    f"720x1280_30fps_h264_crf{VIDEO_CRF}_audio{AUDIO_BITRATE}_sem_marca_v2"
)
INSTAGRAM_AUDIO_CACHE_VERSION = "instagram_audio_v3"

INSTAGRAM_COOKIES_TEXT = os.environ.get("INSTAGRAM_COOKIES_TEXT", "")
TIKTOK_COOKIES_TEXT = os.environ.get("TIKTOK_COOKIES_TEXT", "")
TIKTOK_DEVICE_ID_TEXT = os.environ.get("TIKTOK_DEVICE_ID", "")
TIKWM_API_URL = os.environ.get("TIKWM_API_URL", "https://www.tikwm.com/api/").strip()

TIKTOK_COOKIE_LOCK = Lock()
TIKTOK_COOKIES_ENV_APLICADOS = False
TIKTOK_DEVICE_LOCK = Lock()
AVISO_GERAL_LOCK = Lock()
BACKUP_ADMIN_LOCK = Lock()
DIAGNOSTIC_ADMIN_LOCK = Lock()
DOWNLOAD_RATE_LOCK = Lock()
DOWNLOAD_RATE_EVENTS = defaultdict(deque)
DOWNLOAD_GLOBAL_EVENTS = deque()
PAYMENT_USER_LOCKS = [Lock() for _ in range(64)]
PAYMENT_ORDER_LOCKS = [Lock() for _ in range(64)]
DOWNLOAD_PENDING_LOCK = Lock()
DOWNLOAD_PENDING_USERS = set()
DOWNLOAD_QUEUE = PriorityQueue(maxsize=DOWNLOAD_QUEUE_MAX)
DOWNLOAD_QUEUE_STATE_LOCK = Lock()
DOWNLOAD_SEQUENCE = itertools.count()
DISK_SPACE_ALERT_LOCK = Lock()
DISK_SPACE_ALERT_STATE = {"active": False, "last_alert_at": 0.0}
SHUTDOWN_EVENT = Event()
SHUTDOWN_SIGNAL = None
SHUTDOWN_DEADLINE_MONOTONIC = None
HEALTH_SERVER_LOCK = Lock()
HEALTH_SERVER = None
TIKWM_CIRCUIT_LOCK = Lock()
TIKWM_CIRCUIT_STATE = {"failures": 0, "open_until": 0.0}
BOT_STATE_LOCK = Lock()
BOT_STATE = "starting"
BOT_LAST_UPDATE_AT = None
DOWNLOAD_WORKER_STATE_LOCK = Lock()
DOWNLOAD_WORKER_RUNNING = False
DOWNLOAD_WORKER_STATE = {
    "busy": False,
    "phase": "starting",
    "heartbeat_monotonic": None,
    "job_started_monotonic": None,
    "last_progress_at": None,
    "job_started_at": None,
    "last_completed_at": None,
    "completed_jobs": 0,
    "stall_alert_active": False,
    "stall_alerted_at": None,
    "stall_detected_monotonic": None,
    "restart_in_progress": False,
    "restart_blocked_reason": None,
    "restart_retry_after_monotonic": 0.0,
    "active_user_id": None,
    "active_has_download_reservation": False,
}
COMPONENT_MONITOR_LOCK = Lock()
COMPONENTES_PLATAFORMA = ("TikTok", "Instagram", "Pinterest", "RedNote")
COMPONENTES_INTERNOS = (
    "Telegram",
    "Processamento",
    "MongoDB",
    "Armazenamento",
    "Interno",
)
COMPONENT_MONITOR_STATE = {
    componente: {
        "failures": deque(),
        "alert_active": False,
        "last_alert_at": 0.0,
        "last_error": None,
        "last_success_at": None,
        "last_success_log_monotonic": None,
    }
    for componente in COMPONENTES_PLATAFORMA + COMPONENTES_INTERNOS
}

ARQUIVOS_PERSISTENTES_DOWNLOAD_DIR = {
    "instagram_cookies.txt",
    "tiktok_cookies.txt",
    "tiktok_device_id.txt",
}

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# =========================================
# LOGS
# =========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("baixar_videos_hd")


# =========================================
# ARMAZENAMENTO PRIVADO LOCAL
# =========================================
def garantir_diretorio_privado(caminho):
    """Cria e valida um diretório acessível somente pelo processo do bot."""
    if os.path.lexists(caminho) and os.path.islink(caminho):
        raise RuntimeError("DIRETORIO_PRIVADO_NAO_PODE_SER_LINK")

    os.makedirs(caminho, mode=0o700, exist_ok=True)
    os.chmod(caminho, 0o700)
    estado = os.stat(caminho, follow_symlinks=False)
    if not stat.S_ISDIR(estado.st_mode):
        raise RuntimeError("CAMINHO_PRIVADO_NAO_E_DIRETORIO")
    if stat.S_IMODE(estado.st_mode) != 0o700:
        raise RuntimeError("PERMISSAO_DIRETORIO_PRIVADO_INVALIDA")
    return caminho


def garantir_estrutura_privada():
    garantir_diretorio_privado(PRIVATE_DIR)
    garantir_diretorio_privado(PRIVATE_COOKIES_DIR)
    garantir_diretorio_privado(PRIVATE_BACKUPS_DIR)
    return True


def garantir_arquivo_privado(caminho):
    """Recusa links e exige permissão 0600 em um arquivo existente."""
    if os.path.islink(caminho):
        raise RuntimeError("ARQUIVO_PRIVADO_NAO_PODE_SER_LINK")

    estado = os.stat(caminho, follow_symlinks=False)
    if not stat.S_ISREG(estado.st_mode):
        raise RuntimeError("CAMINHO_PRIVADO_NAO_E_ARQUIVO")

    os.chmod(caminho, 0o600)
    estado = os.stat(caminho, follow_symlinks=False)
    if stat.S_IMODE(estado.st_mode) != 0o600:
        raise RuntimeError("PERMISSAO_ARQUIVO_PRIVADO_INVALIDA")
    return caminho


def abrir_arquivo_privado_para_escrita(caminho):
    """Abre sem seguir links simbólicos e aplica 0600 antes de escrever."""
    garantir_diretorio_privado(os.path.dirname(caminho))
    if os.path.lexists(caminho) and os.path.islink(caminho):
        raise RuntimeError("ARQUIVO_PRIVADO_NAO_PODE_SER_LINK")

    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    descritor = os.open(caminho, flags, 0o600)
    try:
        os.fchmod(descritor, 0o600)
        return os.fdopen(
            descritor,
            "w",
            encoding="utf-8",
            newline="\n",
        )
    except Exception:
        os.close(descritor)
        raise


def escrever_texto_privado(caminho, texto):
    with abrir_arquivo_privado_para_escrita(caminho) as arquivo:
        arquivo.write(texto)
        arquivo.flush()
    garantir_arquivo_privado(caminho)
    return caminho


def ler_texto_privado(caminho):
    garantir_arquivo_privado(caminho)
    with open(caminho, "r", encoding="utf-8") as arquivo:
        return arquivo.read()


def migrar_arquivo_privado_legado(nome_arquivo):
    """Move cookies antigos da raiz sem manter uma cópia desprotegida."""
    origem = os.path.join(DOWNLOAD_DIR, nome_arquivo)
    destino = os.path.join(PRIVATE_COOKIES_DIR, nome_arquivo)

    if not os.path.lexists(origem):
        if os.path.exists(destino):
            garantir_arquivo_privado(destino)
        return False

    if os.path.islink(origem):
        os.unlink(origem)
        logger.warning(
            f"[ARMAZENAMENTO_PRIVADO] link legado removido nome={nome_arquivo}"
        )
        return False

    estado = os.stat(origem, follow_symlinks=False)
    if not stat.S_ISREG(estado.st_mode):
        raise RuntimeError("ARQUIVO_LEGADO_NAO_E_REGULAR")

    garantir_diretorio_privado(PRIVATE_COOKIES_DIR)
    if os.path.lexists(destino):
        garantir_arquivo_privado(destino)
        os.remove(origem)
        return False

    os.replace(origem, destino)
    garantir_arquivo_privado(destino)
    logger.info(
        f"[ARMAZENAMENTO_PRIVADO] arquivo legado migrado nome={nome_arquivo}"
    )
    return True


def limpar_backups_privados_abandonados():
    """Remove sobras de backups; arquivos válidos só existem durante o envio."""
    garantir_diretorio_privado(PRIVATE_BACKUPS_DIR)
    removidos = 0
    for caminho in glob.glob(os.path.join(PRIVATE_BACKUPS_DIR, "*")):
        try:
            if os.path.islink(caminho) or os.path.isfile(caminho):
                os.remove(caminho)
                removidos += 1
        except Exception as e:
            logger.warning(
                f"[BACKUP_PRIVADO_CLEANUP] arquivo={os.path.basename(caminho)} "
                f"erro={sanitizar_erro_log(e)}"
            )
    if removidos:
        logger.info(f"[BACKUP_PRIVADO_CLEANUP] removidos={removidos}")
    return removidos


def inicializar_armazenamento_privado():
    garantir_estrutura_privada()
    for nome in sorted(ARQUIVOS_PERSISTENTES_DOWNLOAD_DIR):
        migrar_arquivo_privado_legado(nome)
    limpar_backups_privados_abandonados()
    logger.info(
        "[ARMAZENAMENTO_PRIVADO] estrutura_segura=True "
        "diretorios=0700 arquivos=0600"
    )
    return True


# =========================================
# DB / BOT / APP
# =========================================
client = MongoClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    socketTimeoutMS=15000,
    waitQueueTimeoutMS=5000,
    maxPoolSize=10,
)
db = client[MONGO_DB_NAME]
usuarios_col = db["usuarios"]
pedidos_col = db["pedidos"]
metricas_col = db["metricas_diarias"]
midia_cache_col = db["midia_cache"]
auditoria_admin_col = db["auditoria_admin"]
auditoria_sistema_col = db["auditoria_sistema"]
fila_recuperacao_col = db["fila_recuperacao"]
limites_globais_col = db["limites_globais"]
limites_usuarios_col = db["limites_usuarios"]

try:
    usuarios_col.create_index("vip_ate")
    usuarios_col.create_index("ultima_data")
    pedidos_col.create_index("order_nsu", unique=True)
    pedidos_col.create_index("status")
    pedidos_col.create_index("user_id")
    pedidos_col.create_index([("user_id", 1), ("status", 1), ("created_at", -1)])
    pedidos_col.create_index("expires_at", expireAfterSeconds=0)
    midia_cache_col.create_index("expires_at", expireAfterSeconds=0)
    auditoria_admin_col.create_index("created_at")
    auditoria_admin_col.create_index(
        [("target_user_id", 1), ("created_at", -1)]
    )
    auditoria_admin_col.create_index(
        [("action", 1), ("status", 1), ("created_at", -1)]
    )
    auditoria_sistema_col.create_index("created_at")
    auditoria_sistema_col.create_index(
        [("event_type", 1), ("status", 1), ("created_at", -1)]
    )
    fila_recuperacao_col.create_index("expires_at", expireAfterSeconds=0)
    fila_recuperacao_col.create_index(
        [("instance_id", 1), ("status", 1), ("updated_at", 1)]
    )
    limites_globais_col.create_index("expires_at", expireAfterSeconds=0)
    limites_usuarios_col.create_index("expires_at", expireAfterSeconds=0)
except Exception as e:
    erro_inicio = re.sub(
        r"(?i)(mongodb(?:\+srv)?|https?)://[^\s]+",
        "[url]",
        str(e),
    )
    logger.warning(
        "[MONGO_INDEX] Não foi possível garantir índices agora: "
        f"{erro_inicio[:500]}"
    )

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
}

PINTEREST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.pinterest.com/",
    "Origin": "https://www.pinterest.com",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
}

PLANOS = {
    "10.00": {
        "nome": "VIP Mensal",
        "preco_centavos": 1000,
        "dias": 30,
        "descricao": "VIP Mensal 30 dias"
    },
    "79.90": {
        "nome": "VIP Anual",
        "preco_centavos": 7990,
        "dias": 365,
        "descricao": "VIP Anual 365 dias"
    }
}

# =========================================
# FUNÇÕES AUXILIARES
# =========================================
def agora_tz():
    return datetime.now(TZ)


def hoje_str():
    return agora_tz().strftime("%Y-%m-%d")


def formatar_validade_vip(vip_ate):
    if vip_ate == "Vitalício":
        return "Vitalício"
    try:
        return datetime.strptime(str(vip_ate), "%Y-%m-%d").strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(vip_ate or "Ativo")


def is_chat_privado(message):
    return getattr(getattr(message, "chat", None), "type", None) == "private"


def is_admin_privado(message):
    return (
        is_chat_privado(message)
        and int(getattr(getattr(message, "from_user", None), "id", 0) or 0) == ADMIN_ID
        and int(getattr(getattr(message, "chat", None), "id", 0) or 0) == ADMIN_ID
    )


def exigir_admin_privado(message):
    if is_admin_privado(message):
        return True
    if int(getattr(getattr(message, "from_user", None), "id", 0) or 0) == ADMIN_ID:
        orientar_uso_no_privado(message)
    return False


def orientar_uso_no_privado(message):
    safe_reply_to(
        message,
        "🔒 Para proteger seus dados e seu pagamento, use este bot somente no "
        "chat privado. Abra o perfil do bot e toque em *Iniciar*.",
        parse_mode="Markdown",
    )


def referencia_privada_log(tipo, valor, tamanho=12):
    """Cria uma referência estável sem permitir recuperar o valor original."""
    material = str(valor if valor is not None else "ausente").encode(
        "utf-8", errors="ignore"
    )
    digest = hmac.new(
        LOG_ANONYMIZATION_KEY,
        material,
        hashlib.sha256,
    ).hexdigest()[:tamanho]
    rotulo = re.sub(r"[^a-z0-9_-]", "", str(tipo or "ref").lower()) or "ref"
    return f"{rotulo}#{digest}"


def referencia_usuario_log(user_id):
    return referencia_privada_log("usr", user_id)


def referencia_chat_log(chat_id):
    return referencia_privada_log("chat", chat_id)


def referencia_pedido_log(order_nsu):
    return referencia_privada_log("pix", order_nsu)


def referencia_arquivo_log(caminho):
    extensao = os.path.splitext(str(caminho or ""))[1].lower().lstrip(".")
    return referencia_privada_log(extensao or "arquivo", caminho)


def referencia_url_log(url):
    """Identifica uma URL nos logs sem gravar caminho, consulta ou tokens."""
    texto = str(url or "").strip()
    try:
        host = (urlparse(texto).hostname or "desconhecido").lower()
    except Exception:
        host = "desconhecido"
    return f"{host}:{referencia_privada_log('url', texto)}"


def sanitizar_erro_log(erro, limite=1200):
    """Remove segredos, URLs e identificadores antes de qualquer log."""
    texto = str(erro or "")
    texto = re.sub(r"https?://[^\s]+", "[url]", texto, flags=re.IGNORECASE)
    texto = re.sub(
        r"\b\d{6,12}:[A-Za-z0-9_-]{20,}\b",
        "[token_telegram]",
        texto,
    )
    texto = re.sub(
        r"(?i)\b(token|password|senha|secret|api[_-]?key|authorization|"
        r"cookie|sessionid|file[_-]?id)\s*[:=]\s*[^\s,;]+",
        r"\1=[protegido]",
        texto,
    )
    texto = re.sub(
        r"(?i)\b(user[_-]?id|chat[_-]?id|admin[_-]?id|target[_-]?user[_-]?id|"
        r"message[_-]?id|auditoria[_-]?id|order[_-]?nsu)\s*[:=]\s*[^\s,;]+",
        r"\1=[protegido]",
        texto,
    )
    texto = re.sub(
        r"\b\d{7,}_\d{7,}_[0-9a-fA-F]{6,}\b",
        "[pedido]",
        texto,
    )
    texto = re.sub(r"(?<!\d)\d{7,}(?!\d)", "[id]", texto)
    return texto[:limite]


def sanitizar_erro_monitoramento(erro, limite=500):
    """Remove URLs, identificadores longos e segredos antes de alertar o ADM."""
    texto = sanitizar_erro_log(erro, limite=max(limite * 2, 500))
    return texto[:limite]


class FalhaComponenteDownload(RuntimeError):
    """Transporta a origem confirmada sem misturar contadores de componentes."""

    def __init__(self, componente, erro, ja_registrada=False):
        self.componente = normalizar_componente_monitoramento(componente) or "Interno"
        self.erro_original = erro
        self.ja_registrada = bool(ja_registrada)
        super().__init__(str(erro or componente))


def validar_url_http_publica(url, resolver_dns=True):
    """Rejeita credenciais, portas incomuns e destinos de rede privada."""
    try:
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        if parsed.username or parsed.password:
            return False
        porta = parsed.port
        if porta not in (None, 80, 443):
            return False

        if not resolver_dns:
            return True

        host = parsed.hostname.rstrip(".")
        try:
            ips = {ipaddress.ip_address(host)}
        except ValueError:
            infos = socket.getaddrinfo(
                host,
                porta or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            ips = {ipaddress.ip_address(info[4][0]) for info in infos}

        return bool(ips) and all(ip.is_global for ip in ips)
    except (OSError, ValueError):
        return False


def seguir_redirecionamentos_seguros(url, headers=None, max_redirects=5):
    """Segue redirecionamentos somente depois de validar cada destino."""
    atual = str(url or "").strip()
    resposta = None

    for _ in range(max_redirects + 1):
        if not validar_url_http_publica(atual):
            raise RuntimeError("URL_DESTINO_NAO_PUBLICO")

        resposta = requests.get(
            atual,
            allow_redirects=False,
            stream=True,
            timeout=(5, 12),
            headers=headers or DEFAULT_HEADERS,
        )

        if resposta.status_code not in (301, 302, 303, 307, 308):
            resposta.raise_for_status()
            return resposta, atual

        destino = urljoin(atual, resposta.headers.get("Location") or "")
        resposta.close()
        if not destino or destino == atual:
            raise RuntimeError("REDIRECIONAMENTO_INVALIDO")
        atual = destino

    if resposta is not None:
        resposta.close()
    raise RuntimeError("MUITOS_REDIRECIONAMENTOS")


def atualizar_estado_bot(estado, registrar_atividade=False):
    global BOT_STATE, BOT_LAST_UPDATE_AT
    with BOT_STATE_LOCK:
        BOT_STATE = str(estado)
        if registrar_atividade:
            BOT_LAST_UPDATE_AT = agora_tz().isoformat()


def registrar_atividade_bot(_mensagens):
    if not SHUTDOWN_EVENT.is_set():
        atualizar_estado_bot("polling", registrar_atividade=True)


def extrair_primeira_url(texto):
    if not texto:
        return None
    match = re.search(r"(https?://[^\s]+)", texto.strip())
    if not match:
        return None
    url = match.group(1).strip().rstrip(".,);]}>\"'")
    if len(url) > MAX_URL_LENGTH:
        return None
    return url


def hostname_permitido(hostname, dominio_raiz):
    hostname = (hostname or "").lower().rstrip(".")
    dominio_raiz = dominio_raiz.lower().rstrip(".")
    return hostname == dominio_raiz or hostname.endswith("." + dominio_raiz)


def detectar_plataforma_url(url):
    """Classifica apenas hosts oficiais para impedir URLs arbitrárias/SSRF."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, False, False, False

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False, False, False, False

    try:
        if parsed.port not in (None, 80, 443):
            return False, False, False, False
    except ValueError:
        return False, False, False, False

    host = parsed.hostname.lower().rstrip(".")
    is_pinterest = hostname_permitido(host, "pinterest.com") or host == "pin.it"
    is_tiktok = host in {
        "tiktok.com",
        "www.tiktok.com",
        "m.tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
    }
    is_instagram = host in {
        "instagram.com",
        "www.instagram.com",
        "m.instagram.com",
        "instagr.am",
        "www.instagr.am",
    }
    is_rednote = host in {
        "xiaohongshu.com",
        "www.xiaohongshu.com",
        "xhslink.com",
        "www.xhslink.com",
        "rednote.com",
        "www.rednote.com",
    }
    return is_pinterest, is_tiktok, is_instagram, is_rednote


def resolver_url_compartilhada(url):
    """Resolve links curtos sem permitir que escapem da plataforma original."""
    flags_originais = detectar_plataforma_url(url)
    if not any(flags_originais):
        raise RuntimeError("URL_PLATAFORMA_NAO_PERMITIDA")

    host = (urlparse(url).hostname or "").lower().rstrip(".")
    hosts_curtos = {
        "pin.it",
        "vm.tiktok.com",
        "vt.tiktok.com",
        "instagr.am",
        "www.instagr.am",
        "xhslink.com",
        "www.xhslink.com",
    }
    if host not in hosts_curtos:
        if not validar_url_http_publica(url):
            raise RuntimeError("URL_DESTINO_NAO_PUBLICO")
        return url

    resposta, url_final = seguir_redirecionamentos_seguros(url)
    resposta.close()
    flags_finais = detectar_plataforma_url(url_final)
    if not any(flags_finais) or not any(
        original and final
        for original, final in zip(flags_originais, flags_finais)
    ):
        raise RuntimeError("REDIRECIONAMENTO_FORA_DA_PLATAFORMA")
    return url_final


def normalizar_url_instagram(url):
    """Remove parâmetros de rastreamento e padroniza links de post/Reel."""
    match = re.search(
        r"https?://(?:www\.)?instagram\.com/(?:[^/?#]+/)?(p|reels?|tv)/([^/?#&]+)",
        url,
        flags=re.IGNORECASE,
    )
    if not match:
        return url

    tipo = match.group(1).lower()
    if tipo in ("reel", "reels"):
        tipo = "reel"
    return f"https://www.instagram.com/{tipo}/{match.group(2)}/"


def cleanup_prefix(prefix):
    try:
        for arq in glob.glob(f"{prefix}*"):
            try:
                os.remove(arq)
            except Exception as e:
                logger.warning(
                    f"[CLEANUP] arquivo_ref={referencia_arquivo_log(arq)} "
                    f"erro={sanitizar_erro_log(e)}"
                )
    except Exception as e:
        logger.warning(
            f"[CLEANUP] prefixo_ref={referencia_arquivo_log(prefix)} "
            f"erro={sanitizar_erro_log(e)}"
        )


def cleanup_download_dir_old_files(max_age_hours=6):
    agora = time.time()
    max_age_seconds = max_age_hours * 3600

    try:
        for arq in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try:
                if not os.path.isfile(arq):
                    continue
                if os.path.basename(arq) in ARQUIVOS_PERSISTENTES_DOWNLOAD_DIR:
                    continue
                idade = agora - os.path.getmtime(arq)
                if idade > max_age_seconds:
                    os.remove(arq)
                    logger.info(
                        "[CLEANUP_OLD] removido=True "
                        f"arquivo_ref={referencia_arquivo_log(arq)}"
                    )
            except Exception as e:
                logger.warning(
                    f"[CLEANUP_OLD] arquivo_ref={referencia_arquivo_log(arq)} "
                    f"erro={sanitizar_erro_log(e)}"
                )
    except Exception as e:
        logger.warning(
            f"[CLEANUP_OLD] diretorio_ref={referencia_arquivo_log(DOWNLOAD_DIR)} "
            f"erro={sanitizar_erro_log(e)}"
        )


def _consultar_espaco_livre_download():
    uso = shutil.disk_usage(DOWNLOAD_DIR)
    return int(uso.free), int(uso.total)


def _atualizar_alerta_espaco_disco(espaco_baixo, livre_bytes=None):
    """Alerta no máximo uma vez por hora enquanto o disco continuar baixo."""
    agora_monotonic = time.monotonic()
    deve_alertar = False
    recuperou = False

    with DISK_SPACE_ALERT_LOCK:
        estado = DISK_SPACE_ALERT_STATE
        if espaco_baixo:
            cooldown = max(3600, MONITOR_ALERT_COOLDOWN_SECONDS)
            deve_alertar = (
                not estado["active"]
                or agora_monotonic - estado["last_alert_at"] >= cooldown
            )
            estado["active"] = True
            if deve_alertar:
                estado["last_alert_at"] = agora_monotonic
        else:
            recuperou = bool(estado["active"])
            estado["active"] = False

    if deve_alertar:
        livre_mb = max(0, int(livre_bytes or 0)) / (1024 * 1024)
        safe_send_message(
            ADMIN_ID,
            "⚠️ <b>Armazenamento temporário quase cheio</b>\n\n"
            f"Espaço livre: <b>{livre_mb:.0f} MB</b>\n"
            f"Mínimo configurado: <b>{MIN_DISK_FREE_MB} MB</b>\n\n"
            "Novos downloads locais foram pausados para evitar arquivos "
            "incompletos. Entregas já existentes no cache continuam "
            "funcionando.",
            parse_mode="HTML",
        )
    elif recuperou:
        logger.info("[DISK_GUARD] armazenamento_normalizado=True")


def garantir_espaco_para_novo_download():
    """Limpa temporários uma vez e bloqueia se ainda faltar espaço."""
    try:
        livre_antes, _total = _consultar_espaco_livre_download()
    except Exception as e:
        registrar_falha_componente("Armazenamento", e)
        logger.error(
            f"[DISK_GUARD] consulta_falhou=True erro={sanitizar_erro_log(e)}"
        )
        return False, None

    if livre_antes >= MIN_DISK_FREE_BYTES:
        _atualizar_alerta_espaco_disco(False, livre_antes)
        return True, livre_antes

    logger.warning(
        f"[DISK_GUARD] limpeza_necessaria=True "
        f"livre_mb={livre_antes / (1024 * 1024):.0f} "
        f"minimo_mb={MIN_DISK_FREE_MB}"
    )
    cleanup_download_dir_old_files(max_age_hours=0)

    try:
        livre_depois, _total = _consultar_espaco_livre_download()
    except Exception as e:
        registrar_falha_componente("Armazenamento", e)
        logger.error(
            "[DISK_GUARD] consulta_apos_limpeza_falhou=True "
            f"erro={sanitizar_erro_log(e)}"
        )
        return False, None

    if livre_depois >= MIN_DISK_FREE_BYTES:
        _atualizar_alerta_espaco_disco(False, livre_depois)
        logger.info(
            f"[DISK_GUARD] limpeza_recuperou_espaco=True "
            f"livre_mb={livre_depois / (1024 * 1024):.0f}"
        )
        return True, livre_depois

    logger.error(
        f"[DISK_GUARD] download_bloqueado=True "
        f"livre_mb={livre_depois / (1024 * 1024):.0f} "
        f"minimo_mb={MIN_DISK_FREE_MB}"
    )
    _atualizar_alerta_espaco_disco(True, livre_depois)
    return False, livre_depois


def informar_download_pausado_por_espaco(message, status_msg):
    texto = (
        "⏳ O armazenamento temporário do bot está quase cheio. Para evitar "
        "um vídeo incompleto, este download não foi iniciado. Aguarde alguns "
        "instantes e envie o link novamente. Esta tentativa não consumiu seu "
        "limite diário."
    )
    if status_msg and safe_edit_message(
        message.chat.id,
        status_msg.message_id,
        texto,
    ):
        return
    safe_send_message(message.chat.id, texto)


def cleanup_download_dir_periodicamente(interval_minutes=60, max_age_hours=6):
    intervalo_segundos = max(300, int(interval_minutes * 60))
    proxima_limpeza = time.monotonic() + intervalo_segundos
    proximo_aviso_vip = (
        time.monotonic() + VIP_EXPIRATION_NOTICE_INITIAL_DELAY_SECONDS
    )
    recuperar_fila_em = time.monotonic() + QUEUE_RECOVERY_DELAY_SECONDS
    recuperacao_fila_executada = False
    logger.info(
        f"[MAINTENANCE_LOOP] iniciado cleanup_minutes={interval_minutes} "
        f"max_age_hours={max_age_hours} "
        f"watchdog_seconds={WORKER_WATCHDOG_INTERVAL_SECONDS} "
        f"vip_notice_check_seconds={VIP_EXPIRATION_NOTICE_CHECK_SECONDS} "
        f"queue_recovery_delay_seconds={QUEUE_RECOVERY_DELAY_SECONDS} "
        f"queue_recovery_ttl_hours={QUEUE_RECOVERY_TTL_HOURS} "
        "queue_recovery_contains_urls=False"
    )

    while not SHUTDOWN_EVENT.is_set():
        try:
            verificar_travamento_worker()
        except Exception as e:
            logger.warning(f"[WORKER_WATCHDOG] erro={sanitizar_erro_log(e)}")

        agora_monotonic = time.monotonic()
        if (
            not recuperacao_fila_executada
            and agora_monotonic >= recuperar_fila_em
        ):
            recuperar_fila_interrompida()
            recuperacao_fila_executada = True

        if agora_monotonic >= proxima_limpeza:
            try:
                cleanup_download_dir_old_files(max_age_hours=max_age_hours)
            except Exception as e:
                logger.warning(f"[CLEANUP_LOOP] erro={sanitizar_erro_log(e)}")
            proxima_limpeza = agora_monotonic + intervalo_segundos

        if agora_monotonic >= proximo_aviso_vip:
            try:
                notificar_vips_com_vencimento_proximo()
            except Exception as e:
                logger.warning(
                    f"[VIP_EXPIRATION_NOTICE_LOOP] erro={sanitizar_erro_log(e)}"
                )
            proximo_aviso_vip = (
                agora_monotonic + VIP_EXPIRATION_NOTICE_CHECK_SECONDS
            )

        proxima_atividade = min(proxima_limpeza, proximo_aviso_vip)
        if not recuperacao_fila_executada:
            proxima_atividade = min(proxima_atividade, recuperar_fila_em)
        espera = max(
            0.25,
            min(
                WORKER_WATCHDOG_INTERVAL_SECONDS,
                proxima_atividade - time.monotonic(),
            ),
        )
        SHUTDOWN_EVENT.wait(espera)


def encontrar_arquivo_baixado(prefix):
    try:
        candidatos = []
        for arq in glob.glob(f"{prefix}*"):
            nome = arq.lower()
            if nome.endswith(".part") or nome.endswith(".ytdl"):
                continue
            if os.path.isfile(arq):
                candidatos.append(arq)

        if not candidatos:
            return None

        candidatos.sort(key=lambda x: os.path.getsize(x), reverse=True)
        return candidatos[0]
    except OSError as e:
        raise FalhaComponenteDownload("Armazenamento", e) from e


def parse_fps(valor):
    try:
        if not valor or valor in ("0/0", "N/A"):
            return None
        if "/" in str(valor):
            num, den = str(valor).split("/", 1)
            num = float(num)
            den = float(den)
            if den == 0:
                return None
            return num / den
        return float(valor)
    except Exception:
        return None


def obter_info_midia(arquivo_entrada):
    atualizar_heartbeat_worker("analisando_midia")

    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        arquivo_entrada
    ]

    try:
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        logger.warning(
            f"[FFPROBE] arquivo_ref={referencia_arquivo_log(arquivo_entrada)} "
            "tempo_limite=True "
            f"timeout={FFPROBE_TIMEOUT_SECONDS}s"
        )
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFPROBE_TIMEOUT timeout={FFPROBE_TIMEOUT_SECONDS}s",
        ) from e

    if resultado.returncode != 0:
        logger.warning(
            f"[FFPROBE] arquivo_ref={referencia_arquivo_log(arquivo_entrada)} "
            f"erro={sanitizar_erro_log(resultado.stderr[-500:])}"
        )
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFPROBE_FALHOU codigo={resultado.returncode}",
        )

    try:
        import json
        dados = json.loads(resultado.stdout)
    except Exception as e:
        logger.warning(
            f"[FFPROBE] arquivo_ref={referencia_arquivo_log(arquivo_entrada)} "
            f"json_invalido=True erro={sanitizar_erro_log(e)}"
        )
        raise FalhaComponenteDownload(
            "Processamento",
            "FFPROBE_JSON_INVALIDO",
        ) from e

    video_stream = None
    audio_stream = None

    for stream in dados.get("streams", []):
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        elif stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    fps = None
    if video_stream:
        fps = parse_fps(video_stream.get("avg_frame_rate")) or parse_fps(video_stream.get("r_frame_rate"))

    format_name = (dados.get("format", {}) or {}).get("format_name", "")
    duracao = (dados.get("format", {}) or {}).get("duration")
    if duracao in (None, "N/A") and video_stream:
        duracao = video_stream.get("duration")
    try:
        duracao = float(duracao) if duracao not in (None, "N/A") else None
    except (TypeError, ValueError):
        duracao = None
    tamanho = None
    try:
        tamanho = os.path.getsize(arquivo_entrada)
    except OSError as e:
        raise FalhaComponenteDownload("Armazenamento", e) from e

    return {
        "width": (video_stream or {}).get("width"),
        "height": (video_stream or {}).get("height"),
        "fps": fps,
        "vcodec": (video_stream or {}).get("codec_name"),
        "acodec": (audio_stream or {}).get("codec_name") if audio_stream else None,
        "format_name": format_name,
        "size_bytes": tamanho,
        "duration": duracao,
    }


def validar_arquivo_midia(arquivo, limite_bytes, fase="arquivo", exigir_duracao=True):
    """Impede mídia sem duração, longa demais ou grande demais."""
    if not arquivo or not os.path.isfile(arquivo):
        raise FalhaComponenteDownload(
            "Armazenamento",
            f"ARQUIVO_MIDIA_AUSENTE fase={fase}",
        )

    try:
        tamanho = os.path.getsize(arquivo)
    except OSError as e:
        raise FalhaComponenteDownload("Armazenamento", e) from e
    if tamanho <= 0:
        raise RuntimeError(f"ARQUIVO_MIDIA_VAZIO fase={fase}")
    if tamanho > limite_bytes:
        limite_mb = limite_bytes / (1024 * 1024)
        raise RuntimeError(
            f"ARQUIVO_MIDIA_MUITO_GRANDE fase={fase} "
            f"tamanho={tamanho} limite_mb={limite_mb:.0f}"
        )

    info = obter_info_midia(arquivo)
    if not info:
        raise FalhaComponenteDownload(
            "Processamento",
            f"MIDIA_INVALIDA_OU_NAO_ANALISAVEL fase={fase}",
        )

    duracao = info.get("duration")
    if exigir_duracao and (duracao is None or duracao <= 0):
        raise RuntimeError(f"DURACAO_MIDIA_DESCONHECIDA fase={fase}")
    if duracao and duracao > MAX_DURATION_SECONDS + 0.5:
        raise RuntimeError(
            f"VIDEO_MUITO_LONGO fase={fase} duracao={duracao:.2f} "
            f"limite={MAX_DURATION_SECONDS}"
        )

    registrar_sucesso_componente("Armazenamento")
    return info


def arquivo_ja_otimizado_para_envio(arquivo_entrada, info=None, permitir_hevc=True):
    info = info or obter_info_midia(arquivo_entrada)
    if not info:
        return False

    ext = os.path.splitext(arquivo_entrada)[1].lower()
    width = info.get("width") or 0
    height = info.get("height") or 0
    fps = info.get("fps") or 0
    vcodec = (info.get("vcodec") or "").lower()
    acodec = (info.get("acodec") or "none").lower()

    codecs_video_aceitos = {"h264", "avc1"}
    if permitir_hevc:
        codecs_video_aceitos.update({"hevc", "h265", "hev1", "hvc1"})

    return (
        ext == ".mp4"
        and width <= 720
        and height <= 1280
        and fps <= 30.5
        and vcodec in codecs_video_aceitos
        and acodec in ("aac", "none")
    )


def permitir_hevc_por_plataforma(plataforma=None):
    plataforma = (plataforma or "").strip().lower()
    return plataforma in ("tiktok", "rednote")


def remuxar_para_mp4_faststart(arquivo_entrada):
    atualizar_heartbeat_worker("remux_ffmpeg")
    base, _ = os.path.splitext(arquivo_entrada)
    arquivo_saida = f"{base}_remux.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", arquivo_entrada,
        "-c", "copy",
        "-movflags", "+faststart",
        arquivo_saida
    ]

    try:
        atualizar_heartbeat_worker("remux_ffmpeg")
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFMPEG_TIMEOUT remux timeout={FFMPEG_TIMEOUT_SECONDS}s",
        ) from e

    if resultado.returncode != 0:
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFMPEG_REMUX_FALHOU codigo={resultado.returncode}",
        )

    if not os.path.exists(arquivo_saida):
        raise FalhaComponenteDownload(
            "Processamento",
            "FFMPEG_REMUX_NAO_GEROU_SAIDA",
        )

    return arquivo_saida


def arquivo_tem_codec_hevc(arquivo_entrada, info=None):
    info = info or obter_info_midia(arquivo_entrada)
    if not info:
        return False

    vcodec = (info.get("vcodec") or "").lower()
    return vcodec in ("hevc", "h265", "hev1", "hvc1")


def montar_vf_limite_720x1280_30fps(info=None):
    info = info or {}
    width = info.get("width") or 0
    height = info.get("height") or 0
    fps = info.get("fps") or 0

    filtros = []

    if width > 720 or height > 1280:
        filtros.append("scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2")

    if fps > 30.5:
        filtros.append("fps=30")

    return ",".join(filtros) if filtros else None


def converter_para_h264_compativel(arquivo_entrada, info=None):
    """
    Fallback para compatibilidade: converte para MP4 H.264/AAC.
    Mantém resolução/fps originais quando já estão dentro do limite,
    e só reduz quando realmente necessário.
    """
    atualizar_heartbeat_worker("convertendo_h264")
    info = info or obter_info_midia(arquivo_entrada) or {}
    base, _ = os.path.splitext(arquivo_entrada)
    arquivo_saida = f"{base}_fallback_h264.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", arquivo_entrada,
    ]

    vf = montar_vf_limite_720x1280_30fps(info)
    if vf:
        cmd += ["-vf", vf]

    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(VIDEO_CRF),
        "-threads", str(FFMPEG_THREADS),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        arquivo_saida
    ]

    try:
        atualizar_heartbeat_worker("convertendo_h264")
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFMPEG_TIMEOUT fallback timeout={FFMPEG_TIMEOUT_SECONDS}s",
        ) from e

    if resultado.returncode != 0:
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFMPEG_FALLBACK_FALHOU codigo={resultado.returncode}",
        )

    if not os.path.exists(arquivo_saida):
        raise FalhaComponenteDownload(
            "Processamento",
            "FFMPEG_FALLBACK_NAO_GEROU_SAIDA",
        )

    return arquivo_saida


def converter_para_720x1280_30fps(arquivo_entrada):
    """
    Garante saída final em no máximo 720x1280, 30fps, H.264/AAC.
    Mantém a proporção original sem adicionar bordas e nunca amplia vídeos
    que já tenham resolução menor que o limite.
    """
    atualizar_heartbeat_worker("convertendo_video")
    info = obter_info_midia(arquivo_entrada) or {}
    base, _ = os.path.splitext(arquivo_entrada)
    arquivo_saida = f"{base}_720x1280_30fps.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", arquivo_entrada,
    ]

    # Só adiciona escala se o vídeo realmente ultrapassar 720x1280. Se ele
    # for menor e precisar apenas de ajuste de fps/codec, preserva a resolução.
    vf = montar_vf_limite_720x1280_30fps(info)
    if vf:
        cmd += ["-vf", vf]

    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", str(VIDEO_CRF),
        "-threads", str(FFMPEG_THREADS),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-movflags", "+faststart",
        arquivo_saida
    ]

    try:
        atualizar_heartbeat_worker("convertendo_video")
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFMPEG_TIMEOUT conversao timeout={FFMPEG_TIMEOUT_SECONDS}s",
        ) from e

    if resultado.returncode != 0:
        raise FalhaComponenteDownload(
            "Processamento",
            f"FFMPEG_CONVERSAO_FALHOU codigo={resultado.returncode}",
        )

    if not os.path.exists(arquivo_saida):
        raise FalhaComponenteDownload(
            "Processamento",
            "FFMPEG_CONVERSAO_NAO_GEROU_SAIDA",
        )

    return arquivo_saida


def preparar_arquivo_para_envio(arquivo_entrada, plataforma=None):
    atualizar_heartbeat_worker("preparando_envio")
    info = obter_info_midia(arquivo_entrada)
    permitir_hevc = permitir_hevc_por_plataforma(plataforma)

    if arquivo_ja_otimizado_para_envio(arquivo_entrada, info, permitir_hevc=permitir_hevc):
        logger.info(
            f"[MIDIA] Enviando original sem reconversão | plataforma={plataforma} "
            f"arquivo_ref={referencia_arquivo_log(arquivo_entrada)} "
            f"width={info.get('width')} height={info.get('height')} fps={info.get('fps')} "
            f"vcodec={info.get('vcodec')} acodec={info.get('acodec')} permitir_hevc={permitir_hevc}"
        )
        return arquivo_entrada

    if info:
        width = info.get("width") or 0
        height = info.get("height") or 0
        fps = info.get("fps") or 0
        ext = os.path.splitext(arquivo_entrada)[1].lower()
        vcodec = (info.get("vcodec") or "").lower()
        acodec = (info.get("acodec") or "none").lower()

        if (
            width <= 720
            and height <= 1280
            and fps <= 30.5
            and ext != ".mp4"
            and acodec in ("aac", "none")
            and (vcodec in ("h264", "avc1") or (permitir_hevc and vcodec in ("hevc", "h265", "hev1", "hvc1")))
        ):
            logger.info(
                f"[MIDIA] Fazendo apenas remux para MP4 | plataforma={plataforma} "
                f"arquivo_ref={referencia_arquivo_log(arquivo_entrada)} "
                f"width={width} height={height} fps={fps} "
                f"vcodec={info.get('vcodec')} acodec={info.get('acodec')} permitir_hevc={permitir_hevc}"
            )
            return remuxar_para_mp4_faststart(arquivo_entrada)

    logger.info(
        f"[MIDIA] Convertendo arquivo para padrão 720x1280 30fps | plataforma={plataforma} "
        f"arquivo_ref={referencia_arquivo_log(arquivo_entrada)} "
        f"info={info} permitir_hevc={permitir_hevc}"
    )
    return converter_para_720x1280_30fps(arquivo_entrada)


def safe_send_message(chat_id, texto, **kwargs):
    try:
        return bot.send_message(chat_id, texto, **kwargs)
    except Exception as e:
        logger.error(
            f"[SEND_MESSAGE] chat_ref={referencia_chat_log(chat_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return None


def safe_reply_to(message, texto, **kwargs):
    try:
        return bot.reply_to(message, texto, **kwargs)
    except Exception as e:
        logger.error(
            f"[REPLY_TO] chat_ref={referencia_chat_log(message.chat.id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return None


def safe_edit_message(chat_id, message_id, texto, **kwargs):
    try:
        return bot.edit_message_text(texto, chat_id, message_id, **kwargs)
    except Exception as e:
        logger.warning(
            f"[EDIT_MESSAGE] chat_ref={referencia_chat_log(chat_id)} "
            f"mensagem_ref={referencia_privada_log('msg', message_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return None


def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(
            f"[DELETE_MESSAGE] chat_ref={referencia_chat_log(chat_id)} "
            f"mensagem_ref={referencia_privada_log('msg', message_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )


def safe_answer_callback(call_id, **kwargs):
    try:
        bot.answer_callback_query(call_id, **kwargs)
    except Exception as e:
        logger.warning(f"[CALLBACK_ANSWER] erro={sanitizar_erro_log(e)}")


def normalizar_plataforma_monitoramento(plataforma):
    mapa = {
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "pinterest": "Pinterest",
        "rednote": "RedNote",
    }
    return mapa.get(str(plataforma or "").strip().lower())


def normalizar_componente_monitoramento(componente):
    plataforma = normalizar_plataforma_monitoramento(componente)
    if plataforma:
        return plataforma
    mapa = {
        "telegram": "Telegram",
        "processamento": "Processamento",
        "ffmpeg": "Processamento",
        "ffprobe": "Processamento",
        "mongodb": "MongoDB",
        "mongo": "MongoDB",
        "armazenamento": "Armazenamento",
        "disco": "Armazenamento",
        "interno": "Interno",
    }
    return mapa.get(str(componente or "").strip().lower())


def falha_tecnica_monitoravel(erro):
    """Separa falhas do serviço de limitações próprias do conteúdo enviado."""
    texto = str(erro or "").lower()
    marcadores_conteudo = (
        "video_muito_longo",
        "vídeo muito longo",
        "arquivo_midia_muito_grande",
        "arquivo muito grande",
        "private video",
        "this video is private",
        "vídeo privado",
        "video unavailable",
        "video is currently unavailable",
        "vídeo indisponível",
        "no longer available",
        "content is unavailable",
        "has been deleted",
        "removed by the uploader",
        "account is private",
        "pin not found",
        "http error 404",
        "not available in your country",
        "geo-restricted",
        "age-restricted",
        "unsupported url",
        "link não reconhecido",
        "conteúdo não encontrado",
        "content isn't available",
        "post isn't available",
        "redirecionamento_fora_da_plataforma",
    )
    return bool(texto) and not any(
        marcador in texto for marcador in marcadores_conteudo
    )


def registrar_falha_componente(componente, erro):
    """Conta a falha somente na origem confirmada e alerta sem dados sensíveis."""
    componente = normalizar_componente_monitoramento(componente)
    if not componente or not falha_tecnica_monitoravel(erro):
        return False

    agora_monotonic = time.monotonic()
    inicio_janela = agora_monotonic - MONITOR_FAILURE_WINDOW_SECONDS
    erro_limpo = sanitizar_erro_monitoramento(erro, limite=500)
    deve_alertar = False
    total_falhas = 0

    with COMPONENT_MONITOR_LOCK:
        estado = COMPONENT_MONITOR_STATE[componente]
        falhas = estado["failures"]
        while falhas and falhas[0] < inicio_janela:
            falhas.popleft()
        falhas.append(agora_monotonic)
        estado["last_error"] = erro_limpo
        total_falhas = len(falhas)

        cooldown_cumprido = (
            agora_monotonic - float(estado.get("last_alert_at") or 0.0)
            >= MONITOR_ALERT_COOLDOWN_SECONDS
        )
        if total_falhas >= MONITOR_FAILURE_THRESHOLD and (
            not estado["alert_active"] or cooldown_cumprido
        ):
            estado["alert_active"] = True
            estado["last_alert_at"] = agora_monotonic
            deve_alertar = True

    logger.warning(
        f"[MONITOR_FALHA] componente={componente} "
        f"falhas_janela={total_falhas} alerta={deve_alertar} erro={erro_limpo}"
    )

    if deve_alertar:
        janela_minutos = max(1, MONITOR_FAILURE_WINDOW_SECONDS // 60)
        safe_send_message(
            ADMIN_ID,
            "⚠️ <b>Alerta automático de funcionamento</b>\n\n"
            f"Componente: <b>{html.escape(componente)}</b>\n"
            f"Falhas técnicas: <b>{total_falhas}</b> nos últimos "
            f"{janela_minutos} minutos\n"
            f"Última falha: <code>{html.escape(erro_limpo)}</code>\n\n"
            "O bot continuará tentando normalmente. Você será avisado quando "
            "esse componente voltar a funcionar.",
            parse_mode="HTML",
        )
    return deve_alertar


def registrar_sucesso_componente(componente):
    """Atualiza sempre a saúde e reduz somente os logs repetitivos."""
    componente = normalizar_componente_monitoramento(componente)
    if not componente:
        return False

    agora_monotonic = time.monotonic()
    recuperou_alerta = False
    deve_logar = False
    with COMPONENT_MONITOR_LOCK:
        estado = COMPONENT_MONITOR_STATE[componente]
        recuperou_alerta = bool(estado["alert_active"])
        teve_falha_recente = bool(estado["failures"])
        estado["failures"].clear()
        estado["alert_active"] = False
        estado["last_error"] = None
        estado["last_success_at"] = agora_tz().isoformat()
        ultimo_log = estado.get("last_success_log_monotonic")
        deve_logar = (
            recuperou_alerta
            or teve_falha_recente
            or ultimo_log is None
            or agora_monotonic - float(ultimo_log)
            >= MONITOR_SUCCESS_LOG_INTERVAL_SECONDS
        )
        if deve_logar:
            estado["last_success_log_monotonic"] = agora_monotonic

    if deve_logar:
        logger.info(
            f"[MONITOR_SUCESSO] componente={componente} "
            f"recuperacao={recuperou_alerta}"
        )
    if recuperou_alerta:
        safe_send_message(
            ADMIN_ID,
            "✅ <b>Componente normalizado</b>\n\n"
            f"<b>{html.escape(componente)}</b> voltou a funcionar normalmente.",
            parse_mode="HTML",
        )
    return recuperou_alerta


def registrar_falha_plataforma(plataforma, erro):
    return registrar_falha_componente(plataforma, erro)


def registrar_sucesso_plataforma(plataforma):
    return registrar_sucesso_componente(plataforma)


def obter_resumo_monitoramento():
    agora_monotonic = time.monotonic()
    inicio_janela = agora_monotonic - MONITOR_FAILURE_WINDOW_SECONDS
    resumo = {}

    with COMPONENT_MONITOR_LOCK:
        for componente, estado in COMPONENT_MONITOR_STATE.items():
            falhas = estado["failures"]
            while falhas and falhas[0] < inicio_janela:
                falhas.popleft()
            resumo[componente] = {
                "falhas_recentes": len(falhas),
                "alerta_ativo": bool(estado["alert_active"]),
                "ultimo_erro": estado.get("last_error"),
                "ultimo_sucesso": estado.get("last_success_at"),
            }
    return resumo


def definir_estado_worker_download(ativo):
    global DOWNLOAD_WORKER_RUNNING
    agora_monotonic = time.monotonic()
    agora_iso = datetime.now(TZ).isoformat()
    with DOWNLOAD_WORKER_STATE_LOCK:
        DOWNLOAD_WORKER_RUNNING = bool(ativo)
        DOWNLOAD_WORKER_STATE["phase"] = "aguardando" if ativo else "parado"
        DOWNLOAD_WORKER_STATE["heartbeat_monotonic"] = agora_monotonic
        DOWNLOAD_WORKER_STATE["last_progress_at"] = agora_iso
        if not ativo:
            DOWNLOAD_WORKER_STATE["busy"] = False
            DOWNLOAD_WORKER_STATE["active_user_id"] = None
            DOWNLOAD_WORKER_STATE["active_has_download_reservation"] = False
            DOWNLOAD_WORKER_STATE["job_started_monotonic"] = None
            DOWNLOAD_WORKER_STATE["job_started_at"] = None
            DOWNLOAD_WORKER_STATE["stall_alert_active"] = False
            DOWNLOAD_WORKER_STATE["stall_detected_monotonic"] = None
            DOWNLOAD_WORKER_STATE["restart_in_progress"] = False
            DOWNLOAD_WORKER_STATE["restart_blocked_reason"] = None
            DOWNLOAD_WORKER_STATE["restart_retry_after_monotonic"] = 0.0


def worker_download_esta_ativo():
    with DOWNLOAD_WORKER_STATE_LOCK:
        return DOWNLOAD_WORKER_RUNNING


def _notificar_recuperacao_worker(fase):
    logger.info(f"[WORKER_WATCHDOG] recuperado fase={fase}")
    safe_send_message(
        ADMIN_ID,
        "✅ <b>Worker de downloads recuperado</b>\n\n"
        f"O processamento voltou a responder na etapa "
        f"<code>{html.escape(str(fase))}</code>.\n"
        "Nenhum segundo worker foi iniciado.",
        parse_mode="HTML",
    )


def iniciar_trabalho_worker(user_id=None, has_download_reservation=False):
    """Marca um item como ativo sem registrar URL ou identificador nos logs."""
    agora_monotonic = time.monotonic()
    agora_iso = datetime.now(TZ).isoformat()
    recuperou = False
    with DOWNLOAD_WORKER_STATE_LOCK:
        if not DOWNLOAD_WORKER_RUNNING:
            return
        recuperou = bool(DOWNLOAD_WORKER_STATE["stall_alert_active"])
        DOWNLOAD_WORKER_STATE.update({
            "busy": True,
            "active_user_id": str(user_id) if user_id is not None else None,
            "active_has_download_reservation": bool(
                has_download_reservation
            ),
            "phase": "iniciando",
            "heartbeat_monotonic": agora_monotonic,
            "job_started_monotonic": agora_monotonic,
            "last_progress_at": agora_iso,
            "job_started_at": agora_iso,
            "stall_alert_active": False,
            "stall_detected_monotonic": None,
            "restart_in_progress": False,
            "restart_blocked_reason": None,
            "restart_retry_after_monotonic": 0.0,
        })
    if recuperou:
        _notificar_recuperacao_worker("iniciando")


def atualizar_heartbeat_worker(fase):
    """Atualiza o progresso do worker; chamadas fora de um trabalho são ignoradas."""
    agora_monotonic = time.monotonic()
    recuperou = False
    with DOWNLOAD_WORKER_STATE_LOCK:
        if not DOWNLOAD_WORKER_RUNNING or not DOWNLOAD_WORKER_STATE["busy"]:
            return False

        heartbeat_anterior = DOWNLOAD_WORKER_STATE.get("heartbeat_monotonic")
        mesma_fase = DOWNLOAD_WORKER_STATE.get("phase") == str(fase)
        alerta_ativo = bool(DOWNLOAD_WORKER_STATE["stall_alert_active"])
        if (
            mesma_fase
            and not alerta_ativo
            and heartbeat_anterior is not None
            and agora_monotonic - heartbeat_anterior < 1.0
        ):
            return False

        recuperou = alerta_ativo
        agora_iso = datetime.now(TZ).isoformat()
        DOWNLOAD_WORKER_STATE.update({
            "phase": str(fase),
            "heartbeat_monotonic": agora_monotonic,
            "last_progress_at": agora_iso,
            "stall_alert_active": False,
            "stall_detected_monotonic": None,
            "restart_in_progress": False,
            "restart_blocked_reason": None,
            "restart_retry_after_monotonic": 0.0,
        })

    if recuperou:
        _notificar_recuperacao_worker(fase)
    return True


def concluir_trabalho_worker():
    agora_monotonic = time.monotonic()
    agora_iso = datetime.now(TZ).isoformat()
    recuperou = False
    with DOWNLOAD_WORKER_STATE_LOCK:
        recuperou = bool(DOWNLOAD_WORKER_STATE["stall_alert_active"])
        DOWNLOAD_WORKER_STATE.update({
            "busy": False,
            "active_user_id": None,
            "active_has_download_reservation": False,
            "phase": "aguardando",
            "heartbeat_monotonic": agora_monotonic,
            "job_started_monotonic": None,
            "last_progress_at": agora_iso,
            "job_started_at": None,
            "last_completed_at": agora_iso,
            "completed_jobs": int(DOWNLOAD_WORKER_STATE["completed_jobs"]) + 1,
            "stall_alert_active": False,
            "stall_detected_monotonic": None,
            "restart_in_progress": False,
            "restart_blocked_reason": None,
            "restart_retry_after_monotonic": 0.0,
        })
    if recuperou:
        _notificar_recuperacao_worker("trabalho_concluido")


def obter_usuario_ativo_worker():
    """Uso interno no desligamento; o identificador nunca entra no healthcheck."""
    with DOWNLOAD_WORKER_STATE_LOCK:
        user_id = DOWNLOAD_WORKER_STATE.get("active_user_id")
        return str(user_id) if user_id is not None else None


def trabalho_ativo_tem_reserva_download():
    """Uso interno no desligamento; este estado não entra no healthcheck."""
    with DOWNLOAD_WORKER_STATE_LOCK:
        return bool(
            DOWNLOAD_WORKER_STATE.get("active_has_download_reservation")
        )


def obter_saude_worker():
    agora_monotonic = time.monotonic()
    with DOWNLOAD_WORKER_STATE_LOCK:
        running = bool(DOWNLOAD_WORKER_RUNNING)
        estado = dict(DOWNLOAD_WORKER_STATE)

    busy = bool(estado["busy"])
    heartbeat = estado.get("heartbeat_monotonic")
    inicio = estado.get("job_started_monotonic")
    sem_progresso = (
        max(0, int(agora_monotonic - heartbeat))
        if busy and heartbeat is not None
        else None
    )
    tempo_trabalho = (
        max(0, int(agora_monotonic - inicio))
        if busy and inicio is not None
        else None
    )
    travado = bool(
        running
        and busy
        and sem_progresso is not None
        and sem_progresso >= WORKER_STALL_TIMEOUT_SECONDS
    )
    detectado_em = estado.get("stall_detected_monotonic")
    reinicio_em = None
    if travado and detectado_em is not None:
        reinicio_em = max(
            0,
            int(
                WORKER_RESTART_GRACE_SECONDS
                - (agora_monotonic - detectado_em)
            ),
        )

    if not running:
        status = "stopped"
    elif travado:
        status = "stalled"
    elif busy:
        status = "processing"
    else:
        status = "idle"

    return {
        "status": status,
        "running": running,
        "busy": busy,
        "stalled": travado,
        "phase": estado.get("phase"),
        "seconds_without_progress": sem_progresso,
        "active_job_seconds": tempo_trabalho,
        "stall_timeout_seconds": WORKER_STALL_TIMEOUT_SECONDS,
        "auto_restart": {
            "enabled": True,
            "grace_seconds": WORKER_RESTART_GRACE_SECONDS,
            "restart_due_in_seconds": reinicio_em,
            "in_progress": bool(estado.get("restart_in_progress")),
            "blocked_reason": estado.get("restart_blocked_reason"),
            "max_restarts_per_hour": WORKER_MAX_RESTARTS_PER_HOUR,
        },
        "queue_size": DOWNLOAD_QUEUE.qsize(),
        "queue_capacity": DOWNLOAD_QUEUE_MAX,
        "completed_jobs": int(estado.get("completed_jobs") or 0),
        "last_progress_at": estado.get("last_progress_at"),
        "job_started_at": estado.get("job_started_at"),
        "last_completed_at": estado.get("last_completed_at"),
        "last_alerted_at": estado.get("stall_alerted_at"),
        "alert_active": bool(estado.get("stall_alert_active")),
    }


def _worker_ainda_travado_para_reinicio():
    agora_monotonic = time.monotonic()
    with DOWNLOAD_WORKER_STATE_LOCK:
        heartbeat = DOWNLOAD_WORKER_STATE.get("heartbeat_monotonic")
        return bool(
            DOWNLOAD_WORKER_RUNNING
            and DOWNLOAD_WORKER_STATE["busy"]
            and DOWNLOAD_WORKER_STATE["stall_alert_active"]
            and DOWNLOAD_WORKER_STATE["restart_in_progress"]
            and heartbeat is not None
            and agora_monotonic - heartbeat >= WORKER_STALL_TIMEOUT_SECONDS
        )


def _registrar_bloqueio_reinicio_worker(motivo, detalhe=None, retry_seconds=None):
    """Adia uma nova tentativa e evita repetir o mesmo alerta ao administrador."""
    retry_seconds = int(retry_seconds or WORKER_RESTART_RETRY_SECONDS)
    agora_monotonic = time.monotonic()
    deve_alertar = False
    with DOWNLOAD_WORKER_STATE_LOCK:
        motivo_anterior = DOWNLOAD_WORKER_STATE.get("restart_blocked_reason")
        DOWNLOAD_WORKER_STATE["restart_in_progress"] = False
        DOWNLOAD_WORKER_STATE["restart_blocked_reason"] = str(motivo)
        DOWNLOAD_WORKER_STATE["restart_retry_after_monotonic"] = (
            agora_monotonic + max(60, retry_seconds)
        )
        deve_alertar = motivo_anterior != str(motivo)

    logger.error(
        f"[WORKER_AUTO_RESTART_BLOQUEADO] motivo={motivo} "
        f"detalhe={sanitizar_erro_log(detalhe, limite=300) if detalhe else 'n/a'}"
    )
    if deve_alertar:
        mensagem_detalhe = (
            f"\nDetalhe: <code>{html.escape(sanitizar_erro_log(detalhe, limite=180))}</code>"
            if detalhe
            else ""
        )
        safe_send_message(
            ADMIN_ID,
            "⛔ <b>Reinício automático bloqueado</b>\n\n"
            f"Motivo: <code>{html.escape(str(motivo))}</code>"
            f"{mensagem_detalhe}\n\n"
            "O processo não foi encerrado. O bot tentará verificar novamente "
            f"em aproximadamente {max(1, retry_seconds // 60)} minuto(s).",
            parse_mode="HTML",
        )


def _notificar_usuarios_reinicio_worker():
    """Avisa apenas os usuários da fila atual, sem persistir IDs ou URLs."""
    with DOWNLOAD_PENDING_LOCK:
        usuarios_afetados = sorted(DOWNLOAD_PENDING_USERS)

    notificados = 0
    for user_id in usuarios_afetados:
        try:
            enviado = safe_send_message(
                int(user_id),
                "⚠️ O processamento do seu vídeo foi interrompido por uma "
                "recuperação técnica do bot.\n\n"
                "Aguarde alguns instantes e envie o link novamente. Esta "
                "tentativa não consumiu seu limite diário de downloads.",
            )
            if enviado:
                notificados += 1
        except (TypeError, ValueError):
            logger.warning("[WORKER_AUTO_RESTART] user_id pendente inválido")
    return len(usuarios_afetados), notificados


def _encerrar_processo_para_reinicio():
    """Encerra todo o processo; SystemExit em uma thread não seria suficiente."""
    logging.shutdown()
    os._exit(WORKER_RESTART_EXIT_CODE)


def tentar_reinicio_automatico_worker(fase, sem_progresso):
    """Autoriza no MongoDB e só então encerra o processo para a Railway subir outro."""
    if SHUTDOWN_EVENT.is_set():
        return False
    if not _worker_ainda_travado_para_reinicio():
        return False

    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    inicio_janela = agora_utc - timedelta(hours=1)
    evento_id = None

    try:
        client.admin.command("ping")
        reinicios_recentes = auditoria_sistema_col.count_documents({
            "event_type": "worker_auto_restart",
            "status": "restart_triggered",
            "created_at": {"$gte": inicio_janela},
        })
        if reinicios_recentes >= WORKER_MAX_RESTARTS_PER_HOUR:
            mais_antigo = auditoria_sistema_col.find_one(
                {
                    "event_type": "worker_auto_restart",
                    "status": "restart_triggered",
                    "created_at": {"$gte": inicio_janela},
                },
                sort=[("created_at", 1)],
            )
            retry_seconds = WORKER_RESTART_RETRY_SECONDS
            criado_em = (mais_antigo or {}).get("created_at")
            if isinstance(criado_em, datetime):
                if criado_em.tzinfo is not None:
                    criado_em = criado_em.astimezone(timezone.utc).replace(tzinfo=None)
                retry_seconds = max(
                    60,
                    int((criado_em + timedelta(hours=1) - agora_utc).total_seconds()) + 5,
                )
            _registrar_bloqueio_reinicio_worker(
                "limite_horario_atingido",
                detalhe=(
                    f"{reinicios_recentes}/{WORKER_MAX_RESTARTS_PER_HOUR} "
                    "reinicios na ultima hora"
                ),
                retry_seconds=retry_seconds,
            )
            return False

        saude = obter_saude_worker()
        documento = {
            "event_type": "worker_auto_restart",
            "status": "preparing",
            "service": SERVICE_NAME,
            "environment": ENVIRONMENT_NAME,
            "phase": str(fase),
            "seconds_without_progress": int(sem_progresso),
            "active_job_seconds": saude.get("active_job_seconds"),
            "queue_size": int(saude.get("queue_size") or 0),
            "affected_users_count": 0,
            "notified_users_count": 0,
            "stall_timeout_seconds": WORKER_STALL_TIMEOUT_SECONDS,
            "restart_grace_seconds": WORKER_RESTART_GRACE_SECONDS,
            "max_restarts_per_hour": WORKER_MAX_RESTARTS_PER_HOUR,
            "exit_code": WORKER_RESTART_EXIT_CODE,
            "contains_urls": False,
            "contains_user_ids": False,
            "created_at": agora_utc,
            "updated_at": agora_utc,
        }
        resultado = auditoria_sistema_col.insert_one(documento)
        evento_id = getattr(resultado, "inserted_id", None)
        if evento_id is None:
            raise RuntimeError("evento de reinicio sem identificador")
    except Exception as e:
        _registrar_bloqueio_reinicio_worker(
            "mongodb_indisponivel",
            detalhe=e,
        )
        return False

    if not _worker_ainda_travado_para_reinicio():
        try:
            auditoria_sistema_col.update_one(
                {"_id": evento_id, "status": "preparing"},
                {
                    "$set": {
                        "status": "cancelled_worker_recovered",
                        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
                    }
                },
            )
        except Exception as e:
            logger.warning(
                f"[WORKER_AUTO_RESTART_CANCELAMENTO] erro={sanitizar_erro_log(e)}"
            )
        return False

    total_afetados, total_notificados = _notificar_usuarios_reinicio_worker()

    if not _worker_ainda_travado_para_reinicio():
        try:
            auditoria_sistema_col.update_one(
                {"_id": evento_id, "status": "preparing"},
                {
                    "$set": {
                        "status": "cancelled_worker_recovered",
                        "affected_users_count": total_afetados,
                        "notified_users_count": total_notificados,
                        "updated_at": datetime.now(timezone.utc).replace(tzinfo=None),
                    }
                },
            )
        except Exception as e:
            logger.warning(
                f"[WORKER_AUTO_RESTART_CANCELAMENTO] erro={sanitizar_erro_log(e)}"
            )
        return False

    try:
        client.admin.command("ping")
        agora_final = datetime.now(timezone.utc).replace(tzinfo=None)
        resultado = auditoria_sistema_col.update_one(
            {"_id": evento_id, "status": "preparing"},
            {
                "$set": {
                    "status": "restart_triggered",
                    "affected_users_count": total_afetados,
                    "notified_users_count": total_notificados,
                    "triggered_at": agora_final,
                    "updated_at": agora_final,
                }
            },
        )
        if getattr(resultado, "modified_count", 0) != 1:
            raise RuntimeError("evento de reinicio não foi confirmado")
    except Exception as e:
        _registrar_bloqueio_reinicio_worker(
            "mongodb_indisponivel_na_confirmacao",
            detalhe=e,
        )
        return False

    logger.critical(
        f"[WORKER_AUTO_RESTART] evento_ref={referencia_privada_log('evento', evento_id)} "
        f"fase={fase} "
        f"sem_progresso={sem_progresso}s afetados={total_afetados} "
        f"notificados={total_notificados} exit_code={WORKER_RESTART_EXIT_CODE}"
    )
    _encerrar_processo_para_reinicio()
    return True


def verificar_travamento_worker():
    """Alerta após o limite e reinicia somente depois do período de confirmação."""
    if SHUTDOWN_EVENT.is_set():
        return False
    agora_monotonic = time.monotonic()
    deve_alertar = False
    deve_tentar_reinicio = False
    fase = "desconhecida"
    sem_progresso = 0

    with DOWNLOAD_WORKER_STATE_LOCK:
        heartbeat = DOWNLOAD_WORKER_STATE.get("heartbeat_monotonic")
        sem_progresso = (
            max(0, int(agora_monotonic - heartbeat))
            if heartbeat is not None
            else 0
        )
        travado = bool(
            DOWNLOAD_WORKER_RUNNING
            and DOWNLOAD_WORKER_STATE["busy"]
            and heartbeat is not None
            and sem_progresso >= WORKER_STALL_TIMEOUT_SECONDS
        )
        fase = DOWNLOAD_WORKER_STATE.get("phase") or "desconhecida"
        if travado and not DOWNLOAD_WORKER_STATE["stall_alert_active"]:
            DOWNLOAD_WORKER_STATE["stall_alert_active"] = True
            DOWNLOAD_WORKER_STATE["stall_alerted_at"] = datetime.now(TZ).isoformat()
            DOWNLOAD_WORKER_STATE["stall_detected_monotonic"] = agora_monotonic
            DOWNLOAD_WORKER_STATE["restart_blocked_reason"] = None
            DOWNLOAD_WORKER_STATE["restart_retry_after_monotonic"] = 0.0
            deve_alertar = True

        detectado_em = DOWNLOAD_WORKER_STATE.get("stall_detected_monotonic")
        retry_after = float(
            DOWNLOAD_WORKER_STATE.get("restart_retry_after_monotonic") or 0.0
        )
        if (
            travado
            and detectado_em is not None
            and agora_monotonic - detectado_em >= WORKER_RESTART_GRACE_SECONDS
            and agora_monotonic >= retry_after
            and not DOWNLOAD_WORKER_STATE["restart_in_progress"]
        ):
            DOWNLOAD_WORKER_STATE["restart_in_progress"] = True
            DOWNLOAD_WORKER_STATE["restart_blocked_reason"] = None
            deve_tentar_reinicio = True

    if deve_alertar:
        logger.error(
            f"[WORKER_WATCHDOG] travado fase={fase} "
            f"sem_progresso={sem_progresso}s"
        )
        safe_send_message(
            ADMIN_ID,
            "⚠️ <b>Worker de downloads sem progresso</b>\n\n"
            f"Etapa: <code>{html.escape(str(fase))}</code>\n"
            f"Sem progresso há: <b>{sem_progresso // 60} minuto(s)</b>\n"
            f"Fila aguardando: <b>{DOWNLOAD_QUEUE.qsize()}/{DOWNLOAD_QUEUE_MAX}</b>\n\n"
            f"Se continuar travado por mais {max(1, WORKER_RESTART_GRACE_SECONDS // 60)} "
            "minuto(s), o processo será encerrado para a Railway reiniciá-lo. "
            "Nenhum segundo worker será criado.",
            parse_mode="HTML",
        )

    if deve_tentar_reinicio:
        tentar_reinicio_automatico_worker(fase, sem_progresso)

    return deve_alertar or deve_tentar_reinicio


def extrair_dados_midia_telegram(mensagem):
    video = getattr(mensagem, "video", None)
    documento = getattr(mensagem, "document", None)
    video_file_id = getattr(video, "file_id", None)
    if video_file_id:
        return video_file_id, "video"
    documento_file_id = getattr(documento, "file_id", None)
    if documento_file_id:
        return documento_file_id, "document"
    return None, None


def _codigos_erro_telegram(erro):
    """Extrai códigos HTTP/Bot API sem depender de uma classe de exceção."""
    codigos = []
    objetos = (
        erro,
        getattr(erro, "result", None),
        getattr(erro, "response", None),
        getattr(erro, "result_json", None),
    )
    for objeto in objetos:
        if objeto is None:
            continue
        for atributo in ("error_code", "status_code", "status"):
            valor = (
                objeto.get(atributo)
                if isinstance(objeto, dict)
                else getattr(objeto, atributo, None)
            )
            try:
                if valor is not None:
                    codigos.append(int(valor))
            except (TypeError, ValueError):
                pass
    return codigos


def extrair_retry_after_telegram(erro):
    """Lê retry_after das formas usadas pelo Telegram e pelo TeleBot."""
    objetos = (
        erro,
        getattr(erro, "result", None),
        getattr(erro, "response", None),
        getattr(erro, "result_json", None),
    )
    for objeto in objetos:
        if objeto is None:
            continue

        if isinstance(objeto, dict):
            valor = objeto.get("retry_after")
            parametros = objeto.get("parameters")
        else:
            valor = getattr(objeto, "retry_after", None)
            parametros = getattr(objeto, "parameters", None)

        if valor is None and parametros is not None:
            valor = (
                parametros.get("retry_after")
                if isinstance(parametros, dict)
                else getattr(parametros, "retry_after", None)
            )

        try:
            if valor is not None:
                return max(0, int(valor))
        except (TypeError, ValueError):
            pass
    return None


def classificar_erro_envio_arquivo(erro):
    """Decide se um novo upload ou uma conversão realmente podem ajudar."""
    texto = str(erro or "").lower()
    codigos = _codigos_erro_telegram(erro)

    if 429 in codigos or "too many requests" in texto or "retry after" in texto:
        return "temporario_rate_limit"

    marcadores_temporarios = (
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "connection refused",
        "connection error",
        "remote disconnected",
        "network is unreachable",
        "temporary failure",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "internal server error",
        "server disconnected",
        "read operation timed out",
    )
    if any(codigo >= 500 for codigo in codigos) or any(
        marcador in texto for marcador in marcadores_temporarios
    ):
        return "temporario"

    marcadores_destino_indisponivel = (
        "bot was blocked by the user",
        "user is deactivated",
        "chat not found",
        "bot can't initiate conversation",
        "bot cannot initiate conversation",
        "not enough rights to send",
        "have no rights to send",
        "chat_write_forbidden",
        "peer_id_invalid",
        "forbidden: bot",
    )
    if 403 in codigos or any(
        marcador in texto for marcador in marcadores_destino_indisponivel
    ):
        return "destino_indisponivel"

    marcadores_tamanho = (
        "file is too big",
        "file too large",
        "request entity too large",
        "payload too large",
        "file_too_big",
    )
    if 413 in codigos or any(
        marcador in texto for marcador in marcadores_tamanho
    ):
        return "arquivo_muito_grande"

    marcadores_formato = (
        "video_content_type_invalid",
        "video content type invalid",
        "wrong file type",
        "can't use file of type",
        "cannot use file of type",
        "failed to process video",
        "video_process_failed",
        "video file is invalid",
        "video is invalid",
        "invalid video",
        "unsupported video",
        "unsupported codec",
        "video codec",
        "media_invalid",
    )
    if any(marcador in texto for marcador in marcadores_formato):
        return "formato_incompativel"

    return "inconclusivo"


def _enviar_video_local_telegram(chat_id, arquivo):
    with open(arquivo, "rb") as f:
        return bot.send_video(
            chat_id,
            f,
            caption="👉 Download concluído! Aqui está seu vídeo 👊",
        )


def obter_tamanho_arquivo_para_metrica(arquivo):
    """Obtém o tamanho sem transformar uma falha de métrica em falha do download."""
    try:
        return max(0, int(os.path.getsize(arquivo)))
    except (OSError, TypeError, ValueError) as e:
        logger.warning(
            f"[METRICAS_UPLOAD_TAMANHO] "
            f"arquivo_ref={referencia_arquivo_log(arquivo)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return 0


def enviar_arquivo_com_fallback(chat_id, arquivo):
    atualizar_heartbeat_worker("enviando_telegram")
    erro_video = None
    classificacao_video = None
    try:
        mensagem = _enviar_video_local_telegram(chat_id, arquivo)
        telegram_file_id, telegram_media_type = extrair_dados_midia_telegram(mensagem)
        registrar_sucesso_componente("Telegram")
        return (
            True,
            telegram_file_id,
            telegram_media_type,
            obter_tamanho_arquivo_para_metrica(arquivo),
        )
    except Exception as e_video:
        if isinstance(e_video, OSError):
            raise FalhaComponenteDownload("Armazenamento", e_video) from e_video
        erro_video = e_video
        classificacao_video = classificar_erro_envio_arquivo(e_video)
        retry_after = extrair_retry_after_telegram(e_video)
        logger.warning(
            f"[SEND_VIDEO] arquivo_ref={referencia_arquivo_log(arquivo)} "
            f"classificacao={classificacao_video} retry_after={retry_after} "
            f"erro={sanitizar_erro_log(e_video)}"
        )

    if (
        classificacao_video == "temporario_rate_limit"
        and retry_after is not None
        and retry_after <= 5
    ):
        espera = max(1, retry_after)
        logger.info(
            f"[SEND_VIDEO_RETRY] motivo=rate_limit espera={espera}s "
            f"arquivo_ref={referencia_arquivo_log(arquivo)}"
        )
        time.sleep(espera)
        atualizar_heartbeat_worker("reenviando_telegram")
        try:
            mensagem = _enviar_video_local_telegram(chat_id, arquivo)
            telegram_file_id, telegram_media_type = extrair_dados_midia_telegram(
                mensagem
            )
            registrar_sucesso_componente("Telegram")
            return (
                True,
                telegram_file_id,
                telegram_media_type,
                obter_tamanho_arquivo_para_metrica(arquivo),
            )
        except Exception as e_retry:
            if isinstance(e_retry, OSError):
                raise FalhaComponenteDownload(
                    "Armazenamento", e_retry
                ) from e_retry
            erro_video = e_retry
            classificacao_video = classificar_erro_envio_arquivo(e_retry)
            logger.warning(
                f"[SEND_VIDEO_RETRY_FALHA] "
                f"arquivo_ref={referencia_arquivo_log(arquivo)} "
                f"classificacao={classificacao_video} "
                f"erro={sanitizar_erro_log(e_retry)}"
            )

    if classificacao_video != "formato_incompativel":
        logger.info(
            f"[SEND_VIDEO_FALLBACK_BLOQUEADO] "
            f"arquivo_ref={referencia_arquivo_log(arquivo)} "
            f"classificacao={classificacao_video} conversao=False "
            "envio_documento=False"
        )
        raise FalhaComponenteDownload("Telegram", erro_video) from erro_video

    # FFprobe, conversão e novo upload só são executados quando o Telegram
    # confirmou que o problema pertence ao formato do vídeo.
    info = obter_info_midia(arquivo)
    arquivo_fallback = None
    alvo_documento = arquivo

    if arquivo_tem_codec_hevc(arquivo, info):
        try:
            logger.info(
                "[SEND_VIDEO] Tentando fallback automático HEVC -> H.264 | "
                f"arquivo_ref={referencia_arquivo_log(arquivo)} "
                f"width={(info or {}).get('width')} height={(info or {}).get('height')} "
                f"fps={(info or {}).get('fps')} vcodec={(info or {}).get('vcodec')}"
            )
            candidato_fallback = converter_para_h264_compativel(arquivo, info)
            validar_arquivo_midia(
                candidato_fallback,
                MAX_OUTPUT_FILE_BYTES,
                fase="fallback_h264",
            )
            arquivo_fallback = candidato_fallback

            mensagem = _enviar_video_local_telegram(chat_id, arquivo_fallback)

            logger.info(
                "[SEND_VIDEO] Fallback H.264 enviado com sucesso | "
                f"arquivo_ref={referencia_arquivo_log(arquivo_fallback)}"
            )
            telegram_file_id, telegram_media_type = extrair_dados_midia_telegram(mensagem)
            registrar_sucesso_componente("Telegram")
            registrar_sucesso_componente("Processamento")
            return (
                True,
                telegram_file_id,
                telegram_media_type,
                obter_tamanho_arquivo_para_metrica(arquivo_fallback),
            )
        except Exception as e_h264:
            if isinstance(e_h264, OSError):
                raise FalhaComponenteDownload(
                    "Armazenamento", e_h264
                ) from e_h264
            classificacao_h264 = classificar_erro_envio_arquivo(e_h264)
            logger.warning(
                "[SEND_VIDEO] Fallback H.264 também falhou. "
                f"classificacao={classificacao_h264} "
                f"erro={sanitizar_erro_log(e_h264)}"
            )
            if arquivo_fallback is not None:
                if classificacao_h264 != "formato_incompativel":
                    raise FalhaComponenteDownload(
                        "Telegram", e_h264
                    ) from e_h264
                alvo_documento = arquivo_fallback

    try:
        with open(alvo_documento, "rb") as f:
            mensagem = bot.send_document(
                chat_id,
                f,
                caption="👉 Download concluído! Aqui está seu arquivo 👊",
            )
        telegram_file_id, telegram_media_type = extrair_dados_midia_telegram(mensagem)
        registrar_sucesso_componente("Telegram")
        return (
            True,
            telegram_file_id,
            telegram_media_type,
            obter_tamanho_arquivo_para_metrica(alvo_documento),
        )
    except Exception as e_doc:
        logger.error(
            f"[SEND_DOCUMENT] Também falhou. erro={sanitizar_erro_log(e_doc)}"
        )
        if isinstance(e_doc, OSError):
            raise FalhaComponenteDownload("Armazenamento", e_doc) from e_doc
        raise FalhaComponenteDownload("Telegram", e_doc) from e_doc


def perfil_cache_plataforma(plataforma):
    perfil = MEDIA_PROFILE_VERSION
    if str(plataforma or "").strip().lower() == "instagram":
        perfil = f"{perfil}|{INSTAGRAM_AUDIO_CACHE_VERSION}"
    return perfil


def montar_chave_cache_midia(plataforma, info, url):
    source_id = str(
        (info or {}).get("id")
        or (info or {}).get("display_id")
        or (info or {}).get("webpage_url")
        or url
    ).strip()
    perfil_cache = perfil_cache_plataforma(plataforma)
    material = f"{perfil_cache}|source|{plataforma.lower()}|{source_id}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest(), source_id


def normalizar_url_cache(url):
    """Normaliza somente o necessário para reconhecer o mesmo link novamente."""
    url = str(url or "").strip()
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
        parametros_rastreamento = {
            "igsh",
            "share_app_id",
            "share_iid",
            "share_link_id",
            "share_id",
            "sender_device",
            "sender_web_id",
            "is_from_webapp",
            "tt_from",
            "timestamp",
            "_r",
        }
        query_limpa = [
            (chave, valor)
            for chave, valor in parse_qsl(parsed.query, keep_blank_values=True)
            if chave.lower() not in parametros_rastreamento
            and not chave.lower().startswith("utm_")
        ]
        return parsed._replace(
            scheme=scheme,
            netloc=netloc,
            path=path,
            query=urlencode(query_limpa, doseq=True),
            fragment="",
        ).geturl()
    except Exception:
        return url


def montar_chave_cache_url(plataforma, url):
    url_normalizada = normalizar_url_cache(url)
    perfil_cache = perfil_cache_plataforma(plataforma)
    material = f"{perfil_cache}|url|{plataforma.lower()}|{url_normalizada}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest(), url_normalizada


def obter_entrada_cache(cache_key):
    try:
        doc = midia_cache_col.find_one({"_id": cache_key})
        if not doc:
            registrar_sucesso_componente("MongoDB")
            return None
        expires_at = doc.get("expires_at")
        agora_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if expires_at and expires_at < agora_utc_naive:
            midia_cache_col.delete_one({"_id": cache_key})
            registrar_sucesso_componente("MongoDB")
            return None
        telegram_file_id = doc.get("telegram_file_id")
        if not telegram_file_id:
            registrar_sucesso_componente("MongoDB")
            return None
        telegram_media_type = doc.get("telegram_media_type")
        if telegram_media_type not in ("video", "document"):
            telegram_media_type = None
        registrar_sucesso_componente("MongoDB")
        return {
            "telegram_file_id": telegram_file_id,
            "telegram_media_type": telegram_media_type,
        }
    except Exception as e:
        logger.warning(
            f"[CACHE_MIDIA_LEITURA] key={cache_key[:12]} "
            f"erro={sanitizar_erro_log(e)}"
        )
        registrar_falha_componente("MongoDB", e)
        return None


def salvar_file_id_cache(
    cache_key,
    source_id,
    plataforma,
    telegram_file_id,
    telegram_media_type,
    url_cache_key=None,
    url_normalizada=None,
):
    if not telegram_file_id:
        return
    if telegram_media_type not in ("video", "document"):
        logger.warning(
            f"[CACHE_MIDIA_GRAVACAO] key={cache_key[:12]} "
            "tipo_telegram_invalido=True"
        )
        return
    try:
        agora = datetime.now(timezone.utc).replace(tzinfo=None)
        documentos = [
            (cache_key, "source", source_id),
        ]
        if url_cache_key and url_cache_key != cache_key:
            documentos.append((url_cache_key, "url", url_normalizada or source_id))

        for chave, tipo_cache, identificador in documentos:
            identificador_hash = hashlib.sha256(
                str(identificador or "").encode("utf-8", errors="ignore")
            ).hexdigest()
            midia_cache_col.update_one(
                {"_id": chave},
                {
                    "$set": {
                        "source_hash": hashlib.sha256(
                            str(source_id or "").encode("utf-8", errors="ignore")
                        ).hexdigest(),
                        "cache_kind": tipo_cache,
                        "cache_identifier_hash": identificador_hash,
                        "plataforma": plataforma,
                        "telegram_file_id": telegram_file_id,
                        "telegram_media_type": telegram_media_type,
                        "media_profile": MEDIA_PROFILE_VERSION,
                        "updated_at": agora,
                        "expires_at": agora + timedelta(days=MEDIA_CACHE_DAYS),
                    },
                    "$unset": {
                        "source_id": "",
                        "cache_identifier": "",
                    },
                    "$setOnInsert": {"created_at": agora},
                },
                upsert=True,
            )
        registrar_sucesso_componente("MongoDB")
    except Exception as e:
        logger.warning(
            f"[CACHE_MIDIA_GRAVACAO] key={cache_key[:12]} "
            f"erro={sanitizar_erro_log(e)}"
        )
        registrar_falha_componente("MongoDB", e)


class CacheTelegramTemporariamenteIndisponivel(RuntimeError):
    pass


def classificar_erro_envio_cache(erro):
    """Só classifica como inválido quando a resposta aponta para o arquivo."""
    texto = str(erro or "").lower()
    codigos = []
    for objeto in (
        erro,
        getattr(erro, "result", None),
        getattr(erro, "response", None),
    ):
        if objeto is None:
            continue
        for atributo in ("error_code", "status_code", "status"):
            valor = getattr(objeto, atributo, None)
            try:
                if valor is not None:
                    codigos.append(int(valor))
            except (TypeError, ValueError):
                pass

    if 429 in codigos or any(codigo >= 500 for codigo in codigos):
        return "temporario"

    marcadores_temporarios = (
        "too many requests",
        "retry after",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
        "connection refused",
        "connection error",
        "remote disconnected",
        "network is unreachable",
        "temporary failure",
        "temporarily unavailable",
        "bad gateway",
        "service unavailable",
        "gateway timeout",
        "internal server error",
        "server disconnected",
        "read operation timed out",
    )
    if any(marcador in texto for marcador in marcadores_temporarios):
        return "temporario"

    marcadores_file_id_invalido = (
        "wrong file identifier",
        "file identifier/http url specified",
        "file_id is not valid",
        "file id is not valid",
        "invalid file_id",
        "invalid file id",
        "file reference expired",
        "file_reference_expired",
        "file not found",
        "can't use file of type",
        "cannot use file of type",
        "wrong file type",
        "file type mismatch",
        "video_content_type_invalid",
        "document_invalid",
    )
    if any(marcador in texto for marcador in marcadores_file_id_invalido):
        return "file_id_invalido"

    # Chat inexistente, bloqueio do usuário ou uma mensagem desconhecida não
    # provam que o arquivo deixou de existir. O cache permanece preservado.
    return "inconclusivo"


def _enviar_file_id_telegram(chat_id, telegram_file_id, telegram_media_type):
    if telegram_media_type == "document":
        return bot.send_document(
            chat_id,
            telegram_file_id,
            caption="👉 Download concluído! Aqui está seu arquivo 👊",
        )
    return bot.send_video(
        chat_id,
        telegram_file_id,
        caption="👉 Download concluído! Aqui está seu vídeo 👊",
    )


def enviar_midia_cacheada(chat_id, cache_key, entrada_cache):
    """Retorna o tipo usado, None se inválido, ou interrompe em falha temporária."""
    atualizar_heartbeat_worker("enviando_cache")
    telegram_file_id = entrada_cache.get("telegram_file_id")
    tipo_armazenado = entrada_cache.get("telegram_media_type")
    tipos_tentativa = (
        [tipo_armazenado, "document" if tipo_armazenado == "video" else "video"]
        if tipo_armazenado in ("video", "document")
        else ["video", "document"]
    )
    erros_permanentes = 0

    for telegram_media_type in tipos_tentativa:
        for tentativa in range(1, 3):
            try:
                _enviar_file_id_telegram(
                    chat_id,
                    telegram_file_id,
                    telegram_media_type,
                )
                logger.info(
                    f"[CACHE_MIDIA_HIT] key={cache_key[:12]} "
                    f"tipo={telegram_media_type} envio_sem_upload=True"
                )
                if tipo_armazenado != telegram_media_type:
                    try:
                        midia_cache_col.update_one(
                            {
                                "_id": cache_key,
                                "telegram_file_id": telegram_file_id,
                            },
                            {
                                "$set": {
                                    "telegram_media_type": telegram_media_type,
                                    "updated_at": datetime.now(timezone.utc).replace(
                                        tzinfo=None
                                    ),
                                }
                            },
                        )
                        registrar_sucesso_componente("MongoDB")
                    except Exception as e:
                        logger.warning(
                            f"[CACHE_MIDIA_MIGRACAO] key={cache_key[:12]} "
                            f"erro={sanitizar_erro_log(e)}"
                        )
                        registrar_falha_componente("MongoDB", e)
                registrar_sucesso_componente("Telegram")
                return telegram_media_type
            except Exception as e:
                classificacao = classificar_erro_envio_cache(e)
                logger.warning(
                    f"[CACHE_MIDIA_ENVIO_FALHA] key={cache_key[:12]} "
                    f"tipo={telegram_media_type} tentativa={tentativa}/2 "
                    f"classificacao={classificacao} "
                    f"erro={sanitizar_erro_log(e)}"
                )
                if classificacao == "temporario" and tentativa == 1:
                    time.sleep(1)
                    continue
                if classificacao == "file_id_invalido":
                    erros_permanentes += 1
                    break
                if classificacao == "temporario":
                    registrar_falha_componente("Telegram", e)
                raise CacheTelegramTemporariamenteIndisponivel(
                    "CACHE_TELEGRAM_TEMPORARIAMENTE_INDISPONIVEL"
                ) from e

    if erros_permanentes == len(tipos_tentativa):
        try:
            midia_cache_col.delete_one({
                "_id": cache_key,
                "telegram_file_id": telegram_file_id,
            })
            registrar_sucesso_componente("MongoDB")
        except Exception as e:
            logger.warning(
                f"[CACHE_MIDIA_REMOCAO] key={cache_key[:12]} "
                f"erro={sanitizar_erro_log(e)}"
            )
            registrar_falha_componente("MongoDB", e)
        logger.warning(
            f"[CACHE_MIDIA_INVALIDO] key={cache_key[:12]} "
            "confirmado_em_video_e_documento=True"
        )
    return None


def detectar_plataforma(url):
    return detectar_plataforma_url(url)


def nome_plataforma(is_pinterest, is_tiktok, is_instagram, is_rednote):
    if is_pinterest:
        return "Pinterest"
    if is_tiktok:
        return "TikTok"
    if is_instagram:
        return "Instagram"
    if is_rednote:
        return "RedNote"
    return "Desconhecida"


def autorizar_tentativa_download(user_id):
    """Aplica atalhos locais; os contadores persistentes são a autoridade."""
    try:
        if int(user_id) == ADMIN_ID:
            return True, None
    except (TypeError, ValueError):
        pass

    agora = time.monotonic()
    inicio_hora = agora - GLOBAL_RATE_LIMIT_WINDOW_SECONDS
    chave = str(user_id)

    with DOWNLOAD_RATE_LOCK:
        while DOWNLOAD_GLOBAL_EVENTS and DOWNLOAD_GLOBAL_EVENTS[0] < inicio_hora:
            DOWNLOAD_GLOBAL_EVENTS.popleft()

        eventos_usuario = DOWNLOAD_RATE_EVENTS.get(chave)
        if eventos_usuario:
            while eventos_usuario and eventos_usuario[0] < inicio_hora:
                eventos_usuario.popleft()

        if DOWNLOAD_COOLDOWN_SECONDS and eventos_usuario:
            decorrido = agora - eventos_usuario[-1]
            if decorrido < DOWNLOAD_COOLDOWN_SECONDS:
                restante = max(1, int(DOWNLOAD_COOLDOWN_SECONDS - decorrido) + 1)
                return False, (
                    f"⏳ Aguarde {restante} segundos antes de enviar outro link."
                )

        if eventos_usuario and len(eventos_usuario) >= MAX_DOWNLOADS_PER_USER_HOUR:
            return False, (
                "⚠️ Muitas solicitações em pouco tempo. "
                "Aguarde alguns minutos e tente novamente."
            )

        if len(DOWNLOAD_GLOBAL_EVENTS) >= MAX_DOWNLOADS_GLOBAL_HOUR:
            return False, (
                "⚠️ O bot está com alta demanda agora. "
                "Aguarde alguns minutos e tente novamente."
            )

    return True, None


def registrar_evento_usuario_local(user_id):
    """Atualiza o atalho local somente após autorização persistente."""
    agora = time.monotonic()
    inicio_hora = agora - GLOBAL_RATE_LIMIT_WINDOW_SECONDS
    chave = str(user_id)
    with DOWNLOAD_RATE_LOCK:
        eventos_usuario = DOWNLOAD_RATE_EVENTS[chave]
        while eventos_usuario and eventos_usuario[0] < inicio_hora:
            eventos_usuario.popleft()
        eventos_usuario.append(agora)

        # Remove usuários inativos para o dicionário não crescer indefinidamente.
        if len(DOWNLOAD_RATE_EVENTS) > 5000:
            for usuario_antigo in list(DOWNLOAD_RATE_EVENTS.keys())[:1000]:
                fila = DOWNLOAD_RATE_EVENTS[usuario_antigo]
                while fila and fila[0] < inicio_hora:
                    fila.popleft()
                if not fila:
                    DOWNLOAD_RATE_EVENTS.pop(usuario_antigo, None)


def referencia_limite_usuario(user_id):
    """Identificador HMAC estável; o ID real nunca entra no documento."""
    return referencia_privada_log("rate", user_id, tamanho=32)


def _eventos_usuario_recentes(inicio_janela):
    return {
        "$filter": {
            "input": {"$ifNull": ["$events", []]},
            "as": "event",
            "cond": {"$gte": ["$$event.at", inicio_janela]},
        }
    }


def _registrar_evento_usuario_mongodb(
    usuario_ref,
    token,
    agora_utc,
):
    inicio_janela = agora_utc - timedelta(
        seconds=GLOBAL_RATE_LIMIT_WINDOW_SECONDS
    )
    limite_cooldown = agora_utc - timedelta(
        seconds=DOWNLOAD_COOLDOWN_SECONDS
    )
    eventos_recentes = _eventos_usuario_recentes(inicio_janela)
    expira_em = agora_utc + timedelta(
        hours=USER_RATE_LIMIT_DOCUMENT_TTL_HOURS
    )
    return limites_usuarios_col.find_one_and_update(
        {
            "_id": usuario_ref,
            "$expr": {
                "$and": [
                    {
                        "$lt": [
                            {"$size": eventos_recentes},
                            MAX_DOWNLOADS_PER_USER_HOUR,
                        ]
                    },
                    {
                        "$lte": [
                            {
                                "$ifNull": [
                                    "$last_event_at",
                                    datetime(1970, 1, 1),
                                ]
                            },
                            limite_cooldown,
                        ]
                    },
                ]
            },
        },
        [
            {
                "$set": {
                    "events": {
                        "$concatArrays": [
                            eventos_recentes,
                            [{"token": token, "at": agora_utc}],
                        ]
                    },
                    "last_event_at": agora_utc,
                    "updated_at": agora_utc,
                    "expires_at": expira_em,
                    "window_seconds": GLOBAL_RATE_LIMIT_WINDOW_SECONDS,
                    "cooldown_seconds": DOWNLOAD_COOLDOWN_SECONDS,
                    "identifier_anonymized": True,
                    "contains_plain_user_id": False,
                    "contains_urls": False,
                    "contains_message_text": False,
                }
            }
        ],
        # O MongoDB não permite $expr no predicado de uma operação com
        # upsert. Documentos novos são criados separadamente abaixo.
        upsert=False,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 1},
    )


def _criar_limite_usuario_mongodb(usuario_ref, token, agora_utc):
    """Cria o primeiro evento sem $expr; _id resolve corridas entre réplicas."""
    expira_em = agora_utc + timedelta(
        hours=USER_RATE_LIMIT_DOCUMENT_TTL_HOURS
    )
    resultado = limites_usuarios_col.insert_one(
        {
            "_id": usuario_ref,
            "events": [{"token": token, "at": agora_utc}],
            "last_event_at": agora_utc,
            "updated_at": agora_utc,
            "expires_at": expira_em,
            "window_seconds": GLOBAL_RATE_LIMIT_WINDOW_SECONDS,
            "cooldown_seconds": DOWNLOAD_COOLDOWN_SECONDS,
            "identifier_anonymized": True,
            "contains_plain_user_id": False,
            "contains_urls": False,
            "contains_message_text": False,
        }
    )
    return {"_id": resultado.inserted_id}


def _consultar_token_limite_usuario(usuario_ref, token):
    return limites_usuarios_col.find_one(
        {
            "_id": usuario_ref,
            "events.token": token,
        },
        {"_id": 1},
    )


def _mensagem_bloqueio_usuario_persistente(documento, agora_utc):
    ultimo_evento = documento.get("last_event_at") if documento else None
    if isinstance(ultimo_evento, datetime):
        if ultimo_evento.tzinfo is not None:
            ultimo_evento = ultimo_evento.astimezone(timezone.utc).replace(
                tzinfo=None
            )
        decorrido = max(0.0, (agora_utc - ultimo_evento).total_seconds())
        if DOWNLOAD_COOLDOWN_SECONDS and decorrido < DOWNLOAD_COOLDOWN_SECONDS:
            restante = max(
                1,
                int(DOWNLOAD_COOLDOWN_SECONDS - decorrido) + 1,
            )
            return (
                "cooldown",
                f"⏳ Aguarde {restante} segundos antes de enviar outro link.",
            )

    inicio_janela = agora_utc - timedelta(
        seconds=GLOBAL_RATE_LIMIT_WINDOW_SECONDS
    )
    eventos_recentes = [
        evento
        for evento in (documento or {}).get("events", [])
        if isinstance(evento, dict)
        and isinstance(evento.get("at"), datetime)
        and (
            evento["at"].astimezone(timezone.utc).replace(tzinfo=None)
            if evento["at"].tzinfo is not None
            else evento["at"]
        ) >= inicio_janela
    ]
    if len(eventos_recentes) >= MAX_DOWNLOADS_PER_USER_HOUR:
        return (
            "hora",
            "⚠️ Muitas solicitações em pouco tempo. "
            "Aguarde alguns minutos e tente novamente.",
        )

    return (
        "indisponivel",
        "⏳ O controle de solicitações está temporariamente indisponível. "
        "Aguarde alguns instantes e tente novamente.",
    )


def autorizar_limite_usuario_persistente(user_id):
    """Compartilha cooldown e limite individual entre deploys e réplicas."""
    try:
        if int(user_id) == ADMIN_ID:
            return True, None
    except (TypeError, ValueError):
        pass

    usuario_ref = referencia_limite_usuario(user_id)
    token = uuid.uuid4().hex
    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        documento = _registrar_evento_usuario_mongodb(
            usuario_ref,
            token,
            agora_utc,
        )
    except Exception as e:
        try:
            gravado = _consultar_token_limite_usuario(usuario_ref, token)
        except Exception as verificacao_erro:
            registrar_falha_componente("MongoDB", verificacao_erro)
            logger.warning(
                "[LIMITE_USUARIO_PERSISTENTE] verificacao_falhou=True "
                f"user_ref={referencia_usuario_log(user_id)} "
                f"erro={sanitizar_erro_log(verificacao_erro)}"
            )
            return False, (
                "⏳ O controle de solicitações está temporariamente "
                "indisponível. Aguarde alguns instantes e tente novamente."
            )
        if not gravado:
            registrar_falha_componente("MongoDB", e)
            logger.warning(
                "[LIMITE_USUARIO_PERSISTENTE] gravacao_falhou=True "
                f"user_ref={referencia_usuario_log(user_id)} "
                f"erro={sanitizar_erro_log(e)}"
            )
            return False, (
                "⏳ O controle de solicitações está temporariamente "
                "indisponível. Aguarde alguns instantes e tente novamente."
            )
        documento = gravado

    if not documento:
        try:
            # Se ainda não existe contador, esta inserção registra o primeiro
            # evento em uma única escrita e sem predicado $expr.
            documento = _criar_limite_usuario_mongodb(
                usuario_ref,
                token,
                agora_utc,
            )
        except Exception as criacao_erro:
            if getattr(criacao_erro, "code", None) == 11000:
                try:
                    # Outra instância criou o mesmo _id entre a atualização e
                    # a inserção. Repete a decisão atômica no documento vencedor.
                    documento = _registrar_evento_usuario_mongodb(
                        usuario_ref,
                        token,
                        agora_utc,
                    )
                except Exception as retry_error:
                    try:
                        gravado = _consultar_token_limite_usuario(
                            usuario_ref,
                            token,
                        )
                    except Exception as verificacao_erro:
                        registrar_falha_componente("MongoDB", verificacao_erro)
                        logger.warning(
                            "[LIMITE_USUARIO_PERSISTENTE] "
                            "verificacao_retry_falhou=True "
                            f"user_ref={referencia_usuario_log(user_id)} "
                            f"erro={sanitizar_erro_log(verificacao_erro)}"
                        )
                        return False, (
                            "⏳ O controle de solicitações está temporariamente "
                            "indisponível. Aguarde alguns instantes e tente "
                            "novamente."
                        )
                    if not gravado:
                        registrar_falha_componente("MongoDB", retry_error)
                        logger.warning(
                            "[LIMITE_USUARIO_PERSISTENTE] retry_falhou=True "
                            f"user_ref={referencia_usuario_log(user_id)} "
                            f"erro={sanitizar_erro_log(retry_error)}"
                        )
                        return False, (
                            "⏳ O controle de solicitações está temporariamente "
                            "indisponível. Aguarde alguns instantes e tente "
                            "novamente."
                        )
                    documento = gravado
            else:
                try:
                    gravado = _consultar_token_limite_usuario(
                        usuario_ref,
                        token,
                    )
                except Exception as verificacao_erro:
                    registrar_falha_componente("MongoDB", verificacao_erro)
                    logger.warning(
                        "[LIMITE_USUARIO_PERSISTENTE] "
                        "verificacao_criacao_falhou=True "
                        f"user_ref={referencia_usuario_log(user_id)} "
                        f"erro={sanitizar_erro_log(verificacao_erro)}"
                    )
                    return False, (
                        "⏳ O controle de solicitações está temporariamente "
                        "indisponível. Aguarde alguns instantes e tente novamente."
                    )
                if not gravado:
                    registrar_falha_componente("MongoDB", criacao_erro)
                    logger.warning(
                        "[LIMITE_USUARIO_PERSISTENTE] criacao_falhou=True "
                        f"user_ref={referencia_usuario_log(user_id)} "
                        f"erro={sanitizar_erro_log(criacao_erro)}"
                    )
                    return False, (
                        "⏳ O controle de solicitações está temporariamente "
                        "indisponível. Aguarde alguns instantes e tente novamente."
                    )
                documento = gravado

    if not documento:
        try:
            estado = limites_usuarios_col.find_one(
                {"_id": usuario_ref},
                {"events.at": 1, "last_event_at": 1},
            )
        except Exception as consulta_erro:
            registrar_falha_componente("MongoDB", consulta_erro)
            logger.warning(
                "[LIMITE_USUARIO_PERSISTENTE] consulta_bloqueio_falhou=True "
                f"user_ref={referencia_usuario_log(user_id)} "
                f"erro={sanitizar_erro_log(consulta_erro)}"
            )
            return False, (
                "⏳ O controle de solicitações está temporariamente "
                "indisponível. Aguarde alguns instantes e tente novamente."
            )

        motivo, mensagem = _mensagem_bloqueio_usuario_persistente(
            estado,
            agora_utc,
        )
        registrar_sucesso_componente("MongoDB")
        logger.info(
            f"[LIMITE_USUARIO_PERSISTENTE] bloqueado=True motivo={motivo} "
            f"user_ref={referencia_usuario_log(user_id)}"
        )
        return False, mensagem

    registrar_sucesso_componente("MongoDB")
    registrar_evento_usuario_local(user_id)
    return True, None


def registrar_evento_global_local():
    """Mantém um atalho local; o MongoDB continua sendo a autoridade."""
    agora = time.monotonic()
    inicio_hora = agora - GLOBAL_RATE_LIMIT_WINDOW_SECONDS
    with DOWNLOAD_RATE_LOCK:
        while DOWNLOAD_GLOBAL_EVENTS and DOWNLOAD_GLOBAL_EVENTS[0] < inicio_hora:
            DOWNLOAD_GLOBAL_EVENTS.popleft()
        DOWNLOAD_GLOBAL_EVENTS.append(agora)


def _eventos_globais_recentes(inicio_janela):
    return {
        "$filter": {
            "input": {"$ifNull": ["$events", []]},
            "as": "event",
            "cond": {"$gte": ["$$event.at", inicio_janela]},
        }
    }


def _registrar_evento_global_mongodb(token, agora_utc):
    inicio_janela = agora_utc - timedelta(
        seconds=GLOBAL_RATE_LIMIT_WINDOW_SECONDS
    )
    eventos_recentes = _eventos_globais_recentes(inicio_janela)
    expira_em = agora_utc + timedelta(
        hours=GLOBAL_RATE_LIMIT_DOCUMENT_TTL_HOURS
    )
    return limites_globais_col.find_one_and_update(
        {
            "_id": GLOBAL_RATE_LIMIT_DOCUMENT_ID,
            "$expr": {
                "$lt": [
                    {"$size": eventos_recentes},
                    MAX_DOWNLOADS_GLOBAL_HOUR,
                ]
            },
        },
        [
            {
                "$set": {
                    "events": {
                        "$concatArrays": [
                            eventos_recentes,
                            [{"token": token, "at": agora_utc}],
                        ]
                    },
                    "updated_at": agora_utc,
                    "expires_at": expira_em,
                    "window_seconds": GLOBAL_RATE_LIMIT_WINDOW_SECONDS,
                    "contains_user_ids": False,
                    "contains_urls": False,
                    "contains_message_text": False,
                }
            }
        ],
        # O MongoDB não permite $expr no predicado de uma operação com
        # upsert. O primeiro documento global é criado separadamente.
        upsert=False,
        return_document=ReturnDocument.AFTER,
        projection={"_id": 1},
    )


def _criar_limite_global_mongodb(token, agora_utc):
    """Cria o primeiro evento global sem $expr; _id resolve concorrência."""
    expira_em = agora_utc + timedelta(
        hours=GLOBAL_RATE_LIMIT_DOCUMENT_TTL_HOURS
    )
    resultado = limites_globais_col.insert_one(
        {
            "_id": GLOBAL_RATE_LIMIT_DOCUMENT_ID,
            "events": [{"token": token, "at": agora_utc}],
            "updated_at": agora_utc,
            "expires_at": expira_em,
            "window_seconds": GLOBAL_RATE_LIMIT_WINDOW_SECONDS,
            "contains_user_ids": False,
            "contains_urls": False,
            "contains_message_text": False,
        }
    )
    return {"_id": resultado.inserted_id}


def _consultar_token_limite_global(token):
    return limites_globais_col.find_one(
        {
            "_id": GLOBAL_RATE_LIMIT_DOCUMENT_ID,
            "events.token": token,
        },
        {"_id": 1},
    )


def autorizar_limite_global_persistente(user_id):
    """Compartilha a janela real de uma hora entre deploys e réplicas."""
    try:
        if int(user_id) == ADMIN_ID:
            return True, None
    except (TypeError, ValueError):
        pass

    token = uuid.uuid4().hex
    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        documento = _registrar_evento_global_mongodb(
            token,
            agora_utc,
        )
    except Exception as e:
        try:
            gravado = _consultar_token_limite_global(token)
        except Exception as verificacao_erro:
            registrar_falha_componente("MongoDB", verificacao_erro)
            logger.warning(
                "[LIMITE_GLOBAL_PERSISTENTE] verificacao_falhou=True "
                f"erro={sanitizar_erro_log(verificacao_erro)}"
            )
            return False, (
                "⏳ O controle de demanda está temporariamente "
                "indisponível. Aguarde alguns instantes e tente novamente."
            )
        if not gravado:
            registrar_falha_componente("MongoDB", e)
            logger.warning(
                "[LIMITE_GLOBAL_PERSISTENTE] gravacao_falhou=True "
                f"erro={sanitizar_erro_log(e)}"
            )
            return False, (
                "⏳ O controle de demanda está temporariamente "
                "indisponível. Aguarde alguns instantes e tente novamente."
            )
        documento = gravado

    if not documento:
        try:
            documento = _criar_limite_global_mongodb(token, agora_utc)
        except Exception as criacao_erro:
            if getattr(criacao_erro, "code", None) == 11000:
                try:
                    # Outra instância criou o documento entre a atualização e
                    # a inserção. A repetição respeita o limite de 300.
                    documento = _registrar_evento_global_mongodb(
                        token,
                        agora_utc,
                    )
                except Exception as retry_error:
                    try:
                        gravado = _consultar_token_limite_global(token)
                    except Exception as verificacao_erro:
                        registrar_falha_componente("MongoDB", verificacao_erro)
                        logger.warning(
                            "[LIMITE_GLOBAL_PERSISTENTE] "
                            "verificacao_retry_falhou=True "
                            f"erro={sanitizar_erro_log(verificacao_erro)}"
                        )
                        return False, (
                            "⏳ O controle de demanda está temporariamente "
                            "indisponível. Aguarde alguns instantes e tente "
                            "novamente."
                        )
                    if not gravado:
                        registrar_falha_componente("MongoDB", retry_error)
                        logger.warning(
                            "[LIMITE_GLOBAL_PERSISTENTE] retry_falhou=True "
                            f"erro={sanitizar_erro_log(retry_error)}"
                        )
                        return False, (
                            "⏳ O controle de demanda está temporariamente "
                            "indisponível. Aguarde alguns instantes e tente "
                            "novamente."
                        )
                    documento = gravado
            else:
                try:
                    gravado = _consultar_token_limite_global(token)
                except Exception as verificacao_erro:
                    registrar_falha_componente("MongoDB", verificacao_erro)
                    logger.warning(
                        "[LIMITE_GLOBAL_PERSISTENTE] "
                        "verificacao_criacao_falhou=True "
                        f"erro={sanitizar_erro_log(verificacao_erro)}"
                    )
                    return False, (
                        "⏳ O controle de demanda está temporariamente "
                        "indisponível. Aguarde alguns instantes e tente novamente."
                    )
                if not gravado:
                    registrar_falha_componente("MongoDB", criacao_erro)
                    logger.warning(
                        "[LIMITE_GLOBAL_PERSISTENTE] criacao_falhou=True "
                        f"erro={sanitizar_erro_log(criacao_erro)}"
                    )
                    return False, (
                        "⏳ O controle de demanda está temporariamente "
                        "indisponível. Aguarde alguns instantes e tente novamente."
                    )
                documento = gravado

    if not documento:
        registrar_sucesso_componente("MongoDB")
        logger.warning(
            f"[LIMITE_GLOBAL_PERSISTENTE] atingido=True "
            f"limite={MAX_DOWNLOADS_GLOBAL_HOUR} janela=60m"
        )
        return False, (
            "⚠️ O bot está com alta demanda agora. "
            "Aguarde alguns minutos e tente novamente."
        )

    registrar_sucesso_componente("MongoDB")
    registrar_evento_global_local()
    return True, None


def get_instagram_cookiefile():
    texto = (INSTAGRAM_COOKIES_TEXT or "").strip()
    if not texto:
        return None

    garantir_estrutura_privada()

    # Algumas plataformas salvam quebras de linha como os caracteres \n.
    if "\n" not in texto and "\\n" in texto:
        texto = texto.replace("\\r\\n", "\n").replace("\\n", "\n")

    texto = texto.replace("\r\n", "\n").replace("\r", "\n").strip()

    # O yt-dlp espera o formato Netscape/Mozilla.
    if not texto.startswith("# Netscape HTTP Cookie File") and not texto.startswith("# HTTP Cookie File"):
        texto = "# Netscape HTTP Cookie File\n" + texto

    cookie_path = os.path.join(PRIVATE_COOKIES_DIR, "instagram_cookies.txt")
    escrever_texto_privado(cookie_path, texto + "\n")

    linhas = [linha for linha in texto.splitlines() if linha and not linha.startswith("#")]
    tem_sessionid = any(
        len(partes := linha.split("\t")) >= 7 and partes[5] == "sessionid"
        for linha in linhas
    )
    logger.info(
        f"[INSTAGRAM_COOKIES] arquivo_criado=True linhas={len(linhas)} "
        f"tem_sessionid={tem_sessionid}"
    )
    return cookie_path


def normalizar_tiktok_cookies_text(texto):
    texto = (texto or "").strip().lstrip("\ufeff")
    if not texto:
        return ""

    # A Railway pode preservar as quebras/tabs ou recebê-las escapadas.
    if "\n" not in texto and "\\n" in texto:
        texto = texto.replace("\\r\\n", "\n").replace("\\n", "\n")
    if "\t" not in texto and "\\t" in texto:
        texto = texto.replace("\\t", "\t")

    return texto.replace("\r\n", "\n").replace("\r", "\n").strip()


def linhas_validas_tiktok_cookies(texto):
    """Retorna somente registros compatíveis com o formato Netscape."""
    linhas_validas = []
    for linha_original in (texto or "").splitlines():
        linha = linha_original.strip("\r\n")
        linha_sem_espacos = linha.strip()
        if not linha_sem_espacos:
            continue
        if linha_sem_espacos.startswith("#") and not linha_sem_espacos.startswith("#HttpOnly_"):
            continue
        if len(linha.split("\t")) >= 7:
            linhas_validas.append(linha)
    return linhas_validas


def get_tiktok_cookiefile():
    """Aplica cookies da Railway e preserva a sessão atualizada pelo yt-dlp."""
    global TIKTOK_COOKIES_ENV_APLICADOS

    garantir_estrutura_privada()
    cookie_path = os.path.join(PRIVATE_COOKIES_DIR, "tiktok_cookies.txt")
    texto_env = normalizar_tiktok_cookies_text(TIKTOK_COOKIES_TEXT)
    linhas_env = linhas_validas_tiktok_cookies(texto_env)

    if texto_env and not linhas_env:
        logger.error(
            "[TIKTOK_COOKIES_INVALIDOS] A variável TIKTOK_COOKIES_TEXT não "
            "contém registros no formato Netscape."
        )
        raise RuntimeError(
            "TIKTOK_COOKIES_TEXT_INVALIDO: use um arquivo de cookies no formato Netscape"
        )

    with TIKTOK_COOKIE_LOCK:
        texto_arquivo = ""
        if os.path.exists(cookie_path):
            try:
                texto_arquivo = ler_texto_privado(cookie_path)
            except Exception as e:
                logger.warning(
                    f"[TIKTOK_COOKIES_LEITURA_FALHA] erro={sanitizar_erro_log(e)}"
                )

        linhas_arquivo = linhas_validas_tiktok_cookies(texto_arquivo)

        # Na primeira chamada de cada implantação, a variável da Railway é a
        # fonte principal. Isso substitui inclusive o antigo arquivo que tinha
        # apenas o cabeçalho e fazia os cookies reais serem ignorados.
        if linhas_env and not TIKTOK_COOKIES_ENV_APLICADOS:
            texto_gravar = texto_env
            if not (
                texto_gravar.startswith("# Netscape HTTP Cookie File")
                or texto_gravar.startswith("# HTTP Cookie File")
            ):
                texto_gravar = "# Netscape HTTP Cookie File\n" + texto_gravar

            escrever_texto_privado(
                cookie_path,
                texto_gravar.rstrip("\n") + "\n",
            )

            TIKTOK_COOKIES_ENV_APLICADOS = True
            logger.info(
                f"[TIKTOK_COOKIES] origem=variavel_railway "
                f"cookies_fornecidos=True linhas={len(linhas_env)}"
            )
            return cookie_path

        # Depois da primeira aplicação, mantém eventuais cookies de desafio
        # que o próprio yt-dlp tenha atualizado durante a sessão.
        if linhas_arquivo:
            logger.info(
                f"[TIKTOK_COOKIES] origem=arquivo_persistente "
                f"cookies_fornecidos=True linhas={len(linhas_arquivo)}"
            )
            return cookie_path

        # Se o arquivo sumir durante a execução, recria os cookies fornecidos.
        if linhas_env:
            texto_gravar = texto_env
            if not (
                texto_gravar.startswith("# Netscape HTTP Cookie File")
                or texto_gravar.startswith("# HTTP Cookie File")
            ):
                texto_gravar = "# Netscape HTTP Cookie File\n" + texto_gravar

            escrever_texto_privado(
                cookie_path,
                texto_gravar.rstrip("\n") + "\n",
            )

            TIKTOK_COOKIES_ENV_APLICADOS = True
            logger.info(
                f"[TIKTOK_COOKIES] origem=variavel_railway_recriada "
                f"cookies_fornecidos=True linhas={len(linhas_env)}"
            )
            return cookie_path

        # Sem configuração, mantém um cookiefile válido e vazio para o yt-dlp
        # poder salvar uma sessão caso o desafio do TikTok permita.
        escrever_texto_privado(
            cookie_path,
            "# Netscape HTTP Cookie File\n",
        )

        logger.info(
            "[TIKTOK_COOKIES] origem=nenhuma cookies_fornecidos=False linhas=0"
        )
        return cookie_path


def validar_tiktok_device_id(valor):
    """Aceita apenas o identificador numérico de 19 dígitos usado pelo app."""
    valor = str(valor or "").strip()
    return valor if re.fullmatch(r"\d{19}", valor) else None


def get_tiktok_device_id():
    """Mantém um device_id estável entre reinícios usando o volume da Railway."""
    garantir_estrutura_privada()
    device_path = os.path.join(PRIVATE_COOKIES_DIR, "tiktok_device_id.txt")

    with TIKTOK_DEVICE_LOCK:
        device_id_env = validar_tiktok_device_id(TIKTOK_DEVICE_ID_TEXT)
        if TIKTOK_DEVICE_ID_TEXT.strip() and not device_id_env:
            logger.warning(
                "[TIKTOK_DEVICE_ID_INVALIDO] A variável TIKTOK_DEVICE_ID deve "
                "conter exatamente 19 dígitos; será usado o identificador persistente."
            )

        if device_id_env:
            try:
                escrever_texto_privado(device_path, device_id_env + "\n")
            except Exception as e:
                logger.warning(
                    "[TIKTOK_DEVICE_ID_GRAVACAO_FALHA] origem=variavel "
                    f"erro={sanitizar_erro_log(e)}"
                )
            logger.info("[TIKTOK_DEVICE_ID] origem=variavel_railway valido=True")
            return device_id_env

        if os.path.exists(device_path):
            try:
                device_id_arquivo = validar_tiktok_device_id(
                    ler_texto_privado(device_path)
                )
                if device_id_arquivo:
                    logger.info("[TIKTOK_DEVICE_ID] origem=arquivo_persistente valido=True")
                    return device_id_arquivo
            except Exception as e:
                logger.warning(
                    f"[TIKTOK_DEVICE_ID_LEITURA_FALHA] erro={sanitizar_erro_log(e)}"
                )

        # O intervalo é o mesmo usado pelo próprio extrator do yt-dlp. Gravar
        # no volume evita apresentar um aparelho diferente a cada tentativa.
        inicio = 7250000000000000000
        fim = 7325099899999994577
        device_id_novo = str(inicio + (uuid.uuid4().int % (fim - inicio + 1)))
        try:
            escrever_texto_privado(device_path, device_id_novo + "\n")
            logger.info("[TIKTOK_DEVICE_ID] origem=gerado_persistente valido=True")
        except Exception as e:
            logger.warning(
                "[TIKTOK_DEVICE_ID_GRAVACAO_FALHA] origem=gerado "
                f"erro={sanitizar_erro_log(e)}"
            )
        return device_id_novo


def montar_tiktok_extractor_args(api_hostname):
    """Ativa a API móvel sem fixar versões internas que mudam no TikTok.

    O yt-dlp mantém os valores compatíveis de app, versão e aid. Fixá-los aqui
    faz o bot quebrar quando o TikTok ou o extrator são atualizados.
    """
    return {
        "tiktok": {
            "device_id": [get_tiktok_device_id()],
            "api_hostname": [api_hostname],
        }
    }


def fazer_requisicao_tiktok(url, **kwargs):
    """Faz uma requisição com a mesma impressão TLS de um navegador real."""
    timeout = kwargs.pop("timeout", 25)
    headers = {
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        **kwargs.pop("headers", {}),
    }

    if curl_requests is not None:
        return curl_requests.get(
            url,
            impersonate="chrome",
            timeout=timeout,
            headers=headers,
            **kwargs,
        )

    return requests.get(
        url,
        timeout=timeout,
        headers={**DEFAULT_HEADERS, **headers},
        **kwargs,
    )


def extrair_tiktok_video_id(url):
    """Obtém o ID numérico tanto de URLs completas quanto de vt/vm.tiktok."""
    padrao = r"(?:/video/|/v/)(\d{15,22})(?:[/?#]|$)"
    match = re.search(padrao, url or "", flags=re.IGNORECASE)
    if match:
        return match.group(1)

    resposta, url_final = seguir_redirecionamentos_seguros(
        url,
        headers={"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
    )
    if not detectar_plataforma_url(url_final)[1]:
        resposta.close()
        raise RuntimeError("TIKTOK_REDIRECIONAMENTO_FORA_DA_PLATAFORMA")

    for candidato in (url_final, resposta.text):
        match = re.search(padrao, candidato or "", flags=re.IGNORECASE)
        if match:
            resposta.close()
            return match.group(1)

    resposta.close()
    raise RuntimeError("TIKTOK_EMBED_ID_NAO_ENCONTRADO")


def normalizar_url_midia_tikwm(url):
    url = str(url or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.tikwm.com{url}"
    return url


def tikwm_circuito_disponivel():
    agora = time.monotonic()
    with TIKWM_CIRCUIT_LOCK:
        return agora >= float(TIKWM_CIRCUIT_STATE.get("open_until", 0.0) or 0.0)


def registrar_resultado_tikwm(sucesso):
    agora = time.monotonic()
    with TIKWM_CIRCUIT_LOCK:
        if sucesso:
            TIKWM_CIRCUIT_STATE["failures"] = 0
            TIKWM_CIRCUIT_STATE["open_until"] = 0.0
            return

        falhas = int(TIKWM_CIRCUIT_STATE.get("failures", 0) or 0) + 1
        TIKWM_CIRCUIT_STATE["failures"] = falhas
        if falhas >= TIKWM_CIRCUIT_FAILURES:
            TIKWM_CIRCUIT_STATE["open_until"] = (
                agora + TIKWM_CIRCUIT_COOLDOWN_SECONDS
            )
            logger.warning(
                f"[TIKWM_CIRCUIT] pausado_por={TIKWM_CIRCUIT_COOLDOWN_SECONDS}s "
                f"falhas={falhas}"
            )


def extrair_info_tiktok_hd_sem_marca(url):
    """Obtém a variante HD sem marca e evita deliberadamente o campo wmplay.

    No Railway, o curl_cffi pode receber uma resposta diferente da biblioteca
    requests por causa do fingerprint/TLS ou do IP do datacenter. Por isso a
    consulta tenta POST e GET comuns antes do cliente com impersonação.
    """
    if not TIKWM_API_URL:
        raise RuntimeError("TIKWM_API_DESATIVADA")
    if not tikwm_circuito_disponivel():
        raise RuntimeError("TIKWM_API_PAUSA_TEMPORARIA")

    payload = {"url": url, "hd": "1"}
    headers = {
        **DEFAULT_HEADERS,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Origin": "https://www.tikwm.com",
        "Referer": "https://www.tikwm.com/",
    }

    # Mantém uma URL configurável, mas sempre tenta também o endereço canônico.
    api_urls = []
    for api_url in (TIKWM_API_URL, "https://www.tikwm.com/api/"):
        api_url = str(api_url or "").strip()
        if (
            api_url
            and api_url not in api_urls
            and validar_url_http_publica(api_url)
        ):
            api_urls.append(api_url)

    if not api_urls:
        registrar_resultado_tikwm(False)
        raise RuntimeError("TIKWM_API_URL_NAO_PUBLICA")

    metodos = ["requests_post", "requests_get"]
    if curl_requests is not None:
        metodos.append("curl_cffi_post")

    ultimo_erro = None
    inicio = time.monotonic()
    prazo = inicio + TIKWM_TOTAL_TIMEOUT_SECONDS
    for api_url in api_urls:
        for metodo in metodos:
            try:
                restante = prazo - time.monotonic()
                if restante <= 0:
                    raise RuntimeError("TIKWM_TEMPO_TOTAL_EXCEDIDO")
                timeout_tentativa = max(
                    3.0,
                    min(float(TIKWM_REQUEST_TIMEOUT_SECONDS), restante),
                )
                logger.info(
                    f"[TIKTOK_SEM_MARCA_TENTATIVA] metodo={metodo} "
                    f"api_ref={referencia_url_log(api_url)}"
                )
                if metodo == "requests_post":
                    resposta = requests.post(
                        api_url,
                        data=payload,
                        timeout=timeout_tentativa,
                        headers=headers,
                    )
                elif metodo == "requests_get":
                    resposta = requests.get(
                        api_url,
                        params=payload,
                        timeout=timeout_tentativa,
                        headers=headers,
                    )
                else:
                    resposta = curl_requests.post(
                        api_url,
                        data=payload,
                        impersonate="chrome",
                        timeout=timeout_tentativa,
                        headers=headers,
                    )

                resposta.raise_for_status()
                resultado = resposta.json()
                dados = resultado.get("data") or {}
                if resultado.get("code") not in (0, None) or not dados:
                    raise RuntimeError(
                        f"TIKWM_API_ERRO: {resultado.get('msg') or 'resposta sem dados'}"
                    )

                # hdplay é HD sem marca; play é o fallback sem marca comum.
                # wmplay nunca é selecionado porque contém marca d'água.
                url_hd = normalizar_url_midia_tikwm(dados.get("hdplay"))
                url_sem_marca = normalizar_url_midia_tikwm(dados.get("play"))
                video_url = url_hd or url_sem_marca
                if not video_url.startswith("http"):
                    raise RuntimeError("TIKWM_URL_SEM_MARCA_NAO_ENCONTRADA")
                if not validar_url_http_publica(video_url):
                    raise RuntimeError("TIKWM_URL_MIDIA_NAO_PUBLICA")

                usou_hd = bool(url_hd)
                video_id = str(dados.get("id") or extrair_tiktok_video_id(url))
                tamanho = dados.get("hd_size") if usou_hd else dados.get("size")
                logger.info(
                    "[TIKTOK_HD_OK] "
                    f"video_ref={referencia_privada_log('video', video_id)} "
                    "sem_marca=True "
                    f"hd={usou_hd} metodo={metodo} duration={dados.get('duration')} "
                    f"tamanho={tamanho}"
                )
                registrar_resultado_tikwm(True)
                return {
                    "id": video_id,
                    "title": dados.get("title") or f"TikTok {video_id}",
                    "duration": dados.get("duration"),
                    "webpage_url": url,
                    "extractor": "TikTokHDSemMarca",
                    "extractor_key": "TikTokHDSemMarca",
                    "formats": [
                        {
                            "format_id": (
                                "tiktok_hd_sem_marca" if usou_hd else "tiktok_sem_marca"
                            ),
                            "format_note": "HD sem marca" if usou_hd else "Sem marca",
                            "url": video_url,
                            "ext": "mp4",
                            "filesize": tamanho,
                            "http_headers": {
                                "Referer": "https://www.tiktok.com/",
                                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                            },
                        }
                    ],
                }
            except Exception as e:
                ultimo_erro = e
                status = getattr(getattr(e, "response", None), "status_code", None)
                logger.warning(
                    f"[TIKTOK_SEM_MARCA_FALHA] metodo={metodo} "
                    f"api_ref={referencia_url_log(api_url)} status={status} "
                    f"erro={sanitizar_erro_log(e)}"
                )
                if time.monotonic() >= prazo:
                    break
        if time.monotonic() >= prazo:
            break

    registrar_resultado_tikwm(False)
    raise RuntimeError(
        f"TIKWM_SEM_MARCA_FALHOU: {sanitizar_erro_log(ultimo_erro)}"
    )


def montar_info_opts(
    is_instagram=False,
    is_pinterest=False,
    usar_cookies=True,
    is_tiktok=False,
    tiktok_extractor_args=None,
):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 3,
        "extractor_retries": 3,
    }

    if is_instagram:
        # O extrator do yt-dlp configura os cabeçalhos e a impersonação.
        # Cabeçalhos manuais podem ficar incompatíveis quando o Instagram muda.
        if usar_cookies:
            cookiefile = get_instagram_cookiefile()
            if cookiefile:
                opts["cookiefile"] = cookiefile
    elif is_pinterest:
        opts["http_headers"] = PINTEREST_HEADERS
    elif is_tiktok:
        # O extrator do TikTok já solicita impersonação via curl-cffi.
        # Uma pequena pausa reduz falhas intermitentes do desafio da página.
        opts["sleep_interval_requests"] = 1
        if usar_cookies:
            opts["cookiefile"] = get_tiktok_cookiefile()
        if tiktok_extractor_args:
            opts["extractor_args"] = tiktok_extractor_args

    return opts


def montar_download_opts(
    prefix,
    is_instagram=False,
    is_pinterest=False,
    usar_cookies=True,
    is_tiktok=False,
    tiktok_extractor_args=None,
):
    inicio_download = time.monotonic()

    def progress_hook_limites(dados):
        atualizar_heartbeat_worker("baixando")
        if time.monotonic() - inicio_download > DOWNLOAD_TIMEOUT_SECONDS:
            raise RuntimeError(
                f"DOWNLOAD_TIMEOUT limite={DOWNLOAD_TIMEOUT_SECONDS}s"
            )
        baixados = int(dados.get("downloaded_bytes") or 0)
        if baixados > MAX_SOURCE_FILE_BYTES:
            raise RuntimeError(
                f"ARQUIVO_MIDIA_MUITO_GRANDE fase=download "
                f"tamanho={baixados} limite={MAX_SOURCE_FILE_BYTES}"
            )

    opts = {
        "outtmpl": f"{prefix}.%(ext)s",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "max_filesize": MAX_SOURCE_FILE_BYTES,
        "progress_hooks": [progress_hook_limites],
        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 20,
        "http_headers": DEFAULT_HEADERS
    }

    if is_instagram:
        opts.pop("http_headers", None)
        # Prefere uma origem já compatível com o Telegram. Se o Instagram
        # não oferecer H.264/AAC, o yt-dlp mantém os formatos de fallback.
        opts["format_sort"] = ["vcodec:h264", "acodec:aac"]
        if usar_cookies:
            cookiefile = get_instagram_cookiefile()
            if cookiefile:
                opts["cookiefile"] = cookiefile
    elif is_pinterest:
        opts["http_headers"] = PINTEREST_HEADERS
    elif is_tiktok:
        # Evita sobrescrever os cabeçalhos definidos pelo próprio extrator.
        opts.pop("http_headers", None)
        opts["extractor_retries"] = 3
        opts["sleep_interval_requests"] = 1
        if usar_cookies:
            opts["cookiefile"] = get_tiktok_cookiefile()
        if tiktok_extractor_args:
            opts["extractor_args"] = tiktok_extractor_args

    return opts


def erro_instagram_permite_fallback(erro):
    texto = str(erro or "").lower()
    sinais = (
        "http error 400",
        "bad request",
        "instagram api is not granting access",
        "video info extraction failed",
        "rate-limit reached",
        "requested content is not available",
    )
    return any(sinal in texto for sinal in sinais)


def info_instagram_indica_audio(info):
    """Retorna True/False quando os metadados permitem confirmar o áudio.

    None significa que o extrator não informou codecs suficientes. Nesse caso,
    o download é tratado de forma conservadora e um arquivo mudo é rejeitado.
    """
    if not isinstance(info, dict):
        return None

    itens = [info]
    for campo in ("requested_formats", "requested_downloads", "formats"):
        valor = info.get(campo)
        if isinstance(valor, list):
            itens.extend(item for item in valor if isinstance(item, dict))
        elif isinstance(valor, dict):
            itens.append(valor)

    codec_observado = False
    for item in itens:
        acodec = item.get("acodec")
        if acodec not in (None, ""):
            codec_observado = True
            if str(acodec).strip().lower() not in ("none", "null", "unknown"):
                return True

        audio_ext = item.get("audio_ext")
        if audio_ext not in (None, ""):
            codec_observado = True
            if str(audio_ext).strip().lower() not in ("none", "null", "unknown"):
                return True

    return False if codec_observado else None


def arquivo_possui_audio(info_midia):
    acodec = str((info_midia or {}).get("acodec") or "").strip().lower()
    return acodec not in ("", "none", "null", "unknown")


class InstagramYoutubeDLSemImpersonacao(yt_dlp.YoutubeDL):
    """Força o extrator do Instagram a consultar a página pública comum."""

    def _impersonate_target_available(self, target):
        return False


def extrair_info_instagram_com_fallback(url):
    """Tenta cookies, acesso anônimo e página pública sem impersonação."""
    tem_cookies = bool(INSTAGRAM_COOKIES_TEXT.strip())
    tentativas = []
    if tem_cookies:
        tentativas.append((True, False, "cookies"))
    tentativas.append((False, False, "anonima"))
    if CURL_CFFI_VERSION is not None:
        tentativas.append((False, True, "publica_sem_impersonacao"))

    ultimo_erro = None
    primeiro_sucesso = None
    for indice, (usar_cookies, sem_impersonacao, modo) in enumerate(tentativas):
        proxima_tentativa = (
            tentativas[indice + 1][2]
            if indice + 1 < len(tentativas)
            else None
        )
        try:
            logger.info(
                f"[INSTAGRAM_INFO] modo={modo} "
                f"usar_cookies={usar_cookies} "
                f"sem_impersonacao={sem_impersonacao} "
                f"url_ref={referencia_url_log(url)}"
            )
            opts = montar_info_opts(is_instagram=True, usar_cookies=usar_cookies)
            ydl_class = (
                InstagramYoutubeDLSemImpersonacao
                if sem_impersonacao
                else yt_dlp.YoutubeDL
            )
            with ydl_class(opts) as ydl:
                info = ydl.extract_info(url, download=False)

            audio_disponivel = info_instagram_indica_audio(info)
            if primeiro_sucesso is None:
                primeiro_sucesso = (info, usar_cookies)

            if audio_disponivel is True:
                return info, usar_cookies

            if proxima_tentativa is not None:
                logger.warning(
                    "[INSTAGRAM_INFO_SEM_AUDIO] "
                    f"modo={modo} audio_disponivel={audio_disponivel} "
                    f"proxima_tentativa={proxima_tentativa}"
                )
                continue

            if primeiro_sucesso is not None:
                return primeiro_sucesso
            return info, usar_cookies
        except FalhaComponenteDownload:
            raise
        except Exception as e:
            ultimo_erro = e
            logger.warning(
                f"[INSTAGRAM_INFO_FALHA] modo={modo} "
                f"usar_cookies={usar_cookies} "
                f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
            )

            if proxima_tentativa is not None:
                if usar_cookies and not erro_instagram_permite_fallback(e):
                    raise
                logger.warning(
                    "[INSTAGRAM_INFO_FALLBACK] "
                    f"modo={modo} falhou=True "
                    f"proxima_tentativa={proxima_tentativa}"
                )
                continue

            if primeiro_sucesso is not None:
                logger.warning(
                    "[INSTAGRAM_INFO_FALLBACK] "
                    f"modo={modo} falhou=True "
                    "preservando_primeira_resposta=True"
                )
                return primeiro_sucesso
            raise

    if primeiro_sucesso is not None:
        return primeiro_sucesso
    raise ultimo_erro or Exception("Falha ao consultar o Instagram")


def erro_tiktok_permite_nova_tentativa(erro):
    texto = str(erro or "").lower()
    sinais = (
        "unexpected response from webpage request",
        "unable to extract challenge data",
        "unable to solve js challenge",
        "unable to extract universal data for rehydration",
        "http error 403",
        "http error 429",
        "too many requests",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "unable to extract aweme detail info",
        "no working app info is available",
        "failed to parse json",
        "no video formats found",
        "login required",
        "requiring login",
    )
    return any(sinal in texto for sinal in sinais)


def extrair_info_tiktok_com_fallback(url):
    """Prioriza HD sem marca e nunca aceita o embed público com marca."""
    try:
        logger.info(
            f"[TIKTOK_INFO] estrategia=hd_sem_marca "
            f"url_ref={referencia_url_log(url)}"
        )
        return extrair_info_tiktok_hd_sem_marca(url), False, None
    except FalhaComponenteDownload:
        raise
    except Exception as e:
        logger.warning(
            f"[TIKTOK_HD_FALHA] url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )

    estrategias = []

    # Cookies vencidos podem falhar enquanto o mesmo vídeo público funciona
    # anonimamente. Só faz a tentativa autenticada quando cookies foram
    # realmente configurados.
    if TIKTOK_COOKIES_TEXT.strip():
        estrategias.append({
            "usar_cookies": True,
            "total_tentativas": 2,
            "nome": "sessao",
            "extractor_args": None,
        })

    estrategias.extend([
        {
            "usar_cookies": False,
            "total_tentativas": 2,
            "nome": "anonima",
            "extractor_args": None,
        },
        {
            "usar_cookies": True,
            "total_tentativas": 1,
            "nome": "mobile_api_padrao",
            "extractor_args": montar_tiktok_extractor_args(
                "api16-normal-c-useast1a.tiktokv.com"
            ),
        },
        {
            "usar_cookies": True,
            "total_tentativas": 1,
            "nome": "mobile_api_global",
            "extractor_args": montar_tiktok_extractor_args(
                "api22-normal-c-alisg.tiktokv.com"
            ),
        },
    ])
    ultimo_erro = None

    for estrategia in estrategias:
        usar_cookies = estrategia["usar_cookies"]
        total_tentativas = estrategia["total_tentativas"]
        nome_estrategia = estrategia["nome"]
        extractor_args = estrategia["extractor_args"]

        for tentativa in range(1, total_tentativas + 1):
            try:
                logger.info(
                    f"[TIKTOK_INFO] estrategia={nome_estrategia} "
                    f"tentativa={tentativa}/{total_tentativas} "
                    f"url_ref={referencia_url_log(url)}"
                )
                opts = montar_info_opts(
                    is_tiktok=True,
                    usar_cookies=usar_cookies,
                    tiktok_extractor_args=extractor_args,
                )
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                return info, usar_cookies, extractor_args
            except FalhaComponenteDownload:
                raise
            except Exception as e:
                ultimo_erro = e
                logger.warning(
                    f"[TIKTOK_INFO_FALHA] estrategia={nome_estrategia} "
                    f"tentativa={tentativa}/{total_tentativas} "
                    f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
                )

                if tentativa < total_tentativas:
                    # Retenta rapidamente bloqueios transitórios. Para erros
                    # definitivos, ainda avança às demais estratégias em vez
                    # de impedir o fallback anônimo/móvel.
                    if erro_tiktok_permite_nova_tentativa(e):
                        time.sleep(tentativa)

    # O embed público foi removido do fluxo de download: ele só disponibiliza
    # a cópia 576x1024 com a marca do TikTok. É melhor informar indisponibilidade
    # do que entregar ao usuário um arquivo diferente do prometido.
    logger.error(
        f"[TIKTOK_SEM_MARCA_INDISPONIVEL] url_ref={referencia_url_log(url)} "
        f"ultimo_erro={sanitizar_erro_log(ultimo_erro)}"
    )
    raise RuntimeError(
        f"TIKTOK_SEM_MARCA_INDISPONIVEL: {ultimo_erro or 'fontes sem marca falharam'}"
    )


def baixar_info_ja_extraida(info, opts):
    """Baixa usando os formatos já consultados, sem abrir a página novamente.

    Reextrair o link em cada formato multiplica as requisições, aumenta custos
    e pode acionar bloqueios das plataformas.
    """
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.process_ie_result(copy.deepcopy(info), download=True)


def mapear_erro_download(err_text, plataforma="geral"):
    err = (err_text or "").lower()

    if "video_muito_longo" in err:
        return f"⚠️ Vídeo muito longo. O limite é de {MAX_DURATION_SECONDS} segundos."
    if "arquivo_midia_muito_grande" in err or "larger than max-filesize" in err:
        return (
            f"⚠️ O arquivo é muito grande para o limite seguro do bot "
            f"({MAX_SOURCE_FILE_MB} MB de origem e {MAX_OUTPUT_FILE_MB} MB de saída)."
        )
    if "duracao_midia_desconhecida" in err:
        return "❌ Não consegui confirmar a duração desse vídeo com segurança."
    if "ffmpeg_timeout" in err:
        return "❌ O processamento do vídeo ultrapassou o tempo de segurança."
    if "download_timeout" in err:
        return "❌ O download ultrapassou o tempo de segurança. Tente outro link."
    if "midia_invalida_ou_nao_analisavel" in err:
        return "❌ O arquivo recebido da plataforma não é um vídeo válido."

    if plataforma == "pinterest":
        texto_erro = "❌ Erro no link ou formato do Pinterest."
        if "unsupported url" in err:
            return "❌ Esse link do Pinterest não é suportado no momento."
        if "timed out" in err:
            return "❌ O Pinterest demorou para responder. Tente novamente."
        if "403" in err or "404" in err or "json metadata" in err:
            return "❌ O Pinterest bloqueou esse link no momento. Tente outro pin ou tente novamente depois."
        if "720x1280" in err or "30fps" in err:
            return "❌ Não encontrei uma versão do pin compatível com o limite máximo de 720x1280 em até 30 fps."
        return texto_erro

    if plataforma == "instagram":
        if "instagram_audio_ausente_no_arquivo" in err:
            return (
                "❌ O Instagram não forneceu uma versão completa com áudio "
                "deste Reel. Tente novamente em alguns instantes."
            )
        if "login required" in err or "requested content is not available" in err or "rate-limit reached" in err:
            return "❌ O Instagram bloqueou esse link no momento. Para Reels assim, o bot precisa de cookies válidos da conta logada no Instagram."
        if "private" in err:
            return "❌ Esse conteúdo do Instagram é privado."
        if "403" in err:
            return "❌ O Instagram bloqueou temporariamente a requisição. Tente novamente em instantes."
        if "timed out" in err:
            return "❌ O Instagram demorou para responder. Tente novamente."
        return "❌ Não consegui baixar esse link do Instagram agora."

    if plataforma == "tiktok":
        if "tiktok_sem_marca_indisponivel" in err or "tikwm_sem_marca_falhou" in err:
            return (
                "❌ Não encontrei uma versão sem marca d'água deste TikTok agora. "
                "Tente novamente em alguns instantes."
            )
        if "tiktok_cookies_text_invalido" in err:
            return "❌ Os cookies do TikTok estão em formato inválido. Use o formato Netscape e tente novamente."
        if "impersonat" in err or "curl_cffi" in err or "curl-cffi" in err:
            return "❌ O servidor está sem o suporte de navegador exigido pelo TikTok. Instale yt-dlp[default,curl-cffi] e faça um novo deploy."
        if (
            "unexpected response from webpage request" in err
            or "unable to extract challenge data" in err
            or "unable to solve js challenge" in err
            or "unable to extract universal data for rehydration" in err
            or "403" in err
            or "429" in err
        ):
            return "❌ O TikTok bloqueou temporariamente esse acesso. Aguarde alguns instantes e tente novamente."
        if "private" in err or "login required" in err:
            return "❌ Esse vídeo do TikTok é privado ou exige login."
        if "timed out" in err or "timeout" in err:
            return "❌ O TikTok demorou para responder. Tente novamente."
        return "❌ Não consegui baixar esse link do TikTok agora."

    texto_erro = "❌ Erro no link ou formato."
    if "unsupported url" in err:
        return "❌ Esse link não é suportado no momento."
    if "timed out" in err:
        return "❌ O servidor demorou para responder. Tente novamente."
    if "video unavailable" in err:
        return "❌ Vídeo indisponível ou privado."
    if "private" in err or "login required" in err:
        return "❌ Esse conteúdo é privado ou exige login."
    if "403" in err:
        return "❌ A plataforma bloqueou esse link no momento. Tente novamente mais tarde."
    if "720x1280" in err or "30fps" in err:
        return "❌ Não encontrei uma versão compatível com o limite máximo de 720x1280 em até 30 fps."
    return texto_erro


def mapear_falha_componente_download(componente, erro, plataforma="geral"):
    componente = normalizar_componente_monitoramento(componente) or "Interno"
    if componente == "Telegram":
        return (
            "⏳ O Telegram não conseguiu receber o arquivo agora. Aguarde alguns "
            "instantes e envie o link novamente. Esta tentativa não consumiu "
            "seu limite diário."
        )
    if componente == "MongoDB":
        return (
            "⏳ O banco de dados está temporariamente indisponível. Aguarde "
            "alguns instantes e tente novamente."
        )
    if componente == "Armazenamento":
        return (
            "❌ O servidor não conseguiu acessar o arquivo temporário do vídeo. "
            "Tente novamente em alguns instantes."
        )
    if componente == "Processamento":
        texto = str(erro or "").lower()
        if "ffprobe" in texto or "midia_invalida" in texto:
            return (
                "❌ O servidor não conseguiu analisar o arquivo de vídeo. "
                "Tente novamente em alguns instantes."
            )
        if "ffmpeg" in texto:
            return (
                "❌ O servidor não conseguiu preparar o vídeo para envio. "
                "Tente novamente em alguns instantes."
            )
    if componente == "Interno":
        return "❌ O bot encontrou um erro interno. Tente novamente em instantes."
    return mapear_erro_download(str(erro), plataforma=plataforma)


def _expressoes_reserva_download(hoje, agora_utc):
    contagem_hoje = {
        "$cond": [
            {"$eq": ["$ultima_data", hoje]},
            {"$ifNull": ["$downloads_hoje", 0]},
            0,
        ]
    }
    reserva_ativa = {
        "$and": [
            {
                "$ne": [
                    {"$ifNull": ["$download_reserva.token", None]},
                    None,
                ]
            },
            {"$eq": ["$download_reserva.data", hoje]},
            {"$gt": ["$download_reserva.expires_at", agora_utc]},
        ]
    }
    return contagem_hoje, reserva_ativa


def reservar_download_gratis(user_id):
    """Reserva e contabiliza uma vaga gratuita em uma única operação atômica."""
    hoje = hoje_str()
    agora_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    token = uuid.uuid4().hex
    expira_em = agora_utc + timedelta(seconds=DOWNLOAD_RESERVATION_TTL_SECONDS)
    contagem_hoje, reserva_ativa = _expressoes_reserva_download(
        hoje,
        agora_utc,
    )

    try:
        usuario = usuarios_col.find_one_and_update(
            {
                "_id": str(user_id),
                "$expr": {
                    "$and": [
                        {"$lt": [contagem_hoje, FREE_DAILY_LIMIT]},
                        {"$not": [reserva_ativa]},
                    ]
                },
            },
            [
                {
                    "$set": {
                        "downloads_hoje": {"$add": [contagem_hoje, 1]},
                        "ultima_data": hoje,
                        "download_reserva": {
                            "token": token,
                            "instance_id": APP_INSTANCE_ID,
                            "data": hoje,
                            "created_at": agora_utc,
                            "expires_at": expira_em,
                        },
                    }
                }
            ],
            return_document=ReturnDocument.AFTER,
        )
        registrar_sucesso_componente("MongoDB")
    except Exception as e:
        registrar_falha_componente("MongoDB", e)
        logger.error(
            f"[LIMITE_RESERVA_FALHA] user_ref={referencia_usuario_log(user_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        try:
            usuario = usuarios_col.find_one(
                {
                    "_id": str(user_id),
                    "download_reserva.token": token,
                },
                {"downloads_hoje": 1},
            )
            if usuario:
                logger.info(
                    "[LIMITE_RESERVA_CONFIRMADA_APOS_FALHA] "
                    f"user_ref={referencia_usuario_log(user_id)}"
                )
                registrar_sucesso_componente("MongoDB")
            else:
                return None, "indisponivel"
        except Exception as verificacao_erro:
            registrar_falha_componente("MongoDB", verificacao_erro)
            return None, "indisponivel"

    if usuario:
        contagem = int(usuario.get("downloads_hoje") or 0)
        return {
            "token": token,
            "instance_id": APP_INSTANCE_ID,
            "data": hoje,
            "count": contagem,
            "delivered": False,
            "finalized": False,
        }, None

    try:
        atual = usuarios_col.find_one(
            {"_id": str(user_id)},
            {
                "downloads_hoje": 1,
                "ultima_data": 1,
                "download_reserva": 1,
            },
        ) or {}
        registrar_sucesso_componente("MongoDB")
    except Exception as e:
        registrar_falha_componente("MongoDB", e)
        return None, "indisponivel"

    reserva_atual = atual.get("download_reserva") or {}
    expira_atual = reserva_atual.get("expires_at")
    reserva_em_andamento = bool(
        reserva_atual.get("token")
        and reserva_atual.get("data") == hoje
        and isinstance(expira_atual, datetime)
        and expira_atual > agora_utc
    )
    if reserva_em_andamento:
        return None, "em_andamento"
    if (
        atual.get("ultima_data") == hoje
        and int(atual.get("downloads_hoje") or 0) >= FREE_DAILY_LIMIT
    ):
        return None, "limite"
    return None, "concorrencia"


def _atualizar_reserva_com_retentativas(filtro, atualizacao, operacao):
    ultimo_erro = None
    for tentativa in range(1, 4):
        try:
            resultado = usuarios_col.update_one(filtro, atualizacao)
            registrar_sucesso_componente("MongoDB")
            return resultado
        except Exception as e:
            ultimo_erro = e
            logger.warning(
                f"[LIMITE_RESERVA_{operacao}] tentativa={tentativa}/3 "
                f"erro={sanitizar_erro_log(e)}"
            )
            if tentativa < 3:
                time.sleep(0.25 * tentativa)

    registrar_falha_componente("MongoDB", ultimo_erro)
    return None


def confirmar_download_gratis(
    reserva,
    user_id,
    chat_id,
    from_user_id,
):
    """Confirma a vaga já contabilizada depois que o Telegram recebeu o vídeo."""
    if not reserva or reserva.get("finalized"):
        return True

    reserva["delivered"] = True
    resultado = _atualizar_reserva_com_retentativas(
        {
            "_id": str(user_id),
            "download_reserva.token": reserva["token"],
        },
        {"$unset": {"download_reserva": ""}},
        "CONFIRMAR",
    )
    if resultado is None:
        logger.error(
            f"[LIMITE_RESERVA_CONFIRMAR] user_ref={referencia_usuario_log(user_id)} "
            "confirmada=False contador_preservado=True"
        )
        return False

    reserva["finalized"] = True
    novo_count = int(reserva.get("count") or 0)
    safe_send_message(chat_id, f"📊 Uso diário: {novo_count}/{FREE_DAILY_LIMIT}")

    if novo_count >= FREE_DAILY_LIMIT:
        safe_send_message(
            chat_id,
            f"⚠️ *Você atingiu seu limite diário ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT})!*\n"
            "Para continuar baixando sem limite diário, libere um plano VIP: 👇",
            parse_mode="Markdown",
        )
        mostrar_planos_chat(chat_id, from_user_id)
    return True


def devolver_reserva_download_gratis(reserva, user_id, motivo="falha"):
    """Devolve uma reserva não entregue; token torna a operação idempotente."""
    if not reserva or reserva.get("finalized") or reserva.get("delivered"):
        return True

    resultado = _atualizar_reserva_com_retentativas(
        {
            "_id": str(user_id),
            "download_reserva.token": reserva["token"],
        },
        [
            {
                "$set": {
                    "downloads_hoje": {
                        "$cond": [
                            {
                                "$gt": [
                                    {"$ifNull": ["$downloads_hoje", 0]},
                                    0,
                                ]
                            },
                            {
                                "$subtract": [
                                    {"$ifNull": ["$downloads_hoje", 0]},
                                    1,
                                ]
                            },
                            0,
                        ]
                    },
                    "download_reserva": "$$REMOVE",
                }
            }
        ],
        "DEVOLVER",
    )
    if resultado is None:
        logger.error(
            f"[LIMITE_RESERVA_DEVOLVER] user_ref={referencia_usuario_log(user_id)} "
            f"motivo={str(motivo)[:80]} devolvida=False"
        )
        return False

    reserva["finalized"] = True
    logger.info(
        f"[LIMITE_RESERVA_DEVOLVER] user_ref={referencia_usuario_log(user_id)} "
        f"motivo={str(motivo)[:80]} devolvida={bool(resultado.modified_count)}"
    )
    return True


def devolver_reserva_por_instancia(user_id, instance_id):
    """Recuperação idempotente de uma reserva pertencente a processo encerrado."""
    resultado = _atualizar_reserva_com_retentativas(
        {
            "_id": str(user_id),
            "download_reserva.instance_id": str(instance_id),
        },
        [
            {
                "$set": {
                    "downloads_hoje": {
                        "$cond": [
                            {
                                "$gt": [
                                    {"$ifNull": ["$downloads_hoje", 0]},
                                    0,
                                ]
                            },
                            {
                                "$subtract": [
                                    {"$ifNull": ["$downloads_hoje", 0]},
                                    1,
                                ]
                            },
                            0,
                        ]
                    },
                    "download_reserva": "$$REMOVE",
                }
            }
        ],
        "RECUPERAR",
    )
    return resultado is not None


def somar_downloads_gratuitos_usuarios_hoje():
    hoje = hoje_str()
    pipeline = [
        {"$match": {"ultima_data": hoje}},
        {
            "$project": {
                "downloads_concluidos": {
                    "$cond": [
                        {
                            "$and": [
                                {
                                    "$ne": [
                                        {
                                            "$ifNull": [
                                                "$download_reserva.token",
                                                None,
                                            ]
                                        },
                                        None,
                                    ]
                                },
                                {"$eq": ["$download_reserva.data", hoje]},
                                {
                                    "$gt": [
                                        {"$ifNull": ["$downloads_hoje", 0]},
                                        0,
                                    ]
                                },
                            ]
                        },
                        {"$subtract": ["$downloads_hoje", 1]},
                        {"$ifNull": ["$downloads_hoje", 0]},
                    ]
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$downloads_concluidos"},
            }
        },
    ]
    resultado = list(usuarios_col.aggregate(pipeline))
    return int(resultado[0]["total"]) if resultado else 0


def inicializar_metricas_diarias():
    """Preserva como base os downloads gratuitos já feitos antes desta versão."""
    try:
        hoje = hoje_str()
        if metricas_col.find_one({"_id": hoje}, {"_id": 1}):
            return

        gratuitos_existentes = somar_downloads_gratuitos_usuarios_hoje()
        agora = agora_tz()

        metricas_col.update_one(
            {"_id": hoje},
            {
                "$setOnInsert": {
                    "data": hoje,
                    "downloads_total": gratuitos_existentes,
                    "downloads_gratuitos": gratuitos_existentes,
                    "downloads_vips": 0,
                    "downloads_admin_teste": 0,
                    "downloads_cache_url": 0,
                    "downloads_cache_midia": 0,
                    "downloads_upload": 0,
                    "bytes_upload_telegram": 0,
                    "created_at": agora,
                    "updated_at": agora,
                }
            },
            upsert=True,
        )

        logger.info(
            f"[METRICAS_INIT] data={hoje} gratuitos_base={gratuitos_existentes}"
        )
    except Exception as e:
        logger.error(f"[METRICAS_INIT] erro={sanitizar_erro_log(e)}")


def registrar_download_diario(
    vip_status,
    tipo_entrega="upload",
    bytes_upload=0,
    admin_status=False,
):
    """Registra o download e sua forma de entrega na mesma escrita diária."""
    try:
        hoje = hoje_str()
        agora = agora_tz()
        campo_tipo = "downloads_vips" if vip_status else "downloads_gratuitos"
        campos_entrega = {
            "cache_url": "downloads_cache_url",
            "cache_midia": "downloads_cache_midia",
            "upload": "downloads_upload",
        }
        tipo_entrega = str(tipo_entrega or "").strip().lower()
        campo_entrega = campos_entrega.get(tipo_entrega)
        if campo_entrega is None:
            logger.warning(
                f"[METRICAS_DOWNLOAD] tipo_entrega_invalido="
                f"{sanitizar_erro_log(tipo_entrega, limite=50)} usando=upload"
            )
            tipo_entrega = "upload"
            campo_entrega = campos_entrega[tipo_entrega]

        try:
            bytes_upload = max(0, int(bytes_upload or 0))
        except (TypeError, ValueError):
            bytes_upload = 0

        incrementos = {campo_entrega: 1}
        if admin_status:
            incrementos["downloads_admin_teste"] = 1
        else:
            incrementos["downloads_total"] = 1
            incrementos[campo_tipo] = 1
        if tipo_entrega == "upload":
            incrementos["bytes_upload_telegram"] = bytes_upload

        metricas_col.update_one(
            {"_id": hoje},
            {
                "$inc": incrementos,
                "$set": {
                    "updated_at": agora,
                },
                "$setOnInsert": {
                    "data": hoje,
                    "created_at": agora,
                },
            },
            upsert=True,
        )
        registrar_sucesso_componente("MongoDB")
    except Exception as e:
        logger.error(
            f"[METRICAS_DOWNLOAD] vip={vip_status} admin={admin_status} "
            f"tipo={tipo_entrega} "
            f"bytes_upload={bytes_upload} "
            f"erro={sanitizar_erro_log(e)}"
        )
        registrar_falha_componente("MongoDB", e)


def formatar_tamanho_bytes(total_bytes):
    try:
        tamanho = max(0, int(total_bytes or 0))
    except (TypeError, ValueError):
        tamanho = 0

    if tamanho >= 1024 ** 3:
        return f"{tamanho / (1024 ** 3):.2f} GB"
    if tamanho >= 1024 ** 2:
        return f"{tamanho / (1024 ** 2):.1f} MB"
    if tamanho >= 1024:
        return f"{tamanho / 1024:.1f} KB"
    return f"{tamanho} B"


def gerar_order_nsu(user_id):
    # O argumento é mantido para compatibilidade com as chamadas atuais, mas
    # novos códigos não carregam mais o ID do Telegram.
    _ = user_id
    return f"pix_{uuid.uuid4().hex}"


def obter_plano_por_callback(valor_str):
    return PLANOS.get(valor_str)


def calcular_nova_data_vip(user, dias):
    if dias is None:
        return "Vitalício"

    vip_atual = user.get("vip_ate")
    hoje = agora_tz().date()

    if vip_atual == "Vitalício":
        return "Vitalício"

    try:
        if vip_atual:
            validade_atual = datetime.strptime(vip_atual, "%Y-%m-%d").date()
            if validade_atual >= hoje:
                # O período comprado começa no dia seguinte à validade atual.
                return (validade_atual + timedelta(days=dias)).strftime("%Y-%m-%d")
    except Exception:
        pass

    # Em um plano novo ou vencido, hoje já conta como o primeiro dia.
    nova_data = hoje + timedelta(days=dias - 1)
    return nova_data.strftime("%Y-%m-%d")


def obter_lock_distribuido_local(chave, locks):
    digest = hashlib.sha256(str(chave).encode("utf-8")).digest()
    indice = int.from_bytes(digest[:4], "big") % len(locks)
    return locks[indice]


def liberar_vip_por_plano(user_id, plano, order_nsu=None):
    # Serializa pagamentos do mesmo usuário. Assim, dois pedidos distintos
    # aprovados ao mesmo tempo acumulam os dias em vez de sobrescrever a data.
    lock_usuario = obter_lock_distribuido_local(user_id, PAYMENT_USER_LOCKS)
    with lock_usuario:
        user = obter_usuario(user_id)

        if plano.get("vitalicio"):
            novo_vip_ate = "Vitalício"
        else:
            novo_vip_ate = calcular_nova_data_vip(user, plano["dias"])

        filtro = {"_id": str(user_id)}
        if order_nsu:
            filtro["vip_orders_aplicados"] = {"$ne": order_nsu}

        atualizacao = {
            "$set": {
                "vip_ate": novo_vip_ate,
                "ultima_data": hoje_str()
            },
            "$setOnInsert": {
                "downloads_hoje": 0
            }
        }
        if order_nsu:
            atualizacao["$addToSet"] = {"vip_orders_aplicados": order_nsu}

        resultado = usuarios_col.update_one(
            filtro,
            atualizacao,
            upsert=not bool(order_nsu),
        )

        aplicado = bool(resultado.modified_count or resultado.upserted_id)
        if order_nsu and not aplicado:
            usuario_atual = usuarios_col.find_one({"_id": str(user_id)}) or {}
            return usuario_atual.get("vip_ate") or novo_vip_ate, False

        return novo_vip_ate, True


def notificar_pagamento_confirmado(user_id, plano_nome, vip_ate):
    try:
        validade = formatar_validade_vip(vip_ate)
        texto = (
            "✅ *Pagamento confirmado*\n\n"
            f"Plano: *{plano_nome}*\n"
            "Status: *Acesso VIP ativo*\n"
            f"Válido até: *{validade}*\n\n"
            "Seu acesso já está liberado. Envie um link para começar. 🚀"
        )

        return bool(
            safe_send_message(int(user_id), texto, parse_mode="Markdown")
        )
    except Exception as e:
        logger.error(
            f"[NOTIFICAR_PAGAMENTO] user_ref={referencia_usuario_log(user_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return False


def finalizar_aprovacao_pix_em_processamento(order_nsu):
    """Conclui uma aprovação já autorizada pelo administrador.

    O pedido precisa estar em ``approving``. A aplicação do VIP é idempotente
    por ``order_nsu``; por isso, repetir esta função após uma reinicialização
    não acrescenta os dias do mesmo pagamento novamente.
    """
    pedido = pedidos_col.find_one({"order_nsu": order_nsu})
    if not pedido:
        raise RuntimeError("PEDIDO_APROVACAO_NAO_ENCONTRADO")

    if pedido.get("status") == "paid":
        return {
            "pedido": pedido,
            "plano": PLANOS.get(pedido.get("plano_key")) or {},
            "vip_ate": pedido.get("vip_liberado_ate"),
            "vip_aplicado": bool(pedido.get("vip_aplicado_ao_pedido")),
            "finalizado_agora": False,
        }

    if pedido.get("status") != "approving":
        raise RuntimeError("PEDIDO_NAO_ESTA_EM_APROVACAO")

    plano = PLANOS.get(pedido.get("plano_key")) or {}
    if not plano:
        raise RuntimeError("PLANO_DO_PEDIDO_INVALIDO")

    vip_ate, vip_aplicado = liberar_vip_por_plano(
        pedido["user_id"],
        plano,
        order_nsu=order_nsu,
    )
    agora = agora_tz()
    verificado_em = (
        pedido.get("manual_verified_at")
        or pedido.get("approval_started_at")
        or agora
    )

    resultado = pedidos_col.update_one(
        {"order_nsu": order_nsu, "status": "approving"},
        {
            "$set": {
                "status": "paid",
                "paid_at": verificado_em,
                "paid_amount": int(pedido.get("valor_centavos") or 0),
                "capture_method": "pix_manual",
                "payment_verification_status": "manual_verified",
                "manual_verified_by": str(
                    pedido.get("manual_verified_by") or ADMIN_ID
                ),
                "manual_verified_at": verificado_em,
                "approval_completed_at": agora,
                "vip_liberado_ate": vip_ate,
                "vip_aplicado_nesta_chamada": vip_aplicado,
                "vip_aplicado_ao_pedido": True,
            },
            "$unset": {"expires_at": ""},
        },
    )

    if resultado.modified_count:
        pedido_final = pedidos_col.find_one({"order_nsu": order_nsu}) or pedido
        return {
            "pedido": pedido_final,
            "plano": plano,
            "vip_ate": vip_ate,
            "vip_aplicado": vip_aplicado,
            "finalizado_agora": True,
        }

    # Outra execução pode ter concluído o mesmo pedido entre a leitura e a
    # gravação. Aceita somente o estado final esperado.
    pedido_atual = pedidos_col.find_one({"order_nsu": order_nsu}) or {}
    if pedido_atual.get("status") == "paid":
        return {
            "pedido": pedido_atual,
            "plano": plano,
            "vip_ate": pedido_atual.get("vip_liberado_ate") or vip_ate,
            "vip_aplicado": bool(pedido_atual.get("vip_aplicado_ao_pedido")),
            "finalizado_agora": False,
        }

    raise RuntimeError("PEDIDO_APROVACAO_MUDOU_DE_ESTADO")


def recuperar_aprovacoes_pix_interrompidas():
    """Retoma aprovações autorizadas que foram interrompidas por reinício."""
    recuperados = 0
    falhas = 0

    try:
        pedidos_pendentes = list(pedidos_col.find({"status": "approving"}))
    except Exception as e:
        logger.error(
            f"[PIX_RECUPERACAO_LISTAR] erro={sanitizar_erro_log(e)}"
        )
        return 0, 1

    for pedido in pedidos_pendentes:
        order_nsu = str(pedido.get("order_nsu") or "").strip()
        if not order_nsu:
            falhas += 1
            continue

        lock_pedido = obter_lock_distribuido_local(
            order_nsu, PAYMENT_ORDER_LOCKS
        )
        try:
            with lock_pedido:
                aprovacao = finalizar_aprovacao_pix_em_processamento(order_nsu)

            if aprovacao["finalizado_agora"]:
                recuperados += 1
                pedido_final = aprovacao["pedido"]
                plano = aprovacao["plano"]
                notificar_pagamento_confirmado(
                    pedido_final["user_id"],
                    plano.get("nome") or pedido_final.get("plano_nome") or "VIP",
                    aprovacao["vip_ate"],
                )
                logger.info(
                    f"[PIX_RECUPERACAO_OK] pedido_ref={referencia_pedido_log(order_nsu)} "
                    f"user_ref={referencia_usuario_log(pedido_final['user_id'])}"
                )
        except Exception as e:
            falhas += 1
            logger.error(
                f"[PIX_RECUPERACAO_FALHA] pedido_ref={referencia_pedido_log(order_nsu)} "
                f"erro={sanitizar_erro_log(e)}"
            )

    if recuperados or falhas:
        safe_send_message(
            ADMIN_ID,
            "🔄 *Recuperação de pagamentos concluída*\n\n"
            f"✅ Aprovações recuperadas: `{recuperados}`\n"
            f"❌ Falhas que exigem atenção: `{falhas}`",
            parse_mode="Markdown",
        )

    return recuperados, falhas


# =========================================
# USUÁRIO / VIP
# =========================================
def _obter_usuario_db(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    hoje = hoje_str()

    if not user:
        user = {
            "_id": uid,
            "vip_ate": None,
            "downloads_hoje": 0,
            "ultima_data": hoje
        }
        usuarios_col.insert_one(user)
        return user

    alteracoes = {}
    if "downloads_hoje" not in user:
        alteracoes["downloads_hoje"] = 0
        user["downloads_hoje"] = 0

    if "ultima_data" not in user:
        alteracoes["ultima_data"] = hoje
        user["ultima_data"] = hoje

    if "vip_ate" not in user:
        alteracoes["vip_ate"] = None
        user["vip_ate"] = None

    if alteracoes:
        usuarios_col.update_one({"_id": uid}, {"$set": alteracoes})

    if user.get("ultima_data") != hoje:
        usuarios_col.update_one(
            {"_id": uid},
            {
                "$set": {"downloads_hoje": 0, "ultima_data": hoje},
                "$unset": {"download_reserva": ""},
            },
        )
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje
        user.pop("download_reserva", None)

    return user


def obter_usuario(user_id):
    try:
        user = _obter_usuario_db(user_id)
        registrar_sucesso_componente("MongoDB")
        return user
    except Exception as e:
        registrar_falha_componente("MongoDB", e)
        raise


def is_vip_user(user):
    v_ate = user.get("vip_ate")

    if v_ate == "Vitalício":
        return True

    if not v_ate:
        return False

    try:
        return agora_tz().date() <= datetime.strptime(v_ate, "%Y-%m-%d").date()
    except Exception as e:
        logger.warning(
            f"[IS_VIP_USER] validade_invalida=True erro={sanitizar_erro_log(e)}"
        )
        return False


def notificar_vips_com_vencimento_proximo():
    """Envia um único lembrete no dia anterior ao vencimento do VIP."""
    data_alvo = (
        agora_tz().date() + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    filtro_pendente = {
        "vip_ate": data_alvo,
        "vip_expiration_notice_for": {"$ne": data_alvo},
    }
    total_reservados = 0
    total_enviados = 0
    total_falhas = 0

    candidatos = usuarios_col.find(
        filtro_pendente,
        {"_id": 1},
    ).limit(500)

    for candidato in candidatos:
        user_id = str(candidato.get("_id") or "").strip()
        if not user_id.isdigit():
            total_falhas += 1
            logger.warning("[VIP_EXPIRATION_NOTICE] user_ref=invalido status=ignorado")
            continue

        agora = agora_tz()
        reservado = usuarios_col.find_one_and_update(
            {
                "_id": user_id,
                "vip_ate": data_alvo,
                "vip_expiration_notice_for": {"$ne": data_alvo},
            },
            {
                "$set": {
                    "vip_expiration_notice_for": data_alvo,
                    "vip_expiration_notice_status": "reserved",
                    "vip_expiration_notice_updated_at": agora,
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not reservado:
            continue

        total_reservados += 1
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "💠 Renovar VIP Mensal - R$ 10,00",
                callback_data="pay_10.00",
            ),
            types.InlineKeyboardButton(
                "💠 Renovar VIP Anual - R$ 79,90",
                callback_data="pay_79.90",
            ),
        )
        mensagem = (
            "⚠️ *Seu acesso VIP termina amanhã*\n\n"
            f"Válido até: *{formatar_validade_vip(data_alvo)}*\n\n"
            "Renove para continuar com downloads sem limite diário e "
            "prioridade no processamento."
        )

        enviado = safe_send_message(
            int(user_id),
            mensagem,
            parse_mode="Markdown",
            reply_markup=markup,
        )
        status = "sent" if enviado else "failed"
        usuarios_col.update_one(
            {
                "_id": user_id,
                "vip_expiration_notice_for": data_alvo,
            },
            {
                "$set": {
                    "vip_expiration_notice_status": status,
                    "vip_expiration_notice_updated_at": agora_tz(),
                }
            },
        )

        if enviado:
            total_enviados += 1
        else:
            total_falhas += 1

    if total_reservados or total_falhas:
        logger.info(
            f"[VIP_EXPIRATION_NOTICE] data={data_alvo} "
            f"reservados={total_reservados} enviados={total_enviados} "
            f"falhas={total_falhas}"
        )

    return {
        "data": data_alvo,
        "reservados": total_reservados,
        "enviados": total_enviados,
        "falhas": total_falhas,
    }


# =========================================
# PINTEREST
# =========================================
def resolver_link_pinterest(url):
    try:
        url = url.strip()

        if "pin.it/" in url.lower():
            r, url_final = seguir_redirecionamentos_seguros(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.pinterest.com/",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
                },
            )
            r.close()
            if not detectar_plataforma_url(url_final)[0]:
                raise RuntimeError("PINTEREST_REDIRECIONAMENTO_FORA_DA_PLATAFORMA")
            logger.info(
                f"[PINTEREST_REDIRECT] origem={referencia_url_log(url)} "
                f"destino={referencia_url_log(url_final)}"
            )
            return url_final

    except Timeout as e:
        logger.warning(
            f"[PINTEREST_TIMEOUT] url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )
    except RequestException as e:
        logger.warning(
            f"[PINTEREST_REQUEST_ERROR] url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )
    except Exception as e:
        logger.warning(
            f"[PINTEREST_UNKNOWN_ERROR] url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )

    return url


def baixar_pinterest_capado(url, prefix, info=None):
    url = resolver_link_pinterest(url)

    formatos = formatos_por_plataforma(is_pinterest=True)

    common_opts = montar_download_opts(prefix, is_pinterest=True)
    ultimo_erro = None

    for fmt in formatos:
        try:
            cleanup_prefix(prefix)

            opts = common_opts.copy()
            opts["format"] = fmt

            if info:
                baixar_info_ja_extraida(info, opts)
            else:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

            arquivo = encontrar_arquivo_baixado(prefix)
            if arquivo and os.path.exists(arquivo):
                logger.info(
                    f"[PINTEREST_OK] formato={fmt} "
                    f"url_ref={referencia_url_log(url)}"
                )
                return arquivo

        except FalhaComponenteDownload:
            raise
        except Exception as e:
            ultimo_erro = str(e)
            logger.warning(
                f"[PINTEREST_TENTATIVA] formato={fmt} "
                f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
            )

    raise Exception(ultimo_erro or "Falha ao baixar Pinterest")


# =========================================
# MENU / UI
# =========================================
def configurar_menu_comandos():
    """Configura o menu nativo do Telegram para usuários e administrador."""
    comandos_usuario = [
        types.BotCommand("start", "Início e status do plano"),
        types.BotCommand("vip", "Conhecer os planos VIP"),
        types.BotCommand("suporte", "Falar com o suporte"),
    ]

    comandos_admin = comandos_usuario + [
        types.BotCommand("painel", "Abrir o Painel Admin"),
        types.BotCommand("pendentes", "Reabrir comprovantes pendentes"),
        types.BotCommand("darvip", "Liberar VIP manualmente"),
        types.BotCommand("removervip", "Remover VIP de um usuário"),
        types.BotCommand("zerar", "Zerar o limite de um usuário"),
        types.BotCommand("avisogeral", "Enviar comunicado aos usuários"),
        types.BotCommand("diagnostico", "Verificar a saúde do bot"),
        types.BotCommand("backupgeral", "Gerar backup completo"),
    ]

    try:
        # Remove comandos globais antigos para que eles não apareçam em grupos.
        bot.delete_my_commands(scope=types.BotCommandScopeDefault())
        bot.set_my_commands(
            comandos_usuario,
            scope=types.BotCommandScopeAllPrivateChats(),
        )
        bot.set_my_commands(
            comandos_admin,
            scope=types.BotCommandScopeChat(chat_id=ADMIN_ID),
        )
        logger.info(
            "[TELEGRAM_MENU] configurado usuarios=%s admin=%s",
            len(comandos_usuario),
            len(comandos_admin),
        )
        return True
    except Exception as e:
        logger.warning(
            "[TELEGRAM_MENU] não foi possível configurar: "
            f"{sanitizar_erro_log(e)}"
        )
        return False


def mostrar_planos_chat(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💠 VIP Mensal - R$ 10,00 via Pix", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💠 VIP Anual - R$ 79,90 via Pix", callback_data="pay_79.90")
    )

    texto = (
        "🚀 *LIBERAR ACESSO VIP*\n\n"
        "Escolha o plano ideal para baixar sem limite diário.\n\n"
        "✅ Sem limite diário\n"
        "✅ Prioridade no processamento\n"
        "✅ Uso liberado para TikTok, Pinterest, Instagram e RedNote\n"
        "✅ Pagamento exclusivamente via Pix\n"
        "✅ Liberação após conferência do pagamento\n\n"
        f"Sua ID: `{user_id}`"
    )

    safe_send_message(chat_id, texto, parse_mode="Markdown", reply_markup=markup)



def serializar_para_json(valor):
    if isinstance(valor, datetime):
        return valor.isoformat()

    if isinstance(valor, dict):
        return {str(k): serializar_para_json(v) for k, v in valor.items()}

    if isinstance(valor, list):
        return [serializar_para_json(v) for v in valor]

    if isinstance(valor, tuple):
        return [serializar_para_json(v) for v in valor]

    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor

    return str(valor)


def construir_payload_backup(nome, documentos):
    docs_serializados = [serializar_para_json(doc) for doc in documentos]
    return {
        "generated_at": agora_tz().isoformat(),
        "service": SERVICE_NAME,
        "environment": ENVIRONMENT_NAME,
        "backup_type": nome,
        "count": len(docs_serializados),
        "documents": docs_serializados,
    }


def salvar_backup_json(nome_arquivo_base, payload):
    if not re.fullmatch(r"[a-z0-9_]{1,80}", str(nome_arquivo_base or "")):
        raise RuntimeError("NOME_BACKUP_INVALIDO")

    garantir_estrutura_privada()
    timestamp = agora_tz().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(
        PRIVATE_BACKUPS_DIR,
        f"{nome_arquivo_base}_{timestamp}.json",
    )

    with abrir_arquivo_privado_para_escrita(caminho) as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.flush()

    garantir_arquivo_privado(caminho)

    return caminho


def enviar_documento_privado_admin(caminho_arquivo, legenda=None):
    garantir_arquivo_privado(caminho_arquivo)
    with open(caminho_arquivo, "rb") as f:
        bot.send_document(ADMIN_ID, f, caption=legenda)


def consultar_docs_backup(tipo):
    hoje = hoje_str()

    if tipo == "usuarios":
        docs = list(
            usuarios_col.find(
                {},
                {
                    "_id": 1,
                    "vip_ate": 1,
                    "downloads_hoje": 1,
                    "ultima_data": 1,
                    "vip_orders_aplicados": 1,
                    "pix_order_aguardando_comprovante": 1,
                }
            ).sort("_id", 1)
        )
        return docs, "backup_usuarios", "📦 Backup de usuários gerado"

    if tipo == "vips":
        docs = list(
            usuarios_col.find(
                {
                    "$or": [
                        {"vip_ate": "Vitalício"},
                        {"vip_ate": {"$gte": hoje}}
                    ]
                },
                {
                    "_id": 1,
                    "vip_ate": 1,
                    "downloads_hoje": 1,
                    "ultima_data": 1,
                    "vip_orders_aplicados": 1,
                    "pix_order_aguardando_comprovante": 1,
                }
            ).sort("vip_ate", -1)
        )
        return docs, "backup_vips_ativos", "💎 Backup de VIPs ativos gerado"

    if tipo == "pedidos":
        docs = list(
            pedidos_col.find(
                {},
                {
                    "_id": 0,
                    "order_nsu": 1,
                    "user_id": 1,
                    "plano_key": 1,
                    "plano_nome": 1,
                    "valor_centavos": 1,
                    "status": 1,
                    "created_at": 1,
                    "paid_at": 1,
                    "capture_method": 1,
                    "vip_liberado_ate": 1,
                    "vip_aplicado_nesta_chamada": 1,
                    "paid_amount": 1,
                    "payment_verification_status": 1,
                    "expires_at": 1,
                    "expired_at": 1,
                    "cancelled_at": 1,
                    "delivery_failed_at": 1,
                    "receipt_requested_at": 1,
                    "receipt_submitted_at": 1,
                    "receipt_telegram_file_id": 1,
                    "receipt_telegram_type": 1,
                    "receipt_source_chat_id": 1,
                    "receipt_source_message_id": 1,
                    "admin_review_message_id": 1,
                    "receipt_rejected_at": 1,
                    "receipt_rejected_by": 1,
                    "approval_started_at": 1,
                    "approval_completed_at": 1,
                    "last_reopened_at": 1,
                    "last_reopened_by": 1,
                    "receipt_reopen_count": 1,
                    "manual_verified_at": 1,
                    "manual_verified_by": 1,
                    "vip_aplicado_ao_pedido": 1,
                }
            ).sort("created_at", -1)
        )
        return docs, "backup_pedidos", "🧾 Backup de pedidos gerado"

    if tipo == "geral":
        usuarios_docs = list(
            usuarios_col.find(
                {},
                {
                    "_id": 1,
                    "vip_ate": 1,
                    "downloads_hoje": 1,
                    "ultima_data": 1,
                    "vip_orders_aplicados": 1,
                    "pix_order_aguardando_comprovante": 1,
                }
            ).sort("_id", 1)
        )
        vips_docs = list(
            usuarios_col.find(
                {
                    "$or": [
                        {"vip_ate": "Vitalício"},
                        {"vip_ate": {"$gte": hoje}}
                    ]
                },
                {
                    "_id": 1,
                    "vip_ate": 1,
                    "downloads_hoje": 1,
                    "ultima_data": 1,
                    "vip_orders_aplicados": 1,
                    "pix_order_aguardando_comprovante": 1,
                }
            ).sort("vip_ate", -1)
        )
        pedidos_docs = list(
            pedidos_col.find(
                {},
                {
                    "_id": 0,
                    "order_nsu": 1,
                    "user_id": 1,
                    "plano_key": 1,
                    "plano_nome": 1,
                    "valor_centavos": 1,
                    "status": 1,
                    "created_at": 1,
                    "paid_at": 1,
                    "capture_method": 1,
                    "vip_liberado_ate": 1,
                    "vip_aplicado_nesta_chamada": 1,
                    "paid_amount": 1,
                    "payment_verification_status": 1,
                    "expires_at": 1,
                    "expired_at": 1,
                    "cancelled_at": 1,
                    "delivery_failed_at": 1,
                    "receipt_requested_at": 1,
                    "receipt_submitted_at": 1,
                    "receipt_telegram_file_id": 1,
                    "receipt_telegram_type": 1,
                    "receipt_source_chat_id": 1,
                    "receipt_source_message_id": 1,
                    "admin_review_message_id": 1,
                    "receipt_rejected_at": 1,
                    "receipt_rejected_by": 1,
                    "approval_started_at": 1,
                    "approval_completed_at": 1,
                    "last_reopened_at": 1,
                    "last_reopened_by": 1,
                    "receipt_reopen_count": 1,
                    "manual_verified_at": 1,
                    "manual_verified_by": 1,
                    "vip_aplicado_ao_pedido": 1,
                }
            ).sort("created_at", -1)
        )
        metricas_docs = list(
            metricas_col.find({}).sort("_id", -1)
        )
        auditoria_admin_docs = list(
            auditoria_admin_col.find({}).sort("created_at", -1)
        )
        auditoria_sistema_docs = list(
            auditoria_sistema_col.find({}).sort("created_at", -1)
        )
        payload = {
            "generated_at": agora_tz().isoformat(),
            "service": SERVICE_NAME,
            "environment": ENVIRONMENT_NAME,
            "backup_type": "geral",
            "usuarios_count": len(usuarios_docs),
            "vips_ativos_count": len(vips_docs),
            "pedidos_count": len(pedidos_docs),
            "metricas_diarias_count": len(metricas_docs),
            "auditoria_admin_count": len(auditoria_admin_docs),
            "auditoria_sistema_count": len(auditoria_sistema_docs),
            "usuarios": [serializar_para_json(doc) for doc in usuarios_docs],
            "vips_ativos": [serializar_para_json(doc) for doc in vips_docs],
            "pedidos": [serializar_para_json(doc) for doc in pedidos_docs],
            "metricas_diarias": [serializar_para_json(doc) for doc in metricas_docs],
            "auditoria_admin": [
                serializar_para_json(doc) for doc in auditoria_admin_docs
            ],
            "auditoria_sistema": [
                serializar_para_json(doc) for doc in auditoria_sistema_docs
            ],
        }
        return payload, "backup_geral", "🗂 Backup geral gerado"

    raise ValueError("Tipo de backup inválido")


def processar_backup_admin(tipo, origem_chat_id=None):
    if not BACKUP_ADMIN_LOCK.acquire(blocking=False):
        safe_send_message(
            origem_chat_id or ADMIN_ID,
            "⚠️ Já existe um backup sendo gerado. Aguarde a conclusão.",
        )
        return

    caminho_arquivo = None
    try:
        resultado, nome_base, legenda = consultar_docs_backup(tipo)

        if tipo == "geral":
            payload = resultado
            total = (
                int(payload.get("usuarios_count", 0))
                + int(payload.get("vips_ativos_count", 0))
                + int(payload.get("pedidos_count", 0))
                + int(payload.get("metricas_diarias_count", 0))
                + int(payload.get("auditoria_admin_count", 0))
            )
        else:
            documentos = resultado
            payload = construir_payload_backup(tipo, documentos)
            total = payload["count"]

        caminho_arquivo = salvar_backup_json(nome_base, payload)
        enviar_documento_privado_admin(caminho_arquivo, legenda=f"{legenda} | registros: {total}")

        mensagem_ok = f"✅ {legenda} e enviado no seu privado. Registros: {total}"
        safe_send_message(ADMIN_ID, mensagem_ok)

        if origem_chat_id and origem_chat_id != ADMIN_ID:
            safe_send_message(origem_chat_id, "✅ Backup gerado e enviado no privado do ADM.")
    except Exception as e:
        logger.error(
            f"[BACKUP_ADMIN] tipo={tipo} erro={sanitizar_erro_log(e)}"
        )
        safe_send_message(ADMIN_ID, f"❌ Erro ao gerar backup `{tipo}`.", parse_mode="Markdown")
        if origem_chat_id and origem_chat_id != ADMIN_ID:
            safe_send_message(origem_chat_id, "❌ Erro ao gerar backup do ADM.")
    finally:
        if caminho_arquivo and os.path.exists(caminho_arquivo):
            try:
                os.remove(caminho_arquivo)
            except Exception as e:
                logger.warning(
                    "[BACKUP_ADMIN_CLEANUP] "
                    f"arquivo_ref={referencia_arquivo_log(caminho_arquivo)} "
                    f"erro={sanitizar_erro_log(e)}"
                )
        BACKUP_ADMIN_LOCK.release()


def montar_relatorio_diagnostico():
    """Verifica componentes locais e conexões sem baixar nenhum vídeo."""
    linhas = ["🩺 <b>Diagnóstico do bot</b>", ""]
    problemas = []

    estado_bot, ultima_atividade = obter_estado_bot()
    if estado_bot == "polling":
        registrar_sucesso_componente("Telegram")
        linhas.append("✅ Telegram: polling ativo")
    else:
        registrar_falha_componente(
            "Telegram",
            f"POLLING_FORA_DO_ESTADO_ATIVO estado={estado_bot}",
        )
        linhas.append(
            f"⚠️ Telegram: estado {html.escape(str(estado_bot))}"
        )
        problemas.append("Telegram não está em polling")

    try:
        client.admin.command("ping")
        registrar_sucesso_componente("MongoDB")
        linhas.append("✅ MongoDB: conectado")
    except Exception as e:
        registrar_falha_componente("MongoDB", e)
        linhas.append("❌ MongoDB: falha de conexão")
        problemas.append(f"MongoDB: {sanitizar_erro_log(e, limite=180)}")

    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    ffprobe_ok = bool(shutil.which("ffprobe"))
    if ffmpeg_ok and ffprobe_ok:
        registrar_sucesso_componente("Processamento")
        linhas.append("✅ FFmpeg e FFprobe: disponíveis")
    else:
        registrar_falha_componente(
            "Processamento",
            "FFMPEG_OU_FFPROBE_AUSENTE",
        )
        linhas.append("❌ FFmpeg/FFprobe: dependência ausente")
        problemas.append("FFmpeg ou FFprobe ausente")

    saude_worker = obter_saude_worker()
    if saude_worker["stalled"]:
        linhas.append(
            "❌ Worker de downloads: sem progresso há "
            f"{saude_worker['seconds_without_progress']}s "
            f"(etapa {html.escape(str(saude_worker['phase']))})"
        )
        reinicio = saude_worker["auto_restart"]
        if reinicio["blocked_reason"]:
            linhas.append(
                "⛔ Reinício automático: bloqueado por "
                f"{html.escape(str(reinicio['blocked_reason']))}"
            )
        elif reinicio["in_progress"]:
            linhas.append("⚠️ Reinício automático: sendo preparado")
        elif reinicio["restart_due_in_seconds"] is not None:
            linhas.append(
                "ℹ️ Reinício automático em aproximadamente "
                f"{reinicio['restart_due_in_seconds']}s se não houver recuperação"
            )
        problemas.append("Worker de downloads sem progresso")
    elif not saude_worker["running"]:
        linhas.append("❌ Worker de downloads: inativo")
        problemas.append("Worker de downloads inativo")
    elif saude_worker["busy"]:
        linhas.append(
            "✅ Worker de downloads: processando "
            f"(etapa {html.escape(str(saude_worker['phase']))})"
        )
    else:
        linhas.append("✅ Worker de downloads: ativo e aguardando")

    fila_ocupada = saude_worker["queue_size"]
    fila_cheia = fila_ocupada >= DOWNLOAD_QUEUE_MAX
    linhas.append(
        f"{'⚠️' if fila_cheia else '✅'} Fila: "
        f"{fila_ocupada}/{DOWNLOAD_QUEUE_MAX} ocupada"
    )
    if fila_cheia:
        problemas.append("Fila de downloads cheia")

    try:
        uso_disco = shutil.disk_usage(DOWNLOAD_DIR)
        livre_mb = uso_disco.free / (1024 * 1024)
        livre_percentual = (
            (uso_disco.free / uso_disco.total) * 100 if uso_disco.total else 0
        )
        disco_baixo = (
            uso_disco.free < MIN_DISK_FREE_BYTES
            or livre_percentual < 10
        )
        icone_disco = "⚠️" if disco_baixo else "✅"
        linhas.append(
            f"{icone_disco} Disco livre: {livre_mb:.0f} MB "
            f"({livre_percentual:.0f}%, mínimo {MIN_DISK_FREE_MB} MB)"
        )
        if disco_baixo:
            problemas.append("Pouco espaço livre em disco")
        registrar_sucesso_componente("Armazenamento")
    except Exception as e:
        registrar_falha_componente("Armazenamento", e)
        linhas.append("⚠️ Disco: não foi possível consultar")
        problemas.append(f"Disco: {sanitizar_erro_log(e, limite=180)}")

    if TIKTOK_IMPERSONATION_DISPONIVEL:
        linhas.append("✅ TikTok: curl_cffi disponível")
    else:
        linhas.append("❌ TikTok: curl_cffi ausente")
        problemas.append("curl_cffi ausente")

    if tikwm_circuito_disponivel():
        linhas.append("✅ TikTok sem marca: circuito disponível")
    else:
        linhas.append("⚠️ TikTok sem marca: pausa automática temporária")
        problemas.append("Circuito TikTok temporariamente pausado")

    linhas.append(
        "✅ Cookies do Instagram: configurados"
        if INSTAGRAM_COOKIES_TEXT.strip()
        else "ℹ️ Cookies do Instagram: não configurados (opcional)"
    )
    linhas.append(
        "✅ Cookies do TikTok: configurados"
        if TIKTOK_COOKIES_TEXT.strip()
        else "ℹ️ Cookies do TikTok: não configurados (opcional)"
    )

    resumo_monitor = obter_resumo_monitoramento()
    alertas_ativos = [
        componente
        for componente, estado in resumo_monitor.items()
        if estado["alerta_ativo"]
    ]
    falhas_recentes = sum(
        estado["falhas_recentes"] for estado in resumo_monitor.values()
    )
    if alertas_ativos:
        alertas_plataformas = [
            item for item in alertas_ativos if item in COMPONENTES_PLATAFORMA
        ]
        alertas_internos = [
            item for item in alertas_ativos if item in COMPONENTES_INTERNOS
        ]
        if alertas_plataformas:
            linhas.append(
                "⚠️ Plataformas em alerta: "
                + html.escape(", ".join(alertas_plataformas))
            )
        if alertas_internos:
            linhas.append(
                "⚠️ Componentes internos em alerta: "
                + html.escape(", ".join(alertas_internos))
            )
        problemas.append("Há alerta automático ativo")
    else:
        linhas.append(
            f"✅ Monitoramento: normal ({falhas_recentes} falhas técnicas recentes)"
        )

    if ultima_atividade:
        linhas.append(
            "ℹ️ Última atualização do Telegram: "
            f"{html.escape(str(ultima_atividade))}"
        )

    linhas.extend(["", "<b>Resultado:</b>"])
    if problemas:
        linhas.append(
            f"⚠️ Foram encontrados {len(problemas)} ponto(s) para atenção."
        )
    else:
        linhas.append("✅ Todos os componentes verificados estão normais.")
    linhas.append("Nenhum vídeo foi baixado durante este diagnóstico.")

    return "\n".join(linhas)


def processar_diagnostico_admin(chat_id, status_message_id=None):
    if not DIAGNOSTIC_ADMIN_LOCK.acquire(blocking=False):
        safe_send_message(chat_id, "⏳ Já existe um diagnóstico em andamento.")
        return

    try:
        relatorio = montar_relatorio_diagnostico()
        if status_message_id:
            safe_edit_message(
                chat_id,
                status_message_id,
                relatorio,
                parse_mode="HTML",
            )
        else:
            safe_send_message(chat_id, relatorio, parse_mode="HTML")
    except Exception as e:
        logger.error(f"[DIAGNOSTICO] erro={sanitizar_erro_log(e)}")
        safe_send_message(
            chat_id,
            "❌ Não foi possível concluir o diagnóstico agora.",
        )
    finally:
        DIAGNOSTIC_ADMIN_LOCK.release()


# =========================================
# COMANDOS ADMIN
# =========================================
class AuditoriaAdminIndisponivel(RuntimeError):
    pass


def iniciar_auditoria_admin(
    message,
    action,
    target_user_id,
    before,
    after,
    details=None,
):
    """Registra a intenção antes de qualquer alteração administrativa."""
    agora = agora_tz()
    documento = {
        "action": str(action),
        "status": "pending",
        "admin_id": str(ADMIN_ID),
        "target_user_id": str(target_user_id),
        "before": before or {},
        "after": after or {},
        "details": details or {},
        "telegram_chat_id": int(getattr(message.chat, "id", 0) or 0),
        "telegram_message_id": int(getattr(message, "message_id", 0) or 0),
        "created_at": agora,
        "updated_at": agora,
    }

    try:
        resultado = auditoria_admin_col.insert_one(documento)
        if not getattr(resultado, "inserted_id", None):
            raise RuntimeError("registro sem identificador")
        return resultado.inserted_id
    except Exception as e:
        logger.critical(
            f"[AUDITORIA_ADMIN_INICIO_FALHA] action={action} "
            f"user_ref={referencia_usuario_log(target_user_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        raise AuditoriaAdminIndisponivel(
            "AUDITORIA_ADMIN_INDISPONIVEL"
        ) from e


def finalizar_auditoria_admin(
    auditoria_id,
    user_notified,
    admin_notified,
    change_applied=True,
):
    """Finaliza a auditoria; uma falha aqui não desfaz a alteração já feita."""
    agora = agora_tz()
    try:
        resultado = auditoria_admin_col.update_one(
            {"_id": auditoria_id, "status": "pending"},
            {
                "$set": {
                    "status": "completed",
                    "change_applied": bool(change_applied),
                    "user_notified": bool(user_notified),
                    "admin_notified": bool(admin_notified),
                    "completed_at": agora,
                    "updated_at": agora,
                }
            },
        )
        if not resultado.modified_count:
            raise RuntimeError("registro de auditoria não foi finalizado")
        return True
    except Exception as e:
        logger.critical(
            "[AUDITORIA_ADMIN_FINAL_FALHA] "
            f"auditoria_ref={referencia_privada_log('auditoria', auditoria_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        safe_send_message(
            ADMIN_ID,
            "⚠️ *Atenção: auditoria administrativa pendente*\n\n"
            "A alteração foi executada, mas o registro não pôde ser finalizado. "
            f"Identificador: `{auditoria_id}`",
            parse_mode="Markdown",
        )
        return False


def falhar_auditoria_admin(auditoria_id, erro):
    """Registra uma ação que começou, mas não conseguiu alterar o usuário."""
    agora = agora_tz()
    erro_limpo = sanitizar_erro_log(erro, limite=500)
    try:
        auditoria_admin_col.update_one(
            {"_id": auditoria_id, "status": "pending"},
            {
                "$set": {
                    "status": "failed",
                    "error": erro_limpo,
                    "failed_at": agora,
                    "updated_at": agora,
                    "change_applied": False,
                    "user_notified": False,
                }
            },
        )
    except Exception as audit_error:
        logger.critical(
            f"[AUDITORIA_ADMIN_FALHA_NAO_REGISTRADA] "
            f"auditoria_ref={referencia_privada_log('auditoria', auditoria_id)} "
            f"erro={sanitizar_erro_log(audit_error)}"
        )


def responder_falha_comando_admin(message, comando, erro):
    if isinstance(erro, AuditoriaAdminIndisponivel):
        return safe_reply_to(
            message,
            "🛑 A auditoria está indisponível. Por segurança, nenhuma alteração "
            "foi realizada. Tente novamente em instantes.",
        )
    return safe_reply_to(message, comando, parse_mode="Markdown")


@bot.message_handler(commands=["diagnostico"])
def diagnostico_admin(message):
    if not exigir_admin_privado(message):
        return

    status = safe_reply_to(
        message,
        "🩺 Verificando os componentes do bot...",
    )
    Thread(
        target=processar_diagnostico_admin,
        args=(message.chat.id, getattr(status, "message_id", None)),
        daemon=True,
    ).start()


@bot.message_handler(commands=["darvip"])
def dar_vip_manual(message):
    if not exigir_admin_privado(message):
        return

    auditoria_id = None
    try:
        args = message.text.split()
        if len(args) != 3:
            return safe_reply_to(message, "❌ Use: `/darvip ID DIAS`", parse_mode="Markdown")

        alvo_id = str(args[1]).strip()
        if not re.fullmatch(r"[1-9]\d{0,19}", alvo_id):
            raise ValueError("ID inválida")
        dias = int(args[2])
        if dias < 1 or dias > 3650:
            raise ValueError("dias fora do intervalo")

        usuario_anterior = usuarios_col.find_one({"_id": alvo_id})
        nova_data = (
            "Vitalício" if dias == 3650
            else calcular_nova_data_vip(
                usuario_anterior or {"vip_ate": None},
                dias,
            )
        )
        antes = {
            "user_exists": bool(usuario_anterior),
            "vip_ate": (
                usuario_anterior.get("vip_ate") if usuario_anterior else None
            ),
        }
        depois = {
            "user_exists": True,
            "vip_ate": nova_data,
        }
        auditoria_id = iniciar_auditoria_admin(
            message,
            "grant_vip",
            alvo_id,
            antes,
            depois,
            details={"days": dias, "lifetime": dias == 3650},
        )

        resultado = usuarios_col.update_one(
            {"_id": str(alvo_id)},
            {
                "$set": {
                    "vip_ate": nova_data,
                    "ultima_data": hoje_str()
                },
                "$setOnInsert": {
                    "downloads_hoje": 0
                }
            },
            upsert=True
        )

        validade = formatar_validade_vip(nova_data)
        usuario_notificado = bool(
            safe_send_message(
                int(alvo_id),
                "💎 *Acesso VIP liberado*\n\n"
                f"Seu acesso está ativo até *{validade}*.",
                parse_mode="Markdown"
            )
        )
        admin_notificado = bool(
            safe_reply_to(
                message,
                f"✅ VIP liberado para `{alvo_id}` até *{validade}*.",
                parse_mode="Markdown",
            )
        )
        finalizar_auditoria_admin(
            auditoria_id,
            user_notified=usuario_notificado,
            admin_notified=admin_notificado,
            change_applied=bool(
                resultado.modified_count or resultado.upserted_id
            ),
        )
    except Exception as e:
        if auditoria_id is not None:
            falhar_auditoria_admin(auditoria_id, e)
        logger.error(f"[DARVIP] erro={sanitizar_erro_log(e)}")
        if auditoria_id is not None:
            safe_reply_to(
                message,
                "❌ Não foi possível confirmar a alteração. A tentativa foi "
                "registrada como falha na auditoria; verifique o usuário antes "
                "de tentar novamente.",
            )
        else:
            responder_falha_comando_admin(
                message,
                "❌ Use: `/darvip ID DIAS` (de 1 a 3650).",
                e,
            )


@bot.message_handler(commands=["removervip"])
def remover_vip_manual(message):
    if not exigir_admin_privado(message):
        return

    auditoria_id = None
    try:
        args = message.text.split()
        if len(args) != 2:
            return safe_reply_to(
                message,
                "❌ Use: `/removervip ID`",
                parse_mode="Markdown",
            )

        alvo_id = str(args[1]).strip()
        if not re.fullmatch(r"[1-9]\d{0,19}", alvo_id):
            raise ValueError("ID inválida")

        usuario = usuarios_col.find_one({"_id": alvo_id})
        if not usuario:
            auditoria_id = iniciar_auditoria_admin(
                message,
                "remove_vip",
                alvo_id,
                {"user_exists": False, "vip_ate": None},
                {"user_exists": False, "vip_ate": None},
                details={"result": "user_not_found"},
            )
            admin_notificado = bool(
                safe_reply_to(
                    message,
                    f"❌ Usuário `{alvo_id}` não encontrado.",
                    parse_mode="Markdown",
                )
            )
            finalizar_auditoria_admin(
                auditoria_id,
                user_notified=False,
                admin_notified=admin_notificado,
                change_applied=False,
            )
            return

        vip_anterior = usuario.get("vip_ate")
        vip_estava_ativo = is_vip_user(usuario)
        auditoria_id = iniciar_auditoria_admin(
            message,
            "remove_vip",
            alvo_id,
            {"user_exists": True, "vip_ate": vip_anterior},
            {"user_exists": True, "vip_ate": None},
            details={"vip_was_active": vip_estava_ativo},
        )

        resultado = usuarios_col.update_one(
            {"_id": alvo_id},
            {"$set": {"vip_ate": None}},
        )

        logger.info(
            f"[REMOVERVIP] admin_ref={referencia_usuario_log(ADMIN_ID)} "
            f"user_ref={referencia_usuario_log(alvo_id)} "
            f"vip_anterior={vip_anterior} ativo={vip_estava_ativo}"
        )

        if not vip_estava_ativo:
            admin_notificado = bool(
                safe_reply_to(
                    message,
                    f"ℹ️ O usuário `{alvo_id}` já não possuía VIP ativo.",
                    parse_mode="Markdown",
                )
            )
            finalizar_auditoria_admin(
                auditoria_id,
                user_notified=False,
                admin_notified=admin_notificado,
                change_applied=bool(resultado.modified_count),
            )
            return

        usuario_notificado = bool(
            safe_send_message(
                int(alvo_id),
                "ℹ️ *Acesso VIP removido*\n\n"
                "Seu acesso VIP foi encerrado pelo suporte. "
                "Sua conta agora utiliza o plano gratuito.\n\n"
                "Se achar que houve um engano, use /suporte.",
                parse_mode="Markdown",
            )
        )
        admin_notificado = bool(
            safe_reply_to(
                message,
                f"✅ VIP do usuário `{alvo_id}` removido com sucesso.",
                parse_mode="Markdown",
            )
        )
        finalizar_auditoria_admin(
            auditoria_id,
            user_notified=usuario_notificado,
            admin_notified=admin_notificado,
            change_applied=bool(resultado.modified_count),
        )
    except Exception as e:
        if auditoria_id is not None:
            falhar_auditoria_admin(auditoria_id, e)
        logger.error(f"[REMOVERVIP] erro={sanitizar_erro_log(e)}")
        if auditoria_id is not None:
            safe_reply_to(
                message,
                "❌ Não foi possível confirmar a alteração. A tentativa foi "
                "registrada como falha na auditoria; verifique o usuário antes "
                "de tentar novamente.",
            )
        else:
            responder_falha_comando_admin(
                message,
                "❌ Use: `/removervip ID`",
                e,
            )


@bot.message_handler(commands=["zerar"])
def zerar_contador(message):
    if not exigir_admin_privado(message):
        return

    auditoria_id = None
    try:
        args = message.text.split()
        if len(args) != 2:
            return safe_reply_to(message, "❌ Use: `/zerar ID`", parse_mode="Markdown")

        alvo_id = str(args[1]).strip()
        if not re.fullmatch(r"[1-9]\d{0,19}", alvo_id):
            raise ValueError("ID inválida")

        usuario_anterior = usuarios_col.find_one({"_id": alvo_id})
        hoje = hoje_str()
        auditoria_id = iniciar_auditoria_admin(
            message,
            "reset_daily_downloads",
            alvo_id,
            {
                "user_exists": bool(usuario_anterior),
                "downloads_hoje": (
                    usuario_anterior.get("downloads_hoje", 0)
                    if usuario_anterior
                    else None
                ),
                "ultima_data": (
                    usuario_anterior.get("ultima_data")
                    if usuario_anterior
                    else None
                ),
            },
            {
                "user_exists": True,
                "downloads_hoje": 0,
                "ultima_data": hoje,
            },
        )

        resultado = usuarios_col.update_one(
            {"_id": str(alvo_id)},
            {
                "$set": {
                    "downloads_hoje": 0,
                    "ultima_data": hoje
                },
                "$unset": {
                    "download_reserva": "",
                },
                "$setOnInsert": {
                    "vip_ate": None
                }
            },
            upsert=True
        )

        usuario_notificado = bool(
            safe_send_message(
                int(alvo_id),
                "🔄 Suas tentativas diárias foram resetadas pelo suporte. "
                "Pode voltar a baixar!"
            )
        )
        admin_notificado = bool(
            safe_reply_to(
                message,
                f"✅ Contador do usuário {alvo_id} foi zerado!",
            )
        )
        finalizar_auditoria_admin(
            auditoria_id,
            user_notified=usuario_notificado,
            admin_notified=admin_notificado,
            change_applied=bool(
                resultado.modified_count or resultado.upserted_id
            ),
        )
    except Exception as e:
        if auditoria_id is not None:
            falhar_auditoria_admin(auditoria_id, e)
        logger.error(f"[ZERAR] erro={sanitizar_erro_log(e)}")
        if auditoria_id is not None:
            safe_reply_to(
                message,
                "❌ Não foi possível confirmar a alteração. A tentativa foi "
                "registrada como falha na auditoria; verifique o usuário antes "
                "de tentar novamente.",
            )
        else:
            responder_falha_comando_admin(
                message,
                "❌ Use: `/zerar ID`",
                e,
            )


def enviar_aviso_geral_usuario(user_id, msg_texto):
    """Envia um aviso e informa o resultado real da chamada ao Telegram."""
    try:
        chat_id = int(user_id)
        bot.send_message(chat_id, msg_texto, parse_mode="Markdown")
        return "enviado"
    except Exception as e:
        erro_texto = str(e)
        erro_lower = erro_texto.lower()

        if "error code: 403" in erro_lower and "bot was blocked by the user" in erro_lower:
            logger.info(
                f"[AVISOGERAL_BLOQUEADO] user_ref={referencia_usuario_log(user_id)}"
            )
            return "bloqueado"

        logger.error(
            f"[AVISOGERAL_FALHA] user_ref={referencia_usuario_log(user_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return "falha"


def processar_aviso_geral(admin_chat_id, msg_texto):
    if not AVISO_GERAL_LOCK.acquire(blocking=False):
        safe_send_message(
            admin_chat_id,
            "⚠️ Já existe um aviso geral em andamento. Aguarde a conclusão.",
        )
        return

    try:
        usuarios = usuarios_col.find({}, {"_id": 1})
        total_processados = 0
        enviados = 0
        bloqueados = 0
        falhas = 0

        logger.info("[AVISOGERAL_LOOP] iniciado")

        for u in usuarios:
            total_processados += 1
            resultado = enviar_aviso_geral_usuario(u.get("_id"), msg_texto)

            if resultado == "enviado":
                enviados += 1
            elif resultado == "bloqueado":
                bloqueados += 1
            else:
                falhas += 1

            # Mantém o envio abaixo do limite global usual do Telegram.
            time.sleep(0.05)

        relatorio = (
            "📢 *Aviso geral concluído!*\n\n"
            f"✅ Entregues: `{enviados}`\n"
            f"🚫 Bloquearam o bot: `{bloqueados}`\n"
            f"❌ Outras falhas: `{falhas}`\n"
            f"👥 Total processado: `{total_processados}`"
        )
        safe_send_message(admin_chat_id, relatorio, parse_mode="Markdown")
        logger.info(
            f"[AVISOGERAL_LOOP] finalizado total={total_processados} "
            f"enviados={enviados} bloqueados={bloqueados} falhas={falhas}"
        )
    except Exception as e:
        logger.error(f"[AVISOGERAL_LOOP] erro={sanitizar_erro_log(e)}")
        safe_send_message(admin_chat_id, "❌ Erro ao enviar aviso geral.")
    finally:
        AVISO_GERAL_LOCK.release()


@bot.message_handler(commands=["avisogeral"])
def aviso_geral(message):
    if not exigir_admin_privado(message):
        return

    try:
        msg_texto = message.text.replace("/avisogeral", "", 1).strip()
        if not msg_texto:
            return safe_reply_to(message, "❌ Digite a mensagem após o comando.")

        Thread(
            target=processar_aviso_geral,
            args=(message.chat.id, msg_texto),
            daemon=True
        ).start()

        safe_reply_to(message, "📢 Envio do aviso geral iniciado em segundo plano.")
    except Exception as e:
        logger.error(f"[AVISOGERAL] erro={sanitizar_erro_log(e)}")
        safe_reply_to(message, "❌ Erro ao iniciar aviso geral.")


@bot.message_handler(commands=["backupusuarios"])
def backup_usuarios(message):
    if not exigir_admin_privado(message):
        return

    Thread(
        target=processar_backup_admin,
        args=("usuarios", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "📦 Gerando backup de usuários e enviando no seu privado...")


@bot.message_handler(commands=["backupvips"])
def backup_vips(message):
    if not exigir_admin_privado(message):
        return

    Thread(
        target=processar_backup_admin,
        args=("vips", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "💎 Gerando backup de VIPs ativos e enviando no seu privado...")


@bot.message_handler(commands=["backuppedidos"])
def backup_pedidos(message):
    if not exigir_admin_privado(message):
        return

    Thread(
        target=processar_backup_admin,
        args=("pedidos", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "🧾 Gerando backup de pedidos e enviando no seu privado...")


@bot.message_handler(commands=["backupgeral"])
def backup_geral(message):
    if not exigir_admin_privado(message):
        return

    Thread(
        target=processar_backup_admin,
        args=("geral", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "🗂 Gerando backup geral e enviando no seu privado...")


@bot.message_handler(commands=["painel"])
@bot.message_handler(func=lambda m: m.text == "⚙️ Painel Admin")
def painel_admin(message):
    if not exigir_admin_privado(message):
        return

    try:
        hoje = hoje_str()
        total_users = usuarios_col.count_documents({})

        vips_ativos = usuarios_col.count_documents({
            "$or": [
                {"vip_ate": "Vitalício"},
                {"vip_ate": {"$gte": hoje}}
            ]
        })

        metricas_hoje = metricas_col.find_one({"_id": hoje}) or {}
        downloads_totais_hoje = int(metricas_hoje.get("downloads_total", 0) or 0)
        downloads_gratuitos_hoje = int(metricas_hoje.get("downloads_gratuitos", 0) or 0)
        downloads_vips_hoje = int(metricas_hoje.get("downloads_vips", 0) or 0)
        downloads_admin_hoje = int(
            metricas_hoje.get("downloads_admin_teste", 0) or 0
        )
        cache_url_hoje = int(metricas_hoje.get("downloads_cache_url", 0) or 0)
        cache_midia_hoje = int(metricas_hoje.get("downloads_cache_midia", 0) or 0)
        uploads_hoje = int(metricas_hoje.get("downloads_upload", 0) or 0)
        bytes_upload_hoje = int(
            metricas_hoje.get("bytes_upload_telegram", 0) or 0
        )
        cache_total_hoje = cache_url_hoje + cache_midia_hoje
        entregas_medidas_hoje = cache_total_hoje + uploads_hoje
        entregas_operacionais_hoje = (
            downloads_totais_hoje + downloads_admin_hoje
        )
        taxa_cache_hoje = (
            cache_total_hoje * 100 / entregas_medidas_hoje
            if entregas_medidas_hoje > 0
            else 0.0
        )
        cobertura_metricas = ""
        if entregas_medidas_hoje != entregas_operacionais_hoje:
            cobertura_metricas = (
                f"\n📊 Entregas medidas: `{entregas_medidas_hoje}` de "
                f"`{entregas_operacionais_hoje}`"
            )

        comprovantes_em_analise = pedidos_col.count_documents({
            "status": {"$in": ["receipt_submitted", "approving"]}
        })
        pedidos_pagos = pedidos_col.count_documents({"status": "paid"})

        resumo_admin = (
            "⚙️ *Painel Admin*\n\n"
            f"👥 Usuários: `{total_users}`\n"
            f"💎 VIPs: `{vips_ativos}`\n"
            f"📥 Downloads de usuários hoje: `{downloads_totais_hoje}`\n"
            f"   ├ 👤 Gratuitos: `{downloads_gratuitos_hoje}`\n"
            f"   └ 💎 VIPs: `{downloads_vips_hoje}`\n"
            f"🧪 Testes do administrador: `{downloads_admin_hoje}`\n"
            f"♻️ Cache hoje: `{cache_total_hoje}` (`{taxa_cache_hoje:.1f}%`)\n"
            f"   ├ 🔗 Por URL: `{cache_url_hoje}`\n"
            f"   └ 🎞️ Por mídia: `{cache_midia_hoje}`\n"
            f"⬆️ Uploads novos: `{uploads_hoje}`\n"
            f"🌐 Mídia enviada: `{formatar_tamanho_bytes(bytes_upload_hoje)}`"
            f"{cobertura_metricas}\n"
            f"🧾 Comprovantes aguardando análise: `{comprovantes_em_analise}`\n"
            f"✅ Pagamentos aprovados: `{pedidos_pagos}`"
        )

        safe_send_message(message.chat.id, resumo_admin, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[PAINEL_ADMIN] erro={sanitizar_erro_log(e)}")
        safe_send_message(message.chat.id, "❌ Erro ao abrir painel admin.")



# =========================================
# START / PERFIL / PLANOS / SUPORTE
# =========================================
@bot.message_handler(commands=["start", "perfil"])
def start(message):
    if not is_chat_privado(message):
        orientar_uso_no_privado(message)
        return

    user = obter_usuario(message.from_user.id)
    vip = is_vip_user(user)

    if vip:
        validade = formatar_validade_vip(user.get("vip_ate"))

        status = (
            "💎 *Acesso VIP ativo*\n\n"
            "• Sem limite diário\n"
            "• Prioridade na fila: ativa\n"
            f"• Válido até: *{validade}*"
        )
    else:
        status = (
            "👤 *Plano gratuito*\n\n"
            f"• Downloads utilizados hoje: "
            f"{user.get('downloads_hoje', 0)} de {FREE_DAILY_LIMIT}"
        )

    texto = (
        "📥 *Baixar Vídeos HD*\n\n"
        "Baixe vídeos do TikTok, Pinterest, Instagram e RedNote.\n\n"
        "• Qualidade: até 720×1280\n"
        f"• Duração máxima: {MAX_DURATION_SECONDS} segundos\n"
        f"• ID de usuário: `{message.from_user.id}`\n\n"
        f"{status}\n\n"
        "Envie o link de um vídeo para começar ou use o botão *Menu* "
        "para ver as opções."
    )

    safe_send_message(
        message.chat.id,
        texto,
        parse_mode="Markdown",
        reply_markup=types.ReplyKeyboardRemove()
    )


@bot.message_handler(commands=["vip", "planos"])
def cmd_planos(message):
    if not is_chat_privado(message):
        orientar_uso_no_privado(message)
        return
    mostrar_planos_chat(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text in ["🚀 Liberar VIP", "💎 VIP"])
def mostrar_planos(message):
    if not is_chat_privado(message):
        orientar_uso_no_privado(message)
        return
    mostrar_planos_chat(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["suporte"])
@bot.message_handler(func=lambda m: m.text == "📞 Suporte")
def suporte(message):
    if not is_chat_privado(message):
        orientar_uso_no_privado(message)
        return
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Chamar no Suporte", url=LINK_SUPORTE))

        safe_send_message(
            message.chat.id,
            "👋 Precisa de ajuda? Clique abaixo para falar com o suporte oficial:\n"
            f"{SUPORTE_USERNAME}",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"[SUPORTE] erro={sanitizar_erro_log(e)}")
        safe_send_message(
            message.chat.id,
            f"Suporte oficial: {SUPORTE_USERNAME}\n{LINK_SUPORTE}",
        )


def normalizar_datetime_tz(valor):
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(TZ)


def pedido_pix_expirado(pedido):
    expira_em = normalizar_datetime_tz(pedido.get("expires_at"))
    if expira_em is None:
        criado_em = normalizar_datetime_tz(pedido.get("created_at"))
        if criado_em is None:
            return True
        expira_em = criado_em + timedelta(hours=PIX_ORDER_EXPIRATION_HOURS)
    return expira_em <= agora_tz()


def buscar_pedido_pix_ativo(user_id):
    return pedidos_col.find_one(
        {
            "user_id": str(user_id),
            "status": {
                "$in": ["awaiting_pix", "receipt_submitted", "approving"]
            },
        },
        sort=[("created_at", -1)],
    )


def enviar_instrucoes_pix(chat_id, pedido, plano):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton(
        "✅ Já fiz o Pix — enviar comprovante",
        callback_data=f"pix_paid_{pedido['order_nsu']}",
    ))

    valor_reais = int(plano["preco_centavos"]) / 100
    valor_formatado = (
        f"{valor_reais:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    )
    texto = (
        f"💎 <b>{html.escape(plano['nome'])}</b>\n\n"
        "Pagamento exclusivamente via <b>Pix</b>.\n\n"
        f"💰 Valor exato: <b>R$ {valor_formatado}</b>\n"
        f"🔑 Chave Pix: <code>{html.escape(PIX_KEY)}</code>\n"
        f"👤 Recebedor: <b>{html.escape(PIX_RECEIVER_NAME)}</b>\n"
        f"🏦 Instituição: <b>{html.escape(PIX_RECEIVER_BANK)}</b>\n"
        f"🧾 Pedido: <code>{html.escape(pedido['order_nsu'])}</code>\n\n"
        f"Este pedido fica disponível por {PIX_ORDER_EXPIRATION_HOURS} horas. "
        "Depois de pagar, toque no botão abaixo e envie o comprovante. "
        "O VIP será liberado após a entrada do Pix ser conferida."
    )
    return safe_send_message(
        chat_id,
        texto,
        parse_mode="HTML",
        reply_markup=markup,
    )


def montar_painel_comprovantes_pendentes(offset=0):
    """Monta uma página compacta sem carregar os arquivos dos comprovantes."""
    filtro = {"status": {"$in": ["receipt_submitted", "approving"]}}
    total = pedidos_col.count_documents(filtro)
    offset = max(0, int(offset or 0))

    if total and offset >= total:
        offset = ((total - 1) // PIX_PENDING_PAGE_SIZE) * PIX_PENDING_PAGE_SIZE

    pedidos = list(
        pedidos_col.find(
            filtro,
            {
                "_id": 0,
                "order_nsu": 1,
                "user_id": 1,
                "plano_key": 1,
                "plano_nome": 1,
                "valor_centavos": 1,
                "status": 1,
                "created_at": 1,
                "receipt_submitted_at": 1,
                "approval_started_at": 1,
            },
        )
        .sort("created_at", -1)
        .skip(offset)
        .limit(PIX_PENDING_PAGE_SIZE)
    )

    if not pedidos:
        return (
            "🧾 <b>Comprovantes pendentes</b>\n\n"
            "✅ Não há comprovantes aguardando análise.",
            types.InlineKeyboardMarkup(),
            0,
        )

    pagina_atual = (offset // PIX_PENDING_PAGE_SIZE) + 1
    total_paginas = (total + PIX_PENDING_PAGE_SIZE - 1) // PIX_PENDING_PAGE_SIZE
    linhas = [
        "🧾 <b>Comprovantes pendentes</b>",
        "",
        f"Total: <b>{total}</b> | Página: <b>{pagina_atual}/{total_paginas}</b>",
        "",
    ]
    markup = types.InlineKeyboardMarkup(row_width=1)

    for indice, pedido in enumerate(pedidos, start=offset + 1):
        order_nsu = str(pedido.get("order_nsu") or "").strip()
        user_id = str(pedido.get("user_id") or "desconhecido")
        plano = PLANOS.get(pedido.get("plano_key")) or {}
        plano_nome = plano.get("nome") or pedido.get("plano_nome") or "Desconhecido"
        valor = int(pedido.get("valor_centavos") or 0) / 100
        estado = pedido.get("status")
        estado_texto = (
            "aprovação interrompida"
            if estado == "approving"
            else "aguardando análise"
        )
        enviado_em = normalizar_datetime_tz(
            pedido.get("receipt_submitted_at") or pedido.get("created_at")
        )
        enviado_texto = (
            enviado_em.strftime("%d/%m/%Y %H:%M")
            if enviado_em
            else "data indisponível"
        )

        linhas.append(
            f"<b>{indice}.</b> Usuário <code>{html.escape(user_id)}</code>\n"
            f"{html.escape(str(plano_nome))} — R$ {valor:.2f}\n"
            f"{html.escape(estado_texto)} — {enviado_texto}"
        )
        linhas.append("")

        if order_nsu:
            markup.add(
                types.InlineKeyboardButton(
                    f"🧾 Reabrir #{indice} — usuário {user_id}",
                    callback_data=f"pix_reopen_{order_nsu}",
                )
            )

    navegacao = []
    if offset > 0:
        anterior = max(0, offset - PIX_PENDING_PAGE_SIZE)
        navegacao.append(
            types.InlineKeyboardButton(
                "⬅️ Anterior",
                callback_data=f"pix_pending_page_{anterior}",
            )
        )
    if offset + PIX_PENDING_PAGE_SIZE < total:
        proxima = offset + PIX_PENDING_PAGE_SIZE
        navegacao.append(
            types.InlineKeyboardButton(
                "Próxima ➡️",
                callback_data=f"pix_pending_page_{proxima}",
            )
        )
    if navegacao:
        markup.row(*navegacao)

    linhas.append("Toque em um pedido para reenviar o comprovante no seu privado.")
    return "\n".join(linhas), markup, total


def enviar_painel_comprovantes_pendentes(chat_id, offset=0, message_id=None):
    texto, markup, total = montar_painel_comprovantes_pendentes(offset)
    if message_id:
        mensagem = safe_edit_message(
            chat_id,
            message_id,
            texto,
            parse_mode="HTML",
            reply_markup=markup,
        )
    else:
        mensagem = safe_send_message(
            chat_id,
            texto,
            parse_mode="HTML",
            reply_markup=markup,
        )
    return mensagem, total


@bot.message_handler(commands=["pendentes"])
def comprovantes_pendentes_admin(message):
    if not exigir_admin_privado(message):
        return

    try:
        enviar_painel_comprovantes_pendentes(message.chat.id)
    except Exception as e:
        logger.error(f"[PIX_PENDENTES] erro={sanitizar_erro_log(e)}")
        safe_reply_to(
            message,
            "❌ Não foi possível consultar os comprovantes pendentes agora.",
        )


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("pix_pending_page_")
)
def navegar_comprovantes_pendentes(call):
    if (
        call.from_user.id != ADMIN_ID
        or not is_chat_privado(call.message)
        or call.message.chat.id != ADMIN_ID
    ):
        safe_answer_callback(
            call.id,
            text="Acesso restrito ao administrador.",
            show_alert=True,
        )
        return

    try:
        offset_texto = call.data[len("pix_pending_page_"):].strip()
        if not re.fullmatch(r"\d{1,9}", offset_texto):
            raise ValueError("página inválida")
        enviar_painel_comprovantes_pendentes(
            call.message.chat.id,
            offset=int(offset_texto),
            message_id=call.message.message_id,
        )
        safe_answer_callback(call.id)
    except Exception as e:
        logger.error(f"[PIX_PENDENTES_PAGINA] erro={sanitizar_erro_log(e)}")
        safe_answer_callback(
            call.id,
            text="Não foi possível abrir essa página.",
            show_alert=True,
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("pix_reopen_"))
def reabrir_comprovante_pix(call):
    if (
        call.from_user.id != ADMIN_ID
        or not is_chat_privado(call.message)
        or call.message.chat.id != ADMIN_ID
    ):
        safe_answer_callback(
            call.id,
            text="Acesso restrito ao administrador.",
            show_alert=True,
        )
        return

    order_nsu = call.data[len("pix_reopen_"):].strip()
    if not order_nsu or len(order_nsu) > 50:
        safe_answer_callback(call.id, text="Pedido inválido.", show_alert=True)
        return

    lock_pedido = obter_lock_distribuido_local(order_nsu, PAYMENT_ORDER_LOCKS)
    nova_mensagem = None
    try:
        with lock_pedido:
            pedido = pedidos_col.find_one({"order_nsu": order_nsu})
            if not pedido or pedido.get("status") not in (
                "receipt_submitted",
                "approving",
            ):
                safe_answer_callback(
                    call.id,
                    text="Este pedido não está mais pendente.",
                    show_alert=True,
                )
                return

            file_id = str(pedido.get("receipt_telegram_file_id") or "").strip()
            tipo = str(pedido.get("receipt_telegram_type") or "").strip()
            if not file_id or tipo not in ("photo", "document"):
                safe_answer_callback(
                    call.id,
                    text="O arquivo desse comprovante não está disponível.",
                    show_alert=True,
                )
                return

            plano = PLANOS.get(pedido.get("plano_key")) or {}
            plano_nome = plano.get("nome") or pedido.get("plano_nome") or "Desconhecido"
            valor = int(pedido.get("valor_centavos") or 0) / 100
            em_aprovacao = pedido.get("status") == "approving"
            estado_texto = (
                "⚠️ Aprovação anteriormente iniciada; use o botão abaixo para retomar."
                if em_aprovacao
                else "⚠️ Confira a entrada do Pix antes de aprovar."
            )
            legenda = (
                "💠 <b>Comprovante Pix reaberto</b>\n\n"
                f"Pedido: <code>{html.escape(order_nsu)}</code>\n"
                f"Usuário: <code>{html.escape(str(pedido.get('user_id')))}</code>\n"
                f"Plano: <b>{html.escape(str(plano_nome))}</b>\n"
                f"Valor esperado: <b>R$ {valor:.2f}</b>\n\n"
                f"{estado_texto}"
            )

            markup = types.InlineKeyboardMarkup(row_width=1)
            if em_aprovacao:
                markup.add(
                    types.InlineKeyboardButton(
                        "🔄 Retomar aprovação interrompida",
                        callback_data=f"pix_ok_{order_nsu}",
                    )
                )
            else:
                markup.add(
                    types.InlineKeyboardButton(
                        "✅ Aprovar — confirmei o Pix na conta",
                        callback_data=f"pix_ok_{order_nsu}",
                    ),
                    types.InlineKeyboardButton(
                        "❌ Rejeitar comprovante",
                        callback_data=f"pix_no_{order_nsu}",
                    ),
                )

            if tipo == "photo":
                nova_mensagem = bot.send_photo(
                    ADMIN_ID,
                    file_id,
                    caption=legenda,
                    parse_mode="HTML",
                    reply_markup=markup,
                )
            else:
                nova_mensagem = bot.send_document(
                    ADMIN_ID,
                    file_id,
                    caption=legenda,
                    parse_mode="HTML",
                    reply_markup=markup,
                )

            resultado = pedidos_col.update_one(
                {"order_nsu": order_nsu, "status": pedido["status"]},
                {
                    "$set": {
                        "admin_review_message_id": nova_mensagem.message_id,
                        "last_reopened_at": agora_tz(),
                        "last_reopened_by": str(ADMIN_ID),
                    },
                    "$inc": {"receipt_reopen_count": 1},
                },
            )
            if not resultado.modified_count:
                safe_delete_message(ADMIN_ID, nova_mensagem.message_id)
                safe_answer_callback(
                    call.id,
                    text="O pedido mudou de estado. Atualize /pendentes.",
                    show_alert=True,
                )
                return

        safe_answer_callback(call.id, text="Comprovante reaberto abaixo.")
        logger.info(
            f"[PIX_COMPROVANTE_REABERTO] pedido_ref={referencia_pedido_log(order_nsu)} "
            f"status={pedido['status']}"
        )
    except Exception as e:
        logger.error(
            f"[PIX_COMPROVANTE_REABRIR] pedido_ref={referencia_pedido_log(order_nsu)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        if nova_mensagem:
            safe_delete_message(ADMIN_ID, nova_mensagem.message_id)
        safe_answer_callback(
            call.id,
            text="Não foi possível reabrir o comprovante.",
            show_alert=True,
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def iniciar_pagamento_pix_manual(call):
    try:
        if not is_chat_privado(call.message):
            orientar_uso_no_privado(call.message)
            return

        valor = call.data.split("_", 1)[1]
        plano = obter_plano_por_callback(valor)

        if not plano:
            safe_send_message(call.message.chat.id, "❌ Plano inválido.")
            return

        pedido_ativo = buscar_pedido_pix_ativo(call.from_user.id)
        if pedido_ativo and pedido_ativo.get("status") in (
            "receipt_submitted",
            "approving",
        ):
            safe_send_message(
                call.message.chat.id,
                "🧾 Seu comprovante já foi recebido e está aguardando conferência. "
                "Você será avisado aqui.",
            )
            return

        if pedido_ativo and pedido_pix_expirado(pedido_ativo):
            pedidos_col.update_one(
                {"order_nsu": pedido_ativo["order_nsu"], "status": "awaiting_pix"},
                {"$set": {"status": "expired", "expired_at": agora_tz()}},
            )
            pedido_ativo = None

        if pedido_ativo and pedido_ativo.get("plano_key") == valor:
            if not enviar_instrucoes_pix(call.message.chat.id, pedido_ativo, plano):
                raise RuntimeError("falha ao reenviar instruções Pix")
            return

        if pedido_ativo:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "Cancelar pedido anterior",
                callback_data=f"pix_cancel_{pedido_ativo['order_nsu']}",
            ))
            safe_send_message(
                call.message.chat.id,
                "⚠️ Você já possui um pedido Pix em aberto. Cancele o pedido "
                "anterior antes de escolher outro plano.",
                reply_markup=markup,
            )
            return

        agora = agora_tz()
        order_nsu = gerar_order_nsu(call.from_user.id)
        pedido = {
            "order_nsu": order_nsu,
            "user_id": str(call.from_user.id),
            "plano_key": valor,
            "plano_nome": plano["nome"],
            "valor_centavos": int(plano["preco_centavos"]),
            "status": "awaiting_pix",
            "created_at": agora,
            "expires_at": agora + timedelta(hours=PIX_ORDER_EXPIRATION_HOURS),
            "payment_verification_status": "awaiting_manual_receipt",
        }
        pedidos_col.insert_one(pedido)
        if not enviar_instrucoes_pix(call.message.chat.id, pedido, plano):
            pedidos_col.update_one(
                {"order_nsu": order_nsu, "status": "awaiting_pix"},
                {"$set": {"status": "delivery_failed", "delivery_failed_at": agora_tz()}},
            )
            raise RuntimeError("falha ao entregar instruções Pix")

    except Exception as e:
        logger.error(f"[PIX_MANUAL_INICIO] erro={sanitizar_erro_log(e)}")
        safe_send_message(
            call.message.chat.id,
            "❌ Não consegui iniciar seu pagamento Pix agora.\n"
            "Tente novamente em instantes ou fale com o suporte."
        )
    finally:
        safe_answer_callback(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("pix_cancel_"))
def cancelar_pedido_pix(call):
    try:
        if not is_chat_privado(call.message):
            orientar_uso_no_privado(call.message)
            return
        order_nsu = call.data[len("pix_cancel_"):].strip()
        resultado = pedidos_col.update_one(
            {
                "order_nsu": order_nsu,
                "user_id": str(call.from_user.id),
                "status": "awaiting_pix",
            },
            {"$set": {"status": "cancelled", "cancelled_at": agora_tz()}},
        )
        if not resultado.modified_count:
            safe_answer_callback(call.id, text="Pedido não disponível.", show_alert=True)
            return
        usuarios_col.update_one(
            {"_id": str(call.from_user.id), "pix_order_aguardando_comprovante": order_nsu},
            {"$unset": {"pix_order_aguardando_comprovante": ""}},
        )
        safe_edit_message(
            call.message.chat.id,
            call.message.message_id,
            "✅ Pedido anterior cancelado. Agora você pode escolher outro plano.",
        )
        safe_answer_callback(call.id, text="Pedido cancelado.")
    except Exception as e:
        logger.error(f"[PIX_CANCELAR] erro={sanitizar_erro_log(e)}")
        safe_answer_callback(call.id, text="Não foi possível cancelar agora.", show_alert=True)


@bot.callback_query_handler(func=lambda call: call.data.startswith("pix_paid_"))
def solicitar_comprovante_pix(call):
    try:
        if not is_chat_privado(call.message):
            orientar_uso_no_privado(call.message)
            return
        order_nsu = call.data[len("pix_paid_"):].strip()
        pedido = pedidos_col.find_one({"order_nsu": order_nsu})

        if not pedido or str(pedido.get("user_id")) != str(call.from_user.id):
            safe_answer_callback(call.id, text="Pedido inválido.", show_alert=True)
            return

        if pedido.get("status") == "paid":
            safe_answer_callback(call.id, text="Este pedido já foi aprovado.", show_alert=True)
            return

        if pedido.get("status") == "receipt_submitted":
            safe_answer_callback(
                call.id,
                text="Seu comprovante já está aguardando conferência.",
                show_alert=True,
            )
            return

        if pedido.get("status") != "awaiting_pix":
            safe_answer_callback(call.id, text="Este pedido não está disponível.", show_alert=True)
            return

        if pedido_pix_expirado(pedido):
            pedidos_col.update_one(
                {"order_nsu": order_nsu, "status": "awaiting_pix"},
                {"$set": {"status": "expired", "expired_at": agora_tz()}},
            )
            safe_answer_callback(
                call.id,
                text="Este pedido expirou. Escolha o plano novamente.",
                show_alert=True,
            )
            return

        agora = agora_tz()
        resultado = pedidos_col.update_one(
            {"order_nsu": order_nsu, "status": "awaiting_pix"},
            {"$set": {
                "receipt_requested_at": agora,
                "payment_verification_status": "waiting_receipt_upload",
                "expires_at": agora + timedelta(hours=PIX_ORDER_EXPIRATION_HOURS),
            }},
        )
        if not resultado.modified_count:
            safe_answer_callback(
                call.id,
                text="O pedido mudou de estado. Abra os planos novamente.",
                show_alert=True,
            )
            return
        obter_usuario(call.from_user.id)
        usuarios_col.update_one(
            {"_id": str(call.from_user.id)},
            {"$set": {"pix_order_aguardando_comprovante": order_nsu}},
        )
        safe_send_message(
            call.message.chat.id,
            "📎 Agora envie aqui a imagem ou o PDF do comprovante do Pix.\n\n"
            f"Pedido: `{order_nsu}`",
            parse_mode="Markdown",
        )
        safe_answer_callback(call.id, text="Envie o comprovante no chat.")
    except Exception as e:
        logger.error(
            f"[PIX_SOLICITAR_COMPROVANTE] erro={sanitizar_erro_log(e)}"
        )
        safe_answer_callback(call.id, text="Erro ao abrir o envio do comprovante.", show_alert=True)


@bot.message_handler(content_types=["photo", "document"])
def receber_comprovante_pix(message):
    try:
        if not is_chat_privado(message):
            orientar_uso_no_privado(message)
            return

        user = obter_usuario(message.from_user.id)
        order_nsu = str(user.get("pix_order_aguardando_comprovante") or "").strip()
        if not order_nsu:
            return

        pedido = pedidos_col.find_one({"order_nsu": order_nsu})
        if (
            not pedido
            or str(pedido.get("user_id")) != str(message.from_user.id)
            or pedido.get("status") != "awaiting_pix"
            or pedido_pix_expirado(pedido)
        ):
            usuarios_col.update_one(
                {"_id": str(message.from_user.id)},
                {"$unset": {"pix_order_aguardando_comprovante": ""}},
            )
            safe_send_message(message.chat.id, "❌ Esse pedido não está mais aguardando comprovante.")
            return

        tipo = None
        file_id = None
        if getattr(message, "photo", None):
            tipo = "photo"
            file_id = message.photo[-1].file_id
        elif getattr(message, "document", None):
            mime = str(getattr(message.document, "mime_type", "") or "").lower()
            if mime not in ("application/pdf", "image/jpeg", "image/png", "image/webp"):
                safe_send_message(message.chat.id, "❌ Envie o comprovante como imagem ou PDF.")
                return
            tipo = "document"
            file_id = message.document.file_id

        if not file_id:
            safe_send_message(message.chat.id, "❌ Não consegui ler esse comprovante.")
            return

        comprovante_entregue = False
        try:
            bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
            comprovante_entregue = True
        except Exception as e:
            logger.warning(
                f"[PIX_FORWARD_RECEIPT] pedido_ref={referencia_pedido_log(order_nsu)} "
                f"erro={sanitizar_erro_log(e)}"
            )
            try:
                if tipo == "photo":
                    bot.send_photo(ADMIN_ID, file_id, caption=f"Comprovante do pedido {order_nsu}")
                else:
                    bot.send_document(ADMIN_ID, file_id, caption=f"Comprovante do pedido {order_nsu}")
                comprovante_entregue = True
            except Exception as envio_erro:
                logger.error(
                    f"[PIX_SEND_RECEIPT] pedido_ref={referencia_pedido_log(order_nsu)} "
                    f"erro={sanitizar_erro_log(envio_erro)}"
                )

        if not comprovante_entregue:
            safe_send_message(
                message.chat.id,
                "❌ Não consegui entregar o comprovante ao responsável. "
                "Tente enviá-lo novamente em instantes.",
            )
            return

        plano = PLANOS.get(pedido.get("plano_key")) or {}
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton(
                "✅ Aprovar — confirmei o Pix na conta",
                callback_data=f"pix_ok_{order_nsu}",
            ),
            types.InlineKeyboardButton(
                "❌ Rejeitar comprovante",
                callback_data=f"pix_no_{order_nsu}",
            ),
        )
        controle = safe_send_message(
            ADMIN_ID,
            "💠 <b>Comprovante Pix aguardando conferência</b>\n\n"
            f"Pedido: <code>{html.escape(order_nsu)}</code>\n"
            f"Usuário: <code>{html.escape(str(pedido.get('user_id')))}</code>\n"
            f"Plano: <b>{html.escape(plano.get('nome') or pedido.get('plano_nome') or 'Desconhecido')}</b>\n"
            f"Valor esperado: <b>R$ {int(pedido.get('valor_centavos') or 0) / 100:.2f}</b>\n\n"
            "⚠️ O comprovante sozinho não confirma o pagamento. Antes de aprovar, "
            f"confira se o Pix entrou na conta da instituição "
            f"<b>{html.escape(PIX_RECEIVER_BANK)}</b>.",
            parse_mode="HTML",
            reply_markup=markup,
        )

        if not controle:
            safe_send_message(
                message.chat.id,
                "❌ Não consegui abrir a análise do comprovante. "
                "Tente enviá-lo novamente em instantes.",
            )
            return

        agora = agora_tz()
        resultado = pedidos_col.update_one(
            {"order_nsu": order_nsu, "status": "awaiting_pix"},
            {
                "$set": {
                    "status": "receipt_submitted",
                    "payment_verification_status": "manual_review_pending",
                    "receipt_submitted_at": agora,
                    "receipt_telegram_file_id": file_id,
                    "receipt_telegram_type": tipo,
                    "receipt_source_chat_id": message.chat.id,
                    "receipt_source_message_id": message.message_id,
                    "admin_review_message_id": controle.message_id,
                },
                "$unset": {"expires_at": ""},
            },
        )
        if not resultado.modified_count:
            safe_delete_message(ADMIN_ID, controle.message_id)
            safe_send_message(
                message.chat.id,
                "❌ O estado desse pedido mudou. Abra os planos e tente novamente.",
            )
            return

        usuarios_col.update_one(
            {"_id": str(message.from_user.id), "pix_order_aguardando_comprovante": order_nsu},
            {"$unset": {"pix_order_aguardando_comprovante": ""}},
        )

        safe_send_message(
            message.chat.id,
            "✅ Comprovante recebido! O pagamento será conferido e você será avisado aqui.",
        )
    except Exception as e:
        logger.error(
            "[PIX_RECEBER_COMPROVANTE] "
            f"user_ref={referencia_usuario_log(message.from_user.id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        safe_send_message(message.chat.id, "❌ Não consegui registrar o comprovante. Tente novamente.")


@bot.callback_query_handler(func=lambda call: call.data.startswith(("pix_ok_", "pix_no_")))
def revisar_comprovante_pix(call):
    if (
        call.from_user.id != ADMIN_ID
        or not is_chat_privado(call.message)
        or call.message.chat.id != ADMIN_ID
    ):
        safe_answer_callback(call.id, text="Acesso restrito ao administrador.", show_alert=True)
        return

    aprovar = call.data.startswith("pix_ok_")
    prefixo = "pix_ok_" if aprovar else "pix_no_"
    order_nsu = call.data[len(prefixo):].strip()
    lock_pedido = obter_lock_distribuido_local(order_nsu, PAYMENT_ORDER_LOCKS)

    try:
        with lock_pedido:
            pedido = pedidos_col.find_one({"order_nsu": order_nsu})
            if not pedido:
                safe_answer_callback(call.id, text="Pedido não encontrado.", show_alert=True)
                return
            if pedido.get("status") == "paid":
                safe_answer_callback(call.id, text="Pedido já aprovado.", show_alert=True)
                return

            estados_permitidos = (
                ("receipt_submitted", "approving")
                if aprovar
                else ("receipt_submitted",)
            )
            if pedido.get("status") not in estados_permitidos:
                safe_answer_callback(
                    call.id,
                    text="Este pedido não está aguardando análise.",
                    show_alert=True,
                )
                return

            plano = PLANOS.get(pedido.get("plano_key")) or {}
            if not plano:
                safe_answer_callback(call.id, text="Plano do pedido é inválido.", show_alert=True)
                return

            if aprovar:
                if pedido.get("status") == "receipt_submitted":
                    agora = agora_tz()
                    resultado_inicio = pedidos_col.update_one(
                        {
                            "order_nsu": order_nsu,
                            "status": "receipt_submitted",
                        },
                        {
                            "$set": {
                                "status": "approving",
                                "payment_verification_status": (
                                    "manual_approval_processing"
                                ),
                                "approval_started_at": agora,
                                "manual_verified_by": str(ADMIN_ID),
                                "manual_verified_at": agora,
                            },
                            "$unset": {"expires_at": ""},
                        },
                    )
                    if not resultado_inicio.modified_count:
                        pedido_atual = pedidos_col.find_one(
                            {"order_nsu": order_nsu}
                        ) or {}
                        if pedido_atual.get("status") not in (
                            "approving",
                            "paid",
                        ):
                            safe_answer_callback(
                                call.id,
                                text=(
                                    "O pedido mudou de estado. Atualize o painel."
                                ),
                                show_alert=True,
                            )
                            return

                aprovacao = finalizar_aprovacao_pix_em_processamento(order_nsu)
                vip_ate = aprovacao["vip_ate"]
                pedido_final = aprovacao["pedido"]

                if aprovacao["finalizado_agora"]:
                    notificar_pagamento_confirmado(
                        pedido_final["user_id"], plano["nome"], vip_ate
                    )
                safe_edit_message(
                    call.message.chat.id,
                    call.message.message_id,
                    "✅ Pagamento Pix conferido e VIP liberado.\n"
                    f"Pedido: `{order_nsu}`\n"
                    f"VIP até: *{formatar_validade_vip(vip_ate)}*",
                    parse_mode="Markdown",
                )
                safe_answer_callback(call.id, text="VIP liberado com sucesso.")
                logger.info(
                    f"[PIX_MANUAL_APROVADO] pedido_ref={referencia_pedido_log(order_nsu)} "
                    f"user_ref={referencia_usuario_log(pedido_final['user_id'])} "
                    f"vip_ate={vip_ate} "
                    f"recuperado={pedido.get('status') == 'approving'}"
                )
            else:
                agora = agora_tz()
                resultado_rejeicao = pedidos_col.update_one(
                    {"order_nsu": order_nsu, "status": "receipt_submitted"},
                    {
                        "$set": {
                            "status": "awaiting_pix",
                            "payment_verification_status": "manual_receipt_rejected",
                            "receipt_rejected_at": agora,
                            "receipt_rejected_by": str(ADMIN_ID),
                            "expires_at": agora + timedelta(hours=PIX_ORDER_EXPIRATION_HOURS),
                        },
                        "$unset": {
                            "receipt_telegram_file_id": "",
                            "receipt_telegram_type": "",
                        },
                    },
                )
                if not resultado_rejeicao.modified_count:
                    safe_answer_callback(
                        call.id,
                        text="O pedido mudou de estado. Atualize o painel.",
                        show_alert=True,
                    )
                    return
                safe_send_message(
                    int(pedido["user_id"]),
                    "❌ O comprovante não pôde ser confirmado. Confira o pagamento e "
                    "toque novamente em *Já fiz o Pix* para reenviar.",
                    parse_mode="Markdown",
                )
                safe_edit_message(
                    call.message.chat.id,
                    call.message.message_id,
                    "❌ Comprovante rejeitado.\n"
                    f"Pedido: `{order_nsu}`",
                    parse_mode="Markdown",
                )
                safe_answer_callback(call.id, text="Comprovante rejeitado.")
                logger.info(
                    "[PIX_MANUAL_REJEITADO] "
                    f"pedido_ref={referencia_pedido_log(order_nsu)}"
                )
    except Exception as e:
        logger.error(
            f"[PIX_MANUAL_REVISAO] pedido_ref={referencia_pedido_log(order_nsu)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        safe_answer_callback(call.id, text="Erro ao revisar o pagamento.", show_alert=True)


# =========================================
# DOWNLOAD
# =========================================
def formatos_capados_gerais():
    return [
        "bestvideo[ext=mp4][width<=720][height<=1280][fps<=30]+bestaudio[ext=m4a]/best[ext=mp4][width<=720][height<=1280][fps<=30]",
        "bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[width<=720][height<=1280][fps<=30]",
        "best[ext=mp4][width<=720][height<=1280]",
        "best[width<=720][height<=1280]"
    ]


def formatos_por_plataforma(is_tiktok=False, is_instagram=False, is_pinterest=False, is_rednote=False):
    if is_instagram:
        return [
            "best[ext=mp4][vcodec!=none][acodec!=none][width<=720][height<=1280][fps<=30]",
            "best[ext=mp4][vcodec!=none][acodec!=none][width<=720][height<=1280]",
            "bestvideo[ext=mp4][width<=720][height<=1280][fps<=30]+bestaudio[ext=m4a]/best[ext=mp4][width<=720][height<=1280][fps<=30]",
            "bestvideo[ext=mp4][width<=720][height<=1280]+bestaudio[ext=m4a]/best[ext=mp4][width<=720][height<=1280]",
            "best[ext=mp4][vcodec!=none][acodec!=none]",
            "best[vcodec!=none][acodec!=none]",
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]",
            "best[ext=mp4]/best"
        ]

    if is_pinterest:
        return [
            "bestvideo[ext=mp4][width<=720][height<=1280][fps<=30]+bestaudio[ext=m4a]/bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[ext=mp4][width<=720][height<=1280][fps<=30]/best[width<=720][height<=1280][fps<=30]",
            "bestvideo[ext=mp4][width<=720][height<=1280]+bestaudio[ext=m4a]/bestvideo[width<=720][height<=1280]+bestaudio/best[ext=mp4][width<=720][height<=1280]/best[width<=720][height<=1280]",
            "best[ext=mp4][width<=720][height<=1280][fps<=30]",
            "best[ext=mp4][width<=720][height<=1280]",
            "best[width<=720][height<=1280][fps<=30]",
            "best[width<=720][height<=1280]"
        ]

    if is_tiktok:
        # A fonte HD sem marca não informa resolução antes do download. Baixa
        # a melhor variante e o pipeline de mídia aplica depois o limite
        # uniforme de 720x1280 e 30 fps.
        return ["best[ext=mp4]/best"] + formatos_capados_gerais()

    if is_rednote:
        return formatos_capados_gerais() + [
            "best[ext=mp4]/best"
        ]

    return formatos_capados_gerais()


def _processar_download(message, url, status_msg, reserva_download=None):
    atualizar_heartbeat_worker("preparando")
    prefix = None
    plataforma = nome_plataforma(*detectar_plataforma(url))

    try:
        try:
            user = obter_usuario(message.from_user.id)
        except Exception as e:
            raise FalhaComponenteDownload(
                "MongoDB",
                e,
                ja_registrada=True,
            ) from e
        vip_status = is_vip_user(user)

        if status_msg:
            safe_edit_message(
                message.chat.id,
                status_msg.message_id,
                "🔄 Processando seu vídeo...",
            )

        atualizar_heartbeat_worker("resolvendo_link")
        try:
            url = resolver_url_compartilhada(url)
        except Exception as e:
            raise FalhaComponenteDownload(plataforma, e) from e
        is_pinterest, is_tiktok, is_instagram, is_rednote = detectar_plataforma(url)
        plataforma = nome_plataforma(is_pinterest, is_tiktok, is_instagram, is_rednote)

        if is_instagram:
            url = normalizar_url_instagram(url)

        logger.info(
            f"[DOWNLOAD_INICIO] user_ref={referencia_usuario_log(message.from_user.id)} "
            f"plataforma={plataforma} url_ref={referencia_url_log(url)}"
        )

        if not (is_pinterest or is_tiktok or is_instagram or is_rednote):
            texto_nao_reconhecido = "❌ Link não reconhecido. Envie um link do TikTok, Pinterest, Instagram ou RedNote."
            if status_msg:
                safe_edit_message(message.chat.id, status_msg.message_id, texto_nao_reconhecido)
            else:
                safe_send_message(message.chat.id, texto_nao_reconhecido)
            return

        if is_pinterest:
            prefix = os.path.join(DOWNLOAD_DIR, f"v_{uuid.uuid4().hex}")
            try:
                url_resolvida = resolver_link_pinterest(url)
            except Exception as e:
                raise FalhaComponenteDownload(plataforma, e) from e
            info = None
            cache_key = None
            cache_source_id = None
            url_cache_key, url_normalizada = montar_chave_cache_url(
                plataforma, url_resolvida
            )

            entrada_cache_url = obter_entrada_cache(url_cache_key)
            tipo_cache_url = (
                enviar_midia_cacheada(
                    message.chat.id,
                    url_cache_key,
                    entrada_cache_url,
                )
                if entrada_cache_url
                else None
            )
            if tipo_cache_url:
                registrar_download_diario(
                    vip_status,
                    tipo_entrega="cache_url",
                    admin_status=message.from_user.id == ADMIN_ID,
                )
                if reserva_download:
                    confirmar_download_gratis(
                        reserva_download,
                        message.from_user.id,
                        message.chat.id,
                        message.from_user.id,
                    )
                if status_msg:
                    safe_delete_message(message.chat.id, status_msg.message_id)
                return

            try:
                atualizar_heartbeat_worker("consultando_metadados")
                with yt_dlp.YoutubeDL(montar_info_opts(is_pinterest=True)) as ydl:
                    info = ydl.extract_info(url_resolvida, download=False)

                duracao = info.get("duration")
                logger.info(
                    "[META] plataforma=Pinterest "
                    f"user_ref={referencia_usuario_log(message.from_user.id)} "
                    f"duration={duracao}"
                )

                if duracao and duracao > MAX_DURATION_SECONDS:
                    texto = f"⚠️ Vídeo muito longo. O limite é de {MAX_DURATION_SECONDS} segundos."
                    if status_msg:
                        safe_edit_message(message.chat.id, status_msg.message_id, texto)
                    else:
                        safe_send_message(message.chat.id, texto)
                    return

                cache_key, cache_source_id = montar_chave_cache_midia(
                    plataforma, info, url_resolvida
                )
                entrada_cache = obter_entrada_cache(cache_key)
                tipo_cache = (
                    enviar_midia_cacheada(
                        message.chat.id,
                        cache_key,
                        entrada_cache,
                    )
                    if entrada_cache
                    else None
                )
                if tipo_cache:
                    salvar_file_id_cache(
                        cache_key,
                        cache_source_id,
                        plataforma,
                        entrada_cache["telegram_file_id"],
                        tipo_cache,
                        url_cache_key=url_cache_key,
                        url_normalizada=url_normalizada,
                    )
                    registrar_download_diario(
                        vip_status,
                        tipo_entrega="cache_midia",
                        admin_status=message.from_user.id == ADMIN_ID,
                    )
                    if reserva_download:
                        confirmar_download_gratis(
                            reserva_download,
                            message.from_user.id,
                            message.chat.id,
                            message.from_user.id,
                        )
                    if status_msg:
                        safe_delete_message(message.chat.id, status_msg.message_id)
                    return

            except CacheTelegramTemporariamenteIndisponivel:
                raise
            except Exception as e:
                logger.warning(
                    "[PINTEREST_INFO] Falha ao ler metadados: "
                    f"{sanitizar_erro_log(e)}"
                )

            espaco_ok, _livre_bytes = garantir_espaco_para_novo_download()
            if not espaco_ok:
                informar_download_pausado_por_espaco(message, status_msg)
                return

            try:
                atualizar_heartbeat_worker("baixando")
                try:
                    arquivo_final = baixar_pinterest_capado(
                        url_resolvida,
                        prefix,
                        info=info,
                    )
                except FalhaComponenteDownload:
                    raise
                except Exception as e:
                    raise FalhaComponenteDownload(plataforma, e) from e
                registrar_sucesso_plataforma(plataforma)
                validar_arquivo_midia(
                    arquivo_final,
                    MAX_SOURCE_FILE_BYTES,
                    fase="download_pinterest",
                )
                arquivo_envio = preparar_arquivo_para_envio(
                    arquivo_final,
                    plataforma=plataforma,
                )
                validar_arquivo_midia(
                    arquivo_envio,
                    MAX_OUTPUT_FILE_BYTES,
                    fase="envio_pinterest",
                )
                registrar_sucesso_componente("Processamento")

                (
                    enviado,
                    telegram_file_id,
                    telegram_media_type,
                    bytes_upload,
                ) = enviar_arquivo_com_fallback(message.chat.id, arquivo_envio)
                if not enviado:
                    raise Exception("Falha ao enviar arquivo ao Telegram")

                if cache_key is None:
                    cache_key, cache_source_id = montar_chave_cache_midia(
                        plataforma, info, url_resolvida
                    )
                salvar_file_id_cache(
                    cache_key,
                    cache_source_id,
                    plataforma,
                    telegram_file_id,
                    telegram_media_type,
                    url_cache_key=url_cache_key,
                    url_normalizada=url_normalizada,
                )

                registrar_download_diario(
                    vip_status,
                    tipo_entrega="upload",
                    bytes_upload=bytes_upload,
                    admin_status=message.from_user.id == ADMIN_ID,
                )
                if reserva_download:
                    confirmar_download_gratis(
                        reserva_download,
                        message.from_user.id,
                        message.chat.id,
                        message.from_user.id,
                    )

                if status_msg:
                    safe_delete_message(message.chat.id, status_msg.message_id)

                return

            except FalhaComponenteDownload as e:
                if not e.ja_registrada:
                    registrar_falha_componente(e.componente, e.erro_original)
                logger.error(
                    f"[ERRO_PINTEREST] user_ref={referencia_usuario_log(message.from_user.id)} "
                    f"origem={e.componente} url_ref={referencia_url_log(url)} "
                    f"erro={sanitizar_erro_log(e.erro_original)}"
                )
                texto_erro = mapear_falha_componente_download(
                    e.componente,
                    e.erro_original,
                    plataforma="pinterest",
                )

                if status_msg:
                    safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
                else:
                    safe_send_message(message.chat.id, texto_erro)

                if prefix:
                    cleanup_prefix(prefix)
                return
            except Exception as e:
                registrar_falha_componente("Interno", e)
                logger.error(
                    f"[ERRO_PINTEREST] user_ref={referencia_usuario_log(message.from_user.id)} "
                    f"origem=Interno url_ref={referencia_url_log(url)} "
                    f"erro={sanitizar_erro_log(e)}"
                )
                texto_erro = mapear_erro_download(str(e), plataforma="pinterest")
                if status_msg:
                    safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
                else:
                    safe_send_message(message.chat.id, texto_erro)
                if prefix:
                    cleanup_prefix(prefix)
                return

        url_cache_key, url_normalizada = montar_chave_cache_url(plataforma, url)
        entrada_cache_url = obter_entrada_cache(url_cache_key)
        tipo_cache_url = (
            enviar_midia_cacheada(
                message.chat.id,
                url_cache_key,
                entrada_cache_url,
            )
            if entrada_cache_url
            else None
        )
        if tipo_cache_url:
            registrar_download_diario(
                vip_status,
                tipo_entrega="cache_url",
                admin_status=message.from_user.id == ADMIN_ID,
            )
            if reserva_download:
                confirmar_download_gratis(
                    reserva_download,
                    message.from_user.id,
                    message.chat.id,
                    message.from_user.id,
                )
            if status_msg:
                safe_delete_message(message.chat.id, status_msg.message_id)
            return

        prefix = os.path.join(DOWNLOAD_DIR, f"v_{uuid.uuid4().hex}")

        usar_cookies_plataforma = True
        tiktok_extractor_args_usados = None
        atualizar_heartbeat_worker("consultando_metadados")
        try:
            if is_instagram:
                info, usar_cookies_plataforma = extrair_info_instagram_com_fallback(url)
            elif is_tiktok:
                (
                    info,
                    usar_cookies_plataforma,
                    tiktok_extractor_args_usados,
                ) = extrair_info_tiktok_com_fallback(url)
            else:
                with yt_dlp.YoutubeDL(montar_info_opts()) as ydl:
                    info = ydl.extract_info(url, download=False)
        except FalhaComponenteDownload:
            raise
        except Exception as e:
            raise FalhaComponenteDownload(plataforma, e) from e

        audio_instagram_esperado = None
        if is_instagram:
            audio_instagram_esperado = info_instagram_indica_audio(info)
            logger.info(
                "[INSTAGRAM_AUDIO_INFO] "
                f"audio_disponivel={audio_instagram_esperado}"
            )

        duracao = info.get("duration")
        logger.info(
            f"[META] plataforma={plataforma} "
            f"user_ref={referencia_usuario_log(message.from_user.id)} "
            f"duration={duracao}"
        )

        if duracao and duracao > MAX_DURATION_SECONDS:
            texto = f"⚠️ Vídeo muito longo. O limite é de {MAX_DURATION_SECONDS} segundos."
            if status_msg:
                safe_edit_message(message.chat.id, status_msg.message_id, texto)
            else:
                safe_send_message(message.chat.id, texto)
            return

        cache_key, cache_source_id = montar_chave_cache_midia(plataforma, info, url)
        entrada_cache = obter_entrada_cache(cache_key)
        tipo_cache = (
            enviar_midia_cacheada(
                message.chat.id,
                cache_key,
                entrada_cache,
            )
            if entrada_cache
            else None
        )
        if tipo_cache:
            salvar_file_id_cache(
                cache_key,
                cache_source_id,
                plataforma,
                entrada_cache["telegram_file_id"],
                tipo_cache,
                url_cache_key=url_cache_key,
                url_normalizada=url_normalizada,
            )
            registrar_download_diario(
                vip_status,
                tipo_entrega="cache_midia",
                admin_status=message.from_user.id == ADMIN_ID,
            )
            if reserva_download:
                confirmar_download_gratis(
                    reserva_download,
                    message.from_user.id,
                    message.chat.id,
                    message.from_user.id,
                )
            if status_msg:
                safe_delete_message(message.chat.id, status_msg.message_id)
            return

        espaco_ok, _livre_bytes = garantir_espaco_para_novo_download()
        if not espaco_ok:
            informar_download_pausado_por_espaco(message, status_msg)
            return

        formatos = formatos_por_plataforma(
            is_tiktok=is_tiktok,
            is_instagram=is_instagram,
            is_pinterest=is_pinterest,
            is_rednote=is_rednote,
        )
        baixou = False
        ultimo_erro = None

        if is_instagram:
            modos_cookie = [usar_cookies_plataforma]
            if usar_cookies_plataforma and INSTAGRAM_COOKIES_TEXT.strip():
                modos_cookie.append(False)
        elif is_tiktok:
            modos_cookie = [usar_cookies_plataforma]
            if usar_cookies_plataforma:
                modos_cookie.append(False)
        else:
            modos_cookie = [False]

        for usar_cookies in modos_cookie:
            atualizar_heartbeat_worker("baixando")
            common_opts = montar_download_opts(
                prefix,
                is_instagram=is_instagram,
                usar_cookies=usar_cookies,
                is_tiktok=is_tiktok,
                tiktok_extractor_args=tiktok_extractor_args_usados,
            )

            for fmt in formatos:
                try:
                    cleanup_prefix(prefix)

                    opts = common_opts.copy()
                    opts["format"] = fmt

                    # O info bruto já contém as URLs dos formatos. Reutilizá-lo
                    # evita consultar a mesma página antes de cada tentativa.
                    baixar_info_ja_extraida(info, opts)

                    arquivo_baixado = encontrar_arquivo_baixado(prefix)
                    if arquivo_baixado and os.path.exists(arquivo_baixado):
                        if is_instagram and audio_instagram_esperado is not False:
                            info_arquivo_baixado = obter_info_midia(arquivo_baixado)
                            if not arquivo_possui_audio(info_arquivo_baixado):
                                ultimo_erro = (
                                    "INSTAGRAM_AUDIO_AUSENTE_NO_ARQUIVO "
                                    f"metadata={audio_instagram_esperado}"
                                )
                                logger.warning(
                                    "[INSTAGRAM_AUDIO_RETRY] "
                                    f"audio_esperado={audio_instagram_esperado} "
                                    f"formato={fmt} "
                                    f"arquivo_ref={referencia_arquivo_log(arquivo_baixado)}"
                                )
                                cleanup_prefix(prefix)
                                continue
                        baixou = True
                        break

                except FalhaComponenteDownload:
                    raise
                except Exception as e:
                    ultimo_erro = str(e)
                    logger.warning(
                        f"[DOWNLOAD_TENTATIVA] plataforma={plataforma} "
                        f"usar_cookies={usar_cookies} formato={fmt} "
                        f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
                    )

            if baixou:
                break

        if not baixou:
            raise FalhaComponenteDownload(
                plataforma,
                ultimo_erro or "Falha ao baixar dentro do limite 720x1280 30fps",
            )

        registrar_sucesso_plataforma(plataforma)

        arquivo_final = encontrar_arquivo_baixado(prefix)
        if not arquivo_final or not os.path.exists(arquivo_final):
            raise FalhaComponenteDownload(
                "Armazenamento",
                "Arquivo final não encontrado após o download",
            )

        validar_arquivo_midia(
            arquivo_final,
            MAX_SOURCE_FILE_BYTES,
            fase="download",
        )
        arquivo_envio = preparar_arquivo_para_envio(arquivo_final, plataforma=plataforma)
        validar_arquivo_midia(
            arquivo_envio,
            MAX_OUTPUT_FILE_BYTES,
            fase="envio",
        )
        registrar_sucesso_componente("Processamento")

        (
            enviado,
            telegram_file_id,
            telegram_media_type,
            bytes_upload,
        ) = enviar_arquivo_com_fallback(message.chat.id, arquivo_envio)
        if not enviado:
            raise Exception("Falha ao enviar arquivo ao Telegram")

        salvar_file_id_cache(
            cache_key,
            cache_source_id,
            plataforma,
            telegram_file_id,
            telegram_media_type,
            url_cache_key=url_cache_key,
            url_normalizada=url_normalizada,
        )

        registrar_download_diario(
            vip_status,
            tipo_entrega="upload",
            bytes_upload=bytes_upload,
            admin_status=message.from_user.id == ADMIN_ID,
        )
        if reserva_download:
            confirmar_download_gratis(
                reserva_download,
                message.from_user.id,
                message.chat.id,
                message.from_user.id,
            )

        if status_msg:
            safe_delete_message(message.chat.id, status_msg.message_id)
        registrar_sucesso_componente("Interno")

    except CacheTelegramTemporariamenteIndisponivel as e:
        logger.warning(
            f"[CACHE_MIDIA_TEMPORARIO] user_ref={referencia_usuario_log(message.from_user.id)} "
            f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
        )
        texto_cache_temporario = (
            "⏳ O Telegram está temporariamente indisponível. O vídeo continua "
            "salvo no cache; aguarde alguns instantes e envie o link novamente. "
            "Esta tentativa não consumiu seu limite diário."
        )
        if status_msg:
            safe_edit_message(
                message.chat.id,
                status_msg.message_id,
                texto_cache_temporario,
            )
        else:
            safe_send_message(message.chat.id, texto_cache_temporario)
    except FalhaComponenteDownload as e:
        if not e.ja_registrada:
            registrar_falha_componente(e.componente, e.erro_original)
        logger.error(
            f"[ERRO_DOWNLOAD] user_ref={referencia_usuario_log(message.from_user.id)} "
            f"origem={e.componente} url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e.erro_original)}"
        )
        url_erro = (url or "").lower()
        if "instagram.com" in url_erro or "instagr.am" in url_erro:
            plataforma_erro = "instagram"
        elif "tiktok.com" in url_erro:
            plataforma_erro = "tiktok"
        else:
            plataforma_erro = "geral"
        texto_erro = mapear_falha_componente_download(
            e.componente,
            e.erro_original,
            plataforma=plataforma_erro,
        )
        if status_msg:
            safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
        else:
            safe_send_message(message.chat.id, texto_erro)
    except Exception as e:
        registrar_falha_componente("Interno", e)
        logger.error(
            f"[ERRO_DOWNLOAD] user_ref={referencia_usuario_log(message.from_user.id)} "
            f"origem=Interno url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        url_erro = (url or "").lower()
        if "instagram.com" in url_erro or "instagr.am" in url_erro:
            plataforma_erro = "instagram"
        elif "tiktok.com" in url_erro:
            plataforma_erro = "tiktok"
        else:
            plataforma_erro = "geral"
        texto_erro = mapear_erro_download(str(e), plataforma=plataforma_erro)

        if status_msg:
            safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
        else:
            safe_send_message(message.chat.id, texto_erro)

    finally:
        if prefix:
            cleanup_prefix(prefix)


def registrar_trabalho_fila_persistente(user_id):
    """Salva só o necessário para avisar após uma queda; nunca salva o link."""
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        resultado = fila_recuperacao_col.update_one(
            {
                "_id": str(user_id),
                "$or": [
                    {"instance_id": APP_INSTANCE_ID},
                    {"instance_id": {"$exists": False}},
                    {"expires_at": {"$lte": agora}},
                ],
            },
            {
                "$set": {
                    "instance_id": APP_INSTANCE_ID,
                    "status": "pending",
                    "queued_at": agora,
                    "updated_at": agora,
                    "expires_at": agora + timedelta(
                        hours=QUEUE_RECOVERY_TTL_HOURS
                    ),
                    "contains_url": False,
                    "contains_message_text": False,
                },
                "$unset": {
                    "recovery_claimed_by": "",
                    "recovery_claimed_at": "",
                },
            },
            upsert=True,
        )
        registrar_sucesso_componente("MongoDB")
        if resultado.modified_count or resultado.upserted_id:
            return True, None
        return False, "em_andamento"
    except Exception as e:
        if getattr(e, "code", None) == 11000:
            logger.info(
                "[FILA_PERSISTENTE_OCUPADA] "
                f"user_ref={referencia_usuario_log(user_id)}"
            )
            return False, "em_andamento"
        registrar_falha_componente("MongoDB", e)
        logger.warning(
            "[FILA_PERSISTENTE_REGISTRO] "
            f"user_ref={referencia_usuario_log(user_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return False, "indisponivel"


def remover_trabalho_fila_persistente(user_id, instance_id=None):
    """Remove somente o registro pertencente a esta execução do bot."""
    filtro = {
        "_id": str(user_id),
        "instance_id": str(instance_id or APP_INSTANCE_ID),
    }
    try:
        fila_recuperacao_col.delete_one(filtro)
        registrar_sucesso_componente("MongoDB")
        return True
    except Exception as e:
        registrar_falha_componente("MongoDB", e)
        logger.warning(
            "[FILA_PERSISTENTE_REMOCAO] "
            f"user_ref={referencia_usuario_log(user_id)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return False


def _filtro_reivindicacao_recuperacao(documento):
    filtro = {
        "_id": documento["_id"],
        "instance_id": documento.get("instance_id"),
        "status": {"$in": ["pending", "recovering"]},
    }
    reivindicacao_anterior = documento.get("recovery_claimed_by")
    if reivindicacao_anterior:
        filtro["recovery_claimed_by"] = reivindicacao_anterior
    else:
        filtro["recovery_claimed_by"] = {"$exists": False}
    return filtro


def recuperar_fila_interrompida():
    """Avisa usuários de outra execução sem restaurar nem armazenar URLs."""
    if SHUTDOWN_EVENT.is_set():
        return 0, 0

    try:
        documentos = list(
            fila_recuperacao_col.find(
                {
                    "instance_id": {"$ne": APP_INSTANCE_ID},
                    "status": {"$in": ["pending", "recovering"]},
                },
                {
                    "_id": 1,
                    "instance_id": 1,
                    "status": 1,
                    "recovery_claimed_by": 1,
                },
            ).limit(DOWNLOAD_QUEUE_MAX * 5)
        )
        registrar_sucesso_componente("MongoDB")
    except Exception as e:
        registrar_falha_componente("MongoDB", e)
        logger.warning(
            f"[FILA_RECUPERACAO_LISTAR] erro={sanitizar_erro_log(e)}"
        )
        return 0, 0

    recuperados = 0
    notificados = 0
    for documento in documentos:
        if SHUTDOWN_EVENT.is_set():
            break

        agora = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            resultado = fila_recuperacao_col.update_one(
                _filtro_reivindicacao_recuperacao(documento),
                {
                    "$set": {
                        "status": "recovering",
                        "recovery_claimed_by": APP_INSTANCE_ID,
                        "recovery_claimed_at": agora,
                        "updated_at": agora,
                    }
                },
            )
            if not resultado.modified_count:
                continue
        except Exception as e:
            registrar_falha_componente("MongoDB", e)
            logger.warning(
                f"[FILA_RECUPERACAO_REIVINDICAR] erro={sanitizar_erro_log(e)}"
            )
            continue

        user_id = str(documento.get("_id") or "")
        if not devolver_reserva_por_instancia(
            user_id,
            documento.get("instance_id"),
        ):
            try:
                fila_recuperacao_col.update_one(
                    {
                        "_id": user_id,
                        "recovery_claimed_by": APP_INSTANCE_ID,
                    },
                    {
                        "$set": {"status": "pending", "updated_at": agora},
                        "$unset": {
                            "recovery_claimed_by": "",
                            "recovery_claimed_at": "",
                        },
                    },
                )
            except Exception as e:
                logger.warning(
                    "[FILA_RECUPERACAO_LIMITE] "
                    f"erro={sanitizar_erro_log(e)}"
                )
            continue

        recuperados += 1

        enviado = False
        try:
            enviado = bool(
                safe_send_message(
                    int(user_id),
                    "⚠️ O bot foi reiniciado enquanto seu vídeo estava na "
                    "fila ou em processamento.\n\n"
                    "Envie o link novamente. A tentativa interrompida não "
                    "consumiu seu limite diário de downloads.",
                )
            )
        except (TypeError, ValueError):
            logger.warning("[FILA_RECUPERACAO] identificador inválido")

        try:
            fila_recuperacao_col.delete_one(
                {
                    "_id": user_id,
                    "recovery_claimed_by": APP_INSTANCE_ID,
                }
            )
            if enviado:
                notificados += 1
            registrar_sucesso_componente("MongoDB")
        except Exception as e:
            registrar_falha_componente("MongoDB", e)
            logger.warning(
                f"[FILA_RECUPERACAO_FINALIZAR] erro={sanitizar_erro_log(e)}"
            )

    if recuperados:
        safe_send_message(
            ADMIN_ID,
            "🔄 <b>Recuperação da fila concluída</b>\n\n"
            f"Registros interrompidos: <b>{recuperados}</b>\n"
            f"Usuários avisados: <b>{notificados}</b>\n\n"
            "Nenhum link de vídeo foi armazenado.",
            parse_mode="HTML",
        )
    logger.info(
        f"[FILA_RECUPERACAO] recuperados={recuperados} "
        f"notificados={notificados}"
    )
    return recuperados, notificados


def mensagem_desligamento_para_usuario(em_processamento=False):
    if em_processamento:
        situacao = "O processamento do seu vídeo ainda estava ativo e precisou ser interrompido."
    else:
        situacao = "Seu vídeo ainda estava aguardando na fila."
    return (
        "🔄 O bot está concluindo uma atualização.\n\n"
        f"{situacao} Aguarde alguns instantes e envie o link novamente. "
        "Esta tentativa não consumiu seu limite diário de downloads."
    )


def cancelar_trabalho_aguardando_desligamento(trabalho):
    """Retira um item ainda não iniciado e avisa o usuário uma única vez."""
    message = trabalho.get("message") or None
    status_msg = trabalho.get("status_msg")
    user_id = str(getattr(getattr(message, "from_user", None), "id", "") or "")
    chat_id = getattr(getattr(message, "chat", None), "id", None)
    texto = mensagem_desligamento_para_usuario(em_processamento=False)
    notificado = False

    if chat_id is not None and status_msg is not None:
        mensagem_editada = safe_edit_message(
            chat_id,
            getattr(status_msg, "message_id", None),
            texto,
        )
        notificado = bool(mensagem_editada)
    if chat_id is not None and not notificado:
        notificado = bool(safe_send_message(chat_id, texto))

    if user_id:
        with DOWNLOAD_PENDING_LOCK:
            DOWNLOAD_PENDING_USERS.discard(user_id)
        devolver_reserva_download_gratis(
            trabalho.get("download_reservation"),
            user_id,
            motivo="deploy_fila",
        )
        if trabalho.get("persistent_recorded"):
            remover_trabalho_fila_persistente(user_id)
    return notificado


def cancelar_fila_aguardando_desligamento():
    """Esvazia somente trabalhos que ainda não começaram a ser processados."""
    cancelados = 0
    notificados = 0
    trabalhos = []
    with DOWNLOAD_QUEUE_STATE_LOCK:
        while True:
            try:
                _prioridade, _sequencia, trabalho = DOWNLOAD_QUEUE.get_nowait()
            except Empty:
                break
            trabalhos.append(trabalho)

    for trabalho in trabalhos:
        try:
            cancelados += 1
            if cancelar_trabalho_aguardando_desligamento(trabalho):
                notificados += 1
        finally:
            DOWNLOAD_QUEUE.task_done()

    logger.info(
        f"[SHUTDOWN_FILA] cancelados={cancelados} notificados={notificados}"
    )
    return cancelados, notificados


def solicitar_desligamento_gracioso(numero_sinal, _frame=None):
    """Inicia a drenagem; o trabalho ativo recebe um prazo para terminar."""
    global SHUTDOWN_SIGNAL, SHUTDOWN_DEADLINE_MONOTONIC
    if SHUTDOWN_EVENT.is_set():
        return False

    SHUTDOWN_SIGNAL = int(numero_sinal) if numero_sinal is not None else None
    SHUTDOWN_DEADLINE_MONOTONIC = (
        time.monotonic() + SHUTDOWN_DRAIN_SECONDS
    )
    SHUTDOWN_EVENT.set()
    atualizar_estado_bot("draining")
    logger.warning(
        f"[SHUTDOWN] solicitado sinal={SHUTDOWN_SIGNAL} "
        f"prazo={SHUTDOWN_DRAIN_SECONDS}s"
    )
    try:
        bot.stop_polling()
    except Exception as e:
        logger.warning(
            f"[SHUTDOWN] falha_ao_parar_polling={sanitizar_erro_log(e)}"
        )
    return True


def registrar_sinais_desligamento():
    signal.signal(signal.SIGTERM, solicitar_desligamento_gracioso)
    signal.signal(signal.SIGINT, solicitar_desligamento_gracioso)


def aguardar_trabalho_ativo_no_desligamento():
    """Espera até o limite da Railway, reservando margem para fechar o processo."""
    prazo_final = SHUTDOWN_DEADLINE_MONOTONIC or (
        time.monotonic() + SHUTDOWN_DRAIN_SECONDS
    )
    limite = max(
        time.monotonic(),
        prazo_final - SHUTDOWN_SAFETY_MARGIN_SECONDS,
    )

    while time.monotonic() < limite:
        saude = obter_saude_worker()
        if not saude["busy"]:
            return True
        time.sleep(0.25)

    if not obter_saude_worker()["busy"]:
        return True

    user_id = obter_usuario_ativo_worker()
    if user_id and not trabalho_ativo_tem_reserva_download():
        enviado = safe_send_message(
            int(user_id),
            mensagem_desligamento_para_usuario(em_processamento=True),
        )
        if enviado:
            remover_trabalho_fila_persistente(user_id)
    return False


def executar_desligamento_gracioso():
    """Cancela a espera, tenta concluir o ativo e libera conexões quando seguro."""
    atualizar_estado_bot("draining")
    cancelados, notificados = cancelar_fila_aguardando_desligamento()
    concluido = aguardar_trabalho_ativo_no_desligamento()
    encerrar_healthcheck()

    if concluido:
        try:
            client.close()
        except Exception as e:
            logger.warning(
                f"[SHUTDOWN] falha_ao_fechar_mongodb={sanitizar_erro_log(e)}"
            )

    atualizar_estado_bot("stopped")
    logger.info(
        f"[SHUTDOWN] concluido={concluido} fila_cancelada={cancelados} "
        f"fila_notificada={notificados}"
    )
    return {
        "trabalho_ativo_concluido": concluido,
        "fila_cancelada": cancelados,
        "fila_notificada": notificados,
    }


def loop_fila_downloads():
    logger.info(f"[DOWNLOAD_QUEUE] worker iniciado capacidade={DOWNLOAD_QUEUE_MAX}")
    definir_estado_worker_download(True)
    try:
        while not SHUTDOWN_EVENT.is_set():
            _prioridade, _sequencia, trabalho = DOWNLOAD_QUEUE.get()
            if SHUTDOWN_EVENT.is_set():
                cancelar_trabalho_aguardando_desligamento(trabalho)
                DOWNLOAD_QUEUE.task_done()
                break

            message = trabalho["message"]
            user_id = str(message.from_user.id)
            reserva_download = trabalho.get("download_reservation")
            iniciar_trabalho_worker(
                user_id,
                has_download_reservation=bool(reserva_download),
            )
            try:
                _processar_download(
                    message,
                    trabalho["url"],
                    trabalho.get("status_msg"),
                    reserva_download,
                )
            except Exception as e:
                logger.error(
                    f"[DOWNLOAD_WORKER] user_ref={referencia_usuario_log(user_id)} "
                    f"erro={sanitizar_erro_log(e)}"
                )
                safe_send_message(
                    message.chat.id,
                    "❌ Não consegui processar esse vídeo agora. Tente novamente em instantes.",
                )
            finally:
                devolver_reserva_download_gratis(
                    reserva_download,
                    user_id,
                    motivo="worker_finalizado_sem_entrega",
                )
                if trabalho.get("persistent_recorded"):
                    remover_trabalho_fila_persistente(user_id)
                with DOWNLOAD_PENDING_LOCK:
                    DOWNLOAD_PENDING_USERS.discard(user_id)
                concluir_trabalho_worker()
                DOWNLOAD_QUEUE.task_done()
    finally:
        definir_estado_worker_download(False)
        if SHUTDOWN_EVENT.is_set():
            logger.info("[DOWNLOAD_QUEUE] worker encerrado durante drenagem")
        else:
            logger.error("[DOWNLOAD_QUEUE] worker encerrado inesperadamente")
            safe_send_message(
                ADMIN_ID,
                "❌ <b>Worker de downloads encerrado</b>\n\n"
                "O processo principal continua ativo, mas a fila não será "
                "processada até o serviço ser reiniciado.",
                parse_mode="HTML",
            )


@bot.message_handler(func=lambda message: message.text and "http" in message.text.lower())
def handle_download(message):
    if not is_chat_privado(message):
        orientar_uso_no_privado(message)
        return

    if SHUTDOWN_EVENT.is_set():
        safe_reply_to(
            message,
            "🔄 O bot está concluindo uma atualização. Aguarde alguns "
            "instantes e envie o link novamente.",
        )
        return

    user = obter_usuario(message.from_user.id)
    vip_status = is_vip_user(user)

    url = extrair_primeira_url(message.text)
    if not url or not validar_url_http_publica(url, resolver_dns=False):
        safe_reply_to(message, "❌ Não encontrei um link válido na sua mensagem.")
        return

    if not any(detectar_plataforma(url)):
        safe_reply_to(
            message,
            "❌ Link não reconhecido. Envie um link do TikTok, Pinterest, "
            "Instagram ou RedNote.",
        )
        return

    user_id = str(message.from_user.id)
    with DOWNLOAD_PENDING_LOCK:
        if user_id in DOWNLOAD_PENDING_USERS:
            safe_reply_to(
                message,
                "⏳ Seu vídeo anterior ainda está na fila. Aguarde a conclusão antes "
                "de enviar outro link.",
            )
            return
        if DOWNLOAD_QUEUE.full():
            safe_reply_to(
                message,
                "⏳ A fila está cheia neste momento. Aguarde um pouco e tente novamente.",
            )
            return

    autorizado, mensagem_limite = autorizar_tentativa_download(message.from_user.id)
    if not autorizado:
        safe_reply_to(message, mensagem_limite)
        return

    recusado_desligamento = False
    duplicado = False
    fila_ficou_cheia = False
    with DOWNLOAD_QUEUE_STATE_LOCK:
        if SHUTDOWN_EVENT.is_set():
            recusado_desligamento = True
        else:
            with DOWNLOAD_PENDING_LOCK:
                if user_id in DOWNLOAD_PENDING_USERS:
                    duplicado = True
                elif DOWNLOAD_QUEUE.full():
                    fila_ficou_cheia = True
                else:
                    DOWNLOAD_PENDING_USERS.add(user_id)

    if recusado_desligamento:
        safe_reply_to(
            message,
            "🔄 O bot está concluindo uma atualização. Aguarde alguns "
            "instantes e envie o link novamente.",
        )
        return
    if duplicado:
        safe_reply_to(
            message,
            "⏳ Seu vídeo anterior ainda está na fila. Aguarde a conclusão "
            "antes de enviar outro link.",
        )
        return
    if fila_ficou_cheia:
        safe_reply_to(
            message,
            "⏳ A fila está cheia neste momento. Aguarde um pouco e tente novamente.",
        )
        return

    registro_persistido, erro_registro = registrar_trabalho_fila_persistente(
        user_id
    )
    if not registro_persistido:
        with DOWNLOAD_PENDING_LOCK:
            DOWNLOAD_PENDING_USERS.discard(user_id)
        if erro_registro == "em_andamento":
            safe_reply_to(
                message,
                "⏳ Seu vídeo anterior ainda está na fila ou em processamento. "
                "Aguarde a conclusão antes de enviar outro link.",
            )
        else:
            safe_reply_to(
                message,
                "⏳ O banco de dados está temporariamente indisponível. "
                "Aguarde alguns instantes e tente novamente.",
            )
        return

    reserva_download = None
    if not vip_status:
        reserva_download, erro_reserva = reservar_download_gratis(user_id)
        if not reserva_download:
            with DOWNLOAD_PENDING_LOCK:
                DOWNLOAD_PENDING_USERS.discard(user_id)
            if erro_reserva == "limite":
                remover_trabalho_fila_persistente(user_id)

            if erro_reserva == "limite":
                safe_reply_to(
                    message,
                    f"⚠️ *Limite diário atingido ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT})!*\n"
                    "Para continuar baixando sem limite diário, libere o VIP abaixo: 👇",
                    parse_mode="Markdown",
                )
                mostrar_planos_chat(message.chat.id, message.from_user.id)
            elif erro_reserva == "em_andamento":
                safe_reply_to(
                    message,
                    "⏳ Seu vídeo anterior ainda está na fila ou em processamento. "
                    "Aguarde a conclusão antes de enviar outro link.",
                )
            elif erro_reserva == "indisponivel":
                safe_reply_to(
                    message,
                    "⏳ O banco de dados está temporariamente indisponível. "
                    "Aguarde alguns instantes e tente novamente.",
                )
            else:
                safe_reply_to(
                    message,
                    "⏳ Não consegui reservar sua tentativa agora. Aguarde alguns "
                    "instantes e envie o link novamente.",
                )
            return

    limite_usuario_ok, mensagem_limite_usuario = (
        autorizar_limite_usuario_persistente(user_id)
    )
    if not limite_usuario_ok:
        with DOWNLOAD_PENDING_LOCK:
            DOWNLOAD_PENDING_USERS.discard(user_id)
        devolver_reserva_download_gratis(
            reserva_download,
            user_id,
            motivo="limite_usuario",
        )
        remover_trabalho_fila_persistente(user_id)
        safe_reply_to(message, mensagem_limite_usuario)
        return

    limite_global_ok, mensagem_limite_global = (
        autorizar_limite_global_persistente(user_id)
    )
    if not limite_global_ok:
        with DOWNLOAD_PENDING_LOCK:
            DOWNLOAD_PENDING_USERS.discard(user_id)
        devolver_reserva_download_gratis(
            reserva_download,
            user_id,
            motivo="limite_global",
        )
        remover_trabalho_fila_persistente(user_id)
        safe_reply_to(message, mensagem_limite_global)
        return

    status_msg = safe_reply_to(
        message,
        "💎 Link recebido com prioridade VIP. Aguarde o processamento..."
        if vip_status
        else "⏳ Link recebido. Aguarde o processamento...",
    )

    recusado_desligamento = False
    fila_ficou_cheia = False
    with DOWNLOAD_QUEUE_STATE_LOCK:
        if SHUTDOWN_EVENT.is_set():
            recusado_desligamento = True
        else:
            try:
                DOWNLOAD_QUEUE.put_nowait(
                    (
                        0 if vip_status else 1,
                        next(DOWNLOAD_SEQUENCE),
                        {
                            "message": message,
                            "url": url,
                            "status_msg": status_msg,
                            "persistent_recorded": registro_persistido,
                            "download_reservation": reserva_download,
                        },
                    )
                )
            except Full:
                fila_ficou_cheia = True

    if recusado_desligamento or fila_ficou_cheia:
        with DOWNLOAD_PENDING_LOCK:
            DOWNLOAD_PENDING_USERS.discard(user_id)
        if registro_persistido:
            remover_trabalho_fila_persistente(user_id)
        devolver_reserva_download_gratis(
            reserva_download,
            user_id,
            motivo="fila_nao_aceita",
        )

    if recusado_desligamento:
        texto = (
            "🔄 O bot está concluindo uma atualização. Aguarde alguns "
            "instantes e envie o link novamente."
        )
        if status_msg:
            safe_edit_message(
                message.chat.id,
                status_msg.message_id,
                texto,
            )
        else:
            safe_reply_to(message, texto)
        return

    if fila_ficou_cheia:
        texto = "⏳ A fila ficou cheia. Aguarde um pouco e tente novamente."
        if status_msg:
            safe_edit_message(
                message.chat.id,
                status_msg.message_id,
                texto,
            )
        else:
            safe_reply_to(message, texto)


# =========================================
# HEALTHCHECK
# =========================================
def obter_estado_bot():
    with BOT_STATE_LOCK:
        return BOT_STATE, BOT_LAST_UPDATE_AT


def montar_payload_health():
    estado, ultima_atividade = obter_estado_bot()
    worker = obter_saude_worker()
    encerrando = SHUTDOWN_EVENT.is_set()
    saudavel = (
        not encerrando
        and estado == "polling"
        and worker["running"]
        and not worker["stalled"]
    )
    return {
        "status": "ok" if saudavel else "degraded",
        "service": SERVICE_NAME,
        "bot": estado,
        "accepting_downloads": not encerrando,
        "worker": worker,
        "started_at": APP_STARTED_AT,
        "last_update_at": ultima_atividade,
    }


class HealthRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        caminho = urlparse(self.path).path
        if caminho == "/":
            corpo = b"ONLINE"
            content_type = "text/plain; charset=utf-8"
            status = 200
        elif caminho == "/health":
            corpo = json.dumps(
                montar_payload_health(), ensure_ascii=False
            ).encode("utf-8")
            content_type = "application/json; charset=utf-8"
            # O endpoint é de vida do contêiner. Polling ou worker degradados
            # aparecem no JSON sem provocar ciclos automáticos de reinício.
            status = 200
        else:
            corpo = b"NOT FOUND"
            content_type = "text/plain; charset=utf-8"
            status = 404

        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, _format, *_args):
        return


def servir_healthcheck():
    global HEALTH_SERVER
    porta = int(os.environ.get("PORT", 8080))
    servidor = ThreadingHTTPServer(("0.0.0.0", porta), HealthRequestHandler)
    servidor.daemon_threads = True
    with HEALTH_SERVER_LOCK:
        HEALTH_SERVER = servidor
    logger.info(f"[HEALTH] servidor iniciado porta={porta}")
    try:
        servidor.serve_forever(poll_interval=0.25)
    finally:
        servidor.server_close()
        with HEALTH_SERVER_LOCK:
            if HEALTH_SERVER is servidor:
                HEALTH_SERVER = None


def encerrar_healthcheck():
    with HEALTH_SERVER_LOCK:
        servidor = HEALTH_SERVER
    if servidor is not None:
        servidor.shutdown()


# =========================================
# MAIN
# =========================================
if __name__ == "__main__":
    logger.info(f"[YT_DLP] versao={YT_DLP_VERSION}")
    logger.info(
        f"[MIDIA_CONFIG] profile={MEDIA_PROFILE_VERSION} "
        f"max_duration={MAX_DURATION_SECONDS}s source_max={MAX_SOURCE_FILE_MB}MB "
        f"output_max={MAX_OUTPUT_FILE_MB}MB ffmpeg_timeout={FFMPEG_TIMEOUT_SECONDS}s "
        f"threads={FFMPEG_THREADS}"
    )
    logger.info(
        f"[DISK_GUARD_CONFIG] minimo_livre={MIN_DISK_FREE_MB}MB "
        "limpeza_automatica=True cache_telegram_bloqueado=False "
        "mongo_writes=0"
    )
    logger.info(
        f"[CUSTO_CONFIG] cooldown={DOWNLOAD_COOLDOWN_SECONDS}s "
        f"user_hour={MAX_DOWNLOADS_PER_USER_HOUR} "
        f"global_hour={MAX_DOWNLOADS_GLOBAL_HOUR}"
    )
    logger.info(
        f"[LIMITE_GLOBAL_CONFIG] persistente=True janela_movel="
        f"{GLOBAL_RATE_LIMIT_WINDOW_SECONDS}s "
        f"limite={MAX_DOWNLOADS_GLOBAL_HOUR} mongo_writes_por_aceite=1 "
        "compartilhado_entre_instancias=True expr_em_upsert=False "
        "primeira_solicitacao_ops=2 contains_user_ids=False "
        "contains_urls=False"
    )
    logger.info(
        f"[LIMITE_USUARIO_CONFIG] persistente=True janela_movel="
        f"{GLOBAL_RATE_LIMIT_WINDOW_SECONDS}s "
        f"limite={MAX_DOWNLOADS_PER_USER_HOUR} "
        f"cooldown={DOWNLOAD_COOLDOWN_SECONDS}s "
        "mongo_writes_por_aceite=1 compartilhado_entre_instancias=True "
        "expr_em_upsert=False primeira_solicitacao_ops=2 "
        "identifier_anonymized=True contains_plain_user_id=False "
        "contains_urls=False"
    )
    logger.info(
        f"[LIMITE_GRATIS_CONFIG] atomico=True limite={FREE_DAILY_LIMIT} "
        f"reserva_ttl={DOWNLOAD_RESERVATION_TTL_SECONDS}s "
        "devolve_em_falha=True escrita_adicional_sucesso=1 "
        "vip_sem_reserva=True"
    )
    logger.info(
        f"[MONITOR_CONFIG] threshold={MONITOR_FAILURE_THRESHOLD} "
        f"window={MONITOR_FAILURE_WINDOW_SECONDS}s "
        f"alert_cooldown={MONITOR_ALERT_COOLDOWN_SECONDS}s "
        f"success_log_interval={MONITOR_SUCCESS_LOG_INTERVAL_SECONDS}s "
        "downloads_automaticos=False logs_sucesso_repetitivos=False"
    )
    logger.info(
        f"[WORKER_WATCHDOG_CONFIG] stall_timeout="
        f"{WORKER_STALL_TIMEOUT_SECONDS}s interval="
        f"{WORKER_WATCHDOG_INTERVAL_SECONDS}s auto_restart=True "
        f"restart_grace={WORKER_RESTART_GRACE_SECONDS}s "
        f"max_restarts_hour={WORKER_MAX_RESTARTS_PER_HOUR}"
    )
    logger.info(
        f"[SHUTDOWN_CONFIG] sigterm=True drain={SHUTDOWN_DRAIN_SECONDS}s "
        f"safety_margin={SHUTDOWN_SAFETY_MARGIN_SECONDS}s "
        f"railway_configurada={RAILWAY_DRAINING_CONFIGURED} "
        "aceita_novos_durante_drenagem=False"
    )
    if not RAILWAY_DRAINING_CONFIGURED:
        logger.warning(
            "[SHUTDOWN_CONFIG] variável "
            "RAILWAY_DEPLOYMENT_DRAINING_SECONDS ausente; a Railway pode "
            "encerrar o processo antes da drenagem"
        )
        safe_send_message(
            ADMIN_ID,
            "⚠️ <b>Configuração necessária na Railway</b>\n\n"
            "Adicione a variável:\n"
            "<code>RAILWAY_DEPLOYMENT_DRAINING_SECONDS=120</code>\n\n"
            "Sem ela, o desligamento seguro durante deploys não terá tempo "
            "para concluir os vídeos ativos.",
            parse_mode="HTML",
        )
    logger.info("[PAGAMENTO_CONFIG] modo=manual_pix configurado=True")
    logger.info(
        "[INSTAGRAM_AUDIO_CONFIG] validacao=True "
        f"cache_version={INSTAGRAM_AUDIO_CACHE_VERSION} "
        "prefer_h264=True fallback_com_audio=True"
    )
    if TIKTOK_IMPERSONATION_DISPONIVEL:
        logger.info(f"[TIKTOK_DEPENDENCIAS] curl_cffi={CURL_CFFI_VERSION}")
    else:
        logger.warning(
            "[TIKTOK_DEPENDENCIAS] curl_cffi ausente. No requirements.txt, "
            "use yt-dlp[default,curl-cffi] para habilitar a impersonacao."
        )
    try:
        inicializar_armazenamento_privado()
    except Exception as e:
        logger.critical(
            "[ARMAZENAMENTO_PRIVADO_FALHA] cookies e backups locais ficarão "
            f"indisponíveis erro={sanitizar_erro_log(e)}"
        )
    inicializar_metricas_diarias()
    cleanup_download_dir_old_files(max_age_hours=6)
    configurar_menu_comandos()
    recuperar_aprovacoes_pix_interrompidas()
    bot.set_update_listener(registrar_atividade_bot)
    registrar_sinais_desligamento()

    Thread(
        target=cleanup_download_dir_periodicamente,
        kwargs={"interval_minutes": 60, "max_age_hours": 6},
        daemon=True
    ).start()

    Thread(
        target=loop_fila_downloads,
        daemon=True,
    ).start()

    Thread(
        target=servir_healthcheck,
        daemon=True
    ).start()

    while not SHUTDOWN_EVENT.is_set():
        try:
            atualizar_estado_bot("polling")
            logger.info("Iniciando bot.infinity_polling...")
            bot.infinity_polling(skip_pending=False, timeout=20, long_polling_timeout=50)
        except Exception as e:
            if SHUTDOWN_EVENT.is_set():
                break
            atualizar_estado_bot("reconnecting")
            logger.error(f"[POLLING] erro={sanitizar_erro_log(e)}")
            time.sleep(5)

    if SHUTDOWN_EVENT.is_set():
        executar_desligamento_gracioso()
        logging.shutdown()
