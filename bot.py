import os
import re
import glob
import uuid
import time
import logging
from threading import Thread, Lock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import telebot
import yt_dlp
import subprocess
import json

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


TOKEN_TELEGRAM = get_env_required("TOKEN_TELEGRAM")
MONGO_URI = get_env_required("MONGO_URI")
MONGO_DB_NAME = get_env_required("MONGO_DB_NAME")
LINK_SUPORTE = get_env_required("LINK_SUPORTE")
ADMIN_ID = int(get_env_required("ADMIN_ID"))

# InfinitePay
INFINITEPAY_HANDLE = get_env_required("INFINITEPAY_HANDLE")
INFINITEPAY_WEBHOOK_SECRET = get_env_required("INFINITEPAY_WEBHOOK_SECRET")
APP_BASE_URL = get_env_required("APP_BASE_URL").rstrip("/")
INFINITEPAY_CHECKOUT_URL = "https://api.infinitepay.io/invoices/public/checkout/links"

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
PENDING_ORDER_EXPIRATION_HOURS = max(1, int(os.environ.get("PENDING_ORDER_EXPIRATION_HOURS", "24")))

INSTAGRAM_COOKIES_TEXT = os.environ.get("INSTAGRAM_COOKIES_TEXT", "").strip()
INSTAGRAM_COOKIEFILE_PATH = None

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# =========================================
# LOGS
# =========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("afiliadotools")


class YtDlpQuietLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        pass


DOWNLOADS_EM_ANDAMENTO = {}
DOWNLOADS_EM_ANDAMENTO_LOCK = Lock()

# =========================================
# DB / BOT / APP
# =========================================
client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = client[MONGO_DB_NAME]
usuarios_col = db["usuarios"]
pedidos_col = db["pedidos"]

try:
    usuarios_col.create_index("vip_ate")
    usuarios_col.create_index("ultima_data")
    pedidos_col.create_index("order_nsu", unique=True)
    pedidos_col.create_index("status")
    pedidos_col.create_index("user_id")
except Exception as e:
    logger.warning(f"[MONGO_INDEX] Não foi possível garantir índices agora: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

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

INSTAGRAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.instagram.com/",
    "Origin": "https://www.instagram.com",
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin"
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
    },
    "297.00": {
        "nome": "VIP Vitalício",
        "preco_centavos": 29700,
        "dias": None,
        "descricao": "VIP Vitalício",
        "vitalicio": True
    }
}

# =========================================
# FUNÇÕES AUXILIARES
# =========================================
def agora_tz():
    return datetime.now(TZ)


def hoje_str():
    return agora_tz().strftime("%Y-%m-%d")


def redirect_url():
    return f"{APP_BASE_URL}/pagamento/sucesso"


def webhook_url():
    return f"{APP_BASE_URL}/webhook/infinitepay?secret={INFINITEPAY_WEBHOOK_SECRET}"


def extrair_primeira_url(texto):
    if not texto:
        return None
    match = re.search(r"(https?://[^\s]+)", texto.strip())
    if not match:
        return None
    return match.group(1).strip().rstrip(".,);]}>\"'")


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


def ffmpeg_disponivel():
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return r.returncode == 0
    except Exception:
        return False


def ffprobe_disponivel():
    try:
        r = subprocess.run(
            ["ffprobe", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return r.returncode == 0
    except Exception:
        return False


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
    if not ffprobe_disponivel():
        return None

    cmd = [
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        arquivo_entrada
    ]

    resultado = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

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
    }


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


def codecs_compativeis_para_remux_mp4(info):
    if not info:
        return False

    vcodec = (info.get("vcodec") or "").lower()
    acodec = (info.get("acodec") or "none").lower()

    return vcodec in ("h264", "avc1", "hevc", "h265", "hev1") and acodec in ("aac", "none")


def remuxar_para_mp4_faststart(arquivo_entrada):
    base, _ = os.path.splitext(arquivo_entrada)
    arquivo_saida = f"{base}_remux.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", arquivo_entrada,
        "-c", "copy",
        "-movflags", "+faststart",
        arquivo_saida
    ]

    resultado = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

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
        "-i", arquivo_entrada,
    ]

    vf = montar_vf_limite_720x1280_30fps(info)
    if vf:
        cmd += ["-vf", vf]

    cmd += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "25",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",
        "-movflags", "+faststart",
        arquivo_saida
    ]

    resultado = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if resultado.returncode != 0:
        raise Exception(f"Falha no ffmpeg fallback H.264: {resultado.stderr[-1500:]}")

    if not os.path.exists(arquivo_saida):
        raise Exception("Arquivo fallback H.264 não foi gerado.")

    return arquivo_saida


def converter_para_720x1280_30fps(arquivo_entrada):
    """
    Garante saída final em no máximo 720x1280, 30fps, H.264/AAC.
    Mantém a proporção original sem adicionar bordas.
    """
    base, _ = os.path.splitext(arquivo_entrada)
    arquivo_saida = f"{base}_720x1280_30fps.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", arquivo_entrada,
        "-vf", "scale=720:1280:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=30",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "25",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "96k",
        "-movflags", "+faststart",
        arquivo_saida
    ]

    resultado = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

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


def contar_downloads_em_andamento():
    with DOWNLOADS_EM_ANDAMENTO_LOCK:
        return sum(1 for estado in DOWNLOADS_EM_ANDAMENTO.values() if estado.get("active"))


