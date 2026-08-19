# BUILD_FILE: ML_CLIPS_V1_20260817
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
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlparse
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
INSTAGRAM_AUDIO_CACHE_VERSION = "instagram_audio_v5_nocookies"
FACEBOOK_AUDIO_CACHE_VERSION = "facebook_audio_v2"
ML_CLIPS_CACHE_VERSION = "ml_clips_hls_720_v1"

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
COMPONENTES_PLATAFORMA = (
    "TikTok",
    "Instagram",
    "Pinterest",
    "RedNote",
    "Facebook Reels",
    "Shopee Video",
    "Mercado Livre Clips",
)
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
    # Plano disponível para novas compras.
    "10.00": {
        "nome": "VIP Mensal",
        "preco_centavos": 1000,
        "dias": 30,
        "descricao": "VIP Mensal 30 dias"
    },

    # Compatibilidade histórica: NÃO é oferecido para novas compras.
    # Mantido para que pedidos anuais antigos continuem podendo ser
    # consultados, aprovados ou recuperados sem quebrar o histórico.
    "79.90": {
        "nome": "VIP Anual",
        "preco_centavos": 7990,
        "dias": 365,
        "descricao": "VIP Anual 365 dias"
    }
}

PLANOS_VENDA_ATIVOS = frozenset({"10.00"})

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


def eh_url_facebook_reel_ou_compartilhada(url):
    """Aceita somente Reels individuais e atalhos próprios de compartilhamento."""
    try:
        parsed = urlparse(str(url or "").strip())
    except Exception:
        return False

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False

    try:
        if parsed.port not in (None, 80, 443):
            return False
    except ValueError:
        return False

    host = parsed.hostname.lower().rstrip(".")
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    hosts_facebook = {
        "facebook.com",
        "www.facebook.com",
        "m.facebook.com",
        "mbasic.facebook.com",
        "web.facebook.com",
    }

    if host in {"fb.watch", "www.fb.watch"}:
        return bool(path.strip("/"))
    if host not in hosts_facebook:
        return False

    return bool(
        re.fullmatch(r"/(?:reel|reels)/[^/]+/?", path, flags=re.IGNORECASE)
        or re.fullmatch(r"/share/r/[^/]+/?", path, flags=re.IGNORECASE)
    )


def detectar_plataforma_url(url):
    """Classifica apenas hosts oficiais para impedir URLs arbitrárias/SSRF."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, False, False, False, False, False, False

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        return False, False, False, False, False, False, False

    try:
        if parsed.port not in (None, 80, 443):
            return False, False, False, False, False, False, False
    except ValueError:
        return False, False, False, False, False, False, False

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
    is_facebook_reel = eh_url_facebook_reel_ou_compartilhada(url)
    # O compartilhamento de Shopee Video usa br.shp.ee e páginas oficiais
    # em shopee.com.br (incluindo sv.shopee.com.br/share-video). A validação
    # específica do vídeo é feita depois da resolução do link curto.
    is_shopee = host == "br.shp.ee" or hostname_permitido(host, "shopee.com.br")

    # Mercado Livre Clips: aceite somente as rotas públicas de Clips que
    # carregam um short_id explícito. Outros links do marketplace continuam
    # fora do downloader.
    caminho_ml = re.sub(r"/{2,}", "/", parsed.path or "/").rstrip("/") or "/"
    parametros_ml = dict(parse_qsl(parsed.query, keep_blank_values=True))
    short_id_ml = str(parametros_ml.get("short_id") or "").strip()
    is_mercado_livre_clips = (
        hostname_permitido(host, "mercadolivre.com.br")
        and caminho_ml in ("/clips", "/live/videos")
        and bool(re.fullmatch(r"[A-Za-z0-9_-]{3,64}", short_id_ml))
    )

    return (
        is_pinterest,
        is_tiktok,
        is_instagram,
        is_rednote,
        is_facebook_reel,
        is_shopee,
        is_mercado_livre_clips,
    )

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
        "fb.watch",
        "www.fb.watch",
        "br.shp.ee",
    }
    caminho = (urlparse(url).path or "").lower()
    compartilhamento_facebook = (
        flags_originais[4]
        and bool(re.fullmatch(r"/share/r/[^/]+/?", caminho))
    )
    if host not in hosts_curtos and not compartilhamento_facebook:
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


def normalizar_url_facebook_reel(url):
    """Remove rastreamento sem transformar um Reel em outro tipo de link."""
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        if not eh_url_facebook_reel_ou_compartilhada(url):
            raise RuntimeError("FACEBOOK_REELS_SOMENTE")

        netloc = (
            "fb.watch"
            if host in {"fb.watch", "www.fb.watch"}
            else "www.facebook.com"
        )
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        if not path.endswith("/"):
            path += "/"
        return parsed._replace(
            scheme="https",
            netloc=netloc,
            path=path,
            query="",
            fragment="",
        ).geturl()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError("FACEBOOK_REELS_SOMENTE") from e


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
        "facebook": "Facebook Reels",
        "facebook reel": "Facebook Reels",
        "facebook reels": "Facebook Reels",
        "shopee": "Shopee Video",
        "shopee video": "Shopee Video",
        "mercado livre": "Mercado Livre Clips",
        "mercado livre clips": "Mercado Livre Clips",
        "mercadolivre": "Mercado Livre Clips",
        "ml clips": "Mercado Livre Clips",
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
    plataforma_normalizada = str(plataforma or "").strip().lower()
    if plataforma_normalizada == "instagram":
        perfil = f"{perfil}|{INSTAGRAM_AUDIO_CACHE_VERSION}"
    elif plataforma_normalizada in ("facebook", "facebook reels", "facebook_reels"):
        perfil = f"{perfil}|{FACEBOOK_AUDIO_CACHE_VERSION}"
    elif plataforma_normalizada in (
        "mercado livre clips",
        "mercadolivre clips",
        "ml clips",
    ):
        perfil = f"{perfil}|{ML_CLIPS_CACHE_VERSION}"
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


def nome_plataforma(
    is_pinterest,
    is_tiktok,
    is_instagram,
    is_rednote,
    is_facebook_reel,
    is_shopee=False,
    is_mercado_livre_clips=False,
):
    if is_pinterest:
        return "Pinterest"
    if is_tiktok:
        return "TikTok"
    if is_instagram:
        return "Instagram"
    if is_rednote:
        return "RedNote"
    if is_facebook_reel:
        return "Facebook Reels"
    if is_shopee:
        return "Shopee Video"
    if is_mercado_livre_clips:
        return "Mercado Livre Clips"
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
    is_facebook_reel=False,
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
        # Instagram funciona apenas em modo público/anônimo.
        # Nenhuma sessão, cookie ou credencial de conta é enviada.
        pass
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
    elif is_facebook_reel:
        opts["http_headers"] = {
            **DEFAULT_HEADERS,
            "Referer": "https://www.facebook.com/",
        }

    return opts


def montar_download_opts(
    prefix,
    is_instagram=False,
    is_pinterest=False,
    usar_cookies=True,
    is_tiktok=False,
    tiktok_extractor_args=None,
    is_facebook_reel=False,
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
        # Instagram funciona apenas em modo público/anônimo.
        # O yt-dlp define os cabeçalhos/impersonação e nenhuma sessão é usada.
        opts["extractor_retries"] = 3
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
    elif is_facebook_reel:
        opts["http_headers"] = {
            **DEFAULT_HEADERS,
            "Referer": "https://www.facebook.com/",
        }
        opts["format_sort"] = ["vcodec:h264", "acodec:aac"]
        opts["extractor_retries"] = 2

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


def info_plataforma_indica_audio(info):
    """Retorna True/False/None conforme a certeza dos metadados de áudio.

    True  = existe ao menos um stream confirmado com áudio.
    False = todos os formatos observáveis são explicitamente video-only.
    None  = há formatos com codec desconhecido; o arquivo precisa de ffprobe.
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

    viu_sem_audio_explicito = False
    viu_codec_desconhecido = False

    for item in itens:
        acodec_raw = item.get("acodec")
        audio_ext_raw = item.get("audio_ext")

        if acodec_raw in (None, "") and audio_ext_raw in (None, ""):
            # Formatos progressivos do Instagram costumam aparecer assim.
            viu_codec_desconhecido = True
            continue

        acodec = str(acodec_raw or "").strip().lower()
        audio_ext = str(audio_ext_raw or "").strip().lower()

        if acodec and acodec not in ("none", "null", "unknown"):
            return True
        if audio_ext and audio_ext not in ("none", "null", "unknown"):
            return True

        if acodec == "unknown" or audio_ext == "unknown":
            viu_codec_desconhecido = True
        if acodec in ("none", "null") or audio_ext in ("none", "null"):
            viu_sem_audio_explicito = True

    if viu_codec_desconhecido:
        return None
    if viu_sem_audio_explicito:
        return False
    return None


def arquivo_possui_audio(info_midia):
    acodec = str((info_midia or {}).get("acodec") or "").strip().lower()
    return acodec not in ("", "none", "null", "unknown")


def extrair_id_facebook_para_fallback(info, url):
    """Obtém somente um ID numérico para montar páginas oficiais alternativas."""
    candidatos = [
        (info or {}).get("id") if isinstance(info, dict) else None,
        (info or {}).get("display_id") if isinstance(info, dict) else None,
    ]

    try:
        parsed = urlparse(str(url or "").strip())
        match_path = re.search(
            r"/(?:reel|reels)/(\d+)(?:/|$)",
            parsed.path or "",
            flags=re.IGNORECASE,
        )
        if match_path:
            candidatos.append(match_path.group(1))

        parametros = dict(parse_qsl(parsed.query, keep_blank_values=True))
        candidatos.extend([parametros.get("v"), parametros.get("fbid")])
    except Exception:
        pass

    for candidato in candidatos:
        candidato = str(candidato or "").strip()
        if re.fullmatch(r"\d{5,30}", candidato):
            return candidato
    return None



def resumir_formatos_facebook(info, origem="desconhecida"):
    """
    Registra os formatos retornados pelo Facebook sem expor URLs assinadas,
    cookies ou outros dados sensíveis. É apenas diagnóstico: não altera o
    formato escolhido nem o comportamento do download.
    """
    if not isinstance(info, dict):
        logger.info(
            f"[FACEBOOK_FORMATOS] origem={origem} total=0 info_valida=False"
        )
        return

    formatos = info.get("formats")
    if not isinstance(formatos, list):
        formatos = []

    resumo = []
    for item in formatos[:40]:
        if not isinstance(item, dict):
            continue

        format_id = sanitizar_erro_log(item.get("format_id"), limite=80)
        ext = sanitizar_erro_log(item.get("ext"), limite=20)
        vcodec = sanitizar_erro_log(item.get("vcodec"), limite=40)
        acodec = sanitizar_erro_log(item.get("acodec"), limite=40)
        protocolo = sanitizar_erro_log(item.get("protocol"), limite=40)

        resumo.append(
            "{id=%s ext=%s v=%s a=%s %sx%s fps=%s proto=%s "
            "tbr=%s vbr=%s abr=%s size=%s}" % (
                format_id,
                ext,
                vcodec,
                acodec,
                item.get("width"),
                item.get("height"),
                item.get("fps"),
                protocolo,
                item.get("tbr"),
                item.get("vbr"),
                item.get("abr"),
                item.get("filesize") or item.get("filesize_approx"),
            )
        )

    requested_formats = info.get("requested_formats")
    requested_downloads = info.get("requested_downloads")

    logger.info(
        f"[FACEBOOK_FORMATOS] origem={origem} "
        f"total={len(formatos)} "
        f"requested_formats={len(requested_formats) if isinstance(requested_formats, list) else 0} "
        f"requested_downloads={len(requested_downloads) if isinstance(requested_downloads, list) else 0} "
        f"top_ext={sanitizar_erro_log(info.get('ext'), limite=20)} "
        f"top_v={sanitizar_erro_log(info.get('vcodec'), limite=40)} "
        f"top_a={sanitizar_erro_log(info.get('acodec'), limite=40)} "
        f"itens={' '.join(resumo)[:7000]}"
    )




