import os
import re
import glob
import uuid
import time
import logging
from threading import Thread
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import telebot
import yt_dlp
import subprocess
import json
import html
from urllib.parse import unquote

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

INSTAGRAM_COOKIES_TEXT = os.environ.get("INSTAGRAM_COOKIES_TEXT", "").strip()

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

SHOPEE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Referer": "https://shopee.com.br/",
    "Origin": "https://shopee.com.br",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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

    duracao = None
    try:
        duracao_raw = (dados.get("format", {}) or {}).get("duration")
        if duracao_raw:
            duracao = float(duracao_raw)
    except Exception:
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
        "duration": duracao,
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


def safe_answer_callback(call_id):
    try:
        bot.answer_callback_query(call_id)
    except Exception as e:
        logger.warning(f"[CALLBACK_ANSWER] erro={e}")


def enviar_arquivo_com_fallback(chat_id, arquivo):
    try:
        with open(arquivo, "rb") as f:
            bot.send_video(chat_id, f, caption="👉 Download concluído! Aqui está seu vídeo 👊")
        return True
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

            with open(arquivo_fallback, "rb") as f:
                bot.send_video(chat_id, f, caption="👉 Download concluído! Aqui está seu vídeo 👊")

            logger.info(f"[SEND_VIDEO] Fallback H.264 enviado com sucesso | arquivo={arquivo_fallback}")
            return True
        except Exception as e_h264:
            logger.warning(f"[SEND_VIDEO] Fallback H.264 também falhou. erro={e_h264}")

    alvo_documento = arquivo_fallback if arquivo_fallback and os.path.exists(arquivo_fallback) else arquivo

    try:
        with open(alvo_documento, "rb") as f:
            bot.send_document(chat_id, f, caption="👉 Download concluído! Aqui está seu arquivo 👊")
        return True
    except Exception as e_doc:
        logger.error(f"[SEND_DOCUMENT] Também falhou. erro={e_doc}")
        return False


def detectar_plataforma(url_lower):
    is_pinterest = ("pin.it" in url_lower) or ("pinterest" in url_lower)
    is_tiktok = ("tiktok.com" in url_lower) or ("vm.tiktok.com" in url_lower) or ("vt.tiktok.com" in url_lower)
    is_instagram = ("instagram.com" in url_lower) or ("instagr.am" in url_lower)
    is_rednote = ("xiaohongshu.com" in url_lower) or ("xhslink.com" in url_lower) or ("rednote" in url_lower)
    is_shopee = ("shopee.com" in url_lower) or ("shp.ee" in url_lower) or ("sv.shopee" in url_lower)
    return is_pinterest, is_tiktok, is_instagram, is_rednote, is_shopee


def nome_plataforma(is_pinterest, is_tiktok, is_instagram, is_rednote, is_shopee=False):
    if is_pinterest:
        return "Pinterest"
    if is_tiktok:
        return "TikTok"
    if is_instagram:
        return "Instagram"
    if is_rednote:
        return "RedNote"
    if is_shopee:
        return "Shopee"
    return "Desconhecida"