def iniciar_controle_download_usuario(user_id, message_date=None):
    uid = str(user_id)
    agora_ts = int(time.time())

    try:
        message_ts = int(message_date) if message_date is not None else agora_ts
    except Exception:
        message_ts = agora_ts

    with DOWNLOADS_EM_ANDAMENTO_LOCK:
        estado = DOWNLOADS_EM_ANDAMENTO.get(uid, {})
        last_started_at = int(estado.get("last_started_at") or 0)
        last_finished_at = int(estado.get("last_finished_at") or 0)

        if estado.get("active"):
            logger.info(
                f"[ANTI_FLOOD_BLOCK] user_id={uid} reason=active_now "
                f"msg_ts={message_ts} last_started_at={last_started_at}"
            )
            return False

        if last_started_at and last_finished_at and last_started_at <= message_ts < last_finished_at:
            logger.info(
                f"[ANTI_FLOOD_BLOCK] user_id={uid} reason=queued_during_previous "
                f"msg_ts={message_ts} last_started_at={last_started_at} last_finished_at={last_finished_at}"
            )
            return False

        DOWNLOADS_EM_ANDAMENTO[uid] = {
            "active": True,
            "last_started_at": agora_ts,
            "active_message_ts": message_ts,
            "last_finished_at": last_finished_at,
        }

        active_total = sum(1 for item in DOWNLOADS_EM_ANDAMENTO.values() if item.get("active"))

        logger.info(
            f"[ANTI_FLOOD_START] user_id={uid} msg_ts={message_ts} active_total={active_total}"
        )
        return True


def finalizar_controle_download_usuario(user_id):
    uid = str(user_id)
    agora_ts = int(time.time())

    with DOWNLOADS_EM_ANDAMENTO_LOCK:
        estado = DOWNLOADS_EM_ANDAMENTO.get(uid)
        if not estado:
            return

        estado["active"] = False
        estado["last_finished_at"] = agora_ts
        estado["active_message_ts"] = None
        DOWNLOADS_EM_ANDAMENTO[uid] = estado

        active_total = sum(1 for item in DOWNLOADS_EM_ANDAMENTO.values() if item.get("active"))

        logger.info(
            f"[ANTI_FLOOD_END] user_id={uid} finished_at={agora_ts} active_total={active_total}"
        )


def safe_answer_callback(call_id):
    try:
        bot.answer_callback_query(call_id)
    except Exception as e:
        logger.warning(f"[CALLBACK_ANSWER] erro={e}")


def enviar_arquivo_com_fallback(chat_id, arquivo, plataforma=None):
    info = obter_info_midia(arquivo)
    arquivo_fallback = None

    try:
        with open(arquivo, "rb") as f:
            bot.send_video(chat_id, f, caption="👉 Download concluído! Aqui está seu vídeo 👊")

        logger.info(
            f"[SEND_VIDEO_OK] plataforma={plataforma} modo=video_direto arquivo={arquivo} "
            f"width={(info or {}).get('width')} height={(info or {}).get('height')} "
            f"fps={(info or {}).get('fps')} vcodec={(info or {}).get('vcodec')} "
            f"acodec={(info or {}).get('acodec')}"
        )
        return True
    except Exception as e_video:
        logger.warning(
            f"[SEND_VIDEO_FAIL] plataforma={plataforma} modo=video_direto arquivo={arquivo} "
            f"width={(info or {}).get('width')} height={(info or {}).get('height')} "
            f"fps={(info or {}).get('fps')} vcodec={(info or {}).get('vcodec')} erro={e_video}"
        )

    if arquivo_tem_codec_hevc(arquivo, info):
        try:
            logger.info(
                f"[SEND_VIDEO] Tentando fallback automático HEVC -> H.264 | plataforma={plataforma} arquivo={arquivo} "
                f"width={(info or {}).get('width')} height={(info or {}).get('height')} "
                f"fps={(info or {}).get('fps')} vcodec={(info or {}).get('vcodec')}"
            )
            arquivo_fallback = converter_para_h264_compativel(arquivo, info)
            info_fallback = obter_info_midia(arquivo_fallback)

            with open(arquivo_fallback, "rb") as f:
                bot.send_video(chat_id, f, caption="👉 Download concluído! Aqui está seu vídeo 👊")

            logger.info(
                f"[SEND_VIDEO_OK] plataforma={plataforma} modo=fallback_h264 arquivo_original={arquivo} "
                f"arquivo_enviado={arquivo_fallback} width={(info_fallback or {}).get('width')} "
                f"height={(info_fallback or {}).get('height')} fps={(info_fallback or {}).get('fps')} "
                f"vcodec={(info_fallback or {}).get('vcodec')} acodec={(info_fallback or {}).get('acodec')}"
            )
            return True
        except Exception as e_h264:
            logger.warning(f"[SEND_VIDEO] Fallback H.264 também falhou. plataforma={plataforma} erro={e_h264}")

    alvo_documento = arquivo_fallback if arquivo_fallback and os.path.exists(arquivo_fallback) else arquivo
    origem_documento = "fallback_h264" if alvo_documento == arquivo_fallback and arquivo_fallback else "arquivo_original"
    info_documento = obter_info_midia(alvo_documento)

    try:
        with open(alvo_documento, "rb") as f:
            bot.send_document(chat_id, f, caption="👉 Download concluído! Aqui está seu arquivo 👊")

        logger.info(
            f"[SEND_DOCUMENT_OK] plataforma={plataforma} origem={origem_documento} arquivo={alvo_documento} "
            f"width={(info_documento or {}).get('width')} height={(info_documento or {}).get('height')} "
            f"fps={(info_documento or {}).get('fps')} vcodec={(info_documento or {}).get('vcodec')} "
            f"acodec={(info_documento or {}).get('acodec')}"
        )
        return True
    except Exception as e_doc:
        logger.error(
            f"[SEND_DOCUMENT_FAIL] plataforma={plataforma} origem={origem_documento} arquivo={alvo_documento} erro={e_doc}"
        )
        return False


def detectar_plataforma(url_lower):
    is_pinterest = ("pin.it" in url_lower) or ("pinterest" in url_lower)
    is_tiktok = ("tiktok.com" in url_lower) or ("vm.tiktok.com" in url_lower) or ("vt.tiktok.com" in url_lower)
    is_instagram = ("instagram.com" in url_lower) or ("instagr.am" in url_lower)
    is_rednote = ("xiaohongshu.com" in url_lower) or ("xhslink.com" in url_lower) or ("rednote" in url_lower)
    return is_pinterest, is_tiktok, is_instagram, is_rednote


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


