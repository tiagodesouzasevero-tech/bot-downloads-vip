import os
import re
import glob
import uuid
import time
import copy
import html
import hashlib
import ipaddress
import itertools
import logging
import socket
import shutil
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Full, PriorityQueue
from threading import Lock, Thread
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
from pymongo import MongoClient
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
LINK_SUPORTE = get_env_required("LINK_SUPORTE")
ADMIN_ID = int(get_env_required("ADMIN_ID"))

# Vendas exclusivamente por Pix manual. Nenhuma integração de checkout ou
# cartão é carregada pelo bot. Os dados ficam somente nas variáveis do Railway.
PIX_KEY = get_env_required("PIX_KEY")
PIX_RECEIVER_NAME = get_env_required("PIX_RECEIVER_NAME")
PIX_RECEIVER_BANK = get_env_required("PIX_RECEIVER_BANK")

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads_temp")
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

FREE_DAILY_LIMIT = 3
MAX_DURATION_SECONDS = 90
MAX_URL_LENGTH = get_env_int("MAX_URL_LENGTH", 2048, 256, 8192)
MAX_SOURCE_FILE_MB = get_env_int("MAX_SOURCE_FILE_MB", 100, 10, 500)
MAX_OUTPUT_FILE_MB = get_env_int("MAX_OUTPUT_FILE_MB", 50, 5, 200)
MAX_SOURCE_FILE_BYTES = MAX_SOURCE_FILE_MB * 1024 * 1024
MAX_OUTPUT_FILE_BYTES = MAX_OUTPUT_FILE_MB * 1024 * 1024
FFPROBE_TIMEOUT_SECONDS = get_env_int("FFPROBE_TIMEOUT_SECONDS", 30, 5, 120)
FFMPEG_TIMEOUT_SECONDS = get_env_int("FFMPEG_TIMEOUT_SECONDS", 300, 30, 1800)
DOWNLOAD_TIMEOUT_SECONDS = get_env_int("DOWNLOAD_TIMEOUT_SECONDS", 240, 30, 1800)
FFMPEG_THREADS = get_env_int("FFMPEG_THREADS", 2, 1, 8)
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
DOWNLOAD_QUEUE_MAX = get_env_int("DOWNLOAD_QUEUE_MAX", 10, 1, 50)
PIX_ORDER_EXPIRATION_HOURS = get_env_int(
    "PIX_ORDER_EXPIRATION_HOURS", 24, 1, 168
)
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
MEDIA_PROFILE_VERSION = (
    f"720x1280_30fps_h264_crf{VIDEO_CRF}_audio{AUDIO_BITRATE}_sem_marca_v2"
)

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
DOWNLOAD_SEQUENCE = itertools.count()
TIKWM_CIRCUIT_LOCK = Lock()
TIKWM_CIRCUIT_STATE = {"failures": 0, "open_until": 0.0}
BOT_STATE_LOCK = Lock()
BOT_STATE = "starting"
BOT_LAST_UPDATE_AT = None
DOWNLOAD_WORKER_STATE_LOCK = Lock()
DOWNLOAD_WORKER_RUNNING = False
PLATFORM_MONITOR_LOCK = Lock()
PLATFORM_MONITOR_STATE = {
    plataforma: {
        "failures": deque(),
        "alert_active": False,
        "last_alert_at": 0.0,
        "last_error": None,
        "last_success_at": None,
    }
    for plataforma in ("TikTok", "Instagram", "Pinterest", "RedNote")
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

try:
    usuarios_col.create_index("vip_ate")
    usuarios_col.create_index("ultima_data")
    pedidos_col.create_index("order_nsu", unique=True)
    pedidos_col.create_index("status")
    pedidos_col.create_index("user_id")
    pedidos_col.create_index([("user_id", 1), ("status", 1), ("created_at", -1)])
    pedidos_col.create_index("expires_at", expireAfterSeconds=0)
    midia_cache_col.create_index("expires_at", expireAfterSeconds=0)
except Exception as e:
    logger.warning(f"[MONGO_INDEX] Não foi possível garantir índices agora: {e}")

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


def referencia_url_log(url):
    """Identifica uma URL nos logs sem gravar caminho, consulta ou tokens."""
    texto = str(url or "").strip()
    try:
        host = (urlparse(texto).hostname or "desconhecido").lower()
    except Exception:
        host = "desconhecido"
    digest = hashlib.sha256(texto.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"{host}#{digest}"


def sanitizar_erro_log(erro, limite=1200):
    texto = str(erro or "")
    texto = re.sub(r"https?://[^\s]+", "[url]", texto, flags=re.IGNORECASE)
    return texto[:limite]


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
                logger.warning(f"[CLEANUP] Falha ao remover {arq}: {e}")
    except Exception as e:
        logger.warning(f"[CLEANUP] Falha geral no prefixo {prefix}: {e}")


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
                    logger.info(f"[CLEANUP_OLD] Removido arquivo antigo: {arq}")
            except Exception as e:
                logger.warning(f"[CLEANUP_OLD] Falha ao remover {arq}: {e}")
    except Exception as e:
        logger.warning(f"[CLEANUP_OLD] Falha geral no diretório {DOWNLOAD_DIR}: {e}")


def cleanup_download_dir_periodicamente(interval_minutes=60, max_age_hours=6):
    intervalo_segundos = max(300, int(interval_minutes * 60))
    logger.info(
        f"[CLEANUP_LOOP] iniciado interval_minutes={interval_minutes} max_age_hours={max_age_hours}"
    )

    while True:
        try:
            cleanup_download_dir_old_files(max_age_hours=max_age_hours)
        except Exception as e:
            logger.warning(f"[CLEANUP_LOOP] erro={e}")
        time.sleep(intervalo_segundos)


def encontrar_arquivo_baixado(prefix):
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
    except subprocess.TimeoutExpired:
        logger.warning(
            f"[FFPROBE] Tempo limite excedido arquivo={arquivo_entrada} "
            f"timeout={FFPROBE_TIMEOUT_SECONDS}s"
        )
        return None

    if resultado.returncode != 0:
        logger.warning(f"[FFPROBE] Falha ao analisar {arquivo_entrada}: {resultado.stderr[-500:]}")
        return None

    try:
        import json
        dados = json.loads(resultado.stdout)
    except Exception as e:
        logger.warning(f"[FFPROBE] JSON inválido para {arquivo_entrada}: {e}")
        return None

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
    except Exception:
        tamanho = None

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
        raise RuntimeError(f"ARQUIVO_MIDIA_AUSENTE fase={fase}")

    tamanho = os.path.getsize(arquivo)
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
        raise RuntimeError(f"MIDIA_INVALIDA_OU_NAO_ANALISAVEL fase={fase}")

    duracao = info.get("duration")
    if exigir_duracao and (duracao is None or duracao <= 0):
        raise RuntimeError(f"DURACAO_MIDIA_DESCONHECIDA fase={fase}")
    if duracao and duracao > MAX_DURATION_SECONDS + 0.5:
        raise RuntimeError(
            f"VIDEO_MUITO_LONGO fase={fase} duracao={duracao:.2f} "
            f"limite={MAX_DURATION_SECONDS}"
        )

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
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"FFMPEG_TIMEOUT remux timeout={FFMPEG_TIMEOUT_SECONDS}s"
        ) from e

    if resultado.returncode != 0:
        raise Exception(f"Falha no remux do ffmpeg: {resultado.stderr[-1500:]}")

    if not os.path.exists(arquivo_saida):
        raise Exception("Arquivo remuxado não foi gerado.")

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
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"FFMPEG_TIMEOUT fallback timeout={FFMPEG_TIMEOUT_SECONDS}s"
        ) from e

    if resultado.returncode != 0:
        raise Exception(f"Falha no ffmpeg fallback H.264: {resultado.stderr[-1500:]}")

    if not os.path.exists(arquivo_saida):
        raise Exception("Arquivo fallback H.264 não foi gerado.")

    return arquivo_saida