def get_instagram_cookiefile():
    if INSTAGRAM_COOKIES_TEXT:
        cookie_path = os.path.join(DOWNLOAD_DIR, "instagram_cookies.txt")
        with open(cookie_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(INSTAGRAM_COOKIES_TEXT)
        return cookie_path
    return None


def montar_info_opts(is_instagram=False, is_pinterest=False, is_shopee=False):
    opts = {
        "quiet": True,
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
    elif is_shopee:
        opts["http_headers"] = SHOPEE_HEADERS

    return opts


def montar_download_opts(prefix, is_instagram=False, is_pinterest=False, is_shopee=False):
    opts = {
        "outtmpl": f"{prefix}.%(ext)s",
        "nocheckcertificate": True,
        "quiet": True,
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
    elif is_shopee:
        opts["http_headers"] = SHOPEE_HEADERS

    return opts


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

    if plataforma == "shopee":
        if "nenhuma url direta" in err or "não encontrei o vídeo" in err:
            return "❌ Não encontrei o vídeo nesse link da Shopee. Envie o link direto do Shopee Vídeo."
        if "403" in err or "forbidden" in err:
            return "❌ A Shopee bloqueou esse link no momento. Tente novamente ou envie outro link do vídeo."
        if "timed out" in err or "timeout" in err:
            return "❌ A Shopee demorou para responder. Tente novamente."
        return "❌ Não consegui baixar esse Shopee Vídeo agora."

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
# SHOPEE VÍDEOS
# =========================================
def resolver_link_shopee(url):
    try:
        url = url.strip()

        r = requests.get(
            url,
            allow_redirects=True,
            timeout=(5, 15),
            headers=SHOPEE_HEADERS
        )

        if r.url:
            logger.info(f"[SHOPEE_REDIRECT] {url} -> {r.url}")
            return r.url, r.text

    except Timeout as e:
        logger.warning(f"[SHOPEE_TIMEOUT] url={url} erro={e}")
    except RequestException as e:
        logger.warning(f"[SHOPEE_REQUEST_ERROR] url={url} erro={e}")
    except Exception as e:
        logger.warning(f"[SHOPEE_UNKNOWN_ERROR] url={url} erro={e}")

    return url, None


def normalizar_url_midia_shopee(raw_url):
    if not raw_url:
        return None

    url = str(raw_url).strip().strip("\"' ")
    url = html.unescape(url)

    # A Shopee costuma entregar URLs em vários formatos:
    # normal, com barras escapadas, unicode escaped e/ou percent-encoded.
    for _ in range(3):
        antes = url
        try:
            url = json.loads(f'"{url}"')
        except Exception:
            pass

        url = (
            url
            .replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("&amp;", "&")
        )

        try:
            url = unquote(url)
        except Exception:
            pass

        if url == antes:
            break

    if url.startswith("//"):
        url = "https:" + url

    # Corrige URLs que ficaram com barras ainda escapadas depois do decode.
    url = url.replace("\\/", "/")

    return url


def url_parece_video_shopee(url):
    if not url:
        return False

    u = url.lower()
    if any(x in u for x in ("thumbnail", "thumb", "cover", "avatar", "image", ".jpg", ".jpeg", ".png", ".webp", ".gif")):
        return False

    return (
        ".mp4" in u
        or ".m3u8" in u
        or "vod.susercontent.com" in u
        or "down-" in u and "susercontent.com" in u
    )


def pontuar_contexto_shopee(url, contexto="", origem=""):
    texto = f"{url} {contexto} {origem}".lower()
    score = 0

    # Prioridade máxima: versões originais/sem marca d'água quando a página expõe esse campo.
    termos_sem_marca = [
        "no_watermark", "no-watermark", "nowatermark", "without_watermark",
        "without-watermark", "watermarkless", "sem_marca", "sem-marca"
    ]
    if any(t in texto for t in termos_sem_marca):
        score += 500

    termos_original = [
        "origin_video", "original_video", "originurl", "originalurl", "origin_url",
        "original_url", "source_url", "raw_url", "rawurl", "video_original", "video_origin"
    ]
    if any(t in texto for t in termos_original):
        score += 260

    if "video_url" in texto or "videourl" in texto or "play_url" in texto or "playurl" in texto:
        score += 80

    # Evita candidatos declaradamente com marca d'água ou prévias/miniaturas.
    if "watermark" in texto and not any(t in texto for t in termos_sem_marca):
        score -= 350
    if re.search(r"(^|[^a-z])wm([^a-z]|$)", texto) and not any(t in texto for t in termos_sem_marca):
        score -= 120
    if any(t in texto for t in ("preview", "cover", "thumbnail", "thumb", "compressed", "low_quality", "lowquality")):
        score -= 220

    # Preferências de qualidade, sem forçar upscale.
    if "720" in texto or "1280" in texto:
        score += 90
    if "540" in texto or "960" in texto:
        score += 45
    if "480" in texto or "854" in texto:
        score += 20
    if "360" in texto or "640" in texto:
        score += 5

    if ".m3u8" in texto:
        score += 35
    if ".mp4" in texto:
        score += 25

    return score


def _adicionar_candidato_shopee(candidatos, vistos, raw_url, origem="", contexto=""):
    url = normalizar_url_midia_shopee(raw_url)
    if not url or not url_parece_video_shopee(url):
        return

    chave = url.split("#", 1)[0]
    if chave in vistos:
        return

    vistos.add(chave)
    candidatos.append({
        "url": url,
        "origem": origem,
        "contexto": contexto or "",
        "score_contexto": pontuar_contexto_shopee(url, contexto, origem),
    })


def extrair_candidatos_video_shopee_html(html_text):
    if not html_text:
        return []

    candidatos = []
    vistos = set()

    # URLs normais, escapadas e percent-encoded.
    padroes = [
        r'https?:\\?/\\?/[^"\'<>\s]+?(?:\.mp4|\.m3u8)(?:\?[^"\'<>\s]*)?',
        r'//[^"\'<>\s]+?(?:\.mp4|\.m3u8)(?:\?[^"\'<>\s]*)?',
        r'https?:\\?/\\?/[^"\'<>\s]*vod\.susercontent\.com[^"\'<>\s]*',
        r'//[^"\'<>\s]*vod\.susercontent\.com[^"\'<>\s]*',
        r'https%3A%2F%2F[^"\'<>\s]+?(?:\.mp4|\.m3u8|%2Emp4|%2Em3u8)(?:[^"\'<>\s]*)?',
        r'https%3A%2F%2F[^"\'<>\s]*vod\.susercontent\.com[^"\'<>\s]*',
    ]

    for padrao in padroes:
        for match in re.finditer(padrao, html_text, flags=re.IGNORECASE):
            ini = max(0, match.start() - 180)
            fim = min(len(html_text), match.end() + 180)
            contexto = html_text[ini:fim]
            _adicionar_candidato_shopee(
                candidatos,
                vistos,
                match.group(0),
                origem="regex_url",
                contexto=contexto
            )

    # Campos JSON/JS que podem indicar versão original ou sem marca d'água.
    chaves_video = [
        "no_watermark_url", "noWatermarkUrl", "nowatermark_url", "without_watermark_url",
        "origin_video_url", "original_video_url", "originVideoUrl", "originalVideoUrl",
        "source_video_url", "raw_video_url", "video_url", "videoUrl", "play_url", "playUrl",
        "url", "src"
    ]

    for chave in chaves_video:
        padrao_chave = rf'["\']{re.escape(chave)}["\']\s*:\s*["\']([^"\']+)["\']'
        for match in re.finditer(padrao_chave, html_text, flags=re.IGNORECASE):
            ini = max(0, match.start() - 180)
            fim = min(len(html_text), match.end() + 180)
            contexto = html_text[ini:fim]
            _adicionar_candidato_shopee(
                candidatos,
                vistos,
                match.group(1),
                origem=f"json_key:{chave}",
                contexto=contexto
            )

    # Remove duplicados e coloca em primeiro as URLs com maior chance de serem HD/sem marca.
    candidatos.sort(
        key=lambda c: (
            c.get("score_contexto", 0),
            1 if ".m3u8" in c.get("url", "").lower() else 0,
            len(c.get("url", ""))
        ),
        reverse=True
    )

    return candidatos


def extrair_urls_video_shopee_html(html_text):
    # Mantida por compatibilidade com versões anteriores do código.
    return [c["url"] for c in extrair_candidatos_video_shopee_html(html_text)]


def baixar_url_direta_shopee(video_url, prefix):
    video_url = normalizar_url_midia_shopee(video_url)

    if not video_url:
        raise Exception("URL direta da Shopee inválida")

    if ".m3u8" in video_url.lower():
        opts = montar_download_opts(prefix, is_shopee=True)
        opts["format"] = "best[width<=720][height<=1280][fps<=30]/best[width<=720][height<=1280]/best"

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([video_url])

        arquivo = encontrar_arquivo_baixado(prefix)
        if arquivo and os.path.exists(arquivo):
            return arquivo

        raise Exception("Arquivo Shopee m3u8 não foi gerado")

    arquivo_saida = f"{prefix}.mp4"

    with requests.get(
        video_url,
        stream=True,
        timeout=(8, 90),
        headers=SHOPEE_HEADERS
    ) as r:
        if not r.ok:
            raise Exception(f"Falha ao baixar vídeo da Shopee. status={r.status_code}")

        with open(arquivo_saida, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)

    if not os.path.exists(arquivo_saida) or os.path.getsize(arquivo_saida) < 10_000:
        raise Exception("Arquivo da Shopee não foi gerado corretamente")

    return arquivo_saida


def pontuar_arquivo_shopee(arquivo, candidato):
    info = obter_info_midia(arquivo) or {}
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    fps = float(info.get("fps") or 0)
    pixels = width * height
    score_contexto = int(candidato.get("score_contexto") or 0)

    cabe_no_limite = (
        width > 0
        and height > 0
        and width <= 720
        and height <= 1280
        and (fps == 0 or fps <= 30.5)
    )

    # Mantém o mesmo comportamento dos outros apps: pega a melhor qualidade disponível
    # dentro do limite. Não faz upscale de 480 para 720.
    score = score_contexto
    score += 100000 if cabe_no_limite else 0
    score += min(pixels, 720 * 1280) // 10

    # Preferência leve por vídeos verticais de feed/reels.
    if height >= width:
        score += 120

    # Penaliza candidatos acima do limite quando houver outro dentro do limite.
    if width > 720 or height > 1280 or fps > 30.5:
        score -= 30000

    return score, info


def baixar_melhor_candidato_shopee(candidatos, prefix, url_resolvida):
    if not candidatos:
        raise Exception("Não encontrei o vídeo no link da Shopee")

    # Testa vários candidatos, porque a Shopee pode expor 480p, 720p,
    # versão com marca e versão original na mesma página.
    melhores = []
    ultimo_erro = None
    limite_tentativas = min(len(candidatos), 14)

    for idx, candidato in enumerate(candidatos[:limite_tentativas]):
        video_url = candidato.get("url")
        prefix_candidato = f"{prefix}_shopee_{idx}"

        try:
            cleanup_prefix(prefix_candidato)
            arquivo = baixar_url_direta_shopee(video_url, prefix_candidato)

            if not arquivo or not os.path.exists(arquivo):
                continue

            score, info = pontuar_arquivo_shopee(arquivo, candidato)
            logger.info(
                f"[SHOPEE_CANDIDATO] idx={idx} score={score} score_contexto={candidato.get('score_contexto')} "
                f"width={info.get('width')} height={info.get('height')} fps={info.get('fps')} "
                f"origem={candidato.get('origem')} url={video_url[:140]}"
            )

            melhores.append({
                "arquivo": arquivo,
                "score": score,
                "info": info,
                "candidato": candidato,
            })

        except Exception as e:
            ultimo_erro = str(e)
            logger.warning(f"[SHOPEE_TENTATIVA] idx={idx} url={url_resolvida} erro={e}")
            cleanup_prefix(prefix_candidato)

    if not melhores:
        raise Exception(ultimo_erro or "Falha ao baixar Shopee Vídeo")

    melhores.sort(key=lambda item: item["score"], reverse=True)
    escolhido = melhores[0]

    # Remove arquivos dos candidatos que não foram escolhidos.
    arquivo_escolhido = escolhido["arquivo"]
    for item in melhores[1:]:
        try:
            if item["arquivo"] != arquivo_escolhido and os.path.exists(item["arquivo"]):
                os.remove(item["arquivo"])
        except Exception:
            pass

    info = escolhido.get("info") or {}
    candidato = escolhido.get("candidato") or {}
    logger.info(
        f"[SHOPEE_OK] url={url_resolvida} escolhido={arquivo_escolhido} "
        f"width={info.get('width')} height={info.get('height')} fps={info.get('fps')} "
        f"origem={candidato.get('origem')} score_contexto={candidato.get('score_contexto')} "
        f"video_url={str(candidato.get('url', ''))[:140]}"
    )

    return arquivo_escolhido


def baixar_shopee_video(url, prefix):
    url_resolvida, html_text = resolver_link_shopee(url)

    candidatos = extrair_candidatos_video_shopee_html(html_text)

    # Fallback: se o HTML inicial não trouxe o vídeo, tenta buscar a URL final de novo.
    if not candidatos:
        try:
            resp = requests.get(
                url_resolvida,
                timeout=(5, 20),
                headers=SHOPEE_HEADERS
            )
            candidatos = extrair_candidatos_video_shopee_html(resp.text)
        except Exception as e:
            logger.warning(f"[SHOPEE_HTML_FALLBACK] url={url_resolvida} erro={e}")

    if candidatos:
        return baixar_melhor_candidato_shopee(candidatos, prefix, url_resolvida)

    # Último fallback: tenta pelo extrator genérico do yt-dlp, mantendo o limite do bot.
    try:
        opts = montar_download_opts(prefix, is_shopee=True)
        opts["format"] = (
            "bestvideo[ext=mp4][width<=720][height<=1280][fps<=30]+bestaudio[ext=m4a]/"
            "best[ext=mp4][width<=720][height<=1280][fps<=30]/"
            "best[width<=720][height<=1280][fps<=30]/"
            "best[ext=mp4]/best"
        )

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url_resolvida])

        arquivo = encontrar_arquivo_baixado(prefix)
        if arquivo and os.path.exists(arquivo):
            logger.info(f"[SHOPEE_OK_YTDLP] url={url_resolvida}")
            return arquivo
    except Exception as e:
        logger.warning(f"[SHOPEE_YTDLP_FALLBACK] url={url_resolvida} erro={e}")

    raise Exception("Não encontrei o vídeo no link da Shopee")


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
        "✅ Uso liberado para TikTok, Pinterest, Instagram, RedNote e Shopee Vídeos\n"
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
        cont = 0

        logger.info("[AVISOGERAL_LOOP] iniciado")

        for u in usuarios:
            try:
                safe_send_message(int(u["_id"]), msg_texto, parse_mode="Markdown")
                cont += 1
                time.sleep(0.05)
            except Exception:
                pass

        safe_send_message(admin_chat_id, f"📢 Aviso enviado para {cont} usuários!")
        logger.info(f"[AVISOGERAL_LOOP] finalizado enviados={cont}")
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

        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$downloads_hoje"}}}]
        res_downloads = list(usuarios_col.aggregate(pipeline))
        downloads_totais_hoje = res_downloads[0]["total"] if res_downloads else 0

        pedidos_pendentes = pedidos_col.count_documents({"status": "pending"})
        pedidos_pagos = pedidos_col.count_documents({"status": "paid"})

        resumo_admin = (
            "⚙️ *Painel Admin*\n\n"
            f"👥 Usuários: `{total_users}`\n"
            f"💎 VIPs: `{vips_ativos}`\n"
            f"📥 Downloads hoje: `{downloads_totais_hoje}`\n"
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
        "Baixe vídeos em HD do TikTok, Pinterest, Instagram, RedNote e Shopee Vídeos.\n\n"
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
        "• RedNote\n"
        "• Shopee Vídeos\n\n"
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
            "status": "pending",
            "created_at": agora_tz(),
            "checkout_url": None,
            "transaction_nsu": None,
            "receipt_url": None
        }

        pedidos_col.insert_one(pedido)

        checkout_url = criar_checkout_infinitepay(order_nsu, plano)

        pedidos_col.update_one(
            {"order_nsu": order_nsu},
            {"$set": {"checkout_url": checkout_url}}
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


def formatos_por_plataforma(is_tiktok=False, is_instagram=False, is_pinterest=False, is_rednote=False, is_shopee=False):
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

    if is_tiktok or is_rednote or is_shopee:
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
        url_lower = url.lower()
        is_pinterest, is_tiktok, is_instagram, is_rednote, is_shopee = detectar_plataforma(url_lower)
        plataforma = nome_plataforma(is_pinterest, is_tiktok, is_instagram, is_rednote, is_shopee)

        logger.info(f"[DOWNLOAD_INICIO] user_id={message.from_user.id} plataforma={plataforma} url={url}")

        if not (is_pinterest or is_tiktok or is_instagram or is_rednote or is_shopee):
            texto_nao_reconhecido = "❌ Link não reconhecido. Envie um link do TikTok, Pinterest, Instagram, RedNote ou Shopee Vídeos."
            if status_msg:
                safe_edit_message(message.chat.id, status_msg.message_id, texto_nao_reconhecido)
            else:
                safe_send_message(message.chat.id, texto_nao_reconhecido)
            return

        if is_shopee:
            prefix = os.path.join(DOWNLOAD_DIR, f"v_{message.from_user.id}_{uuid.uuid4().hex}")

            try:
                arquivo_final = baixar_shopee_video(url, prefix)

                info_midia = obter_info_midia(arquivo_final) or {}
                duracao = info_midia.get("duration")
                logger.info(f"[META] plataforma=Shopee user_id={message.from_user.id} duration={duracao}")

                if duracao and duracao > MAX_DURATION_SECONDS:
                    texto = f"⚠️ Vídeo muito longo. O limite é de {MAX_DURATION_SECONDS} segundos."
                    if status_msg:
                        safe_edit_message(message.chat.id, status_msg.message_id, texto)
                    else:
                        safe_send_message(message.chat.id, texto)
                    return

                arquivo_envio = preparar_arquivo_para_envio(arquivo_final, plataforma=plataforma)

                enviado = enviar_arquivo_com_fallback(message.chat.id, arquivo_envio)
                if not enviado:
                    raise Exception("Falha ao enviar arquivo ao Telegram")

                if not vip_status:
                    incrementar_download_gratis(user, message.chat.id, message.from_user.id)

                if status_msg:
                    safe_delete_message(message.chat.id, status_msg.message_id)

                return

            except Exception as e:
                logger.error(f"[ERRO_SHOPEE] user_id={message.from_user.id} url={url} erro={e}")
                texto_erro = mapear_erro_download(str(e), plataforma="shopee")

                if status_msg:
                    safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
                else:
                    safe_send_message(message.chat.id, texto_erro)

                if prefix:
                    cleanup_prefix(prefix)
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

        with yt_dlp.YoutubeDL(montar_info_opts(is_instagram=is_instagram, is_shopee=is_shopee)) as ydl:
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

        common_opts = montar_download_opts(prefix, is_instagram=is_instagram, is_shopee=is_shopee)
        formatos = formatos_por_plataforma(
            is_tiktok=is_tiktok,
            is_instagram=is_instagram,
            is_pinterest=is_pinterest,
            is_rednote=is_rednote,
            is_shopee=is_shopee,
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
        plataforma_erro = (
            "instagram" if ("instagram.com" in url.lower() or "instagr.am" in url.lower())
            else "shopee" if ("shopee." in url.lower() or "shp.ee" in url.lower())
            else "geral"
        )
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
        "flask": "running"
    }), 200


# =========================================
# MAIN
# =========================================
if __name__ == "__main__":
    cleanup_download_dir_old_files(max_age_hours=6)

    Thread(
        target=cleanup_download_dir_periodicamente,
        kwargs={"interval_minutes": 60, "max_age_hours": 6},
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