def get_instagram_cookiefile():
    global INSTAGRAM_COOKIEFILE_PATH

    if not INSTAGRAM_COOKIES_TEXT:
        return None

    cookie_path = os.path.join(DOWNLOAD_DIR, "instagram_cookies.txt")

    if INSTAGRAM_COOKIEFILE_PATH and os.path.exists(INSTAGRAM_COOKIEFILE_PATH):
        return INSTAGRAM_COOKIEFILE_PATH

    precisa_escrever = True

    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                conteudo_atual = f.read()
            if conteudo_atual == INSTAGRAM_COOKIES_TEXT:
                precisa_escrever = False
        except Exception as e:
            logger.warning(f"[INSTAGRAM_COOKIEFILE_READ] erro={e}")

    if precisa_escrever:
        with open(cookie_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(INSTAGRAM_COOKIES_TEXT)
        logger.info("[INSTAGRAM_COOKIEFILE] arquivo de cookies atualizado")

    INSTAGRAM_COOKIEFILE_PATH = cookie_path
    return cookie_path


def aplicar_silencio_ytdlp(opts):
    opts["quiet"] = True
    opts["no_warnings"] = True
    opts["noprogress"] = True
    opts["logger"] = YtDlpQuietLogger()
    return opts


def montar_info_opts(is_instagram=False, is_pinterest=False):
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "verbose": False,
        "nocheckcertificate": True,
        "noplaylist": True,
        "socket_timeout": 20,
        "retries": 2
    }

    if is_instagram:
        opts["http_headers"] = INSTAGRAM_HEADERS
        cookiefile = get_instagram_cookiefile()
        if cookiefile:
            opts["cookiefile"] = cookiefile
    elif is_pinterest:
        opts["http_headers"] = PINTEREST_HEADERS

    return aplicar_silencio_ytdlp(opts)


def montar_download_opts(prefix, is_instagram=False, is_pinterest=False):
    opts = {
        "outtmpl": f"{prefix}.%(ext)s",
        "nocheckcertificate": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "verbose": False,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "retries": 2,
        "fragment_retries": 2,
        "socket_timeout": 20,
        "http_headers": DEFAULT_HEADERS
    }

    if is_instagram:
        opts["http_headers"] = INSTAGRAM_HEADERS
        cookiefile = get_instagram_cookiefile()
        if cookiefile:
            opts["cookiefile"] = cookiefile
    elif is_pinterest:
        opts["http_headers"] = PINTEREST_HEADERS

    return aplicar_silencio_ytdlp(opts)


def mapear_erro_download(err_text, plataforma="geral"):
    err = (err_text or "").lower()

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


def gerar_order_nsu(user_id):
    return f"{user_id}_{int(time.time())}_{uuid.uuid4().hex[:10]}"


def obter_plano_por_callback(valor_str):
    return PLANOS.get(valor_str)


def criar_checkout_infinitepay(order_nsu, plano):
    payload = {
        "handle": INFINITEPAY_HANDLE,
        "redirect_url": redirect_url(),
        "webhook_url": webhook_url(),
        "order_nsu": order_nsu,
        "items": [
            {
                "quantity": 1,
                "price": int(plano["preco_centavos"]),
                "description": plano["descricao"]
            }
        ]
    }

    payload_log = dict(payload)
    payload_log["webhook_url"] = f"{APP_BASE_URL}/webhook/infinitepay?secret=***"
    logger.info(f"[CHECKOUT_CREATE] order_nsu={order_nsu} payload={payload_log}")

    resp = requests.post(
        INFINITEPAY_CHECKOUT_URL,
        json=payload,
        timeout=(5, 20),
        headers={"Content-Type": "application/json"}
    )

    if not resp.ok:
        logger.error(f"[CHECKOUT_CREATE_ERROR] status={resp.status_code} body={resp.text}")
        resp.raise_for_status()

    data = resp.json()
    checkout_url = data.get("url")
    if not checkout_url:
        raise Exception("A InfinitePay não retornou a URL do checkout.")

    return checkout_url


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


def liberar_vip_por_plano(user_id, plano):
    user = obter_usuario(user_id)

    if plano.get("vitalicio"):
        novo_vip_ate = "Vitalício"
    else:
        novo_vip_ate = calcular_nova_data_vip(user, plano["dias"])

    usuarios_col.update_one(
        {"_id": str(user_id)},
        {
            "$set": {
                "vip_ate": novo_vip_ate,
                "ultima_data": hoje_str()
            },
            "$setOnInsert": {
                "downloads_hoje": 0
            }
        },
        upsert=True
    )

    return novo_vip_ate


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


def formatar_valor_centavos(valor_centavos):
    try:
        valor = int(valor_centavos or 0) / 100
        return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return str(valor_centavos)


def formatar_data_admin(valor):
    if not valor:
        return "-"

    if isinstance(valor, str):
        return valor

    try:
        if isinstance(valor, datetime):
            if valor.tzinfo is None:
                valor = valor.replace(tzinfo=TZ)
            else:
                valor = valor.astimezone(TZ)
            return valor.strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        pass

    return str(valor)


def formatar_status_pedido(status):
    mapa = {
        "pending": "pendente",
        "paid": "pago",
        "expired": "expirado",
        "checkout_error": "erro no checkout",
        "creating": "criando checkout",
    }
    return mapa.get(str(status or "").strip().lower(), str(status or "-"))


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


def expirar_pedidos_antigos(expiration_hours=PENDING_ORDER_EXPIRATION_HOURS):
    try:
        limite = agora_tz() - timedelta(hours=max(1, int(expiration_hours)))
        filtro = {
            "status": {"$in": ["pending", "creating"]},
            "created_at": {"$lt": limite}
        }
        atualizacao = {
            "$set": {
                "status": "expired",
                "expired_at": agora_tz(),
                "expired_reason": f"timeout_{int(expiration_hours)}h"
            }
        }

        resultado = pedidos_col.update_many(filtro, atualizacao)

        if resultado.modified_count:
            logger.info(
                f"[PEDIDOS_EXPIRED] expirados={resultado.modified_count} limite_horas={int(expiration_hours)}"
            )

        return resultado.modified_count
    except Exception as e:
        logger.warning(f"[PEDIDOS_EXPIRED] erro={e}")
        return 0