def diagnosticar_dash_manifest_facebook(texto_pagina, origem="desconhecida"):
    """
    Extrai, decodifica e resume DASH manifests presentes no HTML/JSON do Facebook.

    Segurança:
    - não registra BaseURL;
    - não registra query strings, tokens ou URLs assinadas;
    - não registra XML bruto;
    - registra apenas estrutura, contagens, codecs, mime types, bitrates
      e o tipo de transformação necessária para o XML ficar válido.
    """
    import xml.etree.ElementTree as ET

    texto = str(texto_pagina or "")
    if not texto:
        logger.info(
            f"[FACEBOOK_DASH_DIAG] origem={origem} manifests_encontrados=0 "
            "motivo=pagina_vazia"
        )
        return None

    padroes = (
        r'"dash_manifest"\s*:\s*("(?:\\.|[^"\\])*")',
        r'"dash_manifest_xml_string"\s*:\s*("(?:\\.|[^"\\])*")',
        r'"manifest_xml"\s*:\s*("(?:\\.|[^"\\])*")',
    )

    valores_brutos = []
    vistos_brutos = set()

    for padrao in padroes:
        for match in re.finditer(padrao, texto, flags=re.IGNORECASE):
            bruto_json = match.group(1)
            assinatura = hashlib.sha256(
                bruto_json.encode("utf-8", errors="ignore")
            ).hexdigest()
            if assinatura in vistos_brutos:
                continue
            vistos_brutos.add(assinatura)
            valores_brutos.append(bruto_json)

            if len(valores_brutos) >= 20:
                break

        if len(valores_brutos) >= 20:
            break

    def substituir_escape_unicode(match):
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    def substituir_escape_hex(match):
        try:
            return chr(int(match.group(1), 16))
        except Exception:
            return match.group(0)

    def reparar_ampersands_xml(texto_xml):
        """
        Corrige somente '&' que não iniciam uma entidade XML válida.

        Exemplos preservados:
        &amp;  &#123;  &#xAF;

        Exemplo corrigido:
        ?token=abc&expires=123  ->  ?token=abc&amp;expires=123
        """
        padrao = re.compile(
            r"&(?!(?:amp|lt|gt|quot|apos);|#\d+;|#x[0-9a-fA-F]+;)"
        )
        reparado, quantidade = padrao.subn("&amp;", str(texto_xml or ""))
        return reparado, quantidade


    def desescapar_camadas(valor):
        """
        Produz candidatos progressivamente decodificados, sem executar código
        e sem reinterpretar bytes arbitrariamente.
        """
        candidatos = []
        vistos = set()

        def adicionar(rotulo, candidato):
            if not isinstance(candidato, str):
                return
            candidato = candidato.strip()
            if not candidato:
                return
            chave = hashlib.sha256(
                candidato.encode("utf-8", errors="ignore")
            ).hexdigest()
            if chave in vistos:
                return
            vistos.add(chave)
            candidatos.append((rotulo, candidato))

        try:
            valor = json.loads(valor)
            adicionar("json1", valor)
        except Exception:
            adicionar("bruto", valor)

        for _ in range(5):
            snapshot = list(candidatos)
            mudou = False

            for rotulo, atual in snapshot:
                transformacoes = []

                html_dec = html.unescape(atual)
                if html_dec != atual:
                    transformacoes.append((rotulo + "+html", html_dec))

                js_dec = re.sub(
                    r"\\u([0-9a-fA-F]{4})",
                    substituir_escape_unicode,
                    atual,
                )
                js_dec = re.sub(
                    r"\\x([0-9a-fA-F]{2})",
                    substituir_escape_hex,
                    js_dec,
                )
                js_dec = js_dec.replace("\\/", "/")
                js_dec = js_dec.replace('\\"', '"')
                js_dec = js_dec.replace("\\'", "'")
                js_dec = js_dec.replace("\\\\", "\\")
                if js_dec != atual:
                    transformacoes.append((rotulo + "+js", js_dec))

                texto_strip = atual.strip()
                if (
                    len(texto_strip) >= 2
                    and texto_strip[0] == '"'
                    and texto_strip[-1] == '"'
                ):
                    try:
                        json_dec = json.loads(texto_strip)
                        if isinstance(json_dec, str) and json_dec != atual:
                            transformacoes.append((rotulo + "+json", json_dec))
                    except Exception:
                        pass

                for novo_rotulo, novo_valor in transformacoes:
                    antes = len(candidatos)
                    adicionar(novo_rotulo, novo_valor)
                    if len(candidatos) > antes:
                        mudou = True

            if not mudou:
                break

        snapshot = list(candidatos)
        for rotulo, atual in snapshot:
            inicio_mpd = re.search(
                r"<(?:[A-Za-z_][\w.-]*:)?MPD\b",
                atual,
                flags=re.IGNORECASE,
            )
            fim_mpd = list(
                re.finditer(
                    r"</(?:[A-Za-z_][\w.-]*:)?MPD\s*>",
                    atual,
                    flags=re.IGNORECASE,
                )
            )
            if inicio_mpd and fim_mpd:
                ultimo = fim_mpd[-1]
                if ultimo.end() > inicio_mpd.start():
                    adicionar(
                        rotulo + "+recorte_mpd",
                        atual[inicio_mpd.start():ultimo.end()],
                    )

        return candidatos

    manifests = []
    manifests_invalidos = []
    vistos_xml = set()

    for indice, bruto_json in enumerate(valores_brutos, start=1):
        candidatos = desescapar_camadas(bruto_json)
        parseou = False
        melhor_erro = None
        melhor_estrutura = None

        for rotulo, candidato in candidatos:
            estrutura = {
                "rotulo": rotulo,
                "len": len(candidato),
                "comeca_xml": candidato.lstrip().startswith("<"),
                "tem_mpd": bool(re.search(
                    r"<(?:[A-Za-z_][\w.-]*:)?MPD\b",
                    candidato,
                    flags=re.IGNORECASE,
                )),
                "tem_adaptation": "adaptationset" in candidato.lower(),
                "tem_representation": "representation" in candidato.lower(),
                "escape_u": len(re.findall(r"\\u[0-9a-fA-F]{4}", candidato)),
                "escape_x": len(re.findall(r"\\x[0-9a-fA-F]{2}", candidato)),
                "entidade_lt": candidato.lower().count("&lt;"),
                "backslash_quote": candidato.count('\\"'),
            }

            candidato_usado = candidato
            rotulo_usado = rotulo
            reparos_ampersand = 0

            try:
                raiz = ET.fromstring(candidato)
            except ET.ParseError as e_original:
                # Tentativa controlada: corrige somente '&' inválidos.
                candidato_reparado, reparos_ampersand = reparar_ampersands_xml(
                    candidato
                )

                if reparos_ampersand > 0:
                    try:
                        raiz = ET.fromstring(candidato_reparado)
                        candidato_usado = candidato_reparado
                        rotulo_usado = rotulo + "+amp"
                        logger.info(
                            "[FACEBOOK_DASH_REPAIR_OK] "
                            f"origem={origem} indice={indice} "
                            f"reparos_ampersand={reparos_ampersand} "
                            f"decodificacao={rotulo_usado} "
                            f"tamanho={len(candidato_reparado)}"
                        )
                    except ET.ParseError as e:
                        pos = getattr(e, "position", None)
                        erro = {
                            "tipo": type(e).__name__,
                            "linha": pos[0] if pos else None,
                            "coluna": pos[1] if pos else None,
                            "rotulo": rotulo + "+amp",
                            "reparos_ampersand": reparos_ampersand,
                        }

                        pontuacao = (
                            int(estrutura["tem_mpd"]) * 4
                            + int(estrutura["comeca_xml"]) * 2
                            + int(estrutura["tem_adaptation"])
                            + int(estrutura["tem_representation"])
                        )
                        if (
                            melhor_estrutura is None
                            or pontuacao > melhor_estrutura["pontuacao"]
                        ):
                            melhor_estrutura = {
                                **estrutura,
                                "pontuacao": pontuacao,
                                "reparos_ampersand": reparos_ampersand,
                            }
                            melhor_erro = erro
                        continue
                else:
                    pos = getattr(e_original, "position", None)
                    erro = {
                        "tipo": type(e_original).__name__,
                        "linha": pos[0] if pos else None,
                        "coluna": pos[1] if pos else None,
                        "rotulo": rotulo,
                        "reparos_ampersand": 0,
                    }

                    pontuacao = (
                        int(estrutura["tem_mpd"]) * 4
                        + int(estrutura["comeca_xml"]) * 2
                        + int(estrutura["tem_adaptation"])
                        + int(estrutura["tem_representation"])
                    )
                    if (
                        melhor_estrutura is None
                        or pontuacao > melhor_estrutura["pontuacao"]
                    ):
                        melhor_estrutura = {
                            **estrutura,
                            "pontuacao": pontuacao,
                            "reparos_ampersand": 0,
                        }
                        melhor_erro = erro
                    continue
            except Exception as e:
                melhor_erro = {
                    "tipo": type(e).__name__,
                    "linha": None,
                    "coluna": None,
                    "rotulo": rotulo,
                    "reparos_ampersand": 0,
                }
                melhor_estrutura = {
                    **estrutura,
                    "pontuacao": 0,
                    "reparos_ampersand": 0,
                }
                continue

            assinatura_xml = hashlib.sha256(
                candidato_usado.encode("utf-8", errors="ignore")
            ).hexdigest()
            if assinatura_xml not in vistos_xml:
                vistos_xml.add(assinatura_xml)
                manifests.append(
                    {
                        "xml": candidato_usado,
                        "raiz": raiz,
                        "decodificacao": rotulo_usado,
                    }
                )

            logger.info(
                "[FACEBOOK_DASH_DECODE_OK] "
                f"origem={origem} indice={indice} "
                f"decodificacao={rotulo_usado} "
                f"reparos_ampersand={reparos_ampersand} "
                f"tamanho={len(candidato_usado)}"
            )
            parseou = True
            break

        if not parseou:
            estrutura = melhor_estrutura or {
                "rotulo": "nenhum",
                "len": 0,
                "comeca_xml": False,
                "tem_mpd": False,
                "tem_adaptation": False,
                "tem_representation": False,
                "escape_u": 0,
                "escape_x": 0,
                "entidade_lt": 0,
                "backslash_quote": 0,
                "pontuacao": 0,
            }
            erro = melhor_erro or {
                "tipo": "sem_candidato_xml",
                "linha": None,
                "coluna": None,
                "rotulo": estrutura["rotulo"],
            }
            manifests_invalidos.append((indice, estrutura, erro))

            logger.info(
                "[FACEBOOK_DASH_DECODE_FALHA] "
                f"origem={origem} indice={indice} "
                f"candidatos={len(candidatos)} "
                f"melhor={estrutura['rotulo']} "
                f"tamanho={estrutura['len']} "
                f"comeca_xml={estrutura['comeca_xml']} "
                f"tem_mpd={estrutura['tem_mpd']} "
                f"tem_adaptation={estrutura['tem_adaptation']} "
                f"tem_representation={estrutura['tem_representation']} "
                f"escape_u={estrutura['escape_u']} "
                f"escape_x={estrutura['escape_x']} "
                f"entidade_lt={estrutura['entidade_lt']} "
                f"backslash_quote={estrutura['backslash_quote']} "
                f"reparos_ampersand={erro.get('reparos_ampersand', 0)} "
                f"erro_tipo={erro['tipo']} "
                f"erro_linha={erro['linha']} erro_coluna={erro['coluna']}"
            )

    total_audio = 0
    total_video = 0
    total_desconhecido = 0
    manifests_parseados = len(manifests)
    manifests_com_audio = 0
    manifests_com_video = 0
    baseurl_audio = 0
    baseurl_video = 0
    codecs_audio = set()
    codecs_video = set()
    mimes_audio = set()
    mimes_video = set()
    bitrates_audio = []
    bitrates_video = []
    decodificacoes_ok = set()
    candidatos_audio = []
    candidatos_video = []

    def nome_local(tag):
        return str(tag or "").split("}", 1)[-1].lower()

    def classificar(mime_type, content_type, codecs):
        mime = str(mime_type or "").lower()
        content = str(content_type or "").lower()
        codec = str(codecs or "").lower()

        if (
            "audio" in mime
            or content == "audio"
            or codec.startswith(("mp4a", "aac", "opus", "vorbis"))
        ):
            return "audio"

        if (
            "video" in mime
            or content == "video"
            or codec.startswith(
                ("avc", "h264", "hev", "hvc", "vp9", "vp0", "av01")
            )
        ):
            return "video"

        return "desconhecido"

    for manifesto_indice, manifesto in enumerate(manifests, start=1):
        raiz = manifesto["raiz"]
        decodificacoes_ok.add(manifesto["decodificacao"])
        manifesto_tem_audio = False
        manifesto_tem_video = False

        for adaptation in raiz.iter():
            if nome_local(adaptation.tag) != "adaptationset":
                continue

            adapt_mime = (
                adaptation.attrib.get("mimeType")
                or adaptation.attrib.get("mimetype")
            )
            adapt_content = (
                adaptation.attrib.get("contentType")
                or adaptation.attrib.get("contenttype")
            )
            adapt_codecs = adaptation.attrib.get("codecs")

            for rep in adaptation.iter():
                if nome_local(rep.tag) != "representation":
                    continue

                mime = (
                    rep.attrib.get("mimeType")
                    or rep.attrib.get("mimetype")
                    or adapt_mime
                )
                content = (
                    rep.attrib.get("contentType")
                    or rep.attrib.get("contenttype")
                    or adapt_content
                )
                codecs = rep.attrib.get("codecs") or adapt_codecs
                categoria = classificar(mime, content, codecs)

                bandwidth = rep.attrib.get("bandwidth")
                try:
                    bandwidth = (
                        int(float(bandwidth))
                        if bandwidth is not None
                        else None
                    )
                except (TypeError, ValueError):
                    bandwidth = None

                baseurl_valor = next(
                    (
                        str(filho.text or "").strip()
                        for filho in rep
                        if nome_local(filho.tag) == "baseurl"
                        and bool(str(filho.text or "").strip())
                    ),
                    None,
                )
                tem_baseurl = bool(baseurl_valor)

                largura = rep.attrib.get("width")
                altura = rep.attrib.get("height")
                try:
                    largura = int(largura) if largura is not None else None
                except (TypeError, ValueError):
                    largura = None
                try:
                    altura = int(altura) if altura is not None else None
                except (TypeError, ValueError):
                    altura = None

                if categoria == "audio":
                    total_audio += 1
                    manifesto_tem_audio = True
                    if codecs:
                        codecs_audio.add(str(codecs)[:80])
                    if mime:
                        mimes_audio.add(str(mime)[:80])
                    if bandwidth:
                        bitrates_audio.append(bandwidth)
                    if tem_baseurl:
                        baseurl_audio += 1
                        candidatos_audio.append(
                            {
                                "manifesto": manifesto_indice,
                                "url": baseurl_valor,
                                "mime": str(mime or ""),
                                "codecs": str(codecs or ""),
                                "bandwidth": int(bandwidth or 0),
                            }
                        )

                elif categoria == "video":
                    total_video += 1
                    manifesto_tem_video = True
                    if codecs:
                        codecs_video.add(str(codecs)[:80])
                    if mime:
                        mimes_video.add(str(mime)[:80])
                    if bandwidth:
                        bitrates_video.append(bandwidth)
                    if tem_baseurl:
                        baseurl_video += 1
                        candidatos_video.append(
                            {
                                "manifesto": manifesto_indice,
                                "url": baseurl_valor,
                                "mime": str(mime or ""),
                                "codecs": str(codecs or ""),
                                "bandwidth": int(bandwidth or 0),
                                "width": largura,
                                "height": altura,
                            }
                        )

                else:
                    total_desconhecido += 1

        if manifesto_tem_audio:
            manifests_com_audio += 1
        if manifesto_tem_video:
            manifests_com_video += 1

    def resumir_conjunto(valores, limite=6):
        if not valores:
            return "nenhum"
        return ",".join(sorted(valores)[:limite])

    logger.info(
        "[FACEBOOK_DASH_DIAG] "
        f"origem={origem} "
        f"manifests_encontrados={len(valores_brutos)} "
        f"manifests_parseados={manifests_parseados} "
        f"manifests_invalidos={len(manifests_invalidos)} "
        f"decodificacoes_ok={resumir_conjunto(decodificacoes_ok)} "
        f"manifests_com_audio={manifests_com_audio} "
        f"manifests_com_video={manifests_com_video} "
        f"audio_representations={total_audio} "
        f"video_representations={total_video} "
        f"desconhecidas={total_desconhecido} "
        f"audio_baseurl={baseurl_audio} "
        f"video_baseurl={baseurl_video} "
        f"audio_codecs={resumir_conjunto(codecs_audio)} "
        f"video_codecs={resumir_conjunto(codecs_video)} "
        f"audio_mimes={resumir_conjunto(mimes_audio)} "
        f"video_mimes={resumir_conjunto(mimes_video)} "
        f"audio_bitrate_max={max(bitrates_audio) if bitrates_audio else 0} "
        f"video_bitrate_max={max(bitrates_video) if bitrates_video else 0}"
    )

    return {
        "manifests_encontrados": len(valores_brutos),
        "manifests_parseados": manifests_parseados,
        "manifests_invalidos": len(manifests_invalidos),
        "audio_representations": total_audio,
        "video_representations": total_video,
        "audio_baseurl": baseurl_audio,
        "video_baseurl": baseurl_video,
        "audio_codecs": sorted(codecs_audio),
        "video_codecs": sorted(codecs_video),
        "decodificacoes_ok": sorted(decodificacoes_ok),
        # Uso interno do fallback. Estes valores nunca são escritos nos logs.
        "_candidatos_audio": candidatos_audio,
        "_candidatos_video": candidatos_video,
    }


def diagnosticar_pagina_facebook_audio(url, origem="desconhecida"):
    """
    Diagnóstico somente de metadados da página pública do Facebook.

    Procura sinais de DASH/HLS/VideoDelivery e representações de áudio sem
    registrar URLs de mídia, tokens, cookies ou conteúdo completo da página.
    O resultado serve apenas para descobrir se a página contém uma origem de
    áudio que o yt-dlp não transformou em formato utilizável.
    """
    resposta = None
    try:
        resposta, url_final = seguir_redirecionamentos_seguros(
            url,
            headers={
                **DEFAULT_HEADERS,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            max_redirects=5,
        )

        limite_bytes = 5 * 1024 * 1024
        partes = []
        total = 0

        for bloco in resposta.iter_content(chunk_size=65536):
            if not bloco:
                continue
            restante = limite_bytes - total
            if restante <= 0:
                break
            if len(bloco) > restante:
                bloco = bloco[:restante]
            partes.append(bloco)
            total += len(bloco)

        charset = resposta.encoding or "utf-8"
        try:
            texto = b"".join(partes).decode(charset, errors="replace")
        except LookupError:
            texto = b"".join(partes).decode("utf-8", errors="replace")

        # Decodifica apenas entidades HTML. Não loga valores encontrados.
        texto_busca = html.unescape(texto)
        texto_lower = texto_busca.lower()

        diagnosticar_dash_manifest_facebook(
            texto_busca,
            origem=origem,
        )

        def contar_literal(*marcadores):
            return sum(texto_lower.count(str(m).lower()) for m in marcadores)

        # Sinais usados/relacionados ao pipeline moderno do Facebook/yt-dlp.
        sinais = {
            "dash_manifest": contar_literal(
                '"dash_manifest"',
                '"dash_manifests"',
                '"dash_manifest_urls"',
                '"dash_manifest_xml_string"',
                '"manifest_xml"',
            ),
            "playable_dash": contar_literal('"playable_url_dash"'),
            "playable_hd": contar_literal('"playable_url_quality_hd"'),
            "browser_native": contar_literal(
                '"browser_native_hd_url"',
                '"browser_native_sd_url"',
            ),
            "video_delivery": contar_literal(
                '"videodeliveryresponsefragment"',
                '"videodeliveryresponseresult"',
            ),
            "progressive": contar_literal(
                '"progressive_urls"',
                '"progressive_url"',
            ),
            "hls": contar_literal(
                '"hls_playlist_urls"',
                '"hls_playlist_url"',
            ),
            "relay_prefetch": contar_literal(
                "relayprefetchedstreamcache",
                "data-sjs",
            ),
            "audio_mime": contar_literal(
                'mimetype="audio/',
                '"mimetype":"audio/',
                '"mime_type":"audio/',
                'contenttype="audio"',
                '"contenttype":"audio"',
            ),
            "audio_codec": contar_literal(
                "mp4a.40",
                '"acodec":"aac"',
                '"audio_codec"',
                '"audiocodec"',
                "audiosamplingrate",
            ),
            "mpd_audio": contar_literal(
                '<adaptationset contenttype="audio"',
                '<adaptationset mimetype="audio/',
                '<representation mimetype="audio/',
            ),
        }

        possui_sinal_audio = any(
            sinais[chave] > 0
            for chave in ("audio_mime", "audio_codec", "mpd_audio")
        )
        possui_manifesto = any(
            sinais[chave] > 0
            for chave in (
                "dash_manifest",
                "playable_dash",
                "video_delivery",
                "hls",
            )
        )

        logger.info(
            "[FACEBOOK_PAGINA_AUDIO_DIAG] "
            f"origem={origem} "
            f"status={getattr(resposta, 'status_code', None)} "
            f"bytes_lidos={total} limite_bytes={limite_bytes} "
            f"url_final_ref={referencia_url_log(url_final)} "
            f"possui_manifesto={possui_manifesto} "
            f"possui_sinal_audio={possui_sinal_audio} "
            f"dash_manifest={sinais['dash_manifest']} "
            f"playable_dash={sinais['playable_dash']} "
            f"playable_hd={sinais['playable_hd']} "
            f"browser_native={sinais['browser_native']} "
            f"video_delivery={sinais['video_delivery']} "
            f"progressive={sinais['progressive']} "
            f"hls={sinais['hls']} "
            f"relay_prefetch={sinais['relay_prefetch']} "
            f"audio_mime={sinais['audio_mime']} "
            f"audio_codec={sinais['audio_codec']} "
            f"mpd_audio={sinais['mpd_audio']}"
        )
        return sinais

    except Exception as e:
        logger.warning(
            "[FACEBOOK_PAGINA_AUDIO_DIAG_FALHA] "
            f"origem={origem} "
            f"url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        return None

    finally:
        if resposta is not None:
            try:
                resposta.close()
            except Exception:
                pass



def _host_midia_facebook_permitido(url):
    """Restringe o fallback DASH aos CDNs oficiais usados pelo Facebook."""
    try:
        host = (urlparse(str(url or "").strip()).hostname or "").lower().rstrip(".")
    except Exception:
        return False

    return (
        hostname_permitido(host, "fbcdn.net")
        or hostname_permitido(host, "facebook.com")
        or hostname_permitido(host, "fbsbx.com")
    )


def _baixar_url_facebook_dash(url_midia, destino, referer, tipo):
    """
    Baixa uma faixa DASH oficial com redirects validados e limite de tamanho.
    Nunca registra a URL assinada.
    """
    atual = str(url_midia or "").strip()
    resposta = None
    total = 0

    headers = {
        **DEFAULT_HEADERS,
        "Accept": (
            "audio/mp4,audio/*;q=0.9,*/*;q=0.8"
            if tipo == "audio"
            else "video/mp4,video/*;q=0.9,*/*;q=0.8"
        ),
        "Referer": referer,
    }

    try:
        for _ in range(6):
            if not _host_midia_facebook_permitido(atual):
                raise RuntimeError("FACEBOOK_DASH_HOST_NAO_PERMITIDO")
            if not validar_url_http_publica(atual):
                raise RuntimeError("FACEBOOK_DASH_DESTINO_NAO_PUBLICO")

            resposta = requests.get(
                atual,
                headers=headers,
                stream=True,
                allow_redirects=False,
                timeout=(7, 30),
            )

            if resposta.status_code in (301, 302, 303, 307, 308):
                destino_redirect = urljoin(
                    atual,
                    resposta.headers.get("Location") or "",
                )
                resposta.close()
                resposta = None
                if not destino_redirect or destino_redirect == atual:
                    raise RuntimeError("FACEBOOK_DASH_REDIRECT_INVALIDO")
                atual = destino_redirect
                continue

            resposta.raise_for_status()

            tamanho_header = resposta.headers.get("Content-Length")
            if tamanho_header:
                try:
                    if int(tamanho_header) > MAX_SOURCE_FILE_BYTES:
                        raise RuntimeError(
                            "ARQUIVO_MIDIA_MUITO_GRANDE fase=facebook_dash"
                        )
                except ValueError:
                    pass

            with open(destino, "wb") as arquivo:
                for chunk in resposta.iter_content(chunk_size=256 * 1024):
                    atualizar_heartbeat_worker(f"facebook_dash_{tipo}")
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_SOURCE_FILE_BYTES:
                        raise RuntimeError(
                            "ARQUIVO_MIDIA_MUITO_GRANDE fase=facebook_dash"
                        )
                    arquivo.write(chunk)

            if total <= 0:
                raise RuntimeError("FACEBOOK_DASH_ARQUIVO_VAZIO")

            logger.info(
                "[FACEBOOK_DASH_FAIXA_OK] "
                f"tipo={tipo} bytes={total} "
                f"arquivo_ref={referencia_arquivo_log(destino)}"
            )
            return total

        raise RuntimeError("FACEBOOK_DASH_MUITOS_REDIRECTS")

    finally:
        if resposta is not None:
            resposta.close()


def _extrair_candidatos_dash_facebook(url):
    """
    Lê a página original e reaproveita o parser DASH já validado.
    As URLs das faixas permanecem somente em memória.
    """
    resposta = None
    try:
        resposta, url_final = seguir_redirecionamentos_seguros(
            url,
            headers={
                **DEFAULT_HEADERS,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,"
                    "*/*;q=0.8"
                ),
            },
            max_redirects=5,
        )

        limite_bytes = 5 * 1024 * 1024
        partes = []
        total = 0

        for bloco in resposta.iter_content(chunk_size=65536):
            if not bloco:
                continue
            restante = limite_bytes - total
            if restante <= 0:
                break
            if len(bloco) > restante:
                bloco = bloco[:restante]
            partes.append(bloco)
            total += len(bloco)

        charset = resposta.encoding or "utf-8"
        try:
            texto = b"".join(partes).decode(charset, errors="replace")
        except LookupError:
            texto = b"".join(partes).decode("utf-8", errors="replace")

        resultado = diagnosticar_dash_manifest_facebook(
            html.unescape(texto),
            origem="fallback_download",
        ) or {}

        audios = []
        videos = []

        for item in resultado.get("_candidatos_audio", []):
            url_item = urljoin(url_final, str(item.get("url") or "").strip())
            if not url_item or not _host_midia_facebook_permitido(url_item):
                continue
            copia = dict(item)
            copia["url"] = url_item
            audios.append(copia)

        for item in resultado.get("_candidatos_video", []):
            url_item = urljoin(url_final, str(item.get("url") or "").strip())
            if not url_item or not _host_midia_facebook_permitido(url_item):
                continue
            copia = dict(item)
            copia["url"] = url_item
            videos.append(copia)

        logger.info(
            "[FACEBOOK_DASH_CANDIDATOS] "
            f"audio={len(audios)} video={len(videos)} "
            f"pagina_bytes={total}"
        )
        return url_final, audios, videos

    finally:
        if resposta is not None:
            resposta.close()


def _montar_pares_dash_facebook(audios, videos):
    """
    Forma pares do mesmo manifest e prioriza:
    - vídeo AVC/H.264 até 720x1280 (ou 1280x720);
    - maior resolução/bitrate;
    - áudio AAC/mp4a, preferindo LC (mp4a.40.2) e maior bitrate.
    """
    por_manifesto_audio = {}
    por_manifesto_video = {}

    for audio in audios:
        por_manifesto_audio.setdefault(audio.get("manifesto"), []).append(audio)

    for video in videos:
        por_manifesto_video.setdefault(video.get("manifesto"), []).append(video)

    pares = []

    for manifesto, lista_audio in por_manifesto_audio.items():
        lista_video = por_manifesto_video.get(manifesto) or []
        if not lista_video:
            continue

        audios_validos = [
            a for a in lista_audio
            if (
                "audio/mp4" in str(a.get("mime") or "").lower()
                or str(a.get("codecs") or "").lower().startswith(("mp4a", "aac"))
            )
        ]
        if not audios_validos:
            continue

        videos_validos = []
        for v in lista_video:
            codec = str(v.get("codecs") or "").lower()
            mime = str(v.get("mime") or "").lower()
            largura = int(v.get("width") or 0)
            altura = int(v.get("height") or 0)

            if "video/mp4" not in mime and not codec.startswith(("avc", "h264")):
                continue

            # Mantém o limite atual do bot em ambas as orientações.
            dentro_limite = (
                (largura <= 720 and altura <= 1280)
                or (largura <= 1280 and altura <= 720)
            )
            if largura and altura and not dentro_limite:
                continue

            videos_validos.append(v)

        if not videos_validos:
            continue

        audios_validos.sort(
            key=lambda a: (
                1 if str(a.get("codecs") or "").lower().startswith("mp4a.40.2") else 0,
                int(a.get("bandwidth") or 0),
            ),
            reverse=True,
        )

        videos_validos.sort(
            key=lambda v: (
                int(v.get("width") or 0) * int(v.get("height") or 0),
                int(v.get("bandwidth") or 0),
            ),
            reverse=True,
        )

        melhor_audio = audios_validos[0]
        melhor_video = videos_validos[0]

        pares.append(
            {
                "manifesto": manifesto,
                "audio": melhor_audio,
                "video": melhor_video,
                "score": (
                    int(melhor_video.get("width") or 0)
                    * int(melhor_video.get("height") or 0),
                    int(melhor_video.get("bandwidth") or 0),
                    int(melhor_audio.get("bandwidth") or 0),
                ),
            }
        )

    pares.sort(key=lambda p: p["score"], reverse=True)

    logger.info(
        "[FACEBOOK_DASH_PARES] "
        f"total={len(pares)} "
        + (
            "melhor_video="
            f"{pares[0]['video'].get('width')}x{pares[0]['video'].get('height')} "
            f"video_bitrate={pares[0]['video'].get('bandwidth')} "
            f"audio_codec={str(pares[0]['audio'].get('codecs') or '')[:40]} "
            f"audio_bitrate={pares[0]['audio'].get('bandwidth')}"
            if pares
            else "nenhum=True"
        )
    )
    return pares


def _muxar_facebook_dash(video_path, audio_path, saida_path):
    """Junta vídeo e áudio sem reconversão."""
    atualizar_heartbeat_worker("facebook_dash_mux")

    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-i", video_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c", "copy",
        "-movflags", "+faststart",
        "-shortest",
        saida_path,
    ]

    try:
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"FACEBOOK_DASH_MUX_TIMEOUT timeout={FFMPEG_TIMEOUT_SECONDS}s"
        ) from e

    if resultado.returncode != 0:
        raise RuntimeError(
            f"FACEBOOK_DASH_MUX_FALHOU codigo={resultado.returncode}"
        )

    if not os.path.isfile(saida_path) or os.path.getsize(saida_path) <= 0:
        raise RuntimeError("FACEBOOK_DASH_MUX_NAO_GEROU_SAIDA")

    info = obter_info_midia(saida_path)
    if not info or not arquivo_possui_audio(info):
        raise RuntimeError("FACEBOOK_DASH_MUX_SAIDA_SEM_AUDIO")
    if not info.get("vcodec"):
        raise RuntimeError("FACEBOOK_DASH_MUX_SAIDA_SEM_VIDEO")

    logger.info(
        "[FACEBOOK_DASH_MUX_OK] "
        f"width={info.get('width')} height={info.get('height')} "
        f"vcodec={info.get('vcodec')} acodec={info.get('acodec')} "
        f"bytes={os.path.getsize(saida_path)}"
    )
    return saida_path


