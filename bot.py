import os
import re
import glob
import uuid
import time
import copy
import html
import hashlib
import secrets
import logging
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Thread
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
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

from flask import Flask, request, jsonify
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

# InfinitePay
INFINITEPAY_HANDLE = get_env_required("INFINITEPAY_HANDLE")
INFINITEPAY_WEBHOOK_SECRET = get_env_required("INFINITEPAY_WEBHOOK_SECRET")
INFINITEPAY_PAYMENT_CHECK_URL = "https://api.checkout.infinitepay.io/payment_check"

# Novas vendas são exclusivamente por Pix manual. A chave fica no Railway,
# nunca gravada diretamente no código-fonte.
PIX_KEY = os.environ.get("PIX_KEY", "").strip()
PIX_RECEIVER_NAME = os.environ.get("PIX_RECEIVER_NAME", "").strip()
PIX_RECEIVER_BANK = os.environ.get("PIX_RECEIVER_BANK", "InfinitePay").strip() or "InfinitePay"

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads_temp")
TZ = ZoneInfo("America/Sao_Paulo")

SERVICE_NAME = get_first_env(
    ["SERVICE_NAME", "RAILWAY_SERVICE_NAME"],
    default="bot-downloads-vip"
)
APP_VERSION = get_first_env(
    ["APP_VERSION", "RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT", "COMMIT_SHA"],
    default="unknown"
)
DEPLOYMENT_ID = get_first_env(
    ["RAILWAY_DEPLOYMENT_ID", "DEPLOYMENT_ID", "RAILWAY_REPLICA_ID"],
    default="unknown"
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
MEDIA_CACHE_DAYS = get_env_int("MEDIA_CACHE_DAYS", 30, 1, 365)
WEBHOOK_MAX_BODY_KB = get_env_int("WEBHOOK_MAX_BODY_KB", 64, 8, 1024)
WEBHOOK_RATE_LIMIT_PER_MINUTE = get_env_int(
    "WEBHOOK_RATE_LIMIT_PER_MINUTE", 60, 5, 600
)
DOWNLOAD_COOLDOWN_SECONDS = get_env_int(
    "DOWNLOAD_COOLDOWN_SECONDS", 5, 0, 60
)
MAX_DOWNLOADS_PER_USER_HOUR = get_env_int(
    "MAX_DOWNLOADS_PER_USER_HOUR", 30, 3, 1000
)
MAX_DOWNLOADS_GLOBAL_HOUR = get_env_int(
    "MAX_DOWNLOADS_GLOBAL_HOUR", 300, 20, 10000
)
PAYMENT_RETRY_SCAN_SECONDS = get_env_int(
    "PAYMENT_RETRY_SCAN_SECONDS", 60, 30, 600
)
PAYMENT_WORKERS = get_env_int("PAYMENT_WORKERS", 2, 1, 4)
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
WEBHOOK_RATE_LOCK = Lock()
WEBHOOK_RATE_EVENTS = defaultdict(deque)
AVISO_GERAL_LOCK = Lock()
BACKUP_ADMIN_LOCK = Lock()
DOWNLOAD_RATE_LOCK = Lock()
DOWNLOAD_RATE_EVENTS = defaultdict(deque)
DOWNLOAD_GLOBAL_EVENTS = deque()
PAYMENT_USER_LOCKS = [Lock() for _ in range(64)]
PAYMENT_ORDER_LOCKS = [Lock() for _ in range(64)]
PAYMENT_EXECUTOR = ThreadPoolExecutor(
    max_workers=PAYMENT_WORKERS,
    thread_name_prefix="payment_verification",
)

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
logger = logging.getLogger("afiliadotools")

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
    pedidos_col.create_index([
        ("payment_verification_status", 1),
        ("next_payment_retry_at", 1),
    ])
    midia_cache_col.create_index("expires_at", expireAfterSeconds=0)
except Exception as e:
    logger.warning(f"[MONGO_INDEX] Não foi possível garantir índices agora: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = WEBHOOK_MAX_BODY_KB * 1024

# Evita registrar URLs completas do webhook, que contêm o segredo na query.
logging.getLogger("werkzeug").setLevel(logging.WARNING)

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

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False, False, False, False

    host = parsed.hostname.lower().rstrip(".")
    is_pinterest = hostname_permitido(host, "pinterest.com") or host == "pin.it"
    is_tiktok = hostname_permitido(host, "tiktok.com")
    is_instagram = hostname_permitido(host, "instagram.com") or hostname_permitido(
        host, "instagr.am"
    )
    is_rednote = (
        hostname_permitido(host, "xiaohongshu.com")
        or hostname_permitido(host, "xhslink.com")
        or hostname_permitido(host, "rednote.com")
    )
    return is_pinterest, is_tiktok, is_instagram, is_rednote


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
        return parsed._replace(
            scheme=scheme,
            netloc=netloc,
            path=path,
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
            midia_cache_col.update_one(
                {"_id": chave},
                {
                    "$set": {
                        "source_id": source_id,
                        "cache_kind": tipo_cache,
                        "cache_identifier": identificador,
                        "plataforma": plataforma,
                        "telegram_file_id": telegram_file_id,
                        "media_profile": MEDIA_PROFILE_VERSION,
                        "updated_at": agora,
                        "expires_at": agora + timedelta(days=MEDIA_CACHE_DAYS),
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

    resposta = fazer_requisicao_tiktok(url, allow_redirects=True)
    resposta.raise_for_status()

    for candidato in (str(resposta.url), resposta.text):
        match = re.search(padrao, candidato or "", flags=re.IGNORECASE)
        if match:
            return match.group(1)

    raise RuntimeError("TIKTOK_EMBED_ID_NAO_ENCONTRADO")


def extrair_info_tiktok_embed(url):
    """Extrai o MP4 pelo endpoint público de incorporação do TikTok.

    Este caminho é independente do JSON da página principal que, em mudanças
    recentes do TikTok, pode não ser reconhecido pelo extrator do yt-dlp.
    """
    video_id = extrair_tiktok_video_id(url)
    embed_url = f"https://www.tiktok.com/embed/v2/{video_id}"
    resposta = fazer_requisicao_tiktok(embed_url)
    resposta.raise_for_status()

    match = re.search(
        r'<script[^>]+id=["\']__FRONTITY_CONNECT_STATE__["\'][^>]*>(.*?)</script>',
        resposta.text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        raise RuntimeError("TIKTOK_EMBED_DADOS_NAO_ENCONTRADOS")

    estado = json.loads(html.unescape(match.group(1)))
    dados_source = estado.get("source", {}).get("data", {})
    bloco = dados_source.get(f"/embed/v2/{video_id}", {})
    video_data = bloco.get("videoData", {})

    # Protege contra pequenas mudanças no nome da chave da rota.
    if not video_data:
        for valor in dados_source.values():
            if isinstance(valor, dict) and isinstance(valor.get("videoData"), dict):
                video_data = valor["videoData"]
                break

    item = video_data.get("itemInfos", {})
    video = item.get("video", {})
    video_meta = video.get("videoMeta", {})
    urls = [u for u in video.get("urls", []) if isinstance(u, str) and u.startswith("http")]
    if not urls:
        raise RuntimeError("TIKTOK_EMBED_URL_MP4_NAO_ENCONTRADA")

    logger.info(
        f"[TIKTOK_EMBED_OK] video_id={video_id} "
        f"duration={video_meta.get('duration')} "
        f"resolucao={video_meta.get('width')}x{video_meta.get('height')}"
    )
    return {
        "id": video_id,
        "title": item.get("text") or f"TikTok {video_id}",
        "duration": video_meta.get("duration"),
        "webpage_url": url,
        "extractor": "TikTokEmbedFallback",
        "extractor_key": "TikTokEmbedFallback",
        "formats": [
            {
                "format_id": "tiktok_embed_mp4",
                "url": urls[0],
                "ext": "mp4",
                "width": video_meta.get("width"),
                "height": video_meta.get("height"),
                "http_headers": {
                    "Referer": embed_url,
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
            }
        ],
    }


def normalizar_url_midia_tikwm(url):
    url = str(url or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://www.tikwm.com{url}"
    return url


def extrair_info_tiktok_hd_sem_marca(url):
    """Obtém a variante HD sem marca e evita deliberadamente o campo wmplay.

    No Railway, o curl_cffi pode receber uma resposta diferente da biblioteca
    requests por causa do fingerprint/TLS ou do IP do datacenter. Por isso a
    consulta tenta POST e GET comuns antes do cliente com impersonação.
    """
    if not TIKWM_API_URL:
        raise RuntimeError("TIKWM_API_DESATIVADA")

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
        if api_url and api_url not in api_urls:
            api_urls.append(api_url)

    metodos = ["requests_post", "requests_get"]
    if curl_requests is not None:
        metodos.append("curl_cffi_post")

    ultimo_erro = None
    for api_url in api_urls:
        for metodo in metodos:
            try:
                logger.info(
                    f"[TIKTOK_SEM_MARCA_TENTATIVA] metodo={metodo} api={api_url}"
                )
                if metodo == "requests_post":
                    resposta = requests.post(
                        api_url,
                        data=payload,
                        timeout=30,
                        headers=headers,
                    )
                elif metodo == "requests_get":
                    resposta = requests.get(
                        api_url,
                        params=payload,
                        timeout=30,
                        headers=headers,
                    )
                else:
                    resposta = curl_requests.post(
                        api_url,
                        data=payload,
                        impersonate="chrome",
                        timeout=30,
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

                usou_hd = bool(url_hd)
                video_id = str(dados.get("id") or extrair_tiktok_video_id(url))
                tamanho = dados.get("hd_size") if usou_hd else dados.get("size")
                logger.info(
                    f"[TIKTOK_HD_OK] video_id={video_id} sem_marca=True "
                    f"hd={usou_hd} metodo={metodo} duration={dados.get('duration')} "
                    f"tamanho={tamanho}"
                )
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
                    f"[TIKTOK_SEM_MARCA_FALHA] metodo={metodo} api={api_url} "
                    f"status={status} erro={e}"
                )

    raise RuntimeError(f"TIKWM_SEM_MARCA_FALHOU: {ultimo_erro}")


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
            logger.info(f"[INSTAGRAM_INFO] usar_cookies={usar_cookies} url={url}")
            opts = montar_info_opts(is_instagram=True, usar_cookies=usar_cookies)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return info, usar_cookies
        except Exception as e:
            ultimo_erro = e
            logger.warning(
                f"[INSTAGRAM_INFO_FALHA] usar_cookies={usar_cookies} url={url} erro={e}"
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
        logger.info(f"[TIKTOK_INFO] estrategia=hd_sem_marca url={url}")
        return extrair_info_tiktok_hd_sem_marca(url), False, None
    except Exception as e:
        logger.warning(f"[TIKTOK_HD_FALHA] url={url} erro={e}")

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
                    f"tentativa={tentativa}/{total_tentativas} url={url}"
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
                    f"tentativa={tentativa}/{total_tentativas} url={url} erro={e}"
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
        f"[TIKTOK_SEM_MARCA_INDISPONIVEL] url={url} ultimo_erro={ultimo_erro}"
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
            "Para continuar baixando de forma ilimitada agora mesmo, libere um plano VIP: 👇",
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


def webhook_dentro_do_limite(ip):
    """Limite simples por processo para reduzir abuso do endpoint público."""
    agora = time.time()
    janela_inicio = agora - 60
    chave = str(ip or "desconhecido")[:128]

    with WEBHOOK_RATE_LOCK:
        eventos = WEBHOOK_RATE_EVENTS[chave]
        while eventos and eventos[0] < janela_inicio:
            eventos.popleft()
        if len(eventos) >= WEBHOOK_RATE_LIMIT_PER_MINUTE:
            return False
        eventos.append(agora)

        # Evita crescimento permanente do dicionário em caso de muitos IPs.
        if len(WEBHOOK_RATE_EVENTS) > 2000:
            for ip_antigo in list(WEBHOOK_RATE_EVENTS.keys())[:500]:
                fila = WEBHOOK_RATE_EVENTS[ip_antigo]
                while fila and fila[0] < janela_inicio:
                    fila.popleft()
                if not fila:
                    WEBHOOK_RATE_EVENTS.pop(ip_antigo, None)
        return True


def confirmar_pagamento_infinitepay(payload, pedido):
    """Confirma o pagamento diretamente na InfinitePay antes de liberar VIP."""
    order_nsu = str(payload.get("order_nsu") or "").strip()
    transaction_nsu = str(payload.get("transaction_nsu") or "").strip()
    invoice_slug = str(
        payload.get("invoice_slug") or payload.get("slug") or ""
    ).strip()

    if not transaction_nsu or not invoice_slug:
        raise RuntimeError("PAGAMENTO_SEM_TRANSACTION_OU_SLUG")

    resp = requests.post(
        INFINITEPAY_PAYMENT_CHECK_URL,
        json={
            "handle": INFINITEPAY_HANDLE,
            "order_nsu": order_nsu,
            "transaction_nsu": transaction_nsu,
            "slug": invoice_slug,
        },
        timeout=(5, 15),
        headers={"Content-Type": "application/json"},
    )
    resp.raise_for_status()
    dados = resp.json()

    if not dados.get("success") or not dados.get("paid"):
        raise RuntimeError("PAGAMENTO_NAO_CONFIRMADO_NA_INFINITEPAY")

    try:
        valor_confirmado = int(dados.get("amount") or 0)
        valor_esperado = int(pedido.get("valor_centavos") or 0)
    except (TypeError, ValueError) as e:
        raise RuntimeError("PAGAMENTO_VALOR_INVALIDO") from e

    if valor_confirmado != valor_esperado:
        raise RuntimeError(
            f"PAGAMENTO_VALOR_DIVERGENTE esperado={valor_esperado} "
            f"confirmado={valor_confirmado}"
        )

    return {
        "transaction_nsu": transaction_nsu,
        "invoice_slug": invoice_slug,
        "amount": valor_confirmado,
        "paid_amount": dados.get("paid_amount"),
        "capture_method": dados.get("capture_method") or payload.get("capture_method"),
        "receipt_url": payload.get("receipt_url"),
    }


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


def notificar_pagamento_confirmado(user_id, plano_nome, vip_ate, receipt_url=None):
    try:
        texto = (
            "🎉 *PAGAMENTO CONFIRMADO!*\n\n"
            f"Plano: *{plano_nome}*\n"
            f"Status: *VIP LIBERADO*\n"
            f"Válido até: *{vip_ate}*\n\n"
            "Seu acesso VIP já está ativo. 🚀"
        )

        markup = None
        if receipt_url:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🧾 Ver comprovante", url=receipt_url))

        safe_send_message(int(user_id), texto, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logger.error(f"[NOTIFICAR_PAGAMENTO] user_id={user_id} erro={e}")


def _escape_md(texto):
    texto = str(texto)
    for ch in r"_[]()~`>#+-=|{}.!":
        texto = texto.replace(ch, "\\" + ch)
    return texto


def notificar_admin_privado(texto):
    try:
        safe_send_message(ADMIN_ID, texto, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"[NOTIFICAR_ADMIN] erro={e}")


def disparar_notificacao_admin(texto):
    Thread(target=notificar_admin_privado, args=(texto,), daemon=True).start()


def montar_texto_admin_webhook(status, order_nsu=None, user_id=None, plano_nome=None, valor_centavos=None, detalhe=None):
    linhas = [status]
    if order_nsu:
        linhas.append(f"Pedido: `{_escape_md(order_nsu)}`")
    if user_id is not None:
        linhas.append(f"Usuário: `{_escape_md(user_id)}`")
    if plano_nome:
        linhas.append(f"Plano: *{_escape_md(plano_nome)}*")
    if valor_centavos is not None:
        try:
            valor = int(valor_centavos) / 100
            valor_formatado = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            linhas.append(f"Valor: *R$ {valor_formatado}*")
        except Exception:
            linhas.append(f"Valor: `{_escape_md(valor_centavos)}`")
    if detalhe:
        linhas.append(f"Detalhe: {_escape_md(detalhe)}")
    return "\n".join(linhas)


def sanitizar_payload_webhook(payload):
    campos = (
        "order_nsu",
        "transaction_nsu",
        "invoice_slug",
        "slug",
        "amount",
        "paid_amount",
        "installments",
        "capture_method",
        "receipt_url",
    )
    return {campo: payload.get(campo) for campo in campos if campo in payload}


def erro_pagamento_permanente(erro):
    texto = str(erro or "").lower()
    sinais = (
        "pagamento_valor_divergente",
        "pagamento_valor_invalido",
        "pagamento_sem_transaction_ou_slug",
        "transaction_nsu_ja_usado_em_outro_pedido",
        "plano_invalido",
    )
    return any(sinal in texto for sinal in sinais)


def processar_pagamento_pendente(order_nsu):
    """Verifica e libera um pagamento fora da resposta HTTP do webhook."""
    lock_pedido = obter_lock_distribuido_local(order_nsu, PAYMENT_ORDER_LOCKS)
    with lock_pedido:
        pedido = pedidos_col.find_one({"order_nsu": order_nsu})
        if not pedido or pedido.get("status") == "paid":
            return

        payload = pedido.get("webhook_payload") or {}
        plano = PLANOS.get(pedido.get("plano_key")) or {}
        tentativas = int(pedido.get("payment_verification_attempts", 0) or 0) + 1
        agora = agora_tz()

        pedidos_col.update_one(
            {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
            {
                "$set": {
                    "payment_verification_status": "verifying",
                    "payment_verification_attempts": tentativas,
                    "payment_verification_last_attempt_at": agora,
                    # Se o processo for interrompido, o loop recupera após 5 min.
                    "next_payment_retry_at": agora + timedelta(minutes=5),
                }
            },
        )

        try:
            if not plano:
                raise RuntimeError("PLANO_INVALIDO")

            confirmacao = confirmar_pagamento_infinitepay(payload, pedido)
            valor_recebido = confirmacao["amount"]
            transaction_nsu = confirmacao["transaction_nsu"]
            receipt_url = confirmacao["receipt_url"]
            capture_method = confirmacao["capture_method"]

            outro_pedido = pedidos_col.find_one({
                "transaction_nsu": transaction_nsu,
                "order_nsu": {"$ne": order_nsu},
                "status": "paid",
            })
            if outro_pedido:
                raise RuntimeError("TRANSACTION_NSU_JA_USADO_EM_OUTRO_PEDIDO")

            logger.info(
                f"[WEBHOOK_PROCESSANDO] order_nsu={order_nsu} "
                f"user_id={pedido['user_id']} plano={plano['nome']} "
                f"valor={valor_recebido} tentativa={tentativas}"
            )

            vip_ate, vip_aplicado = liberar_vip_por_plano(
                pedido["user_id"],
                plano,
                order_nsu=order_nsu,
            )

            resultado_pedido = pedidos_col.update_one(
                {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
                {
                    "$set": {
                        "status": "paid",
                        "paid_at": agora_tz(),
                        "transaction_nsu": transaction_nsu,
                        "receipt_url": receipt_url,
                        "capture_method": capture_method,
                        "invoice_slug": confirmacao["invoice_slug"],
                        "paid_amount": confirmacao["paid_amount"],
                        "payment_check_verified_at": agora_tz(),
                        "payment_verification_status": "verified",
                        "vip_liberado_ate": vip_ate,
                        "vip_aplicado_nesta_chamada": vip_aplicado,
                    },
                    "$unset": {
                        "webhook_payload": "",
                        "next_payment_retry_at": "",
                        "payment_verification_error": "",
                    },
                },
            )

            if not resultado_pedido.modified_count:
                logger.info(f"[WEBHOOK_CORRIDA_DUPLICADA] order_nsu={order_nsu}")
                return

            logger.info(
                f"[WEBHOOK_APROVADO] order_nsu={order_nsu} "
                f"user_id={pedido['user_id']} plano={plano['nome']} "
                f"vip_ate={vip_ate}"
            )
            disparar_notificacao_admin(
                montar_texto_admin_webhook(
                    "✅ *Pagamento aprovado e VIP liberado*",
                    order_nsu=order_nsu,
                    user_id=pedido.get("user_id"),
                    plano_nome=plano.get("nome"),
                    valor_centavos=valor_recebido,
                    detalhe=f"VIP até: {vip_ate}",
                )
            )
            Thread(
                target=notificar_pagamento_confirmado,
                args=(pedido["user_id"], plano["nome"], vip_ate, receipt_url),
                daemon=True,
            ).start()
        except Exception as e:
            permanente = erro_pagamento_permanente(e)
            atraso = min(1800, 30 * (2 ** min(tentativas, 6)))
            status_verificacao = "rejected" if permanente else "retry_pending"
            atualizacao_erro = {
                "payment_verification_status": status_verificacao,
                "payment_verification_error": str(e)[:1000],
                "payment_verification_failed_at": agora_tz(),
            }
            if not permanente:
                atualizacao_erro["next_payment_retry_at"] = (
                    agora_tz() + timedelta(seconds=atraso)
                )

            update = {"$set": atualizacao_erro}
            if permanente:
                update["$unset"] = {"next_payment_retry_at": ""}
            pedidos_col.update_one(
                {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
                update,
            )
            logger.error(
                f"[PAYMENT_VERIFY] order_nsu={order_nsu} tentativa={tentativas} "
                f"permanente={permanente} erro={e}"
            )
            if permanente or tentativas in (1, 3, 10):
                disparar_notificacao_admin(
                    montar_texto_admin_webhook(
                        "❌ *Falha ao verificar pagamento*",
                        order_nsu=order_nsu,
                        user_id=pedido.get("user_id"),
                        plano_nome=plano.get("nome"),
                        detalhe=(
                            f"tentativa={tentativas} permanente={permanente} erro={e}"
                        ),
                    )
                )


def agendar_processamento_pagamento(order_nsu):
    try:
        PAYMENT_EXECUTOR.submit(processar_pagamento_pendente, order_nsu)
        return True
    except Exception as e:
        # O pedido já foi persistido como queued; o loop periódico o recupera.
        logger.error(f"[PAYMENT_QUEUE] order_nsu={order_nsu} erro={e}")
        return False


def reprocessar_pagamentos_pendentes_periodicamente(interval_seconds=60):
    intervalo = max(30, int(interval_seconds))
    logger.info(f"[PAYMENT_RETRY_LOOP] iniciado interval_seconds={intervalo}")

    while True:
        try:
            agora = agora_tz()
            cursor = pedidos_col.find(
                {
                    "status": {"$ne": "paid"},
                    "payment_verification_status": {
                        "$in": ["queued", "retry_pending", "verifying"]
                    },
                    "next_payment_retry_at": {"$lte": agora},
                },
                {"order_nsu": 1},
            ).limit(20)
            for pedido in cursor:
                order_nsu = pedido.get("order_nsu")
                if order_nsu:
                    agendar_processamento_pagamento(order_nsu)
        except Exception as e:
            logger.error(f"[PAYMENT_RETRY_LOOP] erro={e}")
        time.sleep(intervalo)


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


def is_vip(user_id):
    return is_vip_user(obter_usuario(user_id))


# =========================================
# PINTEREST
# =========================================
def resolver_link_pinterest(url):
    try:
        url = url.strip()

        if "pin.it/" in url.lower():
            r = requests.get(
                url,
                allow_redirects=True,
                timeout=(5, 12),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://www.pinterest.com/",
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
                }
            )
            if r.url:
                logger.info(f"[PINTEREST_REDIRECT] {url} -> {r.url}")
                return r.url

    except Timeout as e:
        logger.warning(f"[PINTEREST_TIMEOUT] url={url} erro={e}")
    except RequestException as e:
        logger.warning(f"[PINTEREST_REQUEST_ERROR] url={url} erro={e}")
    except Exception as e:
        logger.warning(f"[PINTEREST_UNKNOWN_ERROR] url={url} erro={e}")

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
                logger.info(f"[PINTEREST_OK] formato={fmt} url={url}")
                return arquivo

        except Exception as e:
            ultimo_erro = str(e)
            logger.warning(f"[PINTEREST_TENTATIVA] formato={fmt} url={url} erro={e}")

    raise Exception(ultimo_erro or "Falha ao baixar Pinterest")


# =========================================
# MENU / UI
# =========================================
def enviar_menu_principal(is_admin=False):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🚀 Liberar VIP", "📋 Como funciona")
    markup.row("📞 Suporte")

    if is_admin:
        markup.row("⚙️ Painel Admin")

    return markup


def mostrar_planos_chat(chat_id, user_id):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💠 VIP Mensal - R$ 10,00 via Pix", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💠 VIP Anual - R$ 79,90 via Pix", callback_data="pay_79.90")
    )

    texto = (
        "🚀 *LIBERAR ACESSO VIP*\n\n"
        "Escolha o plano ideal para ativar seus downloads ilimitados.\n\n"
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
                    "transaction_nsu": 1,
                    "receipt_url": 1,
                    "capture_method": 1,
                    "vip_liberado_ate": 1,
                    "vip_aplicado_nesta_chamada": 1,
                    "checkout_url": 1,
                    "invoice_slug": 1,
                    "paid_amount": 1,
                    "payment_check_verified_at": 1,
                    "payment_verification_status": 1,
                    "payment_verification_attempts": 1,
                    "payment_verification_last_attempt_at": 1,
                    "payment_verification_failed_at": 1,
                    "payment_verification_error": 1,
                    "webhook_received_at": 1,
                    "next_payment_retry_at": 1,
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
                    "transaction_nsu": 1,
                    "receipt_url": 1,
                    "capture_method": 1,
                    "vip_liberado_ate": 1,
                    "vip_aplicado_nesta_chamada": 1,
                    "checkout_url": 1,
                    "invoice_slug": 1,
                    "paid_amount": 1,
                    "payment_check_verified_at": 1,
                    "payment_verification_status": 1,
                    "payment_verification_attempts": 1,
                    "payment_verification_last_attempt_at": 1,
                    "payment_verification_failed_at": 1,
                    "payment_verification_error": 1,
                    "webhook_received_at": 1,
                    "next_payment_retry_at": 1,
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


# =========================================
# COMANDOS ADMIN
# =========================================
@bot.message_handler(commands=["darvip"])
def dar_vip_manual(message):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        args = message.text.split()
        if len(args) < 3:
            return safe_reply_to(message, "❌ Use: `/darvip ID DIAS`", parse_mode="Markdown")

        alvo_id = args[1]
        dias = int(args[2])

        nova_data = (
            "Vitalício" if dias >= 3650
            else (agora_tz() + timedelta(days=dias)).strftime("%Y-%m-%d")
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

        safe_reply_to(message, f"✅ VIP liberado para {alvo_id}!")
        safe_send_message(
            int(alvo_id),
            "🎉 *PAGAMENTO CONFIRMADO!*\nSeu acesso VIP foi liberado.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"[DARVIP] erro={e}")
        safe_reply_to(message, "❌ Use: `/darvip ID DIAS`", parse_mode="Markdown")


@bot.message_handler(commands=["zerar"])
def zerar_contador(message):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        args = message.text.split()
        if len(args) < 2:
            return safe_reply_to(message, "❌ Use: `/zerar ID`", parse_mode="Markdown")

        alvo_id = args[1]

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
    if message.from_user.id != ADMIN_ID:
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
    if message.from_user.id != ADMIN_ID:
        return

    Thread(
        target=processar_backup_admin,
        args=("usuarios", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "📦 Gerando backup de usuários e enviando no seu privado...")


@bot.message_handler(commands=["backupvips"])
def backup_vips(message):
    if message.from_user.id != ADMIN_ID:
        return

    Thread(
        target=processar_backup_admin,
        args=("vips", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "💎 Gerando backup de VIPs ativos e enviando no seu privado...")


@bot.message_handler(commands=["backuppedidos"])
def backup_pedidos(message):
    if message.from_user.id != ADMIN_ID:
        return

    Thread(
        target=processar_backup_admin,
        args=("pedidos", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "🧾 Gerando backup de pedidos e enviando no seu privado...")


@bot.message_handler(commands=["backupgeral"])
def backup_geral(message):
    if message.from_user.id != ADMIN_ID:
        return

    Thread(
        target=processar_backup_admin,
        args=("geral", message.chat.id),
        daemon=True
    ).start()

    safe_reply_to(message, "🗂 Gerando backup geral e enviando no seu privado...")


@bot.message_handler(func=lambda m: m.text == "⚙️ Painel Admin")
def painel_admin(message):
    if message.from_user.id != ADMIN_ID:
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

        pedidos_pendentes = pedidos_col.count_documents({"status": "pending"})
        pedidos_pagos = pedidos_col.count_documents({"status": "paid"})

        resumo_admin = (
            "⚙️ *Painel Admin*\n\n"
            f"👥 Usuários: `{total_users}`\n"
            f"💎 VIPs: `{vips_ativos}`\n"
            f"📥 Downloads hoje: `{downloads_totais_hoje}`\n"
            f"   ├ 👤 Gratuitos: `{downloads_gratuitos_hoje}`\n"
            f"   └ 💎 VIPs: `{downloads_vips_hoje}`\n"
            f"🕒 Pendentes: `{pedidos_pendentes}`\n"
            f"✅ Pagos: `{pedidos_pagos}`"
        )

        comandos_admin = (
            "*Comandos:*\n"
            "• `/darvip [ID] [Dias]`\n"
            "• `/zerar [ID]`\n"
            "• `/avisogeral [Mensagem]`\n"
            "• `/backupusuarios`\n"
            "• `/backupvips`\n"
            "• `/backuppedidos`\n"
            "• `/backupgeral`"
        )

        safe_send_message(message.chat.id, resumo_admin, parse_mode="Markdown")
        safe_send_message(message.chat.id, comandos_admin, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[PAINEL_ADMIN] erro={e}")
        safe_send_message(message.chat.id, "❌ Erro ao abrir painel admin.")



# =========================================
# START / PERFIL / PLANOS / SUPORTE
# =========================================
@bot.message_handler(commands=["start", "perfil"])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip_user(user)

    status = (
        "💎 *STATUS: VIP PRO*"
        if vip else f"👤 *STATUS: GRÁTIS* ({user.get('downloads_hoje', 0)}/{FREE_DAILY_LIMIT})"
    )

    texto = (
        "🚀 *Afiliado Tools*\n\n"
        "Baixe vídeos em HD do TikTok, Pinterest, Instagram e RedNote.\n\n"
        f"• Duração máx: {MAX_DURATION_SECONDS}s\n"
        f"• Sua ID: `{message.from_user.id}`\n\n"
        f"{status}"
    )

    safe_send_message(
        message.chat.id,
        texto,
        parse_mode="Markdown",
        reply_markup=enviar_menu_principal(is_admin=(message.from_user.id == ADMIN_ID))
    )


@bot.message_handler(commands=["planos"])
def cmd_planos(message):
    mostrar_planos_chat(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text in ["🚀 Liberar VIP", "💎 VIP"])
def mostrar_planos(message):
    mostrar_planos_chat(message.chat.id, message.from_user.id)


@bot.message_handler(func=lambda m: m.text == "📋 Como funciona")
def como_funciona(message):
    texto = (
        "📋 *COMO FUNCIONA*\n\n"
        "Envie o link de um vídeo do:\n"
        "• TikTok\n"
        "• Pinterest\n"
        "• Instagram\n"
        "• RedNote\n\n"
        "O bot faz o download automaticamente.\n\n"
        "✅ Sem marca d'água\n"
        "✅ Qualidade em HD\n"
        "✅ Rápido e prático\n\n"
        "*Plano grátis:*\n"
        f"• {FREE_DAILY_LIMIT} downloads por dia\n\n"
        "*VIP libera:*\n"
        "• Downloads ilimitados\n"
        "• Prioridade no processamento\n"
        "• Sem limite diário\n"
        "• Pagamento exclusivamente via Pix\n"
        "• Liberação após conferência do pagamento\n\n"
        "*Regras:*\n"
        f"• Vídeos de até {MAX_DURATION_SECONDS} segundos\n"
        "• Máximo 720x1280 em até 30 fps\n"
        "• Envie apenas o link do vídeo\n\n"
        "*Como usar:*\n"
        "1. Copie o link do vídeo\n"
        "2. Envie aqui no chat\n"
        "3. Aguarde o download\n\n"
        "Use o botão *🚀 Liberar VIP* para ativar o acesso ilimitado."
    )

    safe_send_message(message.chat.id, texto, parse_mode="Markdown")


@bot.message_handler(func=lambda m: m.text == "📞 Suporte")
def suporte(message):
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


@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def iniciar_pagamento_pix_manual(call):
    try:
        valor = call.data.split("_", 1)[1]
        plano = obter_plano_por_callback(valor)

        if not plano:
            safe_send_message(call.message.chat.id, "❌ Plano inválido.")
            return

        if not PIX_KEY:
            logger.error("[PIX_MANUAL] variável PIX_KEY não configurada")
            safe_send_message(
                call.message.chat.id,
                "❌ O pagamento via Pix está temporariamente indisponível. "
                "Fale com o suporte.",
            )
            safe_send_message(
                ADMIN_ID,
                "⚠️ Configure a variável `PIX_KEY` no Railway para receber pagamentos Pix.",
                parse_mode="Markdown",
            )
            return

        order_nsu = gerar_order_nsu(call.from_user.id)

        pedido = {
            "order_nsu": order_nsu,
            "user_id": str(call.from_user.id),
            "plano_key": valor,
            "plano_nome": plano["nome"],
            "valor_centavos": int(plano["preco_centavos"]),
            "status": "awaiting_pix",
            "created_at": agora_tz(),
            "checkout_url": None,
            "transaction_nsu": None,
            "receipt_url": None,
            "capture_method": "pix_manual",
            "payment_verification_status": "awaiting_manual_receipt",
        }

        pedidos_col.insert_one(pedido)

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "✅ Já fiz o Pix — enviar comprovante",
            callback_data=f"pix_paid_{order_nsu}",
        ))

        valor_reais = int(plano["preco_centavos"]) / 100
        valor_formatado = f"{valor_reais:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        nome_recebedor = html.escape(PIX_RECEIVER_NAME or "Titular da conta")
        banco_recebedor = html.escape(PIX_RECEIVER_BANK)
        chave_pix = html.escape(PIX_KEY)
        pedido_html = html.escape(order_nsu)

        texto = (
            f"💎 <b>{html.escape(plano['nome'])}</b>\n\n"
            "Pagamento exclusivamente via <b>Pix</b>.\n\n"
            f"💰 Valor exato: <b>R$ {valor_formatado}</b>\n"
            f"🔑 Chave Pix: <code>{chave_pix}</code>\n"
            f"👤 Recebedor: <b>{nome_recebedor}</b>\n"
            f"🏦 Instituição: <b>{banco_recebedor}</b>\n"
            f"🧾 Pedido: <code>{pedido_html}</code>\n\n"
            "Depois de pagar, toque no botão abaixo e envie o comprovante. "
            "O VIP será liberado após a entrada do Pix ser conferida."
        )

        safe_send_message(
            call.message.chat.id,
            texto,
            parse_mode="HTML",
            reply_markup=markup
        )

    except Exception as e:
        logger.error(f"[PIX_MANUAL_INICIO] erro={e}")
        safe_send_message(
            call.message.chat.id,
            "❌ Não consegui iniciar seu pagamento Pix agora.\n"
            "Tente novamente em instantes ou fale com o suporte."
        )
    finally:
        safe_answer_callback(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("pix_paid_"))
def solicitar_comprovante_pix(call):
    try:
        order_nsu = call.data[len("pix_paid_"):].strip()
        pedido = pedidos_col.find_one({"order_nsu": order_nsu})

        if not pedido or str(pedido.get("user_id")) != str(call.from_user.id):
            safe_answer_callback(call.id, text="Pedido inválido.", show_alert=True)
            return

        if pedido.get("status") == "paid":
            safe_answer_callback(call.id, text="Este pedido já foi aprovado.", show_alert=True)
            return

        if pedido.get("status") not in ("awaiting_pix", "receipt_submitted"):
            safe_answer_callback(call.id, text="Este pedido não está disponível.", show_alert=True)
            return

        obter_usuario(call.from_user.id)
        agora = agora_tz()
        usuarios_col.update_one(
            {"_id": str(call.from_user.id)},
            {"$set": {"pix_order_aguardando_comprovante": order_nsu}},
        )
        pedidos_col.update_one(
            {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
            {"$set": {
                "receipt_requested_at": agora,
                "payment_verification_status": "waiting_receipt_upload",
            }},
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
        user = obter_usuario(message.from_user.id)
        order_nsu = str(user.get("pix_order_aguardando_comprovante") or "").strip()
        if not order_nsu:
            return

        pedido = pedidos_col.find_one({"order_nsu": order_nsu})
        if (
            not pedido
            or str(pedido.get("user_id")) != str(message.from_user.id)
            or pedido.get("status") == "paid"
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

        agora = agora_tz()
        pedidos_col.update_one(
            {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
            {"$set": {
                "status": "receipt_submitted",
                "payment_verification_status": "manual_review_pending",
                "receipt_submitted_at": agora,
                "receipt_telegram_file_id": file_id,
                "receipt_telegram_type": tipo,
                "receipt_source_chat_id": message.chat.id,
                "receipt_source_message_id": message.message_id,
            }},
        )
        usuarios_col.update_one(
            {"_id": str(message.from_user.id)},
            {"$unset": {"pix_order_aguardando_comprovante": ""}},
        )

        try:
            bot.forward_message(ADMIN_ID, message.chat.id, message.message_id)
        except Exception as e:
            logger.warning(f"[PIX_FORWARD_RECEIPT] order_nsu={order_nsu} erro={e}")
            try:
                if tipo == "photo":
                    bot.send_photo(ADMIN_ID, file_id, caption=f"Comprovante do pedido {order_nsu}")
                else:
                    bot.send_document(ADMIN_ID, file_id, caption=f"Comprovante do pedido {order_nsu}")
            except Exception as envio_erro:
                logger.error(
                    f"[PIX_SEND_RECEIPT] order_nsu={order_nsu} erro={envio_erro}"
                )

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
            "confira se o Pix entrou na sua conta InfinitePay.",
            parse_mode="HTML",
            reply_markup=markup,
        )
        if controle:
            pedidos_col.update_one(
                {"order_nsu": order_nsu},
                {"$set": {"admin_review_message_id": controle.message_id}},
            )

        safe_send_message(
            message.chat.id,
            "✅ Comprovante recebido! O pagamento será conferido e você será avisado aqui.",
        )
    except Exception as e:
        logger.error(f"[PIX_RECEBER_COMPROVANTE] user_id={message.from_user.id} erro={e}")
        safe_send_message(message.chat.id, "❌ Não consegui registrar o comprovante. Tente novamente.")


@bot.callback_query_handler(func=lambda call: call.data.startswith(("pix_ok_", "pix_no_")))
def revisar_comprovante_pix(call):
    if call.from_user.id != ADMIN_ID:
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
                pedidos_col.update_one(
                    {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
                    {"$set": {
                        "status": "paid",
                        "paid_at": agora,
                        "paid_amount": int(pedido.get("valor_centavos") or 0),
                        "capture_method": "pix_manual",
                        "payment_verification_status": "manual_verified",
                        "payment_check_verified_at": agora,
                        "manual_verified_by": str(ADMIN_ID),
                        "manual_verified_at": agora,
                        "vip_liberado_ate": vip_ate,
                        "vip_aplicado_nesta_chamada": vip_aplicado,
                    }},
                )
                notificar_pagamento_confirmado(
                    pedido["user_id"], plano["nome"], vip_ate, receipt_url=None
                )
                safe_edit_message(
                    call.message.chat.id,
                    call.message.message_id,
                    "✅ Pagamento Pix conferido e VIP liberado.\n"
                    f"Pedido: `{order_nsu}`\nVIP até: *{vip_ate}*",
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
                    {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
                    {
                        "$set": {
                            "status": "awaiting_pix",
                            "payment_verification_status": "manual_receipt_rejected",
                            "receipt_rejected_at": agora,
                            "receipt_rejected_by": str(ADMIN_ID),
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
        logger.error(f"[PIX_MANUAL_REVISAO] order_nsu={order_nsu} erro={e}")
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


@bot.message_handler(func=lambda message: message.text and "http" in message.text.lower())
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip_status = is_vip_user(user)
    prefix = None

    if not vip_status and user.get("downloads_hoje", 0) >= FREE_DAILY_LIMIT:
        safe_reply_to(
            message,
            f"⚠️ *Limite diário atingido ({FREE_DAILY_LIMIT}/{FREE_DAILY_LIMIT})!*\n"
            "Para continuar baixando sem limites, libere o VIP abaixo: 👇",
            parse_mode="Markdown"
        )
        return mostrar_planos_chat(message.chat.id, message.from_user.id)

    url = extrair_primeira_url(message.text)
    if not url:
        return safe_reply_to(message, "❌ Não encontrei um link válido na sua mensagem.")

    status_msg = safe_reply_to(
        message,
        "✅ Seu link entrou na fila de download! Aguarde só alguns instantes 👊"
    )

    try:
        is_pinterest, is_tiktok, is_instagram, is_rednote = detectar_plataforma(url)
        plataforma = nome_plataforma(is_pinterest, is_tiktok, is_instagram, is_rednote)

        if is_instagram:
            url = normalizar_url_instagram(url)

        logger.info(f"[DOWNLOAD_INICIO] user_id={message.from_user.id} plataforma={plataforma} url={url}")

        if not (is_pinterest or is_tiktok or is_instagram or is_rednote):
            texto_nao_reconhecido = "❌ Link não reconhecido. Envie um link do TikTok, Pinterest, Instagram ou RedNote."
            if status_msg:
                safe_edit_message(message.chat.id, status_msg.message_id, texto_nao_reconhecido)
            else:
                safe_send_message(message.chat.id, texto_nao_reconhecido)
            return

        autorizado, mensagem_limite = autorizar_tentativa_download(message.from_user.id)
        if not autorizado:
            if status_msg:
                safe_edit_message(message.chat.id, status_msg.message_id, mensagem_limite)
            else:
                safe_send_message(message.chat.id, mensagem_limite)
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

                if not vip_status:
                    incrementar_download_gratis(user, message.chat.id, message.from_user.id)

                if status_msg:
                    safe_delete_message(message.chat.id, status_msg.message_id)

                return

            except Exception as e:
                logger.error(f"[ERRO_PINTEREST] user_id={message.from_user.id} url={url} erro={e}")
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
                        f"usar_cookies={usar_cookies} formato={fmt} url={url} erro={e}"
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

        if not vip_status:
            incrementar_download_gratis(user, message.chat.id, message.from_user.id)

        if status_msg:
            safe_delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.error(f"[ERRO_DOWNLOAD] user_id={message.from_user.id} url={url} erro={e}")
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


# =========================================
# ROTAS INFINITEPAY
# =========================================
@app.route("/pagamento/sucesso")
def pagamento_sucesso():
    order_nsu = html.escape(request.args.get("order_nsu", ""), quote=True)
    capture_method = html.escape(request.args.get("capture_method", ""), quote=True)
    return f"""
    <html>
        <head><title>Pagamento recebido</title></head>
        <body style="font-family: Arial, sans-serif; text-align: center; padding: 40px;">
            <h2>✅ Pagamento recebido</h2>
            <p>Seu pagamento foi processado.</p>
            <p><strong>Pedido:</strong> {order_nsu}</p>
            <p><strong>Forma:</strong> {capture_method}</p>
            <p>Você já pode voltar para o Telegram.</p>
        </body>
    </html>
    """, 200


@app.route("/webhook/infinitepay", methods=["POST"])
def webhook_infinitepay():
    try:
        secret_recebido = (request.args.get("secret") or "").strip()
        if not secrets.compare_digest(secret_recebido, INFINITEPAY_WEBHOOK_SECRET):
            logger.warning("[WEBHOOK_INFINITEPAY] acesso negado: secret inválido")
            return jsonify({
                "success": False,
                "message": "Não autorizado"
            }), 403

        if not webhook_dentro_do_limite(request.remote_addr):
            logger.warning("[WEBHOOK_INFINITEPAY] limite por minuto excedido")
            return jsonify({"success": False, "message": "Muitas requisições"}), 429

        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            return jsonify({"success": False, "message": "JSON inválido"}), 400

        order_nsu = str(payload.get("order_nsu") or "").strip()
        transaction_nsu = str(payload.get("transaction_nsu") or "").strip()
        amount = payload.get("amount")
        capture_method = payload.get("capture_method")

        logger.info(
            f"[WEBHOOK_INFINITEPAY] recebido order_nsu={order_nsu} transaction_nsu={transaction_nsu} "
            f"amount={amount} capture_method={capture_method}"
        )
        if not order_nsu:
            logger.warning("[WEBHOOK_INFINITEPAY] order_nsu ausente")
            return jsonify({
                "success": False,
                "message": "order_nsu ausente"
            }), 400

        pedido = pedidos_col.find_one({"order_nsu": order_nsu})
        if not pedido:
            logger.warning(f"[WEBHOOK_PEDIDO_NAO_ENCONTRADO] order_nsu={order_nsu}")
            return jsonify({
                "success": False,
                "message": "Pedido não encontrado"
            }), 400

        plano = PLANOS.get(pedido.get("plano_key")) or {}
        plano_nome = plano.get("nome")

        if pedido.get("status") == "paid":
            logger.info(f"[WEBHOOK_PEDIDO_JA_PAGO] order_nsu={order_nsu}")
            return jsonify({
                "success": True,
                "message": None
            }), 200

        if not plano:
            logger.warning(f"[WEBHOOK_PLANO_INVALIDO] order_nsu={order_nsu} plano_key={pedido.get('plano_key')}")
            disparar_notificacao_admin(
                montar_texto_admin_webhook(
                    "❌ *Plano inválido no webhook*",
                    order_nsu=order_nsu,
                    user_id=pedido.get("user_id"),
                    detalhe=f"plano_key={pedido.get('plano_key')}"
                )
            )
            return jsonify({
                "success": False,
                "message": "Plano inválido"
            }), 400

        invoice_slug = str(
            payload.get("invoice_slug") or payload.get("slug") or ""
        ).strip()
        if not transaction_nsu or not invoice_slug:
            logger.warning(
                f"[WEBHOOK_DADOS_AUSENTES] order_nsu={order_nsu} "
                f"transaction={bool(transaction_nsu)} slug={bool(invoice_slug)}"
            )
            return jsonify({
                "success": False,
                "message": "Dados da transação ausentes",
            }), 400

        # Persiste antes de responder. Se o processo reiniciar logo depois do
        # HTTP 200, o loop periódico recupera esta verificação da base.
        agora = agora_tz()
        pedidos_col.update_one(
            {"order_nsu": order_nsu, "status": {"$ne": "paid"}},
            {
                "$set": {
                    "webhook_payload": sanitizar_payload_webhook(payload),
                    "webhook_received_at": agora,
                    "payment_verification_status": "queued",
                    "next_payment_retry_at": agora,
                },
                "$unset": {"payment_verification_error": ""},
            },
        )

        agendar_processamento_pagamento(order_nsu)

        return jsonify({
            "success": True,
            "message": "Recebido para verificação"
        }), 200

    except Exception as e:
        logger.error(f"[WEBHOOK_INFINITEPAY] erro={e}")
        disparar_notificacao_admin(
            montar_texto_admin_webhook(
                "❌ *Erro interno no webhook*",
                detalhe=str(e)
            )
        )
        return jsonify({
            "success": False,
            "message": "Erro interno no webhook"
        }), 400



# =========================================
# HEALTHCHECK
# =========================================
@app.route("/")
def root_status():
    return "ONLINE", 200

@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": SERVICE_NAME,
        "version": APP_VERSION,
        "deployment_id": DEPLOYMENT_ID,
        "environment": ENVIRONMENT_NAME,
        "started_at": APP_STARTED_AT,
        "bot": "running",
        "flask": "running",
        "yt_dlp_version": YT_DLP_VERSION,
        "tiktok_impersonation": TIKTOK_IMPERSONATION_DISPONIVEL,
        "curl_cffi_version": CURL_CFFI_VERSION,
        "media_profile": MEDIA_PROFILE_VERSION,
        "max_duration_seconds": MAX_DURATION_SECONDS,
        "max_source_file_mb": MAX_SOURCE_FILE_MB,
        "max_output_file_mb": MAX_OUTPUT_FILE_MB,
        "payment_mode": "manual_pix",
        "pix_configured": bool(PIX_KEY),
        "download_cooldown_seconds": DOWNLOAD_COOLDOWN_SECONDS,
        "max_downloads_per_user_hour": MAX_DOWNLOADS_PER_USER_HOUR,
        "max_downloads_global_hour": MAX_DOWNLOADS_GLOBAL_HOUR,
        "payment_workers": PAYMENT_WORKERS,
        "payment_retry_scan_seconds": PAYMENT_RETRY_SCAN_SECONDS,
    }), 200


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
    if PIX_KEY:
        logger.info("[PAGAMENTO_CONFIG] modo=manual_pix configurado=True")
    else:
        logger.error(
            "[PAGAMENTO_CONFIG] modo=manual_pix configurado=False; "
            "defina PIX_KEY no Railway"
        )
    if TIKTOK_IMPERSONATION_DISPONIVEL:
        logger.info(f"[TIKTOK_DEPENDENCIAS] curl_cffi={CURL_CFFI_VERSION}")
    else:
        logger.warning(
            "[TIKTOK_DEPENDENCIAS] curl_cffi ausente. No requirements.txt, "
            "use yt-dlp[default,curl-cffi] para habilitar a impersonacao."
        )
    inicializar_metricas_diarias()
    cleanup_download_dir_old_files(max_age_hours=6)

    Thread(
        target=cleanup_download_dir_periodicamente,
        kwargs={"interval_minutes": 60, "max_age_hours": 6},
        daemon=True
    ).start()

    # Mantém a recuperação apenas para pagamentos de links InfinitePay que
    # possam ter sido criados antes da mudança para Pix manual.
    Thread(
        target=reprocessar_pagamentos_pendentes_periodicamente,
        kwargs={"interval_seconds": PAYMENT_RETRY_SCAN_SECONDS},
        daemon=True,
    ).start()

    Thread(
        target=lambda: app.run(
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 8080))
        ),
        daemon=True
    ).start()

    while True:
        try:
            logger.info("Iniciando bot.infinity_polling...")
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            logger.error(f"[POLLING] erro={e}")
            time.sleep(5)