def loop_expirar_pedidos_antigos(interval_minutes=60, expiration_hours=PENDING_ORDER_EXPIRATION_HOURS):
    intervalo_segundos = max(300, int(interval_minutes * 60))
    logger.info(
        f"[PEDIDOS_EXPIRED_LOOP] iniciado interval_minutes={interval_minutes} expiration_hours={int(expiration_hours)}"
    )

    while True:
        try:
            expirar_pedidos_antigos(expiration_hours=expiration_hours)
        except Exception as e:
            logger.warning(f"[PEDIDOS_EXPIRED_LOOP] erro={e}")
        time.sleep(intervalo_segundos)


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


def baixar_pinterest_capado(url, prefix):
    url = resolver_link_pinterest(url)

    formatos = formatos_por_plataforma(is_pinterest=True)

    common_opts = montar_download_opts(prefix, is_pinterest=True)
    ultimo_erro = None

    for fmt in formatos:
        try:
            cleanup_prefix(prefix)

            opts = common_opts.copy()
            opts["format"] = fmt

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
        types.InlineKeyboardButton("💳 VIP Mensal - R$ 10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💳 VIP Anual - R$ 79,90", callback_data="pay_79.90"),
        types.InlineKeyboardButton("💎 VIP Vitalício - R$ 297,00", callback_data="pay_297.00")
    )

    texto = (
        "🚀 *LIBERAR ACESSO VIP*\n\n"
        "Escolha o plano ideal para ativar seus downloads ilimitados.\n\n"
        "✅ Sem limite diário\n"
        "✅ Prioridade no processamento\n"
        "✅ Uso liberado para TikTok, Pinterest, Instagram e RedNote\n"
        "✅ Liberação automática após o pagamento\n\n"
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
                {"_id": 1, "vip_ate": 1, "downloads_hoje": 1, "ultima_data": 1}
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
                {"_id": 1, "vip_ate": 1, "downloads_hoje": 1, "ultima_data": 1}
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
                    "checkout_url": 1,
                }
            ).sort("created_at", -1)
        )
        return docs, "backup_pedidos", "🧾 Backup de pedidos gerado"

    if tipo == "geral":
        usuarios_docs = list(
            usuarios_col.find(
                {},
                {"_id": 1, "vip_ate": 1, "downloads_hoje": 1, "ultima_data": 1}
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
                {"_id": 1, "vip_ate": 1, "downloads_hoje": 1, "ultima_data": 1}
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
                    "checkout_url": 1,
                }
            ).sort("created_at", -1)
        )
        payload = {
            "generated_at": agora_tz().isoformat(),
            "service": SERVICE_NAME,
            "environment": ENVIRONMENT_NAME,
            "backup_type": "geral",
            "usuarios_count": len(usuarios_docs),
            "vips_ativos_count": len(vips_docs),
            "pedidos_count": len(pedidos_docs),
            "usuarios": [serializar_para_json(doc) for doc in usuarios_docs],
            "vips_ativos": [serializar_para_json(doc) for doc in vips_docs],
            "pedidos": [serializar_para_json(doc) for doc in pedidos_docs],
        }
        return payload, "backup_geral", "🗂 Backup geral gerado"

    raise ValueError("Tipo de backup inválido")