def converter_para_720x1280_30fps(arquivo_entrada):
    """
    Garante saída final em no máximo 720x1280, 30fps, H.264/AAC.
    Mantém a proporção original sem adicionar bordas e nunca amplia vídeos
    que já tenham resolução menor que o limite.
    """
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
        resultado = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"FFMPEG_TIMEOUT conversao timeout={FFMPEG_TIMEOUT_SECONDS}s"
        ) from e

    if resultado.returncode != 0:
        raise Exception(f"Falha no ffmpeg: {resultado.stderr[-1500:]}")

    if not os.path.exists(arquivo_saida):
        raise Exception("Arquivo convertido não foi gerado.")

    return arquivo_saida


def preparar_arquivo_para_envio(arquivo_entrada, plataforma=None):
    info = obter_info_midia(arquivo_entrada)
    permitir_hevc = permitir_hevc_por_plataforma(plataforma)

    if arquivo_ja_otimizado_para_envio(arquivo_entrada, info, permitir_hevc=permitir_hevc):
        logger.info(
            f"[MIDIA] Enviando original sem reconversão | plataforma={plataforma} arquivo={arquivo_entrada} "
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
                f"[MIDIA] Fazendo apenas remux para MP4 | plataforma={plataforma} arquivo={arquivo_entrada} "
                f"width={width} height={height} fps={fps} "
                f"vcodec={info.get('vcodec')} acodec={info.get('acodec')} permitir_hevc={permitir_hevc}"
            )
            return remuxar_para_mp4_faststart(arquivo_entrada)

    logger.info(
        f"[MIDIA] Convertendo arquivo para padrão 720x1280 30fps | plataforma={plataforma} "
        f"arquivo={arquivo_entrada} info={info} permitir_hevc={permitir_hevc}"
    )
    return converter_para_720x1280_30fps(arquivo_entrada)


def safe_send_message(chat_id, texto, **kwargs):
    try:
        return bot.send_message(chat_id, texto, **kwargs)
    except Exception as e:
        logger.error(f"[SEND_MESSAGE] chat_id={chat_id} erro={e}")
        return None


def safe_reply_to(message, texto, **kwargs):
    try:
        return bot.reply_to(message, texto, **kwargs)
    except Exception as e:
        logger.error(f"[REPLY_TO] chat_id={message.chat.id} erro={e}")
        return None


def safe_edit_message(chat_id, message_id, texto, **kwargs):
    try:
        return bot.edit_message_text(texto, chat_id, message_id, **kwargs)
    except Exception as e:
        logger.warning(f"[EDIT_MESSAGE] chat_id={chat_id} message_id={message_id} erro={e}")
        return None


def safe_delete_message(chat_id, message_id):
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as e:
        logger.warning(f"[DELETE_MESSAGE] chat_id={chat_id} message_id={message_id} erro={e}")


def safe_answer_callback(call_id, **kwargs):
    try:
        bot.answer_callback_query(call_id, **kwargs)
    except Exception as e:
        logger.warning(f"[CALLBACK_ANSWER] erro={e}")


def normalizar_plataforma_monitoramento(plataforma):
    mapa = {
        "tiktok": "TikTok",
        "instagram": "Instagram",
        "pinterest": "Pinterest",
        "rednote": "RedNote",
    }
    return mapa.get(str(plataforma or "").strip().lower())


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