def baixar_facebook_dash_com_audio(url, prefix):
    """
    Fallback final do Facebook:
    página pública -> DASH reparado -> vídeo + áudio -> ffmpeg stream copy.
    """
    atualizar_heartbeat_worker("facebook_dash_preparando")

    url_final, audios, videos = _extrair_candidatos_dash_facebook(url)
    pares = _montar_pares_dash_facebook(audios, videos)

    if not pares:
        raise RuntimeError("FACEBOOK_DASH_SEM_PAR_COMPATIVEL")

    ultimo_erro = None

    # Evita deixar os MP4 mudos tentados antes no mesmo prefixo.
    cleanup_prefix(prefix)

    for tentativa, par in enumerate(pares[:6], start=1):
        video_path = f"{prefix}_fb_dash_video.mp4"
        audio_path = f"{prefix}_fb_dash_audio.m4a"
        saida_path = f"{prefix}_fb_dash_mux.mp4"

        for caminho in (video_path, audio_path, saida_path):
            try:
                if os.path.exists(caminho):
                    os.remove(caminho)
            except OSError:
                pass

        try:
            video = par["video"]
            audio = par["audio"]

            logger.info(
                "[FACEBOOK_DASH_TENTATIVA] "
                f"tentativa={tentativa}/{min(len(pares), 6)} "
                f"manifesto={par.get('manifesto')} "
                f"video={video.get('width')}x{video.get('height')} "
                f"video_bitrate={video.get('bandwidth')} "
                f"audio_codec={str(audio.get('codecs') or '')[:40]} "
                f"audio_bitrate={audio.get('bandwidth')}"
            )

            _baixar_url_facebook_dash(
                video["url"],
                video_path,
                referer=url_final,
                tipo="video",
            )
            _baixar_url_facebook_dash(
                audio["url"],
                audio_path,
                referer=url_final,
                tipo="audio",
            )

            info_video = obter_info_midia(video_path)
            info_audio = obter_info_midia(audio_path)

            if not info_video.get("vcodec"):
                raise RuntimeError("FACEBOOK_DASH_FAIXA_VIDEO_INVALIDA")
            if not arquivo_possui_audio(info_audio):
                raise RuntimeError("FACEBOOK_DASH_FAIXA_AUDIO_INVALIDA")

            _muxar_facebook_dash(video_path, audio_path, saida_path)

            # Remove as faixas separadas; deixa somente o MP4 final.
            for caminho in (video_path, audio_path):
                try:
                    if os.path.exists(caminho):
                        os.remove(caminho)
                except OSError:
                    pass

            return saida_path

        except Exception as e:
            ultimo_erro = e
            logger.warning(
                "[FACEBOOK_DASH_TENTATIVA_FALHA] "
                f"tentativa={tentativa} "
                f"erro={sanitizar_erro_log(e)}"
            )
            for caminho in (video_path, audio_path, saida_path):
                try:
                    if os.path.exists(caminho):
                        os.remove(caminho)
                except OSError:
                    pass

    raise RuntimeError(
        "FACEBOOK_DASH_FALLBACK_FALHOU "
        + sanitizar_erro_log(ultimo_erro or "sem_detalhe", limite=200)
    )