def processar_backup_admin(tipo, origem_chat_id=None):
    caminho_arquivo = None
    try:
        resultado, nome_base, legenda = consultar_docs_backup(tipo)

        if tipo == "geral":
            payload = resultado
            total = (
                int(payload.get("usuarios_count", 0))
                + int(payload.get("vips_ativos_count", 0))
                + int(payload.get("pedidos_count", 0))
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


def processar_aviso_geral(admin_chat_id, msg_texto):
    try:
        usuarios = usuarios_col.find({}, {"_id": 1})
        enviados = 0
        falhas = 0

        logger.info("[AVISOGERAL_LOOP] iniciado")

        for u in usuarios:
            try:
                resp = safe_send_message(int(u["_id"]), msg_texto)
                if resp:
                    enviados += 1
                else:
                    falhas += 1
                time.sleep(0.05)
            except Exception as e:
                falhas += 1
                logger.warning(f"[AVISOGERAL_ITEM] user_id={u.get('_id')} erro={e}")
        safe_send_message(
            admin_chat_id,
            f"📢 Aviso finalizado\n✅ Enviados: {enviados}\n❌ Falhas: {falhas}"
        )
        logger.info(f"[AVISOGERAL_LOOP] finalizado enviados={enviados} falhas={falhas}")
    except Exception as e:
        logger.error(f"[AVISOGERAL_LOOP] erro={e}")
        safe_send_message(admin_chat_id, "❌ Erro ao enviar aviso geral.")


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


def _admin_code(valor, max_len=None):
    texto = str(valor).replace("`", "'")
    if max_len and len(texto) > max_len:
        return texto[:max_len] + "..."
    return texto

def enviar_painel_admin(chat_id):
    try:
        hoje = hoje_str()
        total_users = usuarios_col.count_documents({})

        vips_ativos = usuarios_col.count_documents({
            "$or": [
                {"vip_ate": "Vitalício"},
                {"vip_ate": {"$gte": hoje}}
            ]
        })

        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$downloads_hoje"}}}]
        res_downloads = list(usuarios_col.aggregate(pipeline))
        downloads_totais_hoje = res_downloads[0]["total"] if res_downloads else 0

        pedidos_pendentes = pedidos_col.count_documents({"status": "pending"})
        pedidos_pagos = pedidos_col.count_documents({"status": "paid"})
        pedidos_expirados = pedidos_col.count_documents({"status": "expired"})
        pedidos_checkout_error = pedidos_col.count_documents({"status": "checkout_error"})
        pedidos_creating = pedidos_col.count_documents({"status": "creating"})
        downloads_em_andamento = contar_downloads_em_andamento()

        mongo_status = "ok"
        try:
            client.admin.command("ping")
        except Exception as e:
            mongo_status = f"erro: {str(e)[:80]}"

        resumo_admin = (
            "⚙️ *Painel Admin*\n\n"
            "*Sistema*\n"
            f"🧩 Serviço: `{_admin_code(SERVICE_NAME, 28)}`\n"
            f"🌎 Ambiente: `{_admin_code(ENVIRONMENT_NAME, 20)}`\n"
            f"🆔 Deploy: `{_admin_code(DEPLOYMENT_ID, 18)}`\n"
            f"🔖 Versão: `{_admin_code(APP_VERSION, 18)}`\n\n"
            "*Usuários e uso*\n"
            f"👥 Usuários: `{total_users}`\n"
            f"💎 VIPs ativos: `{vips_ativos}`\n"
            f"📥 Downloads hoje: `{downloads_totais_hoje}`\n"
            f"🚦 Em andamento: `{downloads_em_andamento}`\n\n"
            "*Pedidos*\n"
            f"🕒 Pendentes: `{pedidos_pendentes}`\n"
            f"⏳ Criando checkout: `{pedidos_creating}`\n"
            f"❌ Checkout com erro: `{pedidos_checkout_error}`\n"
            f"⌛ Expirados: `{pedidos_expirados}`\n"
            f"✅ Pagos: `{pedidos_pagos}`\n\n"
            "*Infra*\n"
            f"🗄 Mongo: `{_admin_code(mongo_status, 28)}`\n"
            f"🎬 ffmpeg: `{'ok' if ffmpeg_disponivel() else 'off'}`\n"
            f"🔎 ffprobe: `{'ok' if ffprobe_disponivel() else 'off'}`\n\n"
            "*Config atual*\n"
            f"🆓 Limite grátis: `{FREE_DAILY_LIMIT}/dia`\n"
            f"⏱ Duração máx: `{MAX_DURATION_SECONDS}s`\n"
            f"⌛ Expiração pendentes: `{PENDING_ORDER_EXPIRATION_HOURS}h`"
        )
        comandos_admin = (
            "*Comandos*\n"
            "• `/admin` ou botão *⚙️ Painel Admin*\n"
            "• `/stats`\n"
            "• `/pedido [ORDER_NSU]`\n"
            "• `/user [ID]`\n"
            "• `/darvip [ID] [Dias]`\n"
            "• `/zerar [ID]`\n"
            "• `/avisogeral [Mensagem]`\n"
            "• `/backupusuarios`\n"
            "• `/backupvips`\n"
            "• `/backuppedidos`\n"
            "• `/backupgeral`"
        )

        safe_send_message(chat_id, resumo_admin, parse_mode="Markdown")
        safe_send_message(chat_id, comandos_admin, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[PAINEL_ADMIN] erro={e}")
        safe_send_message(chat_id, "❌ Erro ao abrir painel admin.")


@bot.message_handler(commands=["admin", "paineladmin"])
def painel_admin_cmd(message):
    if message.from_user.id != ADMIN_ID:
        return
    enviar_painel_admin(message.chat.id)


@bot.message_handler(func=lambda m: m.text == "⚙️ Painel Admin")
def painel_admin(message):
    if message.from_user.id != ADMIN_ID:
        return
    enviar_painel_admin(message.chat.id)


@bot.message_handler(commands=["stats"])
def admin_stats(message):
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

        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$downloads_hoje"}}}]
        res_downloads = list(usuarios_col.aggregate(pipeline))
        downloads_totais_hoje = res_downloads[0]["total"] if res_downloads else 0

        pedidos_pendentes = pedidos_col.count_documents({"status": "pending"})
        pedidos_pagos = pedidos_col.count_documents({"status": "paid"})
        pedidos_expirados = pedidos_col.count_documents({"status": "expired"})
        pedidos_checkout_error = pedidos_col.count_documents({"status": "checkout_error"})
        pedidos_creating = pedidos_col.count_documents({"status": "creating"})
        downloads_em_andamento = contar_downloads_em_andamento()

        mongo_status = "ok"
        try:
            client.admin.command("ping")
        except Exception as e:
            mongo_status = f"erro: {str(e)[:80]}"

        texto = (
            "📊 *Stats rápidas*\n\n"
            f"👥 Usuários: `{total_users}`\n"
            f"💎 VIPs ativos: `{vips_ativos}`\n"
            f"📥 Downloads hoje: `{downloads_totais_hoje}`\n"
            f"🚦 Em andamento: `{downloads_em_andamento}`\n\n"
            "💳 *Pedidos*\n"
            f"🕒 Pendentes: `{pedidos_pendentes}`\n"
            f"⏳ Criando checkout: `{pedidos_creating}`\n"
            f"❌ Checkout com erro: `{pedidos_checkout_error}`\n"
            f"⌛ Expirados: `{pedidos_expirados}`\n"
            f"✅ Pagos: `{pedidos_pagos}`\n\n"
            "🖥 *Infra*\n"
            f"🗄 Mongo: `{_admin_code(mongo_status, 28)}`\n"
            f"🎬 ffmpeg: `{'ok' if ffmpeg_disponivel() else 'off'}`\n"
            f"🔎 ffprobe: `{'ok' if ffprobe_disponivel() else 'off'}`"
        )

        safe_send_message(message.chat.id, texto, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[ADMIN_STATS] erro={e}")
        safe_send_message(message.chat.id, "❌ Erro ao consultar stats.")


@bot.message_handler(commands=["pedido"])
def admin_pedido(message):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            return safe_reply_to(message, "❌ Use: `/pedido ORDER_NSU`", parse_mode="Markdown")

        order_nsu = args[1].strip()
        pedido = pedidos_col.find_one({"order_nsu": order_nsu})

        if not pedido:
            return safe_send_message(message.chat.id, "❌ Pedido não encontrado.")

        markup = None
        links = []
        if pedido.get("checkout_url"):
            links.append(types.InlineKeyboardButton("💳 Checkout", url=pedido["checkout_url"]))
        if pedido.get("receipt_url"):
            links.append(types.InlineKeyboardButton("🧾 Comprovante", url=pedido["receipt_url"]))
        if links:
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(*links)

        texto = (
            "🧾 *Consulta de pedido*\n\n"
            f"🔖 NSU: `{_admin_code(pedido.get('order_nsu'), 64)}`\n"
            f"👤 Usuário: `{_admin_code(pedido.get('user_id'), 24)}`\n"
            f"💳 Plano: *{_escape_md(pedido.get('plano_nome') or '-')}*\n"
            f"💰 Valor: *{_escape_md(formatar_valor_centavos(pedido.get('valor_centavos')))}*\n"
            f"📌 Status: *{_escape_md(formatar_status_pedido(pedido.get('status')))}*\n"
            f"🕒 Criado em: `{_admin_code(formatar_data_admin(pedido.get('created_at')), 24)}`\n"
            f"✅ Pago em: `{_admin_code(formatar_data_admin(pedido.get('paid_at')), 24)}`\n"
            f"🔁 Transação: `{_admin_code(pedido.get('transaction_nsu') or '-', 32)}`\n"
            f"💎 VIP liberado até: `{_admin_code(pedido.get('vip_liberado_ate') or '-', 24)}`\n"
            f"⌛ Expirado em: `{_admin_code(formatar_data_admin(pedido.get('expired_at')), 24)}`\n"
            f"⚙️ Forma: `{_admin_code(pedido.get('capture_method') or '-', 24)}`"
        )

        safe_send_message(message.chat.id, texto, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        logger.error(f"[ADMIN_PEDIDO] erro={e}")
        safe_send_message(message.chat.id, "❌ Erro ao consultar pedido.")


@bot.message_handler(commands=["user"])
def admin_user(message):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        args = message.text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            return safe_reply_to(message, "❌ Use: `/user ID`", parse_mode="Markdown")

        alvo_id = args[1].strip()
        user_bruto = usuarios_col.find_one({"_id": str(alvo_id)})
        if not user_bruto:
            return safe_send_message(message.chat.id, "❌ Usuário não encontrado.")

        user = obter_usuario(alvo_id)
        vip = is_vip_user(user)

        pedidos_usuario = list(
            pedidos_col.find(
                {"user_id": str(alvo_id)},
                {
                    "_id": 0,
                    "order_nsu": 1,
                    "plano_nome": 1,
                    "valor_centavos": 1,
                    "status": 1,
                    "created_at": 1,
                    "vip_liberado_ate": 1,
                }
            ).sort("created_at", -1).limit(5)
        )

        if pedidos_usuario:
            linhas_pedidos = []
            for pedido in pedidos_usuario:
                linhas_pedidos.append(
                    "• "
                    f"`{_admin_code(pedido.get('order_nsu') or '-', 18)}` | "
                    f"*{_escape_md(formatar_status_pedido(pedido.get('status')))}* | "
                    f"{_escape_md(pedido.get('plano_nome') or '-')} | "
                    f"{_escape_md(formatar_valor_centavos(pedido.get('valor_centavos')))} | "
                    f"`{_admin_code(formatar_data_admin(pedido.get('created_at')), 16)}`"
                )
            resumo_pedidos = "\n".join(linhas_pedidos)
        else:
            resumo_pedidos = "Nenhum pedido encontrado."

        texto = (
            "👤 *Consulta de usuário*\n\n"
            f"🆔 ID: `{_admin_code(alvo_id, 24)}`\n"
            f"💎 VIP ativo: *{'sim' if vip else 'não'}*\n"
            f"📅 VIP até: `{_admin_code(user.get('vip_ate') or '-', 24)}`\n"
            f"📥 Downloads hoje: `{int(user.get('downloads_hoje', 0) or 0)}`\n"
            f"🗓 Última data: `{_admin_code(user.get('ultima_data') or '-', 16)}`\n\n"
            "🧾 *Últimos pedidos*\n"
            f"{resumo_pedidos}"
        )

        safe_send_message(message.chat.id, texto, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"[ADMIN_USER] erro={e}")
        safe_send_message(message.chat.id, "❌ Erro ao consultar usuário.")


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
        "• Liberação automática após o pagamento\n\n"
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
def checkout_automatico(call):
    order_nsu = None

    try:
        valor = call.data.split("_", 1)[1]
        plano = obter_plano_por_callback(valor)

        if not plano:
            safe_send_message(call.message.chat.id, "❌ Plano inválido.")
            return

        order_nsu = gerar_order_nsu(call.from_user.id)

        pedido = {
            "order_nsu": order_nsu,
            "user_id": str(call.from_user.id),
            "plano_key": valor,
            "plano_nome": plano["nome"],
            "valor_centavos": int(plano["preco_centavos"]),
            "status": "creating",
            "created_at": agora_tz(),
            "checkout_url": None,
            "transaction_nsu": None,
            "receipt_url": None,
            "checkout_error": None
        }

        pedidos_col.insert_one(pedido)

        checkout_url = criar_checkout_infinitepay(order_nsu, plano)

        pedidos_col.update_one(
            {"order_nsu": order_nsu},
            {
                "$set": {
                    "status": "pending",
                    "checkout_url": checkout_url,
                    "checkout_created_at": agora_tz(),
                    "checkout_error": None
                }
            }
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Pagar agora", url=checkout_url))

        texto = (
            f"💎 *{plano['nome']}*\n\n"
            "Seu link de pagamento foi gerado com sucesso.\n\n"
            "✅ Assim que o pagamento for aprovado, o VIP será liberado automaticamente.\n"
            f"🧾 Pedido: `{order_nsu}`"
        )

        safe_send_message(
            call.message.chat.id,
            texto,
            parse_mode="Markdown",
            reply_markup=markup
        )

    except Exception as e:
        logger.error(f"[CHECKOUT_CALLBACK] erro={e}")

        if order_nsu:
            try:
                pedidos_col.update_one(
                    {"order_nsu": order_nsu},
                    {
                        "$set": {
                            "status": "checkout_error",
                            "checkout_error": str(e)[:500],
                            "checkout_error_at": agora_tz()
                        }
                    }
                )
            except Exception as e2:
                logger.error(f"[CHECKOUT_CALLBACK_UPDATE_ERROR] order_nsu={order_nsu} erro={e2}")

        safe_send_message(
            call.message.chat.id,
            "❌ Não consegui gerar seu link de pagamento agora.\n"
            "Tente novamente em instantes ou fale com o suporte."
        )
    finally:
        safe_answer_callback(call.id)


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
            "bestvideo[ext=mp4][width<=720][height<=1280]+bestaudio[ext=m4a]/best[ext=mp4][width<=720][height<=1280]",
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

    if is_tiktok or is_rednote:
        return formatos_capados_gerais() + [
            "best[ext=mp4]/best"
        ]

    return formatos_capados_gerais()


@bot.message_handler(func=lambda message: message.text and "http" in message.text.lower())
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip_status = is_vip_user(user)
    prefix = None
    controle_download_ativo = False

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

    if not iniciar_controle_download_usuario(message.from_user.id, getattr(message, "date", None)):
        return safe_reply_to(
            message,
            "⏳ Já estou processando seu link anterior. Aguarde concluir para enviar outro."
        )

    controle_download_ativo = True

    status_msg = safe_reply_to(
        message,
        "✅ Seu link entrou na fila de download! Aguarde só alguns instantes 👊"
    )

    try:
        url_lower = url.lower()
        is_pinterest, is_tiktok, is_instagram, is_rednote = detectar_plataforma(url_lower)
        plataforma = nome_plataforma(is_pinterest, is_tiktok, is_instagram, is_rednote)

        logger.info(f"[DOWNLOAD_INICIO] user_id={message.from_user.id} plataforma={plataforma} url={url}")

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

            except Exception as e:
                logger.warning(f"[PINTEREST_INFO] Falha ao ler metadados: {e}")

            try:
                arquivo_final = baixar_pinterest_capado(url, prefix)

                enviado = enviar_arquivo_com_fallback(message.chat.id, arquivo_final)
                if not enviado:
                    raise Exception("Falha ao enviar arquivo ao Telegram")

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

        prefix = os.path.join(DOWNLOAD_DIR, f"v_{message.from_user.id}_{uuid.uuid4().hex}")

        with yt_dlp.YoutubeDL(montar_info_opts(is_instagram=is_instagram)) as ydl:
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

        common_opts = montar_download_opts(prefix, is_instagram=is_instagram)
        formatos = formatos_por_plataforma(
            is_tiktok=is_tiktok,
            is_instagram=is_instagram,
            is_pinterest=is_pinterest,
            is_rednote=is_rednote,
        )
        baixou = False
        ultimo_erro = None

        for fmt in formatos:
            try:
                cleanup_prefix(prefix)

                opts = common_opts.copy()
                opts["format"] = fmt

                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([url])

                arquivo_baixado = encontrar_arquivo_baixado(prefix)
                if arquivo_baixado and os.path.exists(arquivo_baixado):
                    logger.info(
                        f"[DOWNLOAD_OK] plataforma={plataforma} formato={fmt} arquivo={arquivo_baixado}"
                    )
                    baixou = True
                    break

            except Exception as e:
                ultimo_erro = str(e)
                logger.warning(f"[DOWNLOAD_TENTATIVA] plataforma={plataforma} formato={fmt} url={url} erro={e}")

        if not baixou:
            raise Exception(ultimo_erro or "Falha ao baixar dentro do limite 720x1280 30fps")

        arquivo_final = encontrar_arquivo_baixado(prefix)
        if not arquivo_final or not os.path.exists(arquivo_final):
            raise Exception("Arquivo final não encontrado após o download")

        if not ffmpeg_disponivel():
            raise Exception("ffmpeg não está instalado no servidor.")

        arquivo_envio = preparar_arquivo_para_envio(arquivo_final, plataforma=plataforma)

        enviado = enviar_arquivo_com_fallback(message.chat.id, arquivo_envio)
        if not enviado:
            raise Exception("Falha ao enviar arquivo ao Telegram")

        if not vip_status:
            incrementar_download_gratis(user, message.chat.id, message.from_user.id)

        if status_msg:
            safe_delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.error(f"[ERRO_DOWNLOAD] user_id={message.from_user.id} url={url} erro={e}")
        texto_erro = mapear_erro_download(str(e), plataforma=("instagram" if "instagram.com" in url.lower() else "geral"))

        if status_msg:
            safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
        else:
            safe_send_message(message.chat.id, texto_erro)

    finally:
        if prefix:
            cleanup_prefix(prefix)
        if controle_download_ativo:
            finalizar_controle_download_usuario(message.from_user.id)


# =========================================
# ROTAS INFINITEPAY
# =========================================
@app.route("/pagamento/sucesso")
def pagamento_sucesso():
    order_nsu = request.args.get("order_nsu", "")
    capture_method = request.args.get("capture_method", "")
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
        if secret_recebido != INFINITEPAY_WEBHOOK_SECRET:
            logger.warning("[WEBHOOK_INFINITEPAY] acesso negado: secret inválido")
            disparar_notificacao_admin(
                montar_texto_admin_webhook(
                    "🚫 *Webhook InfinitePay negado*",
                    detalhe="Secret inválido"
                )
            )
            return jsonify({
                "success": False,
                "message": "Não autorizado"
            }), 403

        payload = request.get_json(silent=True) or {}
        order_nsu = payload.get("order_nsu")
        transaction_nsu = payload.get("transaction_nsu")
        amount = payload.get("amount")
        receipt_url = payload.get("receipt_url")
        capture_method = payload.get("capture_method")

        logger.info(
            f"[WEBHOOK_INFINITEPAY] recebido order_nsu={order_nsu} transaction_nsu={transaction_nsu} "
            f"amount={amount} capture_method={capture_method}"
        )
        disparar_notificacao_admin(
            montar_texto_admin_webhook(
                "📩 *Webhook InfinitePay recebido*",
                order_nsu=order_nsu,
                valor_centavos=amount,
                detalhe=f"Forma: {capture_method or 'não informada'}"
            )
        )

        if not order_nsu:
            logger.warning("[WEBHOOK_INFINITEPAY] order_nsu ausente")
            disparar_notificacao_admin(
                montar_texto_admin_webhook(
                    "⚠️ *Webhook com erro*",
                    detalhe="order_nsu ausente"
                )
            )
            return jsonify({
                "success": False,
                "message": "order_nsu ausente"
            }), 400

        pedido = pedidos_col.find_one({"order_nsu": order_nsu})
        if not pedido:
            logger.warning(f"[WEBHOOK_PEDIDO_NAO_ENCONTRADO] order_nsu={order_nsu}")
            disparar_notificacao_admin(
                montar_texto_admin_webhook(
                    "⚠️ *Pedido não encontrado no webhook*",
                    order_nsu=order_nsu,
                    valor_centavos=amount
                )
            )
            return jsonify({
                "success": False,
                "message": "Pedido não encontrado"
            }), 400

        plano = PLANOS.get(pedido.get("plano_key")) or {}
        plano_nome = plano.get("nome")

        if pedido.get("status") == "paid":
            logger.info(f"[WEBHOOK_PEDIDO_JA_PAGO] order_nsu={order_nsu}")
            disparar_notificacao_admin(
                montar_texto_admin_webhook(
                    "ℹ️ *Webhook duplicado ignorado*",
                    order_nsu=order_nsu,
                    user_id=pedido.get("user_id"),
                    plano_nome=plano_nome,
                    valor_centavos=pedido.get("valor_centavos")
                )
            )
            return jsonify({
                "success": True,
                "message": None
            }), 200

        valor_esperado = int(pedido.get("valor_centavos", 0))
        try:
            valor_recebido = int(amount or 0)
        except Exception:
            valor_recebido = 0

        if valor_recebido != valor_esperado:
            detalhe = f"Esperado {valor_esperado} | Recebido {valor_recebido}"
            logger.warning(f"[WEBHOOK_VALOR_DIVERGENTE] order_nsu={order_nsu} {detalhe}")
            disparar_notificacao_admin(
                montar_texto_admin_webhook(
                    "❌ *Valor divergente no webhook*",
                    order_nsu=order_nsu,
                    user_id=pedido.get("user_id"),
                    plano_nome=plano_nome,
                    valor_centavos=valor_recebido,
                    detalhe=detalhe
                )
            )
            return jsonify({
                "success": False,
                "message": "Valor divergente"
            }), 400

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

        logger.info(
            f"[WEBHOOK_PROCESSANDO] order_nsu={order_nsu} user_id={pedido['user_id']} "
            f"plano={plano['nome']} valor={valor_recebido}"
        )

        vip_ate = liberar_vip_por_plano(pedido["user_id"], plano)

        pedidos_col.update_one(
            {"order_nsu": order_nsu},
            {
                "$set": {
                    "status": "paid",
                    "paid_at": agora_tz(),
                    "transaction_nsu": transaction_nsu,
                    "receipt_url": receipt_url,
                    "capture_method": capture_method,
                    "vip_liberado_ate": vip_ate
                }
            }
        )

        logger.info(
            f"[WEBHOOK_APROVADO] order_nsu={order_nsu} user_id={pedido['user_id']} "
            f"plano={plano['nome']} vip_ate={vip_ate}"
        )
        disparar_notificacao_admin(
            montar_texto_admin_webhook(
                "✅ *Pagamento aprovado e VIP liberado*",
                order_nsu=order_nsu,
                user_id=pedido.get("user_id"),
                plano_nome=plano.get("nome"),
                valor_centavos=valor_recebido,
                detalhe=f"VIP até: {vip_ate}"
            )
        )

        Thread(
            target=notificar_pagamento_confirmado,
            args=(pedido["user_id"], plano["nome"], vip_ate, receipt_url),
            daemon=True
        ).start()

        return jsonify({
            "success": True,
            "message": None
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





def obter_metricas_health():
    metricas = {
        "ffmpeg_available": ffmpeg_disponivel(),
        "ffprobe_available": ffprobe_disponivel(),
        "mongo_status": "unknown",
        "users_total": None,
        "active_vips": None,
        "pending_orders": None,
        "expired_orders": None,
        "paid_orders": None,
        "downloads_in_progress": contar_downloads_em_andamento(),
    }

    try:
        client.admin.command("ping")
        metricas["mongo_status"] = "ok"

        hoje = hoje_str()
        metricas["users_total"] = usuarios_col.count_documents({})
        metricas["active_vips"] = usuarios_col.count_documents({
            "$or": [
                {"vip_ate": "Vitalício"},
                {"vip_ate": {"$gte": hoje}}
            ]
        })
        metricas["pending_orders"] = pedidos_col.count_documents({"status": "pending"})
        metricas["expired_orders"] = pedidos_col.count_documents({"status": "expired"})
        metricas["paid_orders"] = pedidos_col.count_documents({"status": "paid"})
    except Exception as e:
        metricas["mongo_status"] = f"error: {str(e)[:150]}"
        logger.warning(f"[HEALTH_METRICS] erro={e}")

    return metricas


# =========================================
# HEALTHCHECK
# =========================================
@app.route("/")
def root_status():
    return "ONLINE", 200

@app.route("/health")
def health():
    metricas = obter_metricas_health()

    return jsonify({
        "status": "ok",
        "service": SERVICE_NAME,
        "version": APP_VERSION,
        "deployment_id": DEPLOYMENT_ID,
        "environment": ENVIRONMENT_NAME,
        "started_at": APP_STARTED_AT,
        "bot": "running",
        "flask": "running",
        "ffmpeg_available": metricas["ffmpeg_available"],
        "ffprobe_available": metricas["ffprobe_available"],
        "mongo_status": metricas["mongo_status"],
        "users_total": metricas["users_total"],
        "active_vips": metricas["active_vips"],
        "pending_orders": metricas["pending_orders"],
        "expired_orders": metricas["expired_orders"],
        "paid_orders": metricas["paid_orders"],
        "downloads_in_progress": metricas["downloads_in_progress"]
    }), 200


# =========================================
# MAIN
# =========================================
if __name__ == "__main__":
    cleanup_download_dir_old_files(max_age_hours=6)
    expirar_pedidos_antigos(expiration_hours=PENDING_ORDER_EXPIRATION_HOURS)

    Thread(
        target=cleanup_download_dir_periodicamente,
        kwargs={"interval_minutes": 60, "max_age_hours": 6},
        daemon=True
    ).start()

    Thread(
        target=loop_expirar_pedidos_antigos,
        kwargs={"interval_minutes": 60, "expiration_hours": PENDING_ORDER_EXPIRATION_HOURS},
        daemon=True
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