def registrar_falha_plataforma(plataforma, erro):
    """Alerta o administrador apenas após falhas técnicas repetidas."""
    plataforma = normalizar_plataforma_monitoramento(plataforma)
    if not plataforma or not falha_tecnica_monitoravel(erro):
        return False

    agora_monotonic = time.monotonic()
    inicio_janela = agora_monotonic - MONITOR_FAILURE_WINDOW_SECONDS
    erro_limpo = sanitizar_erro_log(erro, limite=500)
    deve_alertar = False
    total_falhas = 0

    with PLATFORM_MONITOR_LOCK:
        estado = PLATFORM_MONITOR_STATE[plataforma]
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
        f"[MONITOR_FALHA] plataforma={plataforma} "
        f"falhas_janela={total_falhas} alerta={deve_alertar} erro={erro_limpo}"
    )

    if deve_alertar:
        janela_minutos = max(1, MONITOR_FAILURE_WINDOW_SECONDS // 60)
        safe_send_message(
            ADMIN_ID,
            "⚠️ <b>Alerta automático de funcionamento</b>\n\n"
            f"Plataforma: <b>{html.escape(plataforma)}</b>\n"
            f"Falhas técnicas: <b>{total_falhas}</b> nos últimos "
            f"{janela_minutos} minutos\n"
            f"Última falha: <code>{html.escape(erro_limpo)}</code>\n\n"
            "O bot continuará tentando normalmente. Você será avisado quando "
            "um download real voltar a funcionar.",
            parse_mode="HTML",
        )
    return deve_alertar


def registrar_sucesso_plataforma(plataforma):
    """Limpa as falhas e avisa quando um serviço em alerta se recupera."""
    plataforma = normalizar_plataforma_monitoramento(plataforma)
    if not plataforma:
        return False

    recuperou = False
    with PLATFORM_MONITOR_LOCK:
        estado = PLATFORM_MONITOR_STATE[plataforma]
        recuperou = bool(estado["alert_active"])
        estado["failures"].clear()
        estado["alert_active"] = False
        estado["last_error"] = None
        estado["last_success_at"] = agora_tz().isoformat()

    logger.info(
        f"[MONITOR_SUCESSO] plataforma={plataforma} recuperacao={recuperou}"
    )
    if recuperou:
        safe_send_message(
            ADMIN_ID,
            "✅ <b>Serviço normalizado</b>\n\n"
            f"A plataforma <b>{html.escape(plataforma)}</b> voltou a concluir "
            "downloads reais normalmente.",
            parse_mode="HTML",
        )
    return recuperou


def obter_resumo_monitoramento():
    agora_monotonic = time.monotonic()
    inicio_janela = agora_monotonic - MONITOR_FAILURE_WINDOW_SECONDS
    resumo = {}

    with PLATFORM_MONITOR_LOCK:
        for plataforma, estado in PLATFORM_MONITOR_STATE.items():
            falhas = estado["failures"]
            while falhas and falhas[0] < inicio_janela:
                falhas.popleft()
            resumo[plataforma] = {
                "falhas_recentes": len(falhas),
                "alerta_ativo": bool(estado["alert_active"]),
                "ultimo_erro": estado.get("last_error"),
                "ultimo_sucesso": estado.get("last_success_at"),
            }
    return resumo


def definir_estado_worker_download(ativo):
    global DOWNLOAD_WORKER_RUNNING
    with DOWNLOAD_WORKER_STATE_LOCK:
        DOWNLOAD_WORKER_RUNNING = bool(ativo)


def worker_download_esta_ativo():
    with DOWNLOAD_WORKER_STATE_LOCK:
        return DOWNLOAD_WORKER_RUNNING


def extrair_file_id_telegram(mensagem):
    video = getattr(mensagem, "video", None)
    documento = getattr(mensagem, "document", None)
    return getattr(video, "file_id", None) or getattr(documento, "file_id", None)


def enviar_arquivo_com_fallback(chat_id, arquivo):
    try:
        with open(arquivo, "rb") as f:
            mensagem = bot.send_video(
                chat_id,
                f,
                caption="👉 Download concluído! Aqui está seu vídeo 👊",
            )
        return True, extrair_file_id_telegram(mensagem)
    except Exception as e_video:
        logger.warning(f"[SEND_VIDEO] Falhou no envio como vídeo. arquivo={arquivo} erro={e_video}")

    info = obter_info_midia(arquivo)
    arquivo_fallback = None

    if arquivo_tem_codec_hevc(arquivo, info):
        try:
            logger.info(
                f"[SEND_VIDEO] Tentando fallback automático HEVC -> H.264 | arquivo={arquivo} "
                f"width={(info or {}).get('width')} height={(info or {}).get('height')} "
                f"fps={(info or {}).get('fps')} vcodec={(info or {}).get('vcodec')}"
            )
            arquivo_fallback = converter_para_h264_compativel(arquivo, info)
            validar_arquivo_midia(
                arquivo_fallback,
                MAX_OUTPUT_FILE_BYTES,
                fase="fallback_h264",
            )

            with open(arquivo_fallback, "rb") as f:
                mensagem = bot.send_video(
                    chat_id,
                    f,
                    caption="👉 Download concluído! Aqui está seu vídeo 👊",
                )

            logger.info(f"[SEND_VIDEO] Fallback H.264 enviado com sucesso | arquivo={arquivo_fallback}")
            return True, extrair_file_id_telegram(mensagem)
        except Exception as e_h264:
            logger.warning(f"[SEND_VIDEO] Fallback H.264 também falhou. erro={e_h264}")

    alvo_documento = arquivo_fallback if arquivo_fallback and os.path.exists(arquivo_fallback) else arquivo

    try:
        with open(alvo_documento, "rb") as f:
            mensagem = bot.send_document(
                chat_id,
                f,
                caption="👉 Download concluído! Aqui está seu arquivo 👊",
            )
        return True, extrair_file_id_telegram(mensagem)
    except Exception as e_doc:
        logger.error(f"[SEND_DOCUMENT] Também falhou. erro={e_doc}")
        return False, None


def montar_chave_cache_midia(plataforma, info, url):
    source_id = str(
        (info or {}).get("id")
        or (info or {}).get("display_id")
        or (info or {}).get("webpage_url")
        or url
    ).strip()
    material = f"{MEDIA_PROFILE_VERSION}|source|{plataforma.lower()}|{source_id}"
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
    material = f"{MEDIA_PROFILE_VERSION}|url|{plataforma.lower()}|{url_normalizada}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest(), url_normalizada


def obter_file_id_cache(cache_key):
    try:
        doc = midia_cache_col.find_one({"_id": cache_key})
        if not doc:
            return None
        expires_at = doc.get("expires_at")
        agora_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        if expires_at and expires_at < agora_utc_naive:
            midia_cache_col.delete_one({"_id": cache_key})
            return None
        return doc.get("telegram_file_id")
    except Exception as e:
        logger.warning(f"[CACHE_MIDIA_LEITURA] key={cache_key[:12]} erro={e}")
        return None


def salvar_file_id_cache(
    cache_key,
    source_id,
    plataforma,
    telegram_file_id,
    url_cache_key=None,
    url_normalizada=None,
):
    if not telegram_file_id:
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
    except Exception as e:
        logger.warning(f"[CACHE_MIDIA_GRAVACAO] key={cache_key[:12]} erro={e}")


def enviar_video_cacheado(chat_id, cache_key, telegram_file_id):
    try:
        bot.send_video(
            chat_id,
            telegram_file_id,
            caption="👉 Download concluído! Aqui está seu vídeo 👊",
        )
        logger.info(f"[CACHE_MIDIA_HIT] key={cache_key[:12]} envio_sem_upload=True")
        return True
    except Exception as e:
        logger.warning(f"[CACHE_MIDIA_INVALIDO] key={cache_key[:12]} erro={e}")
        try:
            midia_cache_col.delete_one({"_id": cache_key})
        except Exception:
            pass
        return False


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
    """Aplica limites de velocidade, sem transformar o VIP em plano diário."""
    try:
        if int(user_id) == ADMIN_ID:
            return True, None
    except (TypeError, ValueError):
        pass

    agora = time.monotonic()
    inicio_hora = agora - 3600
    chave = str(user_id)

    with DOWNLOAD_RATE_LOCK:
        while DOWNLOAD_GLOBAL_EVENTS and DOWNLOAD_GLOBAL_EVENTS[0] < inicio_hora:
            DOWNLOAD_GLOBAL_EVENTS.popleft()

        eventos_usuario = DOWNLOAD_RATE_EVENTS[chave]
        while eventos_usuario and eventos_usuario[0] < inicio_hora:
            eventos_usuario.popleft()

        if DOWNLOAD_COOLDOWN_SECONDS and eventos_usuario:
            decorrido = agora - eventos_usuario[-1]
            if decorrido < DOWNLOAD_COOLDOWN_SECONDS:
                restante = max(1, int(DOWNLOAD_COOLDOWN_SECONDS - decorrido) + 1)
                return False, (
                    f"⏳ Aguarde {restante} segundos antes de enviar outro link."
                )

        if len(eventos_usuario) >= MAX_DOWNLOADS_PER_USER_HOUR:
            return False, (
                "⚠️ Muitas solicitações em pouco tempo. "
                "Aguarde alguns minutos e tente novamente."
            )

        if len(DOWNLOAD_GLOBAL_EVENTS) >= MAX_DOWNLOADS_GLOBAL_HOUR:
            return False, (
                "⚠️ O bot está com alta demanda agora. "
                "Aguarde alguns minutos e tente novamente."
            )

        eventos_usuario.append(agora)
        DOWNLOAD_GLOBAL_EVENTS.append(agora)

        # Remove usuários inativos para o dicionário não crescer indefinidamente.
        if len(DOWNLOAD_RATE_EVENTS) > 5000:
            for usuario_antigo in list(DOWNLOAD_RATE_EVENTS.keys())[:1000]:
                fila = DOWNLOAD_RATE_EVENTS[usuario_antigo]
                while fila and fila[0] < inicio_hora:
                    fila.popleft()
                if not fila:
                    DOWNLOAD_RATE_EVENTS.pop(usuario_antigo, None)

    return True, None


def get_instagram_cookiefile():
    texto = (INSTAGRAM_COOKIES_TEXT or "").strip()
    if not texto:
        return None

    # Algumas plataformas salvam quebras de linha como os caracteres \n.
    if "\n" not in texto and "\\n" in texto:
        texto = texto.replace("\\r\\n", "\n").replace("\\n", "\n")

    texto = texto.replace("\r\n", "\n").replace("\r", "\n").strip()

    # O yt-dlp espera o formato Netscape/Mozilla.
    if not texto.startswith("# Netscape HTTP Cookie File") and not texto.startswith("# HTTP Cookie File"):
        texto = "# Netscape HTTP Cookie File\n" + texto

    cookie_path = os.path.join(DOWNLOAD_DIR, "instagram_cookies.txt")
    with open(cookie_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto + "\n")

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

    cookie_path = os.path.join(DOWNLOAD_DIR, "tiktok_cookies.txt")
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
                with open(cookie_path, "r", encoding="utf-8") as f:
                    texto_arquivo = f.read()
            except OSError as e:
                logger.warning(f"[TIKTOK_COOKIES_LEITURA_FALHA] erro={e}")

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

            with open(cookie_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(texto_gravar.rstrip("\n") + "\n")

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

            with open(cookie_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(texto_gravar.rstrip("\n") + "\n")

            TIKTOK_COOKIES_ENV_APLICADOS = True
            logger.info(
                f"[TIKTOK_COOKIES] origem=variavel_railway_recriada "
                f"cookies_fornecidos=True linhas={len(linhas_env)}"
            )
            return cookie_path

        # Sem configuração, mantém um cookiefile válido e vazio para o yt-dlp
        # poder salvar uma sessão caso o desafio do TikTok permita.
        with open(cookie_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("# Netscape HTTP Cookie File\n")

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
    device_path = os.path.join(DOWNLOAD_DIR, "tiktok_device_id.txt")

    with TIKTOK_DEVICE_LOCK:
        device_id_env = validar_tiktok_device_id(TIKTOK_DEVICE_ID_TEXT)
        if TIKTOK_DEVICE_ID_TEXT.strip() and not device_id_env:
            logger.warning(
                "[TIKTOK_DEVICE_ID_INVALIDO] A variável TIKTOK_DEVICE_ID deve "
                "conter exatamente 19 dígitos; será usado o identificador persistente."
            )

        if device_id_env:
            try:
                with open(device_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(device_id_env + "\n")
            except OSError as e:
                logger.warning(f"[TIKTOK_DEVICE_ID_GRAVACAO_FALHA] origem=variavel erro={e}")
            logger.info("[TIKTOK_DEVICE_ID] origem=variavel_railway valido=True")
            return device_id_env

        if os.path.exists(device_path):
            try:
                with open(device_path, "r", encoding="utf-8") as f:
                    device_id_arquivo = validar_tiktok_device_id(f.read())
                if device_id_arquivo:
                    logger.info("[TIKTOK_DEVICE_ID] origem=arquivo_persistente valido=True")
                    return device_id_arquivo
            except OSError as e:
                logger.warning(f"[TIKTOK_DEVICE_ID_LEITURA_FALHA] erro={e}")

        # O intervalo é o mesmo usado pelo próprio extrator do yt-dlp. Gravar
        # no volume evita apresentar um aparelho diferente a cada tentativa.
        inicio = 7250000000000000000
        fim = 7325099899999994577
        device_id_novo = str(inicio + (uuid.uuid4().int % (fim - inicio + 1)))
        try:
            with open(device_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(device_id_novo + "\n")
            logger.info("[TIKTOK_DEVICE_ID] origem=gerado_persistente valido=True")
        except OSError as e:
            logger.warning(f"[TIKTOK_DEVICE_ID_GRAVACAO_FALHA] origem=gerado erro={e}")
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
                    f"[TIKTOK_HD_OK] video_id={video_id} sem_marca=True "
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


def extrair_info_instagram_com_fallback(url):
    """Tenta com cookies e repete anonimamente para Reels públicos."""
    tentativas = [True]
    if INSTAGRAM_COOKIES_TEXT.strip():
        tentativas.append(False)

    ultimo_erro = None
    for usar_cookies in tentativas:
        try:
            logger.info(
                f"[INSTAGRAM_INFO] usar_cookies={usar_cookies} "
                f"url_ref={referencia_url_log(url)}"
            )
            opts = montar_info_opts(is_instagram=True, usar_cookies=usar_cookies)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return info, usar_cookies
        except Exception as e:
            ultimo_erro = e
            logger.warning(
                f"[INSTAGRAM_INFO_FALHA] usar_cookies={usar_cookies} "
                f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
            )
            if not usar_cookies or not erro_instagram_permite_fallback(e):
                raise

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


def incrementar_download_gratis(user, chat_id, from_user_id):
    usuarios_col.update_one(
        {"_id": user["_id"]},
        {"$inc": {"downloads_hoje": 1}}
    )

    novo_count = user.get("downloads_hoje", 0) + 1
    safe_send_message(chat_id, f"📊 Uso diário: {novo_count}/{FREE_DAILY_LIMIT}")

    if novo_count >= FREE_DAILY_LIMIT:
        safe_send_message(
            chat_id,
            f"⚠️ *Você atingiu seu limite diário ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT})!*\n"
            "Para continuar baixando sem limite diário, libere um plano VIP: 👇",
            parse_mode="Markdown"
        )
        mostrar_planos_chat(chat_id, from_user_id)


def somar_downloads_gratuitos_usuarios_hoje():
    hoje = hoje_str()
    pipeline = [
        {"$match": {"ultima_data": hoje}},
        {"$group": {"_id": None, "total": {"$sum": "$downloads_hoje"}}}
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
        logger.error(f"[METRICAS_INIT] erro={e}")


def registrar_download_diario(vip_status):
    """Registra um download concluído sem interferir no limite do usuário gratuito."""
    try:
        hoje = hoje_str()
        agora = agora_tz()
        campo_tipo = "downloads_vips" if vip_status else "downloads_gratuitos"

        metricas_col.update_one(
            {"_id": hoje},
            {
                "$inc": {
                    "downloads_total": 1,
                    campo_tipo: 1,
                },
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
    except Exception as e:
        logger.error(f"[METRICAS_DOWNLOAD] vip={vip_status} erro={e}")


def gerar_order_nsu(user_id):
    return f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:10]}"


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
            data_base = datetime.strptime(vip_atual, "%Y-%m-%d").date()
            if data_base < hoje:
                data_base = hoje
        else:
            data_base = hoje
    except Exception:
        data_base = hoje

    nova_data = data_base + timedelta(days=dias)
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

        safe_send_message(int(user_id), texto, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[NOTIFICAR_PAGAMENTO] user_id={user_id} erro={e}")


# =========================================
# USUÁRIO / VIP
# =========================================
def obter_usuario(user_id):
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
            {"$set": {"downloads_hoje": 0, "ultima_data": hoje}}
        )
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje

    return user


def is_vip_user(user):
    v_ate = user.get("vip_ate")

    if v_ate == "Vitalício":
        return True

    if not v_ate:
        return False

    try:
        return agora_tz().date() <= datetime.strptime(v_ate, "%Y-%m-%d").date()
    except Exception as e:
        logger.warning(f"[IS_VIP_USER] vip_ate={v_ate} erro={e}")
        return False


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
        types.BotCommand("darvip", "Liberar VIP manualmente"),
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
        logger.warning(f"[TELEGRAM_MENU] não foi possível configurar: {e}")
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
    timestamp = agora_tz().strftime("%Y%m%d_%H%M%S")
    caminho = os.path.join(DOWNLOAD_DIR, f"{nome_arquivo_base}_{timestamp}.json")

    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return caminho


def enviar_documento_privado_admin(caminho_arquivo, legenda=None):
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
                    "manual_verified_at": 1,
                    "manual_verified_by": 1,
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
                    "manual_verified_at": 1,
                    "manual_verified_by": 1,
                }
            ).sort("created_at", -1)
        )
        metricas_docs = list(
            metricas_col.find({}).sort("_id", -1)
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
            "usuarios": [serializar_para_json(doc) for doc in usuarios_docs],
            "vips_ativos": [serializar_para_json(doc) for doc in vips_docs],
            "pedidos": [serializar_para_json(doc) for doc in pedidos_docs],
            "metricas_diarias": [serializar_para_json(doc) for doc in metricas_docs],
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
        logger.error(f"[BACKUP_ADMIN] tipo={tipo} erro={e}")
        safe_send_message(ADMIN_ID, f"❌ Erro ao gerar backup `{tipo}`.", parse_mode="Markdown")
        if origem_chat_id and origem_chat_id != ADMIN_ID:
            safe_send_message(origem_chat_id, "❌ Erro ao gerar backup do ADM.")
    finally:
        if caminho_arquivo and os.path.exists(caminho_arquivo):
            try:
                os.remove(caminho_arquivo)
            except Exception as e:
                logger.warning(f"[BACKUP_ADMIN_CLEANUP] arquivo={caminho_arquivo} erro={e}")
        BACKUP_ADMIN_LOCK.release()


def montar_relatorio_diagnostico():
    """Verifica componentes locais e conexões sem baixar nenhum vídeo."""
    linhas = ["🩺 <b>Diagnóstico do bot</b>", ""]
    problemas = []

    estado_bot, ultima_atividade = obter_estado_bot()
    if estado_bot == "polling":
        linhas.append("✅ Telegram: polling ativo")
    else:
        linhas.append(
            f"⚠️ Telegram: estado {html.escape(str(estado_bot))}"
        )
        problemas.append("Telegram não está em polling")

    try:
        client.admin.command("ping")
        linhas.append("✅ MongoDB: conectado")
    except Exception as e:
        linhas.append("❌ MongoDB: falha de conexão")
        problemas.append(f"MongoDB: {sanitizar_erro_log(e, limite=180)}")

    ffmpeg_ok = bool(shutil.which("ffmpeg"))
    ffprobe_ok = bool(shutil.which("ffprobe"))
    if ffmpeg_ok and ffprobe_ok:
        linhas.append("✅ FFmpeg e FFprobe: disponíveis")
    else:
        linhas.append("❌ FFmpeg/FFprobe: dependência ausente")
        problemas.append("FFmpeg ou FFprobe ausente")

    worker_ativo = worker_download_esta_ativo()
    linhas.append(
        "✅ Worker de downloads: ativo"
        if worker_ativo
        else "❌ Worker de downloads: inativo"
    )
    if not worker_ativo:
        problemas.append("Worker de downloads inativo")

    fila_ocupada = DOWNLOAD_QUEUE.qsize()
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
        icone_disco = "✅" if livre_percentual >= 10 else "⚠️"
        linhas.append(
            f"{icone_disco} Disco livre: {livre_mb:.0f} MB "
            f"({livre_percentual:.0f}%)"
        )
        if livre_percentual < 10:
            problemas.append("Pouco espaço livre em disco")
    except Exception as e:
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
        plataforma
        for plataforma, estado in resumo_monitor.items()
        if estado["alerta_ativo"]
    ]
    falhas_recentes = sum(
        estado["falhas_recentes"] for estado in resumo_monitor.values()
    )
    if alertas_ativos:
        linhas.append(
            "⚠️ Monitoramento: alerta em "
            + html.escape(", ".join(alertas_ativos))
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

    try:
        args = message.text.split()
        if len(args) < 3:
            return safe_reply_to(message, "❌ Use: `/darvip ID DIAS`", parse_mode="Markdown")

        alvo_id = str(args[1]).strip()
        if not re.fullmatch(r"[1-9]\d{0,19}", alvo_id):
            raise ValueError("ID inválida")
        dias = int(args[2])
        if dias < 1 or dias > 3650:
            raise ValueError("dias fora do intervalo")

        nova_data = (
            "Vitalício" if dias == 3650
            else calcular_nova_data_vip(obter_usuario(alvo_id), dias)
        )

        usuarios_col.update_one(
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
        safe_reply_to(
            message,
            f"✅ VIP liberado para `{alvo_id}` até *{validade}*.",
            parse_mode="Markdown",
        )
        safe_send_message(
            int(alvo_id),
            "💎 *Acesso VIP liberado*\n\n"
            f"Seu acesso está ativo até *{validade}*.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"[DARVIP] erro={sanitizar_erro_log(e)}")
        safe_reply_to(
            message,
            "❌ Use: `/darvip ID DIAS` (de 1 a 3650).",
            parse_mode="Markdown",
        )


@bot.message_handler(commands=["zerar"])
def zerar_contador(message):
    if not exigir_admin_privado(message):
        return

    try:
        args = message.text.split()
        if len(args) < 2:
            return safe_reply_to(message, "❌ Use: `/zerar ID`", parse_mode="Markdown")

        alvo_id = str(args[1]).strip()
        if not re.fullmatch(r"[1-9]\d{0,19}", alvo_id):
            raise ValueError("ID inválida")

        usuarios_col.update_one(
            {"_id": str(alvo_id)},
            {
                "$set": {
                    "downloads_hoje": 0,
                    "ultima_data": hoje_str()
                },
                "$setOnInsert": {
                    "vip_ate": None
                }
            },
            upsert=True
        )

        safe_reply_to(message, f"✅ Contador do usuário {alvo_id} foi zerado!")
        safe_send_message(
            int(alvo_id),
            "🔄 Suas tentativas diárias foram resetadas pelo suporte. Pode voltar a baixar!"
        )
    except Exception as e:
        logger.error(f"[ZERAR] erro={e}")
        safe_reply_to(message, "❌ Use: `/zerar ID`", parse_mode="Markdown")


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
            logger.info(f"[AVISOGERAL_BLOQUEADO] chat_id={user_id}")
            return "bloqueado"

        logger.error(f"[AVISOGERAL_FALHA] chat_id={user_id} erro={e}")
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
        logger.error(f"[AVISOGERAL_LOOP] erro={e}")
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
        logger.error(f"[AVISOGERAL] erro={e}")
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

        comprovantes_em_analise = pedidos_col.count_documents({
            "status": "receipt_submitted"
        })
        pedidos_pagos = pedidos_col.count_documents({"status": "paid"})

        resumo_admin = (
            "⚙️ *Painel Admin*\n\n"
            f"👥 Usuários: `{total_users}`\n"
            f"💎 VIPs: `{vips_ativos}`\n"
            f"📥 Downloads hoje: `{downloads_totais_hoje}`\n"
            f"   ├ 👤 Gratuitos: `{downloads_gratuitos_hoje}`\n"
            f"   └ 💎 VIPs: `{downloads_vips_hoje}`\n"
            f"🧾 Comprovantes aguardando análise: `{comprovantes_em_analise}`\n"
            f"✅ Pagamentos aprovados: `{pedidos_pagos}`"
        )

        safe_send_message(message.chat.id, resumo_admin, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[PAINEL_ADMIN] erro={e}")
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
            "👋 Precisa de ajuda? Clique abaixo para falar com o suporte.",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"[SUPORTE] erro={e}")
        safe_send_message(message.chat.id, f"Suporte: {LINK_SUPORTE}")


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
            "status": {"$in": ["awaiting_pix", "receipt_submitted"]},
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
        if pedido_ativo and pedido_ativo.get("status") == "receipt_submitted":
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
        logger.error(f"[PIX_MANUAL_INICIO] erro={e}")
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
        logger.error(f"[PIX_SOLICITAR_COMPROVANTE] erro={e}")
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
                f"[PIX_FORWARD_RECEIPT] order_nsu={order_nsu} "
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
                    f"[PIX_SEND_RECEIPT] order_nsu={order_nsu} "
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
            f"[PIX_RECEBER_COMPROVANTE] user_id={message.from_user.id} "
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
            if pedido.get("status") != "receipt_submitted":
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
                vip_ate, vip_aplicado = liberar_vip_por_plano(
                    pedido["user_id"],
                    plano,
                    order_nsu=order_nsu,
                )
                agora = agora_tz()
                resultado = pedidos_col.update_one(
                    {"order_nsu": order_nsu, "status": "receipt_submitted"},
                    {
                        "$set": {
                            "status": "paid",
                            "paid_at": agora,
                            "paid_amount": int(pedido.get("valor_centavos") or 0),
                            "capture_method": "pix_manual",
                            "payment_verification_status": "manual_verified",
                            "manual_verified_by": str(ADMIN_ID),
                            "manual_verified_at": agora,
                            "vip_liberado_ate": vip_ate,
                            "vip_aplicado_nesta_chamada": vip_aplicado,
                        },
                        "$unset": {"expires_at": ""},
                    },
                )
                if not resultado.modified_count:
                    safe_answer_callback(
                        call.id,
                        text="O pedido mudou de estado. Atualize o painel.",
                        show_alert=True,
                    )
                    return
                notificar_pagamento_confirmado(
                    pedido["user_id"], plano["nome"], vip_ate
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
                    f"[PIX_MANUAL_APROVADO] order_nsu={order_nsu} "
                    f"user_id={pedido['user_id']} vip_ate={vip_ate}"
                )
            else:
                agora = agora_tz()
                pedidos_col.update_one(
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
                logger.info(f"[PIX_MANUAL_REJEITADO] order_nsu={order_nsu}")
    except Exception as e:
        logger.error(
            f"[PIX_MANUAL_REVISAO] order_nsu={order_nsu} "
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
            "bestvideo[ext=mp4][width<=720][height<=1280][fps<=30]+bestaudio[ext=m4a]/best[ext=mp4][width<=720][height<=1280][fps<=30]",
            "bestvideo[ext=mp4][width<=720][height<=1280]+bestaudio[ext=m4a]/best[ext=mp4][width<=720][height<=1280]",
            "best[ext=mp4][width<=720][height<=1280][fps<=30]",
            "best[ext=mp4][width<=720][height<=1280]",
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


def _processar_download(message, url, status_msg):
    user = obter_usuario(message.from_user.id)
    vip_status = is_vip_user(user)
    prefix = None
    plataforma = nome_plataforma(*detectar_plataforma(url))

    try:
        if status_msg:
            safe_edit_message(
                message.chat.id,
                status_msg.message_id,
                "🔄 Processando seu vídeo...",
            )

        url = resolver_url_compartilhada(url)
        is_pinterest, is_tiktok, is_instagram, is_rednote = detectar_plataforma(url)
        plataforma = nome_plataforma(is_pinterest, is_tiktok, is_instagram, is_rednote)

        if is_instagram:
            url = normalizar_url_instagram(url)

        logger.info(
            f"[DOWNLOAD_INICIO] user_id={message.from_user.id} "
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
            prefix = os.path.join(DOWNLOAD_DIR, f"v_{message.from_user.id}_{uuid.uuid4().hex}")
            url_resolvida = resolver_link_pinterest(url)
            info = None
            cache_key = None
            cache_source_id = None
            url_cache_key, url_normalizada = montar_chave_cache_url(
                plataforma, url_resolvida
            )

            file_id_cache_url = obter_file_id_cache(url_cache_key)
            if file_id_cache_url and enviar_video_cacheado(
                message.chat.id, url_cache_key, file_id_cache_url
            ):
                registrar_download_diario(vip_status)
                if not vip_status:
                    incrementar_download_gratis(
                        user, message.chat.id, message.from_user.id
                    )
                if status_msg:
                    safe_delete_message(message.chat.id, status_msg.message_id)
                return

            try:
                with yt_dlp.YoutubeDL(montar_info_opts(is_pinterest=True)) as ydl:
                    info = ydl.extract_info(url_resolvida, download=False)

                duracao = info.get("duration")
                logger.info(f"[META] plataforma=Pinterest user_id={message.from_user.id} duration={duracao}")

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
                file_id_cache = obter_file_id_cache(cache_key)
                if file_id_cache and enviar_video_cacheado(
                    message.chat.id, cache_key, file_id_cache
                ):
                    salvar_file_id_cache(
                        cache_key,
                        cache_source_id,
                        plataforma,
                        file_id_cache,
                        url_cache_key=url_cache_key,
                        url_normalizada=url_normalizada,
                    )
                    registrar_download_diario(vip_status)
                    if not vip_status:
                        incrementar_download_gratis(
                            user, message.chat.id, message.from_user.id
                        )
                    if status_msg:
                        safe_delete_message(message.chat.id, status_msg.message_id)
                    return

            except Exception as e:
                logger.warning(f"[PINTEREST_INFO] Falha ao ler metadados: {e}")

            try:
                arquivo_final = baixar_pinterest_capado(
                    url_resolvida,
                    prefix,
                    info=info,
                )
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

                enviado, telegram_file_id = enviar_arquivo_com_fallback(
                    message.chat.id, arquivo_envio
                )
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
                    url_cache_key=url_cache_key,
                    url_normalizada=url_normalizada,
                )

                registrar_download_diario(vip_status)
                registrar_sucesso_plataforma(plataforma)

                if not vip_status:
                    incrementar_download_gratis(user, message.chat.id, message.from_user.id)

                if status_msg:
                    safe_delete_message(message.chat.id, status_msg.message_id)

                return

            except Exception as e:
                registrar_falha_plataforma(plataforma, e)
                logger.error(
                    f"[ERRO_PINTEREST] user_id={message.from_user.id} "
                    f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
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
        file_id_cache_url = obter_file_id_cache(url_cache_key)
        if file_id_cache_url and enviar_video_cacheado(
            message.chat.id, url_cache_key, file_id_cache_url
        ):
            registrar_download_diario(vip_status)
            if not vip_status:
                incrementar_download_gratis(user, message.chat.id, message.from_user.id)
            if status_msg:
                safe_delete_message(message.chat.id, status_msg.message_id)
            return

        prefix = os.path.join(DOWNLOAD_DIR, f"v_{message.from_user.id}_{uuid.uuid4().hex}")

        usar_cookies_plataforma = True
        tiktok_extractor_args_usados = None
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

        duracao = info.get("duration")
        logger.info(f"[META] plataforma={plataforma} user_id={message.from_user.id} duration={duracao}")

        if duracao and duracao > MAX_DURATION_SECONDS:
            texto = f"⚠️ Vídeo muito longo. O limite é de {MAX_DURATION_SECONDS} segundos."
            if status_msg:
                safe_edit_message(message.chat.id, status_msg.message_id, texto)
            else:
                safe_send_message(message.chat.id, texto)
            return

        cache_key, cache_source_id = montar_chave_cache_midia(plataforma, info, url)
        file_id_cache = obter_file_id_cache(cache_key)
        if file_id_cache and enviar_video_cacheado(
            message.chat.id, cache_key, file_id_cache
        ):
            salvar_file_id_cache(
                cache_key,
                cache_source_id,
                plataforma,
                file_id_cache,
                url_cache_key=url_cache_key,
                url_normalizada=url_normalizada,
            )
            registrar_download_diario(vip_status)
            if not vip_status:
                incrementar_download_gratis(user, message.chat.id, message.from_user.id)
            if status_msg:
                safe_delete_message(message.chat.id, status_msg.message_id)
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
                        baixou = True
                        break

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
            raise Exception(ultimo_erro or "Falha ao baixar dentro do limite 720x1280 30fps")

        arquivo_final = encontrar_arquivo_baixado(prefix)
        if not arquivo_final or not os.path.exists(arquivo_final):
            raise Exception("Arquivo final não encontrado após o download")

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

        enviado, telegram_file_id = enviar_arquivo_com_fallback(
            message.chat.id, arquivo_envio
        )
        if not enviado:
            raise Exception("Falha ao enviar arquivo ao Telegram")

        salvar_file_id_cache(
            cache_key,
            cache_source_id,
            plataforma,
            telegram_file_id,
            url_cache_key=url_cache_key,
            url_normalizada=url_normalizada,
        )

        registrar_download_diario(vip_status)
        registrar_sucesso_plataforma(plataforma)

        if not vip_status:
            incrementar_download_gratis(user, message.chat.id, message.from_user.id)

        if status_msg:
            safe_delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        registrar_falha_plataforma(plataforma, e)
        logger.error(
            f"[ERRO_DOWNLOAD] user_id={message.from_user.id} "
            f"url_ref={referencia_url_log(url)} erro={sanitizar_erro_log(e)}"
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


def loop_fila_downloads():
    logger.info(f"[DOWNLOAD_QUEUE] worker iniciado capacidade={DOWNLOAD_QUEUE_MAX}")
    definir_estado_worker_download(True)
    try:
        while True:
            _prioridade, _sequencia, trabalho = DOWNLOAD_QUEUE.get()
            message = trabalho["message"]
            user_id = str(message.from_user.id)
            try:
                _processar_download(
                    message,
                    trabalho["url"],
                    trabalho.get("status_msg"),
                )
            except Exception as e:
                logger.error(
                    f"[DOWNLOAD_WORKER] user_id={user_id} "
                    f"erro={sanitizar_erro_log(e)}"
                )
                safe_send_message(
                    message.chat.id,
                    "❌ Não consegui processar esse vídeo agora. Tente novamente em instantes.",
                )
            finally:
                with DOWNLOAD_PENDING_LOCK:
                    DOWNLOAD_PENDING_USERS.discard(user_id)
                DOWNLOAD_QUEUE.task_done()
    finally:
        definir_estado_worker_download(False)
        logger.error("[DOWNLOAD_QUEUE] worker encerrado inesperadamente")


@bot.message_handler(func=lambda message: message.text and "http" in message.text.lower())
def handle_download(message):
    if not is_chat_privado(message):
        orientar_uso_no_privado(message)
        return

    user = obter_usuario(message.from_user.id)
    vip_status = is_vip_user(user)
    if not vip_status and user.get("downloads_hoje", 0) >= FREE_DAILY_LIMIT:
        safe_reply_to(
            message,
            f"⚠️ *Limite diário atingido ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT})!*\n"
            "Para continuar baixando sem limite diário, libere o VIP abaixo: 👇",
            parse_mode="Markdown",
        )
        mostrar_planos_chat(message.chat.id, message.from_user.id)
        return

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

    status_msg = safe_reply_to(
        message,
        "💎 Link recebido com prioridade VIP. Aguarde o processamento..."
        if vip_status
        else "⏳ Link recebido. Aguarde o processamento...",
    )

    with DOWNLOAD_PENDING_LOCK:
        if user_id in DOWNLOAD_PENDING_USERS:
            if status_msg:
                safe_delete_message(message.chat.id, status_msg.message_id)
            return
        DOWNLOAD_PENDING_USERS.add(user_id)

    try:
        DOWNLOAD_QUEUE.put_nowait(
            (
                0 if vip_status else 1,
                next(DOWNLOAD_SEQUENCE),
                {"message": message, "url": url, "status_msg": status_msg},
            )
        )
    except Full:
        with DOWNLOAD_PENDING_LOCK:
            DOWNLOAD_PENDING_USERS.discard(user_id)
        if status_msg:
            safe_edit_message(
                message.chat.id,
                status_msg.message_id,
                "⏳ A fila ficou cheia. Aguarde um pouco e tente novamente.",
            )


# =========================================
# HEALTHCHECK
# =========================================
def obter_estado_bot():
    with BOT_STATE_LOCK:
        return BOT_STATE, BOT_LAST_UPDATE_AT


def montar_payload_health():
    estado, ultima_atividade = obter_estado_bot()
    return {
        "status": "ok" if estado == "polling" else "degraded",
        "service": SERVICE_NAME,
        "bot": estado,
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
            # O endpoint é de vida do contêiner. Durante uma reconexão do
            # Telegram ele continua 200, mas informa "degraded" no JSON.
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
    porta = int(os.environ.get("PORT", 8080))
    servidor = ThreadingHTTPServer(("0.0.0.0", porta), HealthRequestHandler)
    logger.info(f"[HEALTH] servidor iniciado porta={porta}")
    servidor.serve_forever()


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
        f"[CUSTO_CONFIG] cooldown={DOWNLOAD_COOLDOWN_SECONDS}s "
        f"user_hour={MAX_DOWNLOADS_PER_USER_HOUR} "
        f"global_hour={MAX_DOWNLOADS_GLOBAL_HOUR}"
    )
    logger.info(
        f"[MONITOR_CONFIG] threshold={MONITOR_FAILURE_THRESHOLD} "
        f"window={MONITOR_FAILURE_WINDOW_SECONDS}s "
        f"alert_cooldown={MONITOR_ALERT_COOLDOWN_SECONDS}s "
        "downloads_automaticos=False"
    )
    logger.info("[PAGAMENTO_CONFIG] modo=manual_pix configurado=True")
    if TIKTOK_IMPERSONATION_DISPONIVEL:
        logger.info(f"[TIKTOK_DEPENDENCIAS] curl_cffi={CURL_CFFI_VERSION}")
    else:
        logger.warning(
            "[TIKTOK_DEPENDENCIAS] curl_cffi ausente. No requirements.txt, "
            "use yt-dlp[default,curl-cffi] para habilitar a impersonacao."
        )
    inicializar_metricas_diarias()
    cleanup_download_dir_old_files(max_age_hours=6)
    configurar_menu_comandos()
    bot.set_update_listener(registrar_atividade_bot)

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

    while True:
        try:
            atualizar_estado_bot("polling")
            logger.info("Iniciando bot.infinity_polling...")
            bot.infinity_polling(skip_pending=False, timeout=20, long_polling_timeout=20)
        except Exception as e:
            atualizar_estado_bot("reconnecting")
            logger.error(f"[POLLING] erro={sanitizar_erro_log(e)}")
            time.sleep(5)