def extrair_info_facebook_com_fallback(url):
    """
    Prefere uma origem pública com áudio confirmado.

    True  -> áudio confirmado: usa a origem.
    False -> sem áudio confirmado: tenta a página pública alternativa.
    None  -> metadados inconclusivos: deixa o download seguir para que
             o ffprobe confirme o áudio no arquivo real.
    """
    primeiro_info = None
    ultimo_erro = None

    try:
        logger.info(
            "[FACEBOOK_REELS_INFO] modo=reel_publico "
            f"url_ref={referencia_url_log(url)}"
        )
        with yt_dlp.YoutubeDL(
            montar_info_opts(is_facebook_reel=True)
        ) as ydl:
            primeiro_info = ydl.extract_info(url, download=False)
            resumir_formatos_facebook(primeiro_info, origem="reel_publico")
    except FalhaComponenteDownload:
        raise
    except Exception as e:
        ultimo_erro = e
        logger.warning(
            "[FACEBOOK_REELS_INFO_FALHA] modo=reel_publico "
            f"url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )

    audio_primeira_consulta = info_plataforma_indica_audio(primeiro_info)

    if audio_primeira_consulta is True:
        return primeiro_info

    # Metadados inconclusivos não significam ausência de áudio.
    # O arquivo real será validado depois com ffprobe.
    if audio_primeira_consulta is None and primeiro_info is not None:
        logger.info(
            "[FACEBOOK_REELS_INFO_AUDIO_INCONCLUSIVO] "
            "modo=reel_publico proxima_etapa=ffprobe"
        )
        return primeiro_info

    # Só chegamos ao fallback quando os metadados realmente indicam
    # ausência de áudio ou quando a primeira extração falhou.
    if audio_primeira_consulta is False:
        diagnosticar_pagina_facebook_audio(
            url,
            origem="reel_publico",
        )

    video_id = extrair_id_facebook_para_fallback(primeiro_info, url)
    if not video_id:
        logger.warning(
            "[FACEBOOK_REELS_INFO_SEM_AUDIO] modo=reel_publico "
            f"audio_disponivel={audio_primeira_consulta} "
            "fallback_disponivel=False"
        )
        if primeiro_info is not None:
            logger.info(
                "[FACEBOOK_REELS_PROBE_REAL] "
                "origem=reel_publico motivo=metadata_sem_audio "
                "proxima_etapa=baixar_hd_sd_e_ffprobe"
            )
            return primeiro_info
        if ultimo_erro is not None:
            raise ultimo_erro
        raise RuntimeError("FACEBOOK_AUDIO_INDISPONIVEL_PUBLICO")

    url_alternativa = (
        "https://m.facebook.com/watch/?"
        f"{urlencode({'v': video_id})}"
    )

    logger.warning(
        "[FACEBOOK_REELS_INFO_SEM_AUDIO] modo=reel_publico "
        f"audio_disponivel={audio_primeira_consulta} "
        "proxima_tentativa=pagina_publica_alternativa"
    )

    try:
        logger.info(
            "[FACEBOOK_REELS_INFO] modo=pagina_publica_alternativa "
            f"url_ref={referencia_url_log(url_alternativa)}"
        )
        with yt_dlp.YoutubeDL(
            montar_info_opts(is_facebook_reel=True)
        ) as ydl:
            info_alternativa = ydl.extract_info(
                url_alternativa,
                download=False,
            )
            resumir_formatos_facebook(
                info_alternativa,
                origem="pagina_publica_alternativa",
            )
    except FalhaComponenteDownload:
        raise
    except Exception as e:
        logger.warning(
            "[FACEBOOK_REELS_INFO_FALHA] "
            "modo=pagina_publica_alternativa "
            f"url_ref={referencia_url_log(url_alternativa)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        if primeiro_info is not None:
            logger.info(
                "[FACEBOOK_REELS_PROBE_REAL] "
                "origem=reel_publico motivo=fallback_falhou "
                "proxima_etapa=baixar_hd_sd_e_ffprobe"
            )
            return primeiro_info
        raise RuntimeError("FACEBOOK_AUDIO_INDISPONIVEL_PUBLICO") from e

    audio_alternativo = info_plataforma_indica_audio(info_alternativa)

    if audio_alternativo is True:
        logger.info(
            "[FACEBOOK_REELS_INFO_FALLBACK_OK] "
            "modo=pagina_publica_alternativa audio_disponivel=True"
        )
        return info_alternativa

    # Também não rejeita a página alternativa quando os metadados
    # forem inconclusivos. O ffprobe decide depois.
    if audio_alternativo is None:
        logger.info(
            "[FACEBOOK_REELS_INFO_AUDIO_INCONCLUSIVO] "
            "modo=pagina_publica_alternativa proxima_etapa=ffprobe"
        )
        return info_alternativa

    if audio_alternativo is False:
        diagnosticar_pagina_facebook_audio(
            url_alternativa,
            origem="pagina_publica_alternativa",
        )

    logger.warning(
        "[FACEBOOK_REELS_INFO_SEM_AUDIO] "
        "modo=pagina_publica_alternativa "
        f"audio_disponivel={audio_alternativo} fallback_disponivel=False"
    )
    logger.info(
        "[FACEBOOK_REELS_PROBE_REAL] "
        "origem=pagina_publica_alternativa motivo=metadata_sem_audio "
        "proxima_etapa=baixar_hd_sd_e_ffprobe"
    )
    return info_alternativa

def resumir_formatos_instagram(info):
    """Registra codecs/formats sem expor URLs assinadas do Instagram."""
    formatos = (info or {}).get("formats") if isinstance(info, dict) else None
    if not isinstance(formatos, list):
        logger.info("[INSTAGRAM_FORMATOS] total=0")
        return

    resumo = []
    for item in formatos[:20]:
        if not isinstance(item, dict):
            continue
        resumo.append(
            "{id=%s ext=%s v=%s a=%s %sx%s fps=%s proto=%s}" % (
                item.get("format_id"),
                item.get("ext"),
                item.get("vcodec"),
                item.get("acodec"),
                item.get("width"),
                item.get("height"),
                item.get("fps"),
                item.get("protocol"),
            )
        )

    logger.info(
        f"[INSTAGRAM_FORMATOS] total={len(formatos)} "
        f"itens={' '.join(resumo)[:3500]}"
    )



def formatos_progressivos_facebook(info):
    """
    Prioriza os MP4 progressivos 'hd' e 'sd' do Facebook.

    O Facebook pode publicar esses formatos com acodec/vcodec ausentes nos
    metadados. Por isso não confiamos apenas no campo acodec: o arquivo é
    baixado e o ffprobe confirma se existe áudio real.
    """
    formatos = (info or {}).get("formats") if isinstance(info, dict) else None
    if not isinstance(formatos, list):
        return []

    por_id = {}
    for item in formatos:
        if not isinstance(item, dict):
            continue
        format_id = str(item.get("format_id") or "").strip()
        if not format_id:
            continue
        por_id.setdefault(format_id.lower(), item)

    candidatos = []
    for preferido in ("hd", "sd"):
        item = por_id.get(preferido)
        if not item:
            continue
        if str(item.get("ext") or "").strip().lower() != "mp4":
            continue
        candidatos.append(str(item.get("format_id")))

    if candidatos:
        logger.info(
            "[FACEBOOK_PROGRESSIVOS] "
            f"candidatos={','.join(candidatos)} "
            "validacao=ffprobe"
        )
    else:
        logger.info("[FACEBOOK_PROGRESSIVOS] candidatos=nenhum")

    return candidatos


def formatos_progressivos_instagram(info):
    """Retorna MP4s HTTP diretos antes dos DASH video-only.

    O Instagram frequentemente expõe os codecs desses MP4s como desconhecidos
    (None/unknown), embora o arquivo final possa ser H.264 + AAC. Por isso cada
    candidato é baixado e confirmado com ffprobe antes de ser aceito.
    """
    formatos = (info or {}).get("formats") if isinstance(info, dict) else None
    if not isinstance(formatos, list):
        return []

    candidatos = []
    for item in formatos:
        if not isinstance(item, dict):
            continue
        format_id = str(item.get("format_id") or "").strip()
        if not format_id or format_id.lower().startswith("dash-"):
            continue
        if str(item.get("ext") or "").lower() != "mp4":
            continue
        protocolo = str(item.get("protocol") or "").lower()
        if protocolo and not protocolo.startswith("http"):
            continue

        # Mesmo quando o Instagram informa acodec=none, ainda vale testar os
        # MP4 HTTP diretos. O campo has_audio da resposta pública pode não
        # descrever corretamente o arquivo progressivo entregue pelo CDN.
        # A decisão final é sempre feita com ffprobe no arquivo real.
        largura = item.get("width")
        altura = item.get("height")
        try:
            if largura and int(largura) > 720:
                continue
            if altura and int(altura) > 1280:
                continue
        except (TypeError, ValueError):
            pass

        candidatos.append(format_id)

    # Remove duplicados preservando a ordem entregue pelo Instagram.
    candidatos = list(dict.fromkeys(candidatos))
    logger.info(
        f"[INSTAGRAM_PROGRESSIVOS] total={len(candidatos)} "
        f"ids={','.join(candidatos[:12])}"
    )
    return candidatos



def extrair_shortcode_instagram(url):
    match = re.search(
        r"https?://(?:www\.)?instagram\.com/(?:[^/?#]+/)?(?:p|reels?|tv)/([^/?#&]+)",
        str(url or ""),
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _normalizar_url_escapada_instagram(valor):
    """Converte URLs escapadas de JSON/HTML sem aceitar esquemas arbitrários."""
    texto = html.unescape(str(valor or "").strip())
    if not texto:
        return None

    # Campos JSON do Instagram costumam usar \/ e escapes unicode.
    texto = texto.replace(r"\/", "/")
    texto = re.sub(
        r"\\u([0-9a-fA-F]{4})",
        lambda m: chr(int(m.group(1), 16)),
        texto,
    )
    texto = texto.replace(r"\\&", "&")

    if texto.startswith("//"):
        texto = "https:" + texto
    if not texto.startswith(("http://", "https://")):
        return None
    return texto


def _host_midia_instagram_permitido(url):
    try:
        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        host = parsed.hostname.lower().rstrip(".")
        return any(
            hostname_permitido(host, dominio)
            for dominio in ("cdninstagram.com", "fbcdn.net", "instagram.com")
        )
    except Exception:
        return False


def extrair_urls_midia_instagram_html(webpage):
    """Coleta apenas URLs de vídeo de dados públicos da página/embeds."""
    texto = str(webpage or "")
    if not texto:
        return []

    candidatos = []

    # Metadados HTML comuns. Em algumas respostas públicas, og:video aponta
    # para um MP4 progressivo diferente da lista DASH da API.
    for padrao in (
        r'<meta[^>]+property=["\']og:video(?::url|:secure_url)?["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::url|:secure_url)?["\']',
        r'<meta[^>]+name=["\']twitter:player:stream["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:player:stream["\']',
    ):
        candidatos.extend(re.findall(padrao, texto, flags=re.IGNORECASE))

    # JSON-LD e dados serializados do React/Relay.
    for chave in ("video_url", "videoUrl", "contentUrl", "content_url"):
        padrao = rf'["\']{re.escape(chave)}["\']\s*:\s*["\']((?:\\.|[^"\'])+)["\']'
        candidatos.extend(re.findall(padrao, texto, flags=re.IGNORECASE))

    # Último recurso: URLs CDN explicitamente terminadas em mp4 dentro do HTML.
    # Limita-se a domínios de mídia do ecossistema Instagram/Meta.
    candidatos.extend(re.findall(
        r'(https?:\\?/\\?/(?:[^"\'<>\\\s]+\.)?(?:cdninstagram\.com|fbcdn\.net)/[^"\'<>\\\s]+?\.mp4(?:\?[^"\'<>\\\s]*)?)',
        texto,
        flags=re.IGNORECASE,
    ))

    resultado = []
    vistos = set()
    for bruto in candidatos:
        url = _normalizar_url_escapada_instagram(bruto)
        if not url or url in vistos:
            continue
        if not _host_midia_instagram_permitido(url):
            continue
        # Não faz DNS aqui para não multiplicar consultas; cada download valida
        # novamente o destino e seus redirects antes de transferir bytes.
        if not validar_url_http_publica(url, resolver_dns=False):
            continue
        vistos.add(url)
        resultado.append(url)
        if len(resultado) >= 16:
            break
    return resultado


def _obter_pagina_publica_instagram(url):
    """Busca página pública sem cookies, preferindo fingerprint de navegador."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    if not validar_url_http_publica(url):
        raise RuntimeError("INSTAGRAM_PAGINA_DESTINO_NAO_PUBLICO")

    if curl_requests is not None:
        resposta = curl_requests.get(
            url,
            impersonate="chrome",
            timeout=20,
            headers=headers,
            allow_redirects=True,
        )
        final_url = str(getattr(resposta, "url", url) or url)
        if not detectar_plataforma_url(final_url)[2]:
            raise RuntimeError("INSTAGRAM_PAGINA_REDIRECIONOU_FORA")
        if int(getattr(resposta, "status_code", 0) or 0) >= 400:
            raise RuntimeError(
                f"INSTAGRAM_PAGINA_HTTP_{getattr(resposta, 'status_code', 0)}"
            )
        return str(getattr(resposta, "text", "") or "")

    resposta, final_url = seguir_redirecionamentos_seguros(url, headers=headers)
    try:
        if not detectar_plataforma_url(final_url)[2]:
            raise RuntimeError("INSTAGRAM_PAGINA_REDIRECIONOU_FORA")
        return resposta.text
    finally:
        resposta.close()


def coletar_urls_publicas_instagram(url):
    """Tenta página canônica e embeds oficiais, sem cookies/credenciais."""
    shortcode = extrair_shortcode_instagram(url)
    if not shortcode:
        return []

    parsed = urlparse(normalizar_url_instagram(url))
    tipo = "reel" if "/reel/" in (parsed.path or "").lower() else "p"
    paginas = [
        f"https://www.instagram.com/{tipo}/{shortcode}/",
        f"https://www.instagram.com/{tipo}/{shortcode}/embed/",
        f"https://www.instagram.com/{tipo}/{shortcode}/embed/captioned/",
        f"https://www.instagram.com/p/{shortcode}/",
        f"https://www.instagram.com/p/{shortcode}/embed/",
    ]
    paginas = list(dict.fromkeys(paginas))

    urls = []
    vistos = set()
    for indice, pagina in enumerate(paginas, start=1):
        try:
            logger.info(
                f"[INSTAGRAM_HTML_PAGINA] tentativa={indice}/{len(paginas)} "
                f"url_ref={referencia_url_log(pagina)}"
            )
            webpage = _obter_pagina_publica_instagram(pagina)
            encontrados = extrair_urls_midia_instagram_html(webpage)
            logger.info(
                f"[INSTAGRAM_HTML_CANDIDATOS] pagina={indice} "
                f"total={len(encontrados)}"
            )
            for candidato in encontrados:
                if candidato in vistos:
                    continue
                vistos.add(candidato)
                urls.append(candidato)
                if len(urls) >= 16:
                    return urls
        except Exception as e:
            logger.warning(
                f"[INSTAGRAM_HTML_PAGINA_FALHA] pagina={indice} "
                f"erro={sanitizar_erro_log(e)}"
            )
    return urls


def baixar_url_midia_instagram_publica(url_midia, destino, referer):
    """Baixa um candidato CDN com limite de tamanho e redirects validados."""
    atual = str(url_midia or "").strip()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151.0.0.0 Safari/537.36"
        ),
        "Accept": "video/av,video/mp4,video/*;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": referer,
    }

    resposta = None
    total = 0
    try:
        for _ in range(6):
            if not _host_midia_instagram_permitido(atual):
                raise RuntimeError("INSTAGRAM_MIDIA_HOST_NAO_PERMITIDO")
            if not validar_url_http_publica(atual):
                raise RuntimeError("INSTAGRAM_MIDIA_DESTINO_NAO_PUBLICO")

            resposta = requests.get(
                atual,
                headers=headers,
                stream=True,
                allow_redirects=False,
                timeout=(7, 25),
            )
            if resposta.status_code in (301, 302, 303, 307, 308):
                destino_redirect = urljoin(
                    atual, resposta.headers.get("Location") or ""
                )
                resposta.close()
                resposta = None
                if not destino_redirect or destino_redirect == atual:
                    raise RuntimeError("INSTAGRAM_MIDIA_REDIRECT_INVALIDO")
                atual = destino_redirect
                continue

            resposta.raise_for_status()
            tamanho_header = resposta.headers.get("Content-Length")
            if tamanho_header:
                try:
                    if int(tamanho_header) > MAX_SOURCE_FILE_BYTES:
                        raise RuntimeError("ARQUIVO_MIDIA_MUITO_GRANDE fase=instagram_html")
                except ValueError:
                    pass

            with open(destino, "wb") as arquivo:
                for chunk in resposta.iter_content(chunk_size=256 * 1024):
                    atualizar_heartbeat_worker("baixando_instagram_html")
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_SOURCE_FILE_BYTES:
                        raise RuntimeError("ARQUIVO_MIDIA_MUITO_GRANDE fase=instagram_html")
                    arquivo.write(chunk)
            return total

        raise RuntimeError("INSTAGRAM_MIDIA_MUITOS_REDIRECTS")
    finally:
        if resposta is not None:
            resposta.close()


def baixar_instagram_publico_com_audio(url, prefix):
    """Fallback público: procura MP4 oficial no HTML e só aceita áudio real."""
    candidatos = coletar_urls_publicas_instagram(url)
    logger.info(
        f"[INSTAGRAM_HTML_FALLBACK] candidatos={len(candidatos)} "
        f"url_ref={referencia_url_log(url)}"
    )
    if not candidatos:
        return None

    ultimo_erro = None
    for indice, candidato in enumerate(candidatos[:12], start=1):
        try:
            cleanup_prefix(prefix)
            destino = f"{prefix}.igpublic.mp4"
            tamanho = baixar_url_midia_instagram_publica(
                candidato,
                destino,
                referer=normalizar_url_instagram(url),
            )
            info_midia = obter_info_midia(destino)
            tem_audio = arquivo_possui_audio(info_midia)
            logger.info(
                f"[INSTAGRAM_HTML_PROBE] candidato={indice}/{min(len(candidatos), 12)} "
                f"bytes={tamanho} tem_audio={tem_audio} "
                f"vcodec={info_midia.get('vcodec')} acodec={info_midia.get('acodec')}"
            )
            if tem_audio:
                logger.info(
                    f"[INSTAGRAM_HTML_AUDIO_OK] candidato={indice} "
                    f"arquivo_ref={referencia_arquivo_log(destino)}"
                )
                return destino
            ultimo_erro = "INSTAGRAM_HTML_CANDIDATO_SEM_AUDIO"
        except FalhaComponenteDownload:
            raise
        except Exception as e:
            ultimo_erro = e
            logger.warning(
                f"[INSTAGRAM_HTML_TENTATIVA_FALHA] candidato={indice} "
                f"erro={sanitizar_erro_log(e)}"
            )

    cleanup_prefix(prefix)
    logger.warning(
        "[INSTAGRAM_HTML_SEM_AUDIO] "
        f"tentativas={min(len(candidatos), 12)} "
        f"erro={sanitizar_erro_log(ultimo_erro)}"
    )
    return None


def extrair_info_instagram_com_fallback(url):
    """Consulta o Instagram somente em modo público/anônimo.

    Cookies e credenciais de conta do Instagram ficam deliberadamente
    desativados para evitar qualquer dependência de uma sessão pessoal.
    """
    logger.info(
        "[INSTAGRAM_INFO] modo=anonima usar_cookies=False "
        f"url_ref={referencia_url_log(url)}"
    )
    try:
        opts = montar_info_opts(is_instagram=True, usar_cookies=False)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        audio_disponivel = info_plataforma_indica_audio(info)
        logger.info(
            "[INSTAGRAM_INFO_OK] "
            f"modo=anonima audio_disponivel={audio_disponivel}"
        )
        resumir_formatos_instagram(info)
        return info, False
    except FalhaComponenteDownload:
        raise
    except Exception as e:
        logger.warning(
            "[INSTAGRAM_INFO_FALHA] modo=anonima usar_cookies=False "
            f"url_ref={referencia_url_log(url)} "
            f"erro={sanitizar_erro_log(e)}"
        )
        raise

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
            return "❌ Esse conteúdo do Instagram não está disponível pelo acesso público no momento."
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

    if plataforma in ("shopee", "shopee_video"):
        if "watermark_video_url_nao_encontrada" in err or "original_nao_derivado" in err:
            return (
                "❌ Não consegui localizar o vídeo original sem marca d'água "
                "nesse link da Shopee Video. Tente outro vídeo."
            )
        if "audio_ausente" in err:
            return "❌ A Shopee não forneceu o vídeo original com áudio nesse link."
        if "403" in err or "429" in err:
            return "❌ A Shopee bloqueou temporariamente esse acesso. Tente novamente em instantes."
        if "404" in err:
            return "❌ Esse vídeo da Shopee não está mais disponível."
        if "timeout" in err or "timed out" in err:
            return "❌ A Shopee demorou para responder. Tente novamente."
        if "redirecionamento_fora_da_plataforma" in err:
            return "❌ Envie um link válido de Shopee Video."
        return "❌ Não consegui baixar esse vídeo da Shopee agora."

    if plataforma in ("mercado_livre_clips", "mercado livre clips", "mercadolivre", "ml_clips"):
        if "video_url_nao_encontrada" in err or "short_nao_encontrado" in err:
            return "❌ Não consegui localizar esse Mercado Livre Clip. Tente outro link."
        if "audio_ausente" in err:
            return "❌ O Mercado Livre não forneceu esse Clip com áudio."
        if "video_muito_longo" in err:
            return f"⚠️ Clip muito longo. O limite é de {MAX_DURATION_SECONDS} segundos."
        if "403" in err or "429" in err:
            return "❌ O Mercado Livre bloqueou temporariamente esse acesso. Tente novamente em instantes."
        if "404" in err:
            return "❌ Esse Mercado Livre Clip não está mais disponível."
        if "timeout" in err or "timed out" in err:
            return "❌ O Mercado Livre demorou para responder. Tente novamente."
        if "host_invalido" in err or "redirecionamento" in err:
            return "❌ Envie um link válido de Mercado Livre Clips."
        return "❌ Não consegui baixar esse Mercado Livre Clip agora."

    if plataforma in ("facebook", "facebook_reels"):
        if (
            "facebook_reels_somente" in err
            or "redirecionamento_fora_da_plataforma" in err
            or "unsupported url" in err
        ):
            return (
                "❌ Envie somente o link público de um Facebook Reel. "
                "Vídeos comuns, lives, grupos e conteúdos privados não são "
                "suportados."
            )
        if (
            "facebook_audio_ausente_no_arquivo" in err
            or "facebook_audio_indisponivel_publico" in err
        ):
            return (
                "❌ O Facebook não forneceu uma versão completa com áudio "
                "deste Reel. Tente novamente em alguns instantes."
            )
        if "private" in err or "login required" in err:
            return "❌ Esse Facebook Reel é privado ou exige login."
        if "403" in err or "429" in err:
            return (
                "❌ O Facebook bloqueou temporariamente esse Reel. "
                "Aguarde alguns instantes e tente novamente."
            )
        if "timed out" in err or "timeout" in err:
            return "❌ O Facebook demorou para responder. Tente novamente."
        return "❌ Não consegui baixar esse Facebook Reel público agora."

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
    valor = str(valor_str or "").strip()
    if valor not in PLANOS_VENDA_ATIVOS:
        logger.info(
            "[PLANO_NAO_DISPONIVEL_NOVA_COMPRA] "
            f"plano_key={valor[:20] or 'vazio'}"
        )
        return None
    return PLANOS.get(valor)


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
                "ultima_data": hoje_str(),
                "vip_sync_last_source": "novo_pagamento",
                "vip_sync_last_checked_at": agora_tz(),
            },
            "$setOnInsert": {
                "downloads_hoje": 0
            },
            "$unset": {
                "vip_sync_bloqueado": "",
                "vip_sync_bloqueado_em": "",
                "vip_sync_bloqueado_motivo": "",
                "vip_sync_erro": "",
            },
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


def _vip_ate_comparavel(valor):
    if valor == "Vitalício":
        return (2, None)

    try:
        data = datetime.strptime(str(valor or ""), "%Y-%m-%d").date()
        return (1, data)
    except Exception:
        return (0, None)


def _vip_ate_maior(a, b):
    tipo_a, data_a = _vip_ate_comparavel(a)
    tipo_b, data_b = _vip_ate_comparavel(b)

    if tipo_a == 2 or tipo_b == 2:
        return "Vitalício"

    if tipo_a == 1 and tipo_b == 1:
        return a if data_a >= data_b else b

    if tipo_a == 1:
        return a
    if tipo_b == 1:
        return b
    return None


def garantir_vip_pago_sincronizado(
    user_id,
    vip_ate_esperado,
    order_nsu=None,
    origem="pagamento",
):
    """Garante que um pagamento já confirmado esteja refletido no usuário.

    Nunca reduz uma validade já maior e respeita bloqueio administrativo
    explícito criado por /removervip.
    """
    uid = str(user_id or "").strip()
    esperado = str(vip_ate_esperado or "").strip()

    if not uid or not esperado:
        return {
            "ok": False,
            "corrigido": False,
            "motivo": "dados_incompletos",
        }

    lock_usuario = obter_lock_distribuido_local(uid, PAYMENT_USER_LOCKS)

    with lock_usuario:
        usuario = usuarios_col.find_one({"_id": uid}) or {}

        if usuario.get("vip_sync_bloqueado"):
            logger.warning(
                "[VIP_SYNC_BLOQUEADO] "
                f"user_ref={referencia_usuario_log(uid)} "
                f"origem={origem}"
            )
            return {
                "ok": True,
                "corrigido": False,
                "motivo": "bloqueio_admin",
                "vip_ate": usuario.get("vip_ate"),
            }

        atual = usuario.get("vip_ate")
        alvo = _vip_ate_maior(atual, esperado) or esperado

        # Se o usuário já está igual ou melhor, apenas garante o vínculo do
        # pedido e limpa qualquer marca de reparo antigo.
        precisa_corrigir = atual != alvo

        update = {
            "$set": {
                "vip_sync_last_checked_at": agora_tz(),
                "vip_sync_last_source": str(origem)[:80],
            },
            "$setOnInsert": {
                "downloads_hoje": 0,
                "ultima_data": hoje_str(),
            },
            "$unset": {
                "vip_sync_erro": "",
            },
        }

        if precisa_corrigir:
            update["$set"]["vip_ate"] = alvo
            update["$set"]["vip_sync_last_repaired_at"] = agora_tz()

        if order_nsu:
            update["$addToSet"] = {
                "vip_orders_aplicados": str(order_nsu),
            }

        resultado = usuarios_col.update_one(
            {"_id": uid},
            update,
            upsert=True,
        )

        confirmado = usuarios_col.find_one(
            {"_id": uid},
            {
                "vip_ate": 1,
                "vip_orders_aplicados": 1,
                "vip_sync_bloqueado": 1,
            },
        ) or {}

        vip_confirmado = confirmado.get("vip_ate")
        alvo_confirmado = _vip_ate_maior(vip_confirmado, esperado)

        if vip_confirmado != alvo_confirmado:
            usuarios_col.update_one(
                {"_id": uid},
                {
                    "$set": {
                        "vip_sync_erro": "vip_ate_nao_confirmado",
                        "vip_sync_last_checked_at": agora_tz(),
                    }
                },
            )
            logger.error(
                "[VIP_SYNC_FALHA] "
                f"user_ref={referencia_usuario_log(uid)} "
                f"pedido_ref={referencia_pedido_log(order_nsu) if order_nsu else 'sem_pedido'} "
                f"esperado={esperado} obtido={vip_confirmado} origem={origem}"
            )
            return {
                "ok": False,
                "corrigido": False,
                "motivo": "confirmacao_falhou",
                "vip_ate": vip_confirmado,
            }

        if precisa_corrigir:
            logger.warning(
                "[VIP_SYNC_REPARADO] "
                f"user_ref={referencia_usuario_log(uid)} "
                f"pedido_ref={referencia_pedido_log(order_nsu) if order_nsu else 'sem_pedido'} "
                f"antes={atual} depois={vip_confirmado} origem={origem}"
            )
        else:
            logger.info(
                "[VIP_SYNC_OK] "
                f"user_ref={referencia_usuario_log(uid)} "
                f"pedido_ref={referencia_pedido_log(order_nsu) if order_nsu else 'sem_pedido'} "
                f"vip_ate={vip_confirmado} origem={origem}"
            )

        return {
            "ok": True,
            "corrigido": bool(precisa_corrigir),
            "motivo": "reparado" if precisa_corrigir else "ja_sincronizado",
            "vip_ate": vip_confirmado,
            "db_changed": bool(
                resultado.modified_count or resultado.upserted_id
            ),
        }


def garantir_vip_de_pedido_pago(pedido, origem="pedido_pago"):
    if not pedido or pedido.get("status") != "paid":
        return {
            "ok": False,
            "corrigido": False,
            "motivo": "pedido_nao_pago",
        }

    # Segurança: status="paid" isolado não autoriza reativação.
    # A reconciliação só pode restaurar um VIP se o pedido registrar
    # explicitamente que a liberação final foi aplicada ao pedido.
    if not pedido.get("vip_aplicado_ao_pedido"):
        logger.warning(
            "[VIP_SYNC_PEDIDO_NAO_APLICADO] "
            f"pedido_ref={referencia_pedido_log(pedido.get('order_nsu'))} "
            f"user_ref={referencia_usuario_log(pedido.get('user_id'))} "
            f"origem={origem}"
        )
        return {
            "ok": True,
            "corrigido": False,
            "motivo": "pedido_sem_confirmacao_aplicacao_vip",
        }

    vip_ate = pedido.get("vip_liberado_ate")
    if not vip_ate:
        logger.warning(
            "[VIP_SYNC_PEDIDO_SEM_VALIDADE] "
            f"pedido_ref={referencia_pedido_log(pedido.get('order_nsu'))} "
            f"user_ref={referencia_usuario_log(pedido.get('user_id'))}"
        )
        return {
            "ok": False,
            "corrigido": False,
            "motivo": "pedido_sem_validade",
        }

    return garantir_vip_pago_sincronizado(
        pedido.get("user_id"),
        vip_ate,
        order_nsu=pedido.get("order_nsu"),
        origem=origem,
    )


def sincronizar_vips_pagos_ativos(notificar_admin=True):
    """Reconcilia pedidos pagos ainda válidos com a coleção de usuários.

    Só aumenta/restaura validade. Nunca reduz um VIP já maior.
    /removervip cria um bloqueio explícito para impedir reativação automática.
    """
    hoje = agora_tz().date()
    por_usuario = {}

    try:
        cursor = pedidos_col.find(
            {
                "status": "paid",
                "vip_aplicado_ao_pedido": True,
                "vip_liberado_ate": {
                    "$exists": True,
                    "$nin": [None, ""],
                },
            },
            {
                "_id": 0,
                "order_nsu": 1,
                "user_id": 1,
                "status": 1,
                "vip_liberado_ate": 1,
                "vip_aplicado_ao_pedido": 1,
            },
        )

        for pedido in cursor:
            uid = str(pedido.get("user_id") or "").strip()
            vip_ate = pedido.get("vip_liberado_ate")
            if not uid or not vip_ate:
                continue

            if vip_ate != "Vitalício":
                try:
                    data_vip = datetime.strptime(
                        str(vip_ate),
                        "%Y-%m-%d",
                    ).date()
                except Exception:
                    logger.warning(
                        "[VIP_SYNC_STARTUP_INVALIDO] "
                        f"pedido_ref={referencia_pedido_log(pedido.get('order_nsu'))} "
                        f"vip_ate={vip_ate}"
                    )
                    continue

                if data_vip < hoje:
                    continue

            atual = por_usuario.get(uid)
            if not atual:
                por_usuario[uid] = pedido
                continue

            melhor = _vip_ate_maior(
                atual.get("vip_liberado_ate"),
                vip_ate,
            )
            if melhor == vip_ate:
                por_usuario[uid] = pedido

    except Exception as e:
        registrar_falha_componente("MongoDB", e)
        logger.error(
            "[VIP_SYNC_STARTUP_LISTAR_FALHA] "
            f"erro={sanitizar_erro_log(e)}"
        )
        return {
            "verificados": 0,
            "corrigidos": 0,
            "bloqueados": 0,
            "ignorados": 0,
            "falhas": 1,
        }

    verificados = 0
    corrigidos = 0
    bloqueados = 0
    ignorados = 0
    falhas = 0

    for pedido in por_usuario.values():
        verificados += 1
        try:
            resultado = garantir_vip_de_pedido_pago(
                pedido,
                origem="startup_reconciliation",
            )
            motivo = resultado.get("motivo")
            if motivo == "bloqueio_admin":
                bloqueados += 1
            elif motivo == "pedido_sem_confirmacao_aplicacao_vip":
                ignorados += 1
            elif resultado.get("corrigido"):
                corrigidos += 1
            elif not resultado.get("ok"):
                falhas += 1
                logger.warning(
                    "[VIP_SYNC_STARTUP_RESULTADO_INVALIDO] "
                    f"pedido_ref={referencia_pedido_log(pedido.get('order_nsu'))} "
                    f"user_ref={referencia_usuario_log(pedido.get('user_id'))} "
                    f"motivo={str(resultado.get('motivo') or 'desconhecido')[:80]}"
                )
        except Exception as e:
            falhas += 1
            logger.error(
                "[VIP_SYNC_STARTUP_FALHA] "
                f"pedido_ref={referencia_pedido_log(pedido.get('order_nsu'))} "
                f"user_ref={referencia_usuario_log(pedido.get('user_id'))} "
                f"erro={sanitizar_erro_log(e)}"
            )

    logger.info(
        "[VIP_SYNC_STARTUP] "
        f"verificados={verificados} corrigidos={corrigidos} "
        f"bloqueados={bloqueados} ignorados={ignorados} falhas={falhas}"
    )

    if notificar_admin and (corrigidos or falhas):
        safe_send_message(
            ADMIN_ID,
            "💎 *Sincronização VIP concluída*\n\n"
            f"🔎 Pedidos elegíveis verificados: `{verificados}`\n"
            f"✅ VIPs corrigidos: `{corrigidos}`\n"
            f"🛑 Bloqueados manualmente: `{bloqueados}`\n"
            f"🧯 Ignorados por segurança: `{ignorados}`\n"
            f"❌ Falhas: `{falhas}`",
            parse_mode="Markdown",
        )

    return {
        "verificados": verificados,
        "corrigidos": corrigidos,
        "bloqueados": bloqueados,
        "ignorados": ignorados,
        "falhas": falhas,
    }


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
        sync = garantir_vip_de_pedido_pago(
            pedido,
            origem="pedido_ja_pago",
        )
        return {
            "pedido": pedido,
            "plano": PLANOS.get(pedido.get("plano_key")) or {},
            "vip_ate": sync.get("vip_ate") or pedido.get("vip_liberado_ate"),
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
        sync = garantir_vip_de_pedido_pago(
            pedido_final,
            origem="finalizacao_pagamento",
        )
        return {
            "pedido": pedido_final,
            "plano": plano,
            "vip_ate": sync.get("vip_ate") or vip_ate,
            "vip_aplicado": vip_aplicado,
            "finalizado_agora": True,
        }

    # Outra execução pode ter concluído o mesmo pedido entre a leitura e a
    # gravação. Aceita somente o estado final esperado.
    pedido_atual = pedidos_col.find_one({"order_nsu": order_nsu}) or {}
    if pedido_atual.get("status") == "paid":
        sync = garantir_vip_de_pedido_pago(
            pedido_atual,
            origem="finalizacao_concorrente",
        )
        return {
            "pedido": pedido_atual,
            "plano": plano,
            "vip_ate": (
                sync.get("vip_ate")
                or pedido_atual.get("vip_liberado_ate")
                or vip_ate
            ),
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
# AQUISIÇÃO / ORIGEM
# =========================================
def _normalizar_codigo_tracking(valor, limite=24):
    valor = str(valor or "").strip().lower()
    valor = re.sub(r"[^a-z0-9-]+", "-", valor)
    valor = re.sub(r"-+", "-", valor).strip("-")
    return valor[:limite]


def _extrair_payload_start(message):
    texto = str(getattr(message, "text", "") or "").strip()
    if not texto.lower().startswith("/start"):
        return ""

    partes = texto.split(maxsplit=1)
    if len(partes) < 2:
        return ""

    payload = partes[1].strip()
    # O Telegram limita start parameters; mantemos apenas caracteres seguros.
    payload = re.sub(r"[^A-Za-z0-9_-]+", "", payload)
    return payload[:64]


def _parsear_payload_aquisicao(payload):
    bruto = str(payload or "").strip()
    if not bruto:
        return {
            "origem": "organico",
            "campanha": None,
            "anuncio": None,
            "start_payload": None,
        }

    partes = [p for p in bruto.lower().split("_") if p]
    prefixo = partes[0] if partes else ""

    mapa_origem = {
        "fbads": "facebook_ads",
        "facebook": "facebook_ads",
        "meta": "facebook_ads",
        "igads": "instagram_ads",
        "instagram": "instagram",
        "yt": "youtube",
        "youtube": "youtube",
        "tiktok": "tiktok",
        "kwai": "kwai",
        "ref": "indicacao",
        "indicacao": "indicacao",
        "organico": "organico",
    }
    origem = mapa_origem.get(prefixo, "outro_deeplink")

    campanha = _normalizar_codigo_tracking(
        partes[1] if len(partes) >= 2 else None,
        24,
    ) or None
    anuncio = _normalizar_codigo_tracking(
        "-".join(partes[2:]) if len(partes) >= 3 else None,
        32,
    ) or None

    return {
        "origem": origem,
        "campanha": campanha,
        "anuncio": anuncio,
        "start_payload": bruto[:64],
    }


def registrar_inicio_e_origem(user_id, payload=""):
    """Registra origem somente na primeira aquisição conhecida.

    Usuários antigos sem origem só recebem atribuição se chegarem por um
    deep-link rastreável. A origem já registrada nunca é sobrescrita.
    """
    uid = str(user_id)
    agora = agora_tz()
    hoje = hoje_str()
    atribuicao = _parsear_payload_aquisicao(payload)

    documento_novo = {
        "_id": uid,
        "vip_ate": None,
        "downloads_hoje": 0,
        "ultima_data": hoje,
        "primeiro_acesso": agora,
        # ultimo_acesso é gravado pelo $set abaixo.
        # Não repetir o mesmo campo em $setOnInsert e $set,
        # pois o MongoDB rejeita a atualização por conflito de caminho.
        "origem": atribuicao["origem"],
        "origem_registrada_em": agora,
    }
    if atribuicao.get("campanha"):
        documento_novo["campanha"] = atribuicao["campanha"]
    if atribuicao.get("anuncio"):
        documento_novo["anuncio"] = atribuicao["anuncio"]
    if atribuicao.get("start_payload"):
        documento_novo["start_payload"] = atribuicao["start_payload"]

    # Cria novos usuários já com origem correta (inclusive orgânico).
    usuarios_col.update_one(
        {"_id": uid},
        {
            "$setOnInsert": documento_novo,
            "$set": {"ultimo_acesso": agora},
        },
        upsert=True,
    )

    # Para usuários legados, um deep-link rastreável pode preencher a origem
    # ausente; uma visita orgânica posterior não apaga nem inventa atribuição.
    if payload:
        filtro_sem_origem = {
            "_id": uid,
            "$or": [
                {"origem": {"$exists": False}},
                {"origem": None},
                {"origem": ""},
            ],
        }
        campos = {
            "origem": atribuicao["origem"],
            "origem_registrada_em": agora,
            "start_payload": atribuicao["start_payload"],
        }
        if atribuicao.get("campanha"):
            campos["campanha"] = atribuicao["campanha"]
        if atribuicao.get("anuncio"):
            campos["anuncio"] = atribuicao["anuncio"]

        resultado = usuarios_col.update_one(
            filtro_sem_origem,
            {"$set": campos},
        )
        if resultado.modified_count:
            logger.info(
                "[AQUISICAO_REGISTRADA] "
                f"user_ref={referencia_usuario_log(uid)} "
                f"origem={atribuicao['origem']} "
                f"campanha={atribuicao.get('campanha') or 'na'} "
                f"anuncio={atribuicao.get('anuncio') or 'na'}"
            )

    return atribuicao


def atualizar_ultimo_acesso_usuario(user_id, forcar=False):
    """Atualiza último acesso sem gerar uma escrita a cada download.

    Por padrão, grava no máximo uma vez por dia, aproveitando o campo
    ultima_data já usado pelo controle diário do bot.
    """
    uid = str(user_id)
    agora = agora_tz()
    hoje = hoje_str()
    filtro = {"_id": uid}
    if not forcar:
        filtro["ultima_data"] = {"$ne": hoje}

    try:
        usuarios_col.update_one(
            filtro,
            {"$set": {"ultimo_acesso": agora}},
        )
    except Exception as e:
        logger.warning(
            "[ULTIMO_ACESSO] "
            f"user_ref={referencia_usuario_log(uid)} "
            f"erro={sanitizar_erro_log(e)}"
        )


# =========================================
# USUÁRIO / VIP
# =========================================
def _obter_usuario_db(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    hoje = hoje_str()

    if not user:
        agora = agora_tz()
        user = {
            "_id": uid,
            "vip_ate": None,
            "downloads_hoje": 0,
            "ultima_data": hoje,
            "primeiro_acesso": agora,
            "ultimo_acesso": agora,
            "origem": "organico",
            "origem_registrada_em": agora,
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

    if "ultimo_acesso" not in user:
        alteracoes["ultimo_acesso"] = agora_tz()
        user["ultimo_acesso"] = alteracoes["ultimo_acesso"]

    if alteracoes:
        usuarios_col.update_one({"_id": uid}, {"$set": alteracoes})

    if user.get("ultima_data") != hoje:
        usuarios_col.update_one(
            {"_id": uid},
            {
                "$set": {
                    "downloads_hoje": 0,
                    "ultima_data": hoje,
                    "ultimo_acesso": agora_tz(),
                },
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
            )
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
        types.BotCommand("syncvip", "Sincronizar pagamentos e VIPs"),
        types.BotCommand("linkads", "Gerar link rastreável para anúncio"),
        types.BotCommand("origens", "Ver origem e conversão dos usuários"),
        types.BotCommand("backupvips", "Gerar backup dos VIPs ativos"),
        types.BotCommand("backupgeral", "Gerar backup completo"),
        types.BotCommand("verificarbackup", "Testar backup sem alterar produção"),
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
        types.InlineKeyboardButton(
            "💠 VIP Mensal - R$ 10,00 via Pix",
            callback_data="pay_10.00",
        )
    )

    texto = (
        "🚀 *LIBERAR ACESSO VIP*\n\n"
        "VIP Mensal por *R$ 10,00* com 30 dias de acesso.\n\n"
        "✅ Sem limite diário\n"
        "✅ Prioridade no processamento\n"
        "✅ TikTok, Pinterest, Instagram, Facebook Reels, Shopee Video, "
        "Mercado Livre Clips e RedNote\n"
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
        "schema_version": 2,
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
        # Backup de restauração: documento completo para não perder campos
        # adicionados em versões novas (origem, sincronização VIP, etc.).
        docs = list(
            usuarios_col.find({}).sort("_id", 1)
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
                }
            ).sort("vip_ate", -1)
        )
        return docs, "backup_vips_ativos", "💎 Backup de VIPs ativos gerado"

    if tipo == "pedidos":
        docs = list(
            pedidos_col.find({}).sort("created_at", -1)
        )
        return docs, "backup_pedidos", "🧾 Backup de pedidos gerado"

    if tipo == "geral":
        usuarios_docs = list(
            usuarios_col.find({}).sort("_id", 1)
        )
        vips_docs = list(
            usuarios_col.find(
                {
                    "$or": [
                        {"vip_ate": "Vitalício"},
                        {"vip_ate": {"$gte": hoje}}
                    ]
                }
            ).sort("vip_ate", -1)
        )
        pedidos_docs = list(
            pedidos_col.find({}).sort("created_at", -1)
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
            "schema_version": 2,
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
                + int(payload.get("auditoria_sistema_count", 0))
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



def _vip_backup_ativo(vip_ate, hoje=None):
    hoje = hoje or agora_tz().date()
    if vip_ate == "Vitalício":
        return True
    try:
        return datetime.strptime(str(vip_ate or ""), "%Y-%m-%d").date() >= hoje
    except Exception:
        return False


def _vip_backup_cobre(vip_usuario, vip_esperado):
    """Retorna True se o VIP do usuário cobre a validade esperada."""
    if vip_usuario == "Vitalício":
        return True
    if vip_esperado == "Vitalício":
        return vip_usuario == "Vitalício"
    try:
        atual = datetime.strptime(str(vip_usuario or ""), "%Y-%m-%d").date()
        esperado = datetime.strptime(str(vip_esperado or ""), "%Y-%m-%d").date()
        return atual >= esperado
    except Exception:
        return False


def validar_payload_backup_geral(payload):
    """Valida um backup geral sem escrever nada no MongoDB.

    A 'restauração' é simulada em estruturas temporárias na memória.
    """
    erros = []
    avisos = []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "erros": ["payload_nao_e_objeto"],
            "avisos": [],
            "contagens": {},
            "dry_run": False,
        }

    if payload.get("backup_type") != "geral":
        erros.append("backup_type_invalido")

    secoes = {
        "usuarios": "usuarios_count",
        "vips_ativos": "vips_ativos_count",
        "pedidos": "pedidos_count",
        "metricas_diarias": "metricas_diarias_count",
        "auditoria_admin": "auditoria_admin_count",
        "auditoria_sistema": "auditoria_sistema_count",
    }

    contagens = {}
    for nome, campo_count in secoes.items():
        docs = payload.get(nome)
        if not isinstance(docs, list):
            erros.append(f"{nome}_nao_e_lista")
            docs = []
        esperado = payload.get(campo_count)
        try:
            esperado = int(esperado)
        except Exception:
            erros.append(f"{campo_count}_invalido")
            esperado = -1

        real = len(docs)
        contagens[nome] = real
        if esperado != real:
            erros.append(f"{campo_count}_diverge_{esperado}_{real}")

    usuarios = payload.get("usuarios") if isinstance(payload.get("usuarios"), list) else []
    vips = payload.get("vips_ativos") if isinstance(payload.get("vips_ativos"), list) else []
    pedidos = payload.get("pedidos") if isinstance(payload.get("pedidos"), list) else []
    metricas = (
        payload.get("metricas_diarias")
        if isinstance(payload.get("metricas_diarias"), list)
        else []
    )
    aud_admin = (
        payload.get("auditoria_admin")
        if isinstance(payload.get("auditoria_admin"), list)
        else []
    )
    aud_sistema = (
        payload.get("auditoria_sistema")
        if isinstance(payload.get("auditoria_sistema"), list)
        else []
    )

    # -----------------------------
    # Simulação de restauração
    # -----------------------------
    usuarios_temp = {}
    for i, doc in enumerate(usuarios):
        if not isinstance(doc, dict):
            erros.append(f"usuario_{i}_nao_e_objeto")
            continue
        uid = str(doc.get("_id") or "").strip()
        if not uid:
            erros.append(f"usuario_{i}_sem_id")
            continue
        if uid in usuarios_temp:
            erros.append(f"usuario_id_duplicado_{uid[:12]}")
            continue
        usuarios_temp[uid] = dict(doc)

    pedidos_temp = {}
    pedidos_sem_usuario = 0
    pedidos_pagos_ativos_divergentes = 0
    hoje = agora_tz().date()

    for i, doc in enumerate(pedidos):
        if not isinstance(doc, dict):
            erros.append(f"pedido_{i}_nao_e_objeto")
            continue

        nsu = str(doc.get("order_nsu") or "").strip()
        if not nsu:
            erros.append(f"pedido_{i}_sem_order_nsu")
            continue
        if nsu in pedidos_temp:
            erros.append(f"order_nsu_duplicado_{nsu[:16]}")
            continue
        pedidos_temp[nsu] = dict(doc)

        uid = str(doc.get("user_id") or "").strip()
        if uid and uid not in usuarios_temp:
            pedidos_sem_usuario += 1

        vip_esperado = doc.get("vip_liberado_ate")
        if (
            doc.get("status") == "paid"
            and vip_esperado
            and _vip_backup_ativo(vip_esperado, hoje)
        ):
            usuario = usuarios_temp.get(uid) or {}
            # Remoção manual é intencional: não é divergência de backup.
            if not usuario.get("vip_sync_bloqueado") and not _vip_backup_cobre(
                usuario.get("vip_ate"),
                vip_esperado,
            ):
                pedidos_pagos_ativos_divergentes += 1

    vips_ids = set()
    vips_fora_usuarios = 0
    vips_invalidos = 0
    for i, doc in enumerate(vips):
        if not isinstance(doc, dict):
            erros.append(f"vip_{i}_nao_e_objeto")
            continue
        uid = str(doc.get("_id") or "").strip()
        if not uid:
            erros.append(f"vip_{i}_sem_id")
            continue
        if uid in vips_ids:
            erros.append(f"vip_id_duplicado_{uid[:12]}")
            continue
        vips_ids.add(uid)
        if uid not in usuarios_temp:
            vips_fora_usuarios += 1
        if not _vip_backup_ativo(doc.get("vip_ate"), hoje):
            vips_invalidos += 1

    def _simular_colecao(docs, chave_preferida=None):
        temp = {}
        for pos, doc in enumerate(docs):
            if not isinstance(doc, dict):
                continue
            chave = doc.get(chave_preferida) if chave_preferida else doc.get("_id")
            if chave is None:
                # Auditorias podem ter _id serializado; se faltar, mantemos
                # uma chave posicional apenas para testar se o documento
                # seria copiável sem mutar produção.
                chave = f"pos:{pos}"
            chave = str(chave)
            if chave in temp:
                # Colisões em coleções que deveriam ter chave única.
                if chave_preferida or doc.get("_id") is not None:
                    erros.append(f"chave_duplicada_{chave[:16]}")
                chave = f"{chave}:pos:{pos}"
            temp[chave] = dict(doc)
        return temp

    metricas_temp = _simular_colecao(metricas)
    aud_admin_temp = _simular_colecao(aud_admin)
    aud_sistema_temp = _simular_colecao(aud_sistema)

    if len(usuarios_temp) != len(usuarios):
        erros.append("dry_run_usuarios_incompleto")
    if len(pedidos_temp) != len(pedidos):
        erros.append("dry_run_pedidos_incompleto")
    if len(metricas_temp) != len(metricas):
        erros.append("dry_run_metricas_incompleto")
    if len(aud_admin_temp) != len(aud_admin):
        erros.append("dry_run_auditoria_admin_incompleto")
    if len(aud_sistema_temp) != len(aud_sistema):
        erros.append("dry_run_auditoria_sistema_incompleto")

    if pedidos_sem_usuario:
        avisos.append(f"{pedidos_sem_usuario} pedido(s) apontam para usuário ausente")
    if pedidos_pagos_ativos_divergentes:
        avisos.append(
            f"{pedidos_pagos_ativos_divergentes} pagamento(s) ativo(s) "
            "não batem com vip_ate do usuário"
        )
    if vips_fora_usuarios:
        erros.append(f"{vips_fora_usuarios}_vips_fora_da_colecao_usuarios")
    if vips_invalidos:
        erros.append(f"{vips_invalidos}_vips_nao_ativos_na_secao_vips")

    # Confere que a lista de VIPs é exatamente a visão dos usuários ativos.
    vips_esperados = {
        uid
        for uid, usuario in usuarios_temp.items()
        if _vip_backup_ativo(usuario.get("vip_ate"), hoje)
    }
    if vips_ids != vips_esperados:
        faltando = len(vips_esperados - vips_ids)
        sobrando = len(vips_ids - vips_esperados)
        erros.append(f"secao_vips_diverge_faltando_{faltando}_sobrando_{sobrando}")

    return {
        "ok": not erros,
        "erros": erros,
        "avisos": avisos,
        "contagens": contagens,
        "dry_run": not erros,
        "pedidos_sem_usuario": pedidos_sem_usuario,
        "pagamentos_vip_divergentes": pedidos_pagos_ativos_divergentes,
    }


def executar_verificacao_backup_admin(chat_id):
    """Gera, grava, relê e simula restauração sem tocar nas coleções."""
    if not BACKUP_ADMIN_LOCK.acquire(blocking=False):
        safe_send_message(
            chat_id,
            "⚠️ Já existe uma operação de backup em andamento. Tente novamente em instantes.",
        )
        return

    caminho = None
    try:
        payload, _, _ = consultar_docs_backup("geral")

        # 1) Serializa em arquivo real.
        caminho = salvar_backup_json("verificacao_backup_geral", payload)

        # 2) Relê o JSON do disco. Se estiver truncado/corrompido, json.load falha.
        garantir_arquivo_privado(caminho)
        with open(caminho, "r", encoding="utf-8") as f:
            relido = json.load(f)

        # 3) Validação + restauração simulada apenas em memória.
        resultado = validar_payload_backup_geral(relido)

        # 4) Compara contagens com o banco atual. É somente leitura.
        hoje = hoje_str()
        banco = {
            "usuarios": usuarios_col.count_documents({}),
            "vips_ativos": usuarios_col.count_documents(
                {
                    "$or": [
                        {"vip_ate": "Vitalício"},
                        {"vip_ate": {"$gte": hoje}},
                    ]
                }
            ),
            "pedidos": pedidos_col.count_documents({}),
            "metricas_diarias": metricas_col.count_documents({}),
            "auditoria_admin": auditoria_admin_col.count_documents({}),
            "auditoria_sistema": auditoria_sistema_col.count_documents({}),
        }

        divergencias_banco = []
        for secao, quantidade in banco.items():
            if int(resultado["contagens"].get(secao, -1)) != int(quantidade):
                divergencias_banco.append(secao)

        if divergencias_banco:
            resultado["avisos"].append(
                "contagem mudou durante a verificação: "
                + ", ".join(divergencias_banco)
            )

        status = "✅" if resultado["ok"] else "❌"
        linhas = [
            f"{status} *Verificação do backup*",
            "",
            f"📄 JSON: `{'válido' if resultado['ok'] else 'com problema'}`",
            f"🧪 Restauração simulada: `{'OK' if resultado['dry_run'] else 'FALHOU'}`",
            "🔒 Produção alterada: `NÃO`",
            "",
            f"👥 Usuários: `{resultado['contagens'].get('usuarios', 0)}`",
            f"💎 VIPs ativos: `{resultado['contagens'].get('vips_ativos', 0)}`",
            f"🧾 Pedidos: `{resultado['contagens'].get('pedidos', 0)}`",
            f"📊 Métricas: `{resultado['contagens'].get('metricas_diarias', 0)}`",
            f"🛡 Auditoria ADM: `{resultado['contagens'].get('auditoria_admin', 0)}`",
            f"⚙️ Auditoria sistema: `{resultado['contagens'].get('auditoria_sistema', 0)}`",
        ]

        if resultado["avisos"]:
            linhas.extend(["", "⚠️ *Avisos:*"])
            for aviso in resultado["avisos"][:8]:
                linhas.append(f"• {aviso}")

        if resultado["erros"]:
            linhas.extend(["", "❌ *Erros:*"])
            for erro in resultado["erros"][:8]:
                linhas.append(f"• `{erro}`")

        if resultado["ok"] and not resultado["avisos"]:
            linhas.extend(
                [
                    "",
                    "✅ Estrutura, contagens e relacionamentos principais estão coerentes.",
                ]
            )

        safe_send_message(
            chat_id,
            "\n".join(linhas),
            parse_mode="Markdown",
        )

        logger.info(
            "[BACKUP_VERIFY] "
            f"ok={resultado['ok']} dry_run={resultado['dry_run']} "
            f"usuarios={resultado['contagens'].get('usuarios', 0)} "
            f"vips={resultado['contagens'].get('vips_ativos', 0)} "
            f"pedidos={resultado['contagens'].get('pedidos', 0)} "
            f"avisos={len(resultado['avisos'])} erros={len(resultado['erros'])} "
            "db_writes=0"
        )

    except Exception as e:
        logger.error(
            "[BACKUP_VERIFY_ERRO] "
            f"erro={sanitizar_erro_log(e)} db_writes=0"
        )
        safe_send_message(
            chat_id,
            "❌ Não foi possível validar o backup.\n"
            "A produção não foi alterada.",
        )
    finally:
        if caminho and os.path.exists(caminho):
            try:
                os.remove(caminho)
            except Exception as e:
                logger.warning(
                    "[BACKUP_VERIFY_CLEANUP] "
                    f"arquivo_ref={referencia_arquivo_log(caminho)} "
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

    linhas.append("✅ Instagram: modo público/anônimo, sem cookies")
    linhas.append(
        "✅ Cookies do TikTok: configurados"
        if TIKTOK_COOKIES_TEXT.strip()
        else "ℹ️ Cookies do TikTok: não configurados (opcional)"
    )
    linhas.append("✅ Pinterest: suporte ativo")
    linhas.append("✅ Facebook Reels: links públicos, sem cookies")
    linhas.append("✅ Shopee Vídeo: suporte ativo")
    linhas.append(
        "✅ Mercado Livre Clips: HLS público, sem login, cookies ou token"
    )
    linhas.append("✅ RedNote: suporte ativo")

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


@bot.message_handler(commands=["linkads"])
def gerar_link_facebook_ads(message):
    if not exigir_admin_privado(message):
        return

    partes = str(message.text or "").split()
    if len(partes) < 2:
        safe_reply_to(
            message,
            "📣 *Gerar link rastreável*\n\n"
            "Use: `/linkads campanha anuncio`\n"
            "Exemplo: `/linkads escala01 shopee01`",
            parse_mode="Markdown",
        )
        return

    campanha = _normalizar_codigo_tracking(partes[1], 20)
    anuncio = _normalizar_codigo_tracking(
        partes[2] if len(partes) >= 3 else "geral",
        24,
    )
    if not campanha or not anuncio:
        safe_reply_to(message, "❌ Use nomes simples para campanha e anúncio.")
        return

    payload = f"fbads_{campanha}_{anuncio}"
    if len(payload) > 64:
        safe_reply_to(message, "❌ Campanha/anúncio ficaram longos demais.")
        return

    try:
        username = str(bot.get_me().username or "").strip()
        if not username:
            raise RuntimeError("username do bot indisponível")
        link = f"https://t.me/{username}?start={payload}"
        safe_send_message(
            message.chat.id,
            "📣 <b>Link rastreável criado</b>\n\n"
            f"Campanha: <code>{html.escape(campanha)}</code>\n"
            f"Anúncio: <code>{html.escape(anuncio)}</code>\n\n"
            f"<code>{html.escape(link)}</code>\n\n"
            "Use este link somente nesse anúncio para medir a conversão.",
            parse_mode="HTML",
        )
        logger.info(
            "[LINK_ADS_CRIADO] "
            f"campanha={campanha} anuncio={anuncio} payload_len={len(payload)}"
        )
    except Exception as e:
        logger.error(
            "[LINK_ADS_ERRO] "
            f"erro={sanitizar_erro_log(e)}"
        )
        safe_reply_to(message, "❌ Não foi possível gerar o link agora.")


@bot.message_handler(commands=["origens"])
def relatorio_origens_aquisicao(message):
    if not exigir_admin_privado(message):
        return

    status = safe_reply_to(message, "📊 Calculando origens e conversões...")

    try:
        pagantes = {
            str(uid)
            for uid in pedidos_col.distinct(
                "user_id",
                {"status": "paid"},
            )
            if uid is not None
        }

        grupos = {}
        total = 0
        total_pagantes = 0
        total_vips_ativos = 0
        rastreados = 0

        cursor = usuarios_col.find(
            {},
            {
                "_id": 1,
                "origem": 1,
                "campanha": 1,
                "anuncio": 1,
                "vip_ate": 1,
            },
        )
        for usuario in cursor:
            total += 1
            uid = str(usuario.get("_id"))
            origem = str(usuario.get("origem") or "legado_sem_origem")
            if origem != "legado_sem_origem":
                rastreados += 1

            grupo = grupos.setdefault(
                origem,
                {"usuarios": 0, "pagantes": 0, "vips_ativos": 0},
            )
            grupo["usuarios"] += 1

            if uid in pagantes:
                grupo["pagantes"] += 1
                total_pagantes += 1

            if is_vip_user(usuario):
                grupo["vips_ativos"] += 1
                total_vips_ativos += 1

        linhas = [
            "📊 *Origem dos usuários*",
            "",
            f"👥 Usuários: `{total}`",
            f"🏷️ Com origem rastreada: `{rastreados}`",
            f"💳 Pagantes únicos: `{total_pagantes}`",
            f"💎 VIPs ativos: `{total_vips_ativos}`",
            "",
            "*Por origem:*",
        ]

        for origem, dados in sorted(
            grupos.items(),
            key=lambda item: item[1]["usuarios"],
            reverse=True,
        )[:12]:
            usuarios = dados["usuarios"]
            pag = dados["pagantes"]
            taxa = (pag * 100 / usuarios) if usuarios else 0.0
            linhas.append(
                f"• `{origem}` — {usuarios} usuários | "
                f"{pag} pagantes ({taxa:.1f}%) | "
                f"{dados['vips_ativos']} VIPs ativos"
            )

        texto = "\n".join(linhas)
        if status and getattr(status, "message_id", None):
            safe_edit_message(
                message.chat.id,
                status.message_id,
                texto,
                parse_mode="Markdown",
            )
        else:
            safe_reply_to(message, texto, parse_mode="Markdown")

        logger.info(
            "[ORIGENS_RELATORIO] "
            f"usuarios={total} rastreados={rastreados} "
            f"pagantes={total_pagantes} vips_ativos={total_vips_ativos}"
        )
    except Exception as e:
        logger.error(
            "[ORIGENS_RELATORIO_ERRO] "
            f"erro={sanitizar_erro_log(e)}"
        )
        safe_reply_to(message, "❌ Não foi possível gerar o relatório de origens.")


@bot.message_handler(commands=["syncvip"])
def sincronizar_vip_admin(message):
    if not exigir_admin_privado(message):
        return

    status = safe_reply_to(
        message,
        "💎 Verificando pagamentos e acessos VIP...",
    )

    def executar():
        try:
            resultado = sincronizar_vips_pagos_ativos(
                notificar_admin=False,
            )
            texto = (
                "💎 *Sincronização VIP concluída*\n\n"
                f"🔎 Pedidos elegíveis: `{resultado['verificados']}`\n"
                f"✅ Corrigidos: `{resultado['corrigidos']}`\n"
                f"🛑 Bloqueados manualmente: `{resultado['bloqueados']}`\n"
                f"🧯 Ignorados por segurança: `{resultado.get('ignorados', 0)}`\n"
                f"❌ Falhas: `{resultado['falhas']}`"
            )
            if status and getattr(status, "message_id", None):
                safe_edit_message(
                    message.chat.id,
                    status.message_id,
                    texto,
                    parse_mode="Markdown",
                )
            else:
                safe_reply_to(message, texto, parse_mode="Markdown")
        except Exception as e:
            logger.error(
                "[SYNCVIP_ADMIN] "
                f"erro={sanitizar_erro_log(e)}"
            )
            safe_reply_to(
                message,
                "❌ Não foi possível concluir a sincronização VIP.",
            )

    Thread(target=executar, daemon=True).start()


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
                    "ultima_data": hoje_str(),
                    "vip_sync_last_source": "darvip_manual",
                    "vip_sync_last_checked_at": agora_tz(),
                },
                "$unset": {
                    "vip_sync_bloqueado": "",
                    "vip_sync_bloqueado_em": "",
                    "vip_sync_bloqueado_motivo": "",
                    "vip_sync_erro": "",
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

        agora_remocao = agora_tz()
        resultado = usuarios_col.update_one(
            {"_id": alvo_id},
            {
                "$set": {
                    "vip_ate": None,
                    "vip_sync_bloqueado": True,
                    "vip_sync_bloqueado_em": agora_remocao,
                    "vip_sync_bloqueado_motivo": "remocao_manual_admin",
                }
            },
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


@bot.message_handler(commands=["verificarbackup"])
def verificar_backup_admin(message):
    if not exigir_admin_privado(message):
        return

    Thread(
        target=executar_verificacao_backup_admin,
        args=(message.chat.id,),
        daemon=True,
    ).start()

    safe_reply_to(
        message,
        "🧪 Verificando JSON e simulando restauração sem alterar a produção...",
    )


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

    payload = _extrair_payload_start(message)

    # Rastreamento é auxiliar: uma falha de analytics nunca pode impedir
    # o usuário (VIP ou gratuito) de receber a tela inicial.
    try:
        registrar_inicio_e_origem(message.from_user.id, payload)
    except Exception as e:
        logger.error(
            "[START_TRACKING_ERRO] "
            f"user_ref={referencia_usuario_log(message.from_user.id)} "
            f"erro={sanitizar_erro_log(e)}"
        )

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
        "Baixe vídeos do TikTok, Pinterest, Instagram, Facebook Reels, Shopee Video, Mercado Livre Clips e RedNote.\n\n"
        "• Qualidade: até 720×1280\n"
        f"• Duração máxima: {MAX_DURATION_SECONDS} segundos\n"
        f"• ID de usuário: `{message.from_user.id}`\n\n"
        f"{status}\n\n"
        "Envie o link de um vídeo para começar ou use o botão *Menu* "
        "para ver as opções."
    )

    enviado = safe_send_message(
        message.chat.id,
        texto,
        parse_mode="Markdown",
        reply_markup=types.ReplyKeyboardRemove()
    )

    if enviado:
        logger.info(
            "[START_OK] "
            f"user_ref={referencia_usuario_log(message.from_user.id)} "
            f"plano={'vip' if vip else 'gratis'} "
            f"payload={'sim' if payload else 'nao'}"
        )
    else:
        logger.warning(
            "[START_SEND_FALHA] "
            f"user_ref={referencia_usuario_log(message.from_user.id)} "
            f"plano={'vip' if vip else 'gratis'}"
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
# MERCADO LIVRE CLIPS
# =========================================
MERCADO_LIVRE_CLIPS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 15; SM-S911B) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}


def extrair_ids_mercado_livre_clips(url):
    try:
        parsed = urlparse(str(url or "").strip())
        parametros = dict(parse_qsl(parsed.query, keep_blank_values=True))
    except Exception:
        return None, None

    short_id = str(parametros.get("short_id") or "").strip()
    item_id = str(parametros.get("item_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}", short_id):
        return None, None
    if item_id and not re.fullmatch(r"MLB\d{5,30}", item_id, flags=re.IGNORECASE):
        item_id = ""
    return short_id, item_id or None


def normalizar_url_mercado_livre_clips(url):
    short_id, _item_id = extrair_ids_mercado_livre_clips(url)
    if not short_id:
        return url
    return (
        "https://www.mercadolivre.com.br/clips/"
        f"?shortsparams=true&type=short&short_id={urlencode({'v': short_id})[2:]}"
    )


def _decodificar_url_mercado_livre_clips(valor):
    valor = str(valor or "").strip()
    if not valor:
        return None
    for _ in range(4):
        anterior = valor
        valor = html.unescape(valor)
        valor = (
            valor.replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\/", "/")
            .replace("\\u003A", ":")
            .replace("\\u003a", ":")
            .replace("\\u0026", "&")
            .replace("\\u003D", "=")
            .replace("\\u003d", "=")
        )
        if valor == anterior:
            break
    valor = valor.strip().strip('"\'')
    if valor.startswith("//"):
        valor = "https:" + valor
    return valor if valor.startswith("https://") else None


def _host_midia_mercado_livre_clips_permitido(url):
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        caminho = parsed.path or ""
        return (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and hostname_permitido(host, "mlstatic.com")
            and caminho.startswith("/storage/shorts-api/")
            and caminho.lower().endswith(".m3u8")
        )
    except (ValueError, TypeError):
        return False


def _host_playlist_derivada_ml_clips_permitido(url):
    """
    Permite playlists HLS filhas servidas pela CDN oficial MLStatic.

    A URL inicial continua sendo validada de forma estrita por
    _host_midia_mercado_livre_clips_permitido(). Esta função só é usada
    depois que uma playlist oficial já foi obtida e referenciou outra .m3u8.
    """
    try:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower().rstrip(".")
        caminho = parsed.path or ""
        return (
            parsed.scheme == "https"
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
            and hostname_permitido(host, "mlstatic.com")
            and caminho.lower().endswith(".m3u8")
        )
    except (ValueError, TypeError):
        return False


def extrair_video_mercado_livre_clips(texto, short_id):
    """Extrai somente o videoUrl HLS do short_id solicitado."""
    bruto = str(texto or "")
    if not bruto or not short_id:
        return None, None

    short_re = re.escape(str(short_id))
    candidatos = []

    # Primeiro, associe explicitamente id -> videoUrl para não pegar outro Clip
    # do feed pré-carregado na mesma página.
    padrao_objeto = re.compile(
        rf'"id"\s*:\s*"{short_re}".{{0,5000}}?'
        r'"videoUrl"\s*:\s*"([^"]+)"'
        r'.{0,1200}?"duration"\s*:\s*(\d+(?:\.\d+)?)',
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in padrao_objeto.finditer(bruto):
        candidatos.append((match.group(1), match.group(2)))

    # Algumas versões podem posicionar duration antes/depois ou omiti-la.
    if not candidatos:
        padrao_sem_duracao = re.compile(
            rf'"id"\s*:\s*"{short_re}".{{0,5000}}?'
            r'"videoUrl"\s*:\s*"([^"]+)"',
            flags=re.IGNORECASE | re.DOTALL,
        )
        for match in padrao_sem_duracao.finditer(bruto):
            candidatos.append((match.group(1), None))

    # Fallback estrito: prefira qualquer videoUrl cujo nome termine no short_id.
    if not candidatos:
        for match in re.finditer(
            r'"videoUrl"\s*:\s*"([^"]+\.m3u8(?:\?[^"]*)?)"',
            bruto,
            flags=re.IGNORECASE,
        ):
            candidatos.append((match.group(1), None))

    for valor, duracao_valor in candidatos:
        video_url = _decodificar_url_mercado_livre_clips(valor)
        if not video_url or not _host_midia_mercado_livre_clips_permitido(video_url):
            continue
        nome = os.path.basename(urlparse(video_url).path or "")
        if not nome.lower().startswith(str(short_id).lower() + "."):
            continue
        try:
            duracao = float(duracao_valor) if duracao_valor is not None else None
        except (TypeError, ValueError):
            duracao = None
        return video_url, duracao

    return None, None


def _get_mercado_livre_publico(url, headers, max_redirects=4):
    atual = str(url or "").strip()
    resposta = None
    try:
        for _ in range(max_redirects + 1):
            parsed = urlparse(atual)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (
                parsed.scheme != "https"
                or not hostname_permitido(host, "mercadolivre.com.br")
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or not validar_url_http_publica(atual)
            ):
                raise RuntimeError("ML_CLIPS_PAGINA_HOST_INVALIDO")

            resposta = requests.get(
                atual,
                headers=headers,
                allow_redirects=False,
                timeout=(5, 25),
            )
            if resposta.status_code in (301, 302, 303, 307, 308):
                proxima = urljoin(atual, resposta.headers.get("Location") or "")
                resposta.close()
                resposta = None
                if not proxima or proxima == atual:
                    raise RuntimeError("ML_CLIPS_REDIRECIONAMENTO_INVALIDO")
                atual = proxima
                continue

            resposta.raise_for_status()
            return resposta, atual
        raise RuntimeError("ML_CLIPS_REDIRECIONAMENTOS_DEMAIS")
    except Exception:
        if resposta is not None:
            resposta.close()
        raise


def obter_video_mercado_livre_clips(url):
    """Consulta apenas páginas públicas mobile e obtém o HLS oficial do Clip."""
    short_id, item_id = extrair_ids_mercado_livre_clips(url)
    if not short_id:
        raise RuntimeError("ML_CLIPS_SHORT_NAO_ENCONTRADO")

    short_q = urlencode({"short_id": short_id})
    paginas = [
        f"https://www.mercadolivre.com.br/clips/?shortsparams=true&type=short&{short_q}",
        f"https://www.mercadolivre.com.br/live/videos?type=short&{short_q}",
    ]
    ultimo_erro = None
    for indice, pagina in enumerate(paginas, start=1):
        resposta = None
        try:
            atualizar_heartbeat_worker("ml_clips_consultando_pagina")
            logger.info(
                f"[ML_CLIPS_PAGINA_TENTATIVA] tentativa={indice}/{len(paginas)} "
                "modo=publico_mobile login=False cookies=False token=False"
            )
            resposta, pagina_final = _get_mercado_livre_publico(
                pagina,
                MERCADO_LIVRE_CLIPS_HEADERS,
            )
            texto = resposta.text
            video_url, duracao = extrair_video_mercado_livre_clips(texto, short_id)
            logger.info(
                f"[ML_CLIPS_PAGINA_OK] tentativa={indice} status={resposta.status_code} "
                f"hls_encontrado={bool(video_url)} item_id_presente={bool(item_id)}"
            )
            if not video_url:
                raise RuntimeError("ML_CLIPS_VIDEO_URL_NAO_ENCONTRADA")
            if duracao and duracao > MAX_DURATION_SECONDS + 0.5:
                raise RuntimeError(
                    f"VIDEO_MUITO_LONGO duracao={duracao:.2f} limite={MAX_DURATION_SECONDS}"
                )
            return pagina_final, short_id, item_id, video_url, duracao
        except Exception as e:
            ultimo_erro = e
            logger.warning(
                f"[ML_CLIPS_PAGINA_FALHA] tentativa={indice} "
                f"erro={sanitizar_erro_log(e)}"
            )
        finally:
            if resposta is not None:
                resposta.close()

    raise RuntimeError(
        f"ML_CLIPS_VIDEO_URL_NAO_ENCONTRADA: {ultimo_erro or 'sem fonte publica'}"
    )


def _get_manifesto_ml_clips(url, referer, permitir_cdn_derivada=False):
    atual = str(url or "").strip()
    resposta = None
    try:
        for _ in range(5):
            guard_ok = (
                _host_playlist_derivada_ml_clips_permitido(atual)
                if permitir_cdn_derivada
                else _host_midia_mercado_livre_clips_permitido(atual)
            )
            if not guard_ok:
                parsed_guard = urlparse(str(atual or "").strip())
                logger.warning(
                    "[ML_CLIPS_HLS_GUARD_FALHA] "
                    f"tipo={'cdn_derivada' if permitir_cdn_derivada else 'master'} "
                    f"scheme={parsed_guard.scheme} "
                    f"host={str(parsed_guard.hostname or '').lower()} "
                    f"porta={parsed_guard.port} "
                    f"path_ref={hashlib.sha256(str(parsed_guard.path or '').encode()).hexdigest()[:12]}"
                )
                raise RuntimeError("ML_CLIPS_HLS_HOST_INVALIDO")
            logger.info(
                "[ML_CLIPS_HLS_GUARD_OK] "
                f"tipo={'cdn_derivada' if permitir_cdn_derivada else 'master'} "
                "host_mlstatic=True https=True porta_padrao=True"
            )
            headers = {
                "User-Agent": MERCADO_LIVRE_CLIPS_HEADERS["User-Agent"],
                "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,*/*;q=0.8",
                "Accept-Language": MERCADO_LIVRE_CLIPS_HEADERS["Accept-Language"],
                "Referer": referer,
            }
            resposta = requests.get(
                atual,
                headers=headers,
                allow_redirects=False,
                timeout=(5, 20),
            )
            if resposta.status_code in (301, 302, 303, 307, 308):
                proxima = urljoin(atual, resposta.headers.get("Location") or "")
                resposta.close()
                resposta = None
                redirect_ok = (
                    _host_playlist_derivada_ml_clips_permitido(proxima)
                    if permitir_cdn_derivada
                    else _host_midia_mercado_livre_clips_permitido(proxima)
                )
                if not redirect_ok:
                    raise RuntimeError("ML_CLIPS_HLS_REDIRECIONAMENTO_INVALIDO")
                atual = proxima
                continue
            resposta.raise_for_status()
            texto = resposta.text
            if "#EXTM3U" not in texto[:500].upper():
                raise RuntimeError("ML_CLIPS_HLS_MANIFESTO_INVALIDO")
            return texto, atual
        raise RuntimeError("ML_CLIPS_HLS_REDIRECIONAMENTOS_DEMAIS")
    finally:
        if resposta is not None:
            resposta.close()



def selecionar_variante_hls_mercado_livre_clips(url_master, referer):
    """
    Escolhe explicitamente a melhor variante HLS para o perfil do bot.

    Prioridade:
    1) maior resolução que caiba em 720x1280 (ou 1280x720);
    2) se não houver, a menor resolução acima do alvo;
    3) sem RESOLUTION, usa maior BANDWIDTH.
    """
    texto, final_url = _get_manifesto_ml_clips(
        url_master,
        referer,
        permitir_cdn_derivada=False,
    )
    linhas = [linha.strip() for linha in texto.splitlines()]
    variantes = []

    for i, linha in enumerate(linhas):
        if not linha.upper().startswith("#EXT-X-STREAM-INF:"):
            continue

        attrs = linha.split(":", 1)[1] if ":" in linha else ""
        largura = altura = 0
        largura_match = re.search(
            r"RESOLUTION\s*=\s*(\d+)\s*x\s*(\d+)",
            attrs,
            flags=re.IGNORECASE,
        )
        if largura_match:
            largura = int(largura_match.group(1))
            altura = int(largura_match.group(2))

        bw_match = re.search(
            r"(?:AVERAGE-BANDWIDTH|BANDWIDTH)\s*=\s*(\d+)",
            attrs,
            flags=re.IGNORECASE,
        )
        bandwidth = int(bw_match.group(1)) if bw_match else 0

        uri = None
        for proxima in linhas[i + 1:]:
            if not proxima:
                continue
            if proxima.startswith("#"):
                # Encontrou a próxima tag antes da URI desta variante.
                if proxima.upper().startswith("#EXT-X-STREAM-INF:"):
                    break
                continue
            uri = proxima
            break

        if not uri:
            continue

        absoluta = urljoin(final_url, uri)
        if not _host_playlist_derivada_ml_clips_permitido(absoluta):
            continue

        variantes.append(
            {
                "url": absoluta,
                "width": largura,
                "height": altura,
                "bandwidth": bandwidth,
            }
        )

    if not variantes:
        logger.info(
            "[ML_CLIPS_VARIANTE] master_sem_variantes=True "
            "usar_master=True"
        )
        return final_url, None

    com_resolucao = [
        v for v in variantes
        if v["width"] > 0 and v["height"] > 0
    ]

    dentro_alvo = [
        v for v in com_resolucao
        if min(v["width"], v["height"]) <= 720
        and max(v["width"], v["height"]) <= 1280
    ]

    if dentro_alvo:
        escolhida = max(
            dentro_alvo,
            key=lambda v: (
                v["width"] * v["height"],
                v["bandwidth"],
            ),
        )
        criterio = "maior_ate_720x1280"
    elif com_resolucao:
        acima_alvo = [
            v for v in com_resolucao
            if (
                min(v["width"], v["height"]) > 720
                or max(v["width"], v["height"]) > 1280
            )
        ]
        if acima_alvo:
            escolhida = min(
                acima_alvo,
                key=lambda v: (
                    v["width"] * v["height"],
                    -v["bandwidth"],
                ),
            )
            criterio = "menor_acima_720x1280"
        else:
            escolhida = max(
                com_resolucao,
                key=lambda v: (
                    v["width"] * v["height"],
                    v["bandwidth"],
                ),
            )
            criterio = "maior_resolucao"
    else:
        escolhida = max(
            variantes,
            key=lambda v: v["bandwidth"],
        )
        criterio = "maior_bandwidth"

    logger.info(
        "[ML_CLIPS_VARIANTE] "
        f"total={len(variantes)} criterio={criterio} "
        f"width={escolhida['width'] or 'desconhecida'} "
        f"height={escolhida['height'] or 'desconhecida'} "
        f"bandwidth={escolhida['bandwidth'] or 'desconhecido'}"
    )
    return escolhida["url"], escolhida


def validar_manifestos_mercado_livre_clips(url, referer, profundidade=0, visitados=None):
    """Valida playlists HLS e bloqueia referências absolutas fora do MLStatic."""
    if profundidade > 2:
        return url
    visitados = visitados if visitados is not None else set()
    if url in visitados:
        return url
    visitados.add(url)

    texto, final_url = _get_manifesto_ml_clips(
        url,
        referer,
        permitir_cdn_derivada=profundidade > 0,
    )
    filhos_m3u8 = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue
        uris = []
        if not linha.startswith("#"):
            uris.append(linha)
        for match in re.finditer(r'URI=["\']([^"\']+)["\']', linha, flags=re.IGNORECASE):
            uris.append(match.group(1))
        for uri in uris:
            absoluto = urljoin(final_url, uri)
            parsed = urlparse(absoluto)
            host = (parsed.hostname or "").lower().rstrip(".")
            if (
                parsed.scheme != "https"
                or not hostname_permitido(host, "mlstatic.com")
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
            ):
                raise RuntimeError("ML_CLIPS_HLS_REFERENCIA_FORA_DO_MLSTATIC")
            if (parsed.path or "").lower().endswith(".m3u8"):
                filhos_m3u8.append(absoluto)

    for filho in filhos_m3u8[:8]:
        validar_manifestos_mercado_livre_clips(
            filho,
            referer,
            profundidade=profundidade + 1,
            visitados=visitados,
        )
    return final_url


def baixar_hls_mercado_livre_clips(url_hls, destino, referer):
    """Remuxa a melhor variante HLS pública do MLStatic para MP4."""
    atualizar_heartbeat_worker("ml_clips_selecionando_variante")
    url_selecionada, variante = selecionar_variante_hls_mercado_livre_clips(
        url_hls,
        referer,
    )

    atualizar_heartbeat_worker("ml_clips_validando_hls")
    if variante is None:
        url_ffmpeg = validar_manifestos_mercado_livre_clips(
            url_selecionada,
            referer,
            profundidade=0,
        )
    else:
        url_ffmpeg = validar_manifestos_mercado_livre_clips(
            url_selecionada,
            referer,
            profundidade=1,
        )

    logger.info(
        "[ML_CLIPS_HLS_VALIDADO] host_mlstatic=True referencias_oficiais=True "
        "qualidade_selecionada=True cache_version=ml_clips_hls_720_v1"
    )

    headers_ffmpeg = (
        f"Referer: {referer}\\r\\n"
        f"Accept-Language: {MERCADO_LIVRE_CLIPS_HEADERS['Accept-Language']}\\r\\n"
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-v", "error",
        "-user_agent", MERCADO_LIVRE_CLIPS_HEADERS["User-Agent"],
        "-headers", headers_ffmpeg,
        "-i", url_ffmpeg,
        "-map", "0:v:0",
        "-map", "0:a:0",
        "-c", "copy",
        "-movflags", "+faststart",
        destino,
    ]
    atualizar_heartbeat_worker("ml_clips_baixando_hls")
    try:
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
            f"FFMPEG_TIMEOUT ml_clips timeout={FFMPEG_TIMEOUT_SECONDS}s",
        ) from e

    if resultado.returncode != 0 or not os.path.isfile(destino):
        raise FalhaComponenteDownload(
            "Processamento",
            f"ML_CLIPS_FFMPEG_FALHOU codigo={resultado.returncode} "
            f"detalhe={sanitizar_erro_log(resultado.stderr[-500:])}",
        )
    return destino


def processar_download_mercado_livre_clips(
    message,
    url,
    status_msg,
    vip_status,
    reserva_download=None,
):
    """Pipeline público de Mercado Livre Clips sem login/cookies/token."""
    prefix = os.path.join(DOWNLOAD_DIR, f"mlclips_{uuid.uuid4().hex}")
    plataforma = "Mercado Livre Clips"
    try:
        url = normalizar_url_mercado_livre_clips(url)
        url_cache_key, url_normalizada = montar_chave_cache_url(plataforma, url)
        entrada_cache_url = obter_entrada_cache(url_cache_key)
        tipo_cache_url = (
            enviar_midia_cacheada(message.chat.id, url_cache_key, entrada_cache_url)
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
            logger.info("[ML_CLIPS_CACHE_HIT] tipo=url")
            return True

        espaco_ok, _ = garantir_espaco_para_novo_download()
        if not espaco_ok:
            informar_download_pausado_por_espaco(message, status_msg)
            return False

        pagina_final, short_id, item_id, video_url, duracao = obter_video_mercado_livre_clips(url)
        logger.info(
            "[ML_CLIPS_VIDEO_URL] encontrado=True hls=True host_mlstatic=True "
            f"duracao={duracao if duracao is not None else 'desconhecida'} "
            "login=False cookies=False token=False"
        )

        info_cache = {
            "id": short_id,
            "display_id": short_id,
            "webpage_url": pagina_final,
        }
        cache_key, cache_source_id = montar_chave_cache_midia(
            plataforma,
            info_cache,
            pagina_final,
        )
        entrada_cache = obter_entrada_cache(cache_key)
        tipo_cache = (
            enviar_midia_cacheada(message.chat.id, cache_key, entrada_cache)
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
            logger.info("[ML_CLIPS_CACHE_HIT] tipo=midia")
            return True

        arquivo_baixado = f"{prefix}.mp4"
        baixar_hls_mercado_livre_clips(video_url, arquivo_baixado, pagina_final)
        info_baixada = validar_arquivo_midia(
            arquivo_baixado,
            MAX_SOURCE_FILE_BYTES,
            fase="ml_clips_hls",
        )
        if not arquivo_possui_audio(info_baixada):
            raise RuntimeError("ML_CLIPS_AUDIO_AUSENTE_NO_HLS")

        logger.info(
            "[ML_CLIPS_HLS_OK] "
            f"width={info_baixada.get('width')} height={info_baixada.get('height')} "
            f"fps={info_baixada.get('fps')} vcodec={info_baixada.get('vcodec')} "
            f"acodec={info_baixada.get('acodec')}"
        )

        if os.path.getsize(arquivo_baixado) > MAX_OUTPUT_FILE_BYTES:
            logger.info(
                "[ML_CLIPS_COMPACTACAO] necessaria=True "
                f"limite_mb={MAX_OUTPUT_FILE_MB}"
            )
            arquivo_envio = converter_para_720x1280_30fps(arquivo_baixado)
        else:
            arquivo_envio = preparar_arquivo_para_envio(
                arquivo_baixado,
                plataforma=plataforma,
            )

        info_envio = validar_arquivo_midia(
            arquivo_envio,
            MAX_OUTPUT_FILE_BYTES,
            fase="ml_clips_envio",
        )
        if not arquivo_possui_audio(info_envio):
            raise RuntimeError("ML_CLIPS_AUDIO_AUSENTE_APOS_PROCESSAMENTO")

        enviado, telegram_file_id, telegram_media_type, bytes_upload = (
            enviar_arquivo_com_fallback(message.chat.id, arquivo_envio)
        )
        if not enviado:
            raise RuntimeError("ML_CLIPS_FALHA_ENVIO_TELEGRAM")

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
        registrar_sucesso_plataforma(plataforma)
        registrar_sucesso_componente("Processamento")
        registrar_sucesso_componente("Interno")
        if status_msg:
            safe_delete_message(message.chat.id, status_msg.message_id)
        logger.info(
            "[ML_CLIPS_DOWNLOAD_OK] audio=True cache_salvo=True "
            "login=False cookies=False token=False"
        )
        return True
    finally:
        cleanup_prefix(prefix)


# =========================================
# SHOPEE VIDEO
# =========================================
SHOPEE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _normalizar_url_extraida_shopee(valor):
    valor = str(valor or "").strip()
    if not valor:
        return None

    # A URL pode aparecer como JSON, HTML ou query string e pode estar
    # escapada mais de uma vez dentro do estado inicial da página.
    for _ in range(3):
        anterior = valor
        valor = html.unescape(valor)
        try:
            valor = unquote(valor)
        except Exception:
            pass
        valor = (
            valor.replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\/", "/")
            .replace("\\u0026", "&")
            .replace("\\u003D", "=")
            .replace("\\u003d", "=")
        )
        if valor == anterior:
            break

    valor = valor.strip().strip('"\'')
    if valor.startswith("//"):
        valor = "https:" + valor
    return valor if valor.startswith("https://") else None


def _host_midia_shopee_permitido(url):
    try:
        parsed = urlparse(str(url or "").strip())
        return (
            parsed.scheme == "https"
            and parsed.hostname
            and hostname_permitido(parsed.hostname, "susercontent.com")
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        )
    except (ValueError, TypeError):
        return False


def extrair_urls_watermark_shopee(texto):
    """Localiza somente URLs oficiais declaradas como watermarkVideoUrl."""
    if not texto:
        return []

    bruto = str(texto)
    variantes = [bruto]
    decodificado = html.unescape(bruto)
    try:
        decodificado = unquote(decodificado)
    except Exception:
        pass
    if decodificado not in variantes:
        variantes.append(decodificado)

    # Cria também uma variante com escapes comuns de JSON/JS já resolvidos.
    # Isso permite localizar o valor mesmo quando a página usa https:\/\/ ou
    # https:\u002F\u002F dentro de um bloco serializado.
    normalizado = decodificado
    for _ in range(3):
        anterior = normalizado
        normalizado = (
            normalizado.replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\/", "/")
            .replace("\\u0026", "&")
            .replace("\\u003D", "=")
            .replace("\\u003d", "=")
        )
        if normalizado == anterior:
            break
    if normalizado not in variantes:
        variantes.append(normalizado)

    padroes = (
        r'["\\\']watermarkVideoUrl["\\\']\s*:\s*["\\\']([^"\\\']+)',
        r'watermarkVideoUrl.{0,120}?(https?://[^"\\\'<>\s]+?\.mp4(?:\?[^"\\\'<>\s]*)?)',
    )
    encontrados = []
    for variante in variantes:
        for padrao in padroes:
            for match in re.finditer(padrao, variante, flags=re.IGNORECASE | re.DOTALL):
                candidato = _normalizar_url_extraida_shopee(match.group(1))
                if candidato and _host_midia_shopee_permitido(candidato) and candidato not in encontrados:
                    encontrados.append(candidato)
    return encontrados


def derivar_url_original_shopee(url_watermark):
    """Remove somente o sufixo de marca d'água do nome oficial do MP4."""
    if not _host_midia_shopee_permitido(url_watermark):
        raise RuntimeError("SHOPEE_WATERMARK_HOST_INVALIDO")

    parsed = urlparse(url_watermark)
    caminho = parsed.path or ""
    diretorio, _, nome = caminho.rpartition("/")

    # Exemplo observado na fonte oficial:
    #   ID.16003551782243289.6072.mp4 -> ID.mp4
    match = re.fullmatch(
        r'(.+?)\.\d{10,}\.\d+\.mp4',
        nome,
        flags=re.IGNORECASE,
    )
    if not match:
        raise RuntimeError("SHOPEE_PADRAO_WATERMARK_DESCONHECIDO")

    nome_original = match.group(1) + ".mp4"
    novo_caminho = f"{diretorio}/{nome_original}" if diretorio else f"/{nome_original}"
    original = parsed._replace(path=novo_caminho, query="", fragment="").geturl()
    if not _host_midia_shopee_permitido(original):
        raise RuntimeError("SHOPEE_ORIGINAL_HOST_INVALIDO")
    return original


def obter_originais_shopee(url):
    """Obtém candidatos originais sem marca apenas da página oficial da Shopee."""
    atualizar_heartbeat_worker("shopee_consultando_pagina")
    resposta, url_final = seguir_redirecionamentos_seguros(
        url,
        headers=SHOPEE_HEADERS,
        max_redirects=6,
    )
    try:
        host_final = (urlparse(url_final).hostname or "").lower().rstrip(".")
        if not hostname_permitido(host_final, "shopee.com.br"):
            raise RuntimeError("SHOPEE_REDIRECIONAMENTO_FORA_DA_PLATAFORMA")

        texto = resposta.text
    finally:
        resposta.close()

    watermarks = extrair_urls_watermark_shopee(texto)
    logger.info(
        f"[SHOPEE_WATERMARKS] total={len(watermarks)} "
        f"url_ref={referencia_url_log(url_final)}"
    )
    if not watermarks:
        raise RuntimeError("SHOPEE_WATERMARK_VIDEO_URL_NAO_ENCONTRADA")

    originais = []
    erros = []
    for watermark in watermarks:
        try:
            original = derivar_url_original_shopee(watermark)
            if original not in originais:
                originais.append(original)
        except Exception as e:
            erros.append(str(e))

    if not originais:
        detalhe = erros[-1] if erros else "sem_candidatos"
        raise RuntimeError(f"SHOPEE_ORIGINAL_NAO_DERIVADO: {detalhe}")

    logger.info(
        f"[SHOPEE_ORIGINAIS] total={len(originais)} "
        "somente_susercontent=True sem_watermark=True"
    )
    return url_final, originais


def baixar_url_original_shopee(url_midia, destino, referer):
    """Baixa um MP4 oficial sem permitir redirecionamento fora do CDN Shopee."""
    atual = str(url_midia or "").strip()
    resposta = None
    try:
        for _ in range(6):
            if not _host_midia_shopee_permitido(atual) or not validar_url_http_publica(atual):
                raise RuntimeError("SHOPEE_CDN_URL_NAO_PERMITIDA")

            headers = {
                **SHOPEE_HEADERS,
                "Accept": "video/mp4,video/*;q=0.9,*/*;q=0.8",
                "Referer": referer,
            }
            resposta = requests.get(
                atual,
                headers=headers,
                stream=True,
                allow_redirects=False,
                timeout=(5, 25),
            )

            if resposta.status_code in (301, 302, 303, 307, 308):
                destino_redirect = urljoin(atual, resposta.headers.get("Location") or "")
                resposta.close()
                resposta = None
                if not destino_redirect or destino_redirect == atual:
                    raise RuntimeError("SHOPEE_CDN_REDIRECIONAMENTO_INVALIDO")
                atual = destino_redirect
                continue

            resposta.raise_for_status()
            tamanho_declarado = int(resposta.headers.get("Content-Length") or 0)
            if tamanho_declarado > MAX_SOURCE_FILE_BYTES:
                raise RuntimeError(
                    f"ARQUIVO_MIDIA_MUITO_GRANDE fase=download "
                    f"tamanho={tamanho_declarado} limite={MAX_SOURCE_FILE_BYTES}"
                )

            total = 0
            with open(destino, "wb") as arquivo:
                for chunk in resposta.iter_content(chunk_size=256 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_SOURCE_FILE_BYTES:
                        raise RuntimeError(
                            f"ARQUIVO_MIDIA_MUITO_GRANDE fase=download "
                            f"tamanho={total} limite={MAX_SOURCE_FILE_BYTES}"
                        )
                    arquivo.write(chunk)
                    atualizar_heartbeat_worker("shopee_baixando")
            if total <= 0:
                raise RuntimeError("SHOPEE_ARQUIVO_VAZIO")
            return atual

        raise RuntimeError("SHOPEE_CDN_MUITOS_REDIRECIONAMENTOS")
    finally:
        if resposta is not None:
            resposta.close()


def processar_download_shopee(message, url, status_msg, vip_status, reserva_download=None):
    """Pipeline Shopee Video: original oficial, áudio obrigatório e cache Telegram."""
    prefix = os.path.join(DOWNLOAD_DIR, f"shopee_{uuid.uuid4().hex}")
    plataforma = "Shopee Video"
    try:
        url_cache_key, url_normalizada = montar_chave_cache_url(plataforma, url)
        entrada_cache_url = obter_entrada_cache(url_cache_key)
        tipo_cache_url = (
            enviar_midia_cacheada(message.chat.id, url_cache_key, entrada_cache_url)
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
            logger.info("[SHOPEE_CACHE_HIT] tipo=url")
            return True

        espaco_ok, _ = garantir_espaco_para_novo_download()
        if not espaco_ok:
            informar_download_pausado_por_espaco(message, status_msg)
            return False

        pagina_final, originais = obter_originais_shopee(url)

        # A URL original já contém um identificador estável da mídia. Consulte
        # o cache do Telegram antes de baixar o MP4 novamente do CDN da Shopee.
        original_base = originais[0]
        media_id_base = os.path.basename(
            urlparse(original_base).path or ""
        ).rsplit(".", 1)[0]
        info_cache = {
            "id": media_id_base
            or hashlib.sha256(original_base.encode()).hexdigest()[:24],
            "display_id": media_id_base,
            "webpage_url": pagina_final,
        }
        cache_key, cache_source_id = montar_chave_cache_midia(
            plataforma,
            info_cache,
            pagina_final,
        )
        entrada_cache = obter_entrada_cache(cache_key)
        tipo_cache = (
            enviar_midia_cacheada(message.chat.id, cache_key, entrada_cache)
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
            logger.info("[SHOPEE_CACHE_HIT] tipo=midia")
            return True

        ultimo_erro = None
        arquivo_baixado = None
        info_baixada = None
        original_usada = None

        for indice, original in enumerate(originais, start=1):
            cleanup_prefix(prefix)
            destino = f"{prefix}.mp4"
            try:
                logger.info(
                    f"[SHOPEE_DOWNLOAD_TENTATIVA] candidato={indice}/{len(originais)} "
                    "host_oficial=True sem_watermark=True"
                )
                baixar_url_original_shopee(original, destino, pagina_final)
                info = validar_arquivo_midia(
                    destino,
                    MAX_SOURCE_FILE_BYTES,
                    fase="shopee_original",
                )
                if not arquivo_possui_audio(info):
                    raise RuntimeError("SHOPEE_AUDIO_AUSENTE_NO_ORIGINAL")
                arquivo_baixado = destino
                info_baixada = info
                original_usada = original
                break
            except Exception as e:
                ultimo_erro = e
                logger.warning(
                    f"[SHOPEE_DOWNLOAD_TENTATIVA_FALHA] candidato={indice} "
                    f"erro={sanitizar_erro_log(e)}"
                )

        if not arquivo_baixado:
            raise RuntimeError(
                f"SHOPEE_ORIGINAL_FALHOU: {ultimo_erro or 'nenhum candidato funcionou'}"
            )

        logger.info(
            "[SHOPEE_ORIGINAL_OK] "
            f"width={info_baixada.get('width')} height={info_baixada.get('height')} "
            f"fps={info_baixada.get('fps')} vcodec={info_baixada.get('vcodec')} "
            f"acodec={info_baixada.get('acodec')} sem_watermark=True"
        )

        if os.path.getsize(arquivo_baixado) > MAX_OUTPUT_FILE_BYTES:
            logger.info(
                "[SHOPEE_COMPACTACAO] necessaria=True "
                f"limite_mb={MAX_OUTPUT_FILE_MB}"
            )
            arquivo_envio = converter_para_720x1280_30fps(arquivo_baixado)
        else:
            arquivo_envio = preparar_arquivo_para_envio(
                arquivo_baixado,
                plataforma=plataforma,
            )
        info_envio = validar_arquivo_midia(
            arquivo_envio,
            MAX_OUTPUT_FILE_BYTES,
            fase="shopee_envio",
        )
        if not arquivo_possui_audio(info_envio):
            raise RuntimeError("SHOPEE_AUDIO_AUSENTE_APOS_PROCESSAMENTO")

        enviado, telegram_file_id, telegram_media_type, bytes_upload = (
            enviar_arquivo_com_fallback(message.chat.id, arquivo_envio)
        )
        if not enviado:
            raise RuntimeError("SHOPEE_FALHA_ENVIO_TELEGRAM")

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
        registrar_sucesso_plataforma(plataforma)
        registrar_sucesso_componente("Processamento")
        registrar_sucesso_componente("Interno")
        if status_msg:
            safe_delete_message(message.chat.id, status_msg.message_id)
        logger.info("[SHOPEE_DOWNLOAD_OK] audio=True sem_watermark=True cache_salvo=True")
        return True
    finally:
        cleanup_prefix(prefix)


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


def formatos_por_plataforma(
    is_tiktok=False,
    is_instagram=False,
    is_pinterest=False,
    is_rednote=False,
    is_facebook_reel=False,
):
    if is_instagram:
        # O seletor bv*+ba/b é o padrão moderno recomendado pelo yt-dlp:
        # prefere um vídeo que já possa conter áudio e combina uma faixa de
        # áudio separada quando ela existe. As primeiras opções mantêm o limite
        # do bot; a última é um fallback que o pipeline reduz depois, se preciso.
        return [
            "bv*[ext=mp4][width<=720][height<=1280][fps<=30]+ba[ext=m4a]/b[ext=mp4][width<=720][height<=1280][fps<=30]",
            "bv*[width<=720][height<=1280][fps<=30]+ba/b[width<=720][height<=1280][fps<=30]",
            "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]",
            "bv*+ba/b",
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

    if is_facebook_reel:
        return [
            "best[ext=mp4][vcodec!=none][acodec!=none][width<=720][height<=1280][fps<=30]",
            "best[ext=mp4][vcodec!=none][acodec!=none][width<=720][height<=1280]",
            "bestvideo[ext=mp4][width<=720][height<=1280][fps<=30]+bestaudio[ext=m4a]/best[ext=mp4][width<=720][height<=1280][fps<=30]",
            "bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[width<=720][height<=1280][fps<=30]",
            "best[ext=mp4][vcodec!=none][acodec!=none]",
            "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]",
            "bestvideo+bestaudio/best",
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
        (
            is_pinterest,
            is_tiktok,
            is_instagram,
            is_rednote,
            is_facebook_reel,
            is_shopee,
            is_mercado_livre_clips,
        ) = detectar_plataforma(url)
        plataforma = nome_plataforma(
            is_pinterest,
            is_tiktok,
            is_instagram,
            is_rednote,
            is_facebook_reel,
            is_shopee,
            is_mercado_livre_clips,
        )

        if is_instagram:
            url = normalizar_url_instagram(url)
        elif is_facebook_reel:
            url = normalizar_url_facebook_reel(url)
        elif is_mercado_livre_clips:
            url = normalizar_url_mercado_livre_clips(url)

        logger.info(
            f"[DOWNLOAD_INICIO] user_ref={referencia_usuario_log(message.from_user.id)} "
            f"plataforma={plataforma} url_ref={referencia_url_log(url)}"
        )

        if not (
            is_pinterest
            or is_tiktok
            or is_instagram
            or is_rednote
            or is_facebook_reel
            or is_shopee
            or is_mercado_livre_clips
        ):
            texto_nao_reconhecido = (
                "❌ Link não reconhecido. Envie um link do TikTok, Pinterest, "
                "Instagram, Facebook Reels, Shopee Video, Mercado Livre Clips ou RedNote."
            )
            if status_msg:
                safe_edit_message(message.chat.id, status_msg.message_id, texto_nao_reconhecido)
            else:
                safe_send_message(message.chat.id, texto_nao_reconhecido)
            return

        if is_shopee:
            processar_download_shopee(
                message,
                url,
                status_msg,
                vip_status,
                reserva_download=reserva_download,
            )
            return

        if is_mercado_livre_clips:
            processar_download_mercado_livre_clips(
                message,
                url,
                status_msg,
                vip_status,
                reserva_download=reserva_download,
            )
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
            elif is_facebook_reel:
                info = extrair_info_facebook_com_fallback(url)
            else:
                with yt_dlp.YoutubeDL(montar_info_opts()) as ydl:
                    info = ydl.extract_info(url, download=False)
        except FalhaComponenteDownload:
            raise
        except Exception as e:
            raise FalhaComponenteDownload(plataforma, e) from e

        audio_instagram_esperado = None
        if is_instagram:
            audio_instagram_esperado = info_plataforma_indica_audio(info)
            logger.info(
                "[INSTAGRAM_AUDIO_INFO] "
                f"audio_disponivel={audio_instagram_esperado}"
            )

        audio_facebook_esperado = None
        if is_facebook_reel:
            audio_facebook_esperado = info_plataforma_indica_audio(info)
            logger.info(
                "[FACEBOOK_REELS_AUDIO_INFO] "
                f"audio_disponivel={audio_facebook_esperado}"
            )
            if audio_facebook_esperado is False:
                logger.info(
                    "[FACEBOOK_REELS_PROBE_REAL] "
                    "metadata=False acao=testar_arquivo_real_com_ffprobe"
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

        formatos_progressivos_ig = (
            formatos_progressivos_instagram(info) if is_instagram else []
        )
        formatos_progressivos_fb = (
            formatos_progressivos_facebook(info) if is_facebook_reel else []
        )
        formatos = (
            formatos_progressivos_ig
            + formatos_progressivos_fb
            + formatos_por_plataforma(
            is_tiktok=is_tiktok,
            is_instagram=is_instagram,
            is_pinterest=is_pinterest,
            is_rednote=is_rednote,
            is_facebook_reel=is_facebook_reel,
            )
        )
        formatos = list(dict.fromkeys(formatos))
        baixou = False
        ultimo_erro = None
        instagram_html_fallback_tentado = False

        # Se os metadados públicos já informam que o Reel veio sem áudio,
        # tenta o fallback da página pública IMEDIATAMENTE, antes de qualquer
        # seletor normal do yt-dlp. Isso evita que um MP4/DASH mudo seja aceito
        # antes que o fallback tenha a chance de procurar uma origem completa.
        if is_instagram and audio_instagram_esperado is False:
            instagram_html_fallback_tentado = True
            logger.info(
                "[INSTAGRAM_HTML_INICIO] motivo=metadata_sem_audio "
                f"url_ref={referencia_url_log(url)}"
            )
            try:
                arquivo_html = baixar_instagram_publico_com_audio(url, prefix)
                if arquivo_html and os.path.exists(arquivo_html):
                    info_html = obter_info_midia(arquivo_html)
                    tem_audio_html = arquivo_possui_audio(info_html)
                    logger.info(
                        "[INSTAGRAM_HTML_RESULTADO] "
                        f"tem_audio={tem_audio_html} "
                        f"vcodec={info_html.get('vcodec')} "
                        f"acodec={info_html.get('acodec')}"
                    )
                    if tem_audio_html:
                        baixou = True
                    else:
                        cleanup_prefix(prefix)
            except Exception as e:
                logger.warning(
                    "[INSTAGRAM_HTML_FALLBACK_FALHA] "
                    f"url_ref={referencia_url_log(url)} "
                    f"erro={sanitizar_erro_log(e)}"
                )
                cleanup_prefix(prefix)

        if is_instagram:
            modos_cookie = [False]
        elif is_tiktok:
            modos_cookie = [usar_cookies_plataforma]
            if usar_cookies_plataforma:
                modos_cookie.append(False)
        else:
            modos_cookie = [False]

        for usar_cookies in ([] if baixou else modos_cookie):
            atualizar_heartbeat_worker("baixando")
            common_opts = montar_download_opts(
                prefix,
                is_instagram=is_instagram,
                usar_cookies=usar_cookies,
                is_tiktok=is_tiktok,
                tiktok_extractor_args=tiktok_extractor_args_usados,
                is_facebook_reel=is_facebook_reel,
            )

            for fmt in formatos:
                try:
                    # Primeiro testa todos os MP4 diretos já encontrados pelo
                    # yt-dlp. Se nenhum deles tiver áudio, antes dos seletores
                    # DASH/gerais consulta as páginas públicas/embeds oficiais.
                    if (
                        is_instagram
                        and not instagram_html_fallback_tentado
                        and fmt not in formatos_progressivos_ig
                    ):
                        instagram_html_fallback_tentado = True
                        logger.info(
                            "[INSTAGRAM_HTML_INICIO] motivo=progressivos_sem_audio "
                            f"url_ref={referencia_url_log(url)}"
                        )
                        arquivo_html = baixar_instagram_publico_com_audio(url, prefix)
                        if arquivo_html and os.path.exists(arquivo_html):
                            baixou = True
                            break

                    cleanup_prefix(prefix)

                    opts = common_opts.copy()
                    opts["format"] = fmt

                    # O info bruto já contém as URLs dos formatos. Reutilizá-lo
                    # evita consultar a mesma página antes de cada tentativa.
                    baixar_info_ja_extraida(info, opts)

                    arquivo_baixado = encontrar_arquivo_baixado(prefix)
                    if arquivo_baixado and os.path.exists(arquivo_baixado):
                        if is_instagram:
                            info_arquivo_baixado = obter_info_midia(arquivo_baixado)
                            tem_audio_real = arquivo_possui_audio(info_arquivo_baixado)
                            logger.info(
                                "[INSTAGRAM_AUDIO_PROBE] "
                                f"formato={fmt} tem_audio={tem_audio_real} "
                                f"vcodec={info_arquivo_baixado.get('vcodec')} "
                                f"acodec={info_arquivo_baixado.get('acodec')}"
                            )
                            if not tem_audio_real:
                                ultimo_erro = (
                                    "INSTAGRAM_AUDIO_AUSENTE_NO_ARQUIVO "
                                    f"metadata={audio_instagram_esperado}"
                                )
                                # Os IDs diretos/HTTP são justamente os formatos
                                # que o yt-dlp marca como codec desconhecido. Testa
                                # todos eles antes de aceitar o fallback mudo.
                                if fmt in formatos_progressivos_ig:
                                    logger.warning(
                                        "[INSTAGRAM_PROGRESSIVO_SEM_AUDIO] "
                                        f"formato={fmt} tentando_proximo=True"
                                    )
                                    cleanup_prefix(prefix)
                                    continue
                                if audio_instagram_esperado is True:
                                    logger.warning(
                                        "[INSTAGRAM_AUDIO_RETRY] "
                                        f"audio_esperado={audio_instagram_esperado} "
                                        f"formato={fmt} "
                                        f"arquivo_ref={referencia_arquivo_log(arquivo_baixado)}"
                                    )
                                    cleanup_prefix(prefix)
                                    continue
                                logger.warning(
                                    "[INSTAGRAM_FALLBACK_SEM_AUDIO] "
                                    f"formato={fmt} metadata={audio_instagram_esperado}"
                                )
                        if is_facebook_reel:
                            info_arquivo_baixado = obter_info_midia(arquivo_baixado)
                            if not arquivo_possui_audio(info_arquivo_baixado):
                                ultimo_erro = (
                                    "FACEBOOK_AUDIO_AUSENTE_NO_ARQUIVO "
                                    f"metadata={audio_facebook_esperado}"
                                )
                                logger.warning(
                                    "[FACEBOOK_REELS_AUDIO_RETRY] "
                                    f"audio_esperado={audio_facebook_esperado} "
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

        if not baixou and is_facebook_reel:
            logger.info(
                "[FACEBOOK_DASH_FALLBACK_INICIO] "
                f"url_ref={referencia_url_log(url)}"
            )
            try:
                arquivo_dash = baixar_facebook_dash_com_audio(url, prefix)
                if arquivo_dash and os.path.exists(arquivo_dash):
                    info_dash = obter_info_midia(arquivo_dash)
                    if not arquivo_possui_audio(info_dash):
                        raise RuntimeError("FACEBOOK_DASH_FINAL_SEM_AUDIO")
                    baixou = True
                    logger.info(
                        "[FACEBOOK_DASH_FALLBACK_OK] "
                        f"arquivo_ref={referencia_arquivo_log(arquivo_dash)} "
                        f"width={info_dash.get('width')} "
                        f"height={info_dash.get('height')} "
                        f"vcodec={info_dash.get('vcodec')} "
                        f"acodec={info_dash.get('acodec')}"
                    )
            except Exception as e:
                ultimo_erro = (
                    "FACEBOOK_DASH_FALLBACK_FALHOU "
                    + sanitizar_erro_log(e, limite=300)
                )
                logger.warning(
                    "[FACEBOOK_DASH_FALLBACK_FALHA] "
                    f"erro={sanitizar_erro_log(e)}"
                )

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

        instagram_sem_audio = False
        if is_instagram:
            try:
                instagram_sem_audio = not arquivo_possui_audio(
                    obter_info_midia(arquivo_envio)
                )
            except Exception as e:
                logger.warning(
                    "[INSTAGRAM_AUDIO_CHECK] "
                    f"arquivo_ref={referencia_arquivo_log(arquivo_envio)} "
                    f"erro={sanitizar_erro_log(e)}"
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

        # Nunca guarda no cache um Reel do Instagram que chegou sem áudio.
        # Além de evitar repetir um arquivo defeituoso, isso permite que uma
        # tentativa futura use novamente as rotas web/iOS do extrator.
        if is_instagram and instagram_sem_audio:
            logger.warning(
                "[INSTAGRAM_CACHE_IGNORADO_SEM_AUDIO] "
                f"url_ref={referencia_url_log(url)}"
            )
        else:
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

        if is_instagram and instagram_sem_audio:
            logger.warning(
                "[INSTAGRAM_SEM_AUDIO_ENTREGUE] "
                f"user_ref={referencia_usuario_log(message.from_user.id)} "
                f"url_ref={referencia_url_log(url)}"
            )
            safe_send_message(
                message.chat.id,
                "🔇 Não foi possível incluir o áudio nesta versão.",
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
        elif "facebook.com" in url_erro or "fb.watch" in url_erro:
            plataforma_erro = "facebook"
        elif "shopee.com.br" in url_erro or "shp.ee" in url_erro:
            plataforma_erro = "shopee"
        elif "mercadolivre.com.br" in url_erro and ("/clips" in url_erro or "/live/videos" in url_erro):
            plataforma_erro = "mercado_livre_clips"
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
        elif "facebook.com" in url_erro or "fb.watch" in url_erro:
            plataforma_erro = "facebook"
        elif "shopee.com.br" in url_erro or "shp.ee" in url_erro:
            plataforma_erro = "shopee"
        elif "mercadolivre.com.br" in url_erro and ("/clips" in url_erro or "/live/videos" in url_erro):
            plataforma_erro = "mercado_livre_clips"
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
            "Instagram, Facebook Reels, Shopee Video, Mercado Livre Clips ou RedNote.",
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

    is_admin_download = int(message.from_user.id) == ADMIN_ID
    prioridade_fila = -1 if is_admin_download else (0 if vip_status else 1)

    if is_admin_download:
        texto_fila = "👑 Link recebido com prioridade do administrador. Aguarde o processamento..."
    elif vip_status:
        texto_fila = "💎 Link recebido com prioridade VIP. Aguarde o processamento..."
    else:
        texto_fila = "⏳ Link recebido. Aguarde o processamento..."

    status_msg = safe_reply_to(message, texto_fila)

    recusado_desligamento = False
    fila_ficou_cheia = False
    with DOWNLOAD_QUEUE_STATE_LOCK:
        if SHUTDOWN_EVENT.is_set():
            recusado_desligamento = True
        else:
            try:
                DOWNLOAD_QUEUE.put_nowait(
                    (
                        prioridade_fila,
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
                logger.info(
                    "[QUEUE_ENQUEUE] "
                    f"user_ref={referencia_usuario_log(message.from_user.id)} "
                    f"classe={'admin' if is_admin_download else ('vip' if vip_status else 'gratis')} "
                    f"prioridade={prioridade_fila} tamanho={DOWNLOAD_QUEUE.qsize()}"
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
    logger.info("[BOT_BUILD] bot_downloads_v4_ml_clips_v12_3_start_fix")
    logger.info("[VIP_SYNC_CONFIG] startup=True pos_pagamento=True bloqueio_removervip=True comando_syncvip=True")
    logger.info("[VIP_SYNC_FIX] projection_status=True formatacao_newline=True log_motivo=True")
    logger.info("[VIP_SYNC_POLICY] paid_sozinho_nao_reativa=True exige_vip_aplicado_ao_pedido=True respeita_bloqueio_admin=True")
    logger.info("[START_FIX] mongo_update_conflict=False tracking_nao_bloqueia_start=True vip_e_gratis=True")
    logger.info("[BACKUP_MENU_CONFIG] backupvips=True backupgeral=True")
    logger.info("[AQUISICAO_CONFIG] deep_link=True linkads=True origens=True origem_imutavel=True")
    logger.info("[BACKUP_VERIFY_CONFIG] schema=2 json_roundtrip=True dry_run=True db_writes=0")
    logger.info("[VIP_PLAN_CONFIG] novos=mensal anual=historico_nao_vendavel")
    logger.info("[QUEUE_PRIORITY_CONFIG] admin=-1 vip=0 gratis=1 worker_compartilhado=True")
    logger.info("[ML_CLIPS_CONFIG] enabled=True login=False cookies=False token=False source=public_mobile_html_hls dns_guard=host_allowlist")
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
    logger.info(
        "[FACEBOOK_REELS_CONFIG] publico_somente=True cookies=False "
        "max_duration_compartilhado=True prefer_h264=True "
        "validacao_audio=True fallback_publico=True rejeita_sem_audio=True "
        f"cache_version={FACEBOOK_AUDIO_CACHE_VERSION}"
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
    sincronizar_vips_pagos_ativos(notificar_admin=True)
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
