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


TOKEN_TELEGRAM = get_env_required("TOKEN_TELEGRAM")
MONGO_URI = get_env_required("MONGO_URI")
MONGO_DB_NAME = get_env_required("MONGO_DB_NAME")
LINK_SUPORTE = get_env_required("LINK_SUPORTE")
ADMIN_ID = int(get_env_required("ADMIN_ID"))

# InfinitePay
INFINITEPAY_HANDLE = get_env_required("INFINITEPAY_HANDLE")
APP_BASE_URL = get_env_required("APP_BASE_URL").rstrip("/")
INFINITEPAY_CHECKOUT_URL = "https://api.infinitepay.io/invoices/public/checkout/links"

DOWNLOAD_DIR = os.environ.get("DOWNLOAD_DIR", "downloads_temp")
TZ = ZoneInfo("America/Sao_Paulo")

FREE_DAILY_LIMIT = 5
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

PLANOS = {
    "10.00": {
        "nome": "VIP Mensal",
        "preco_centavos": 1000,
        "dias": 30,
        "descricao": "VIP Mensal 30 dias"
    },
    "69.90": {
        "nome": "VIP Anual",
        "preco_centavos": 6990,
        "dias": 365,
        "descricao": "VIP Anual 365 dias"
    },
    "197.00": {
        "nome": "VIP Vitalício",
        "preco_centavos": 19700,
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
    return f"{APP_BASE_URL}/webhook/infinitepay"


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
    if INSTAGRAM_COOKIES_TEXT:
        cookie_path = os.path.join(DOWNLOAD_DIR, "instagram_cookies.txt")
        with open(cookie_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(INSTAGRAM_COOKIES_TEXT)
        return cookie_path
    return None


def montar_info_opts(is_instagram=False, is_pinterest=False):
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

    return opts


def montar_download_opts(prefix, is_instagram=False, is_pinterest=False):
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

    logger.info(f"[CHECKOUT_CREATE] order_nsu={order_nsu} payload={payload}")

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
        types.InlineKeyboardButton("💳 VIP Anual - R$ 69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 VIP Vitalício - R$ 197,00", callback_data="pay_197.00")
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


@bot.message_handler(commands=["avisogeral"])
def aviso_geral(message):
    if message.from_user.id != ADMIN_ID:
        return

    try:
        msg_texto = message.text.replace("/avisogeral", "", 1).strip()
        if not msg_texto:
            return safe_reply_to(message, "❌ Digite a mensagem após o comando.")

        usuarios = usuarios_col.find({}, {"_id": 1})
        cont = 0

        for u in usuarios:
            try:
                safe_send_message(int(u["_id"]), msg_texto, parse_mode="Markdown")
                cont += 1
                time.sleep(0.05)
            except Exception:
                pass

        safe_reply_to(message, f"📢 Aviso enviado para {cont} usuários!")
    except Exception as e:
        logger.error(f"[AVISOGERAL] erro={e}")
        safe_reply_to(message, "❌ Erro ao enviar aviso geral.")


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

        texto_admin = (
            "🛠 *PAINEL DE CONTROLE ADMIN*\n\n"
            f"👤 Usuários Totais: `{total_users}`\n"
            f"💎 VIPs Ativos: `{vips_ativos}`\n"
            f"📥 Downloads Hoje: `{downloads_totais_hoje}`\n"
            f"🧾 Pedidos Pendentes: `{pedidos_pendentes}`\n"
            f"✅ Pedidos Pagos: `{pedidos_pagos}`\n\n"
            "🚀 *COMANDOS DISPONÍVEIS:*\n"
            "• `/darvip [ID] [Dias]`\n"
            "• `/zerar [ID]`\n"
            "• `/avisogeral [Mensagem]`"
        )

        safe_send_message(message.chat.id, texto_admin, parse_mode="Markdown")
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
        payload = request.get_json(silent=True) or {}
        logger.info(f"[WEBHOOK_INFINITEPAY] payload={payload}")

        order_nsu = payload.get("order_nsu")
        transaction_nsu = payload.get("transaction_nsu")
        amount = payload.get("amount")
        receipt_url = payload.get("receipt_url")
        capture_method = payload.get("capture_method")

        if not order_nsu:
            return jsonify({
                "success": False,
                "message": "order_nsu ausente"
            }), 400

        pedido = pedidos_col.find_one({"order_nsu": order_nsu})
        if not pedido:
            return jsonify({
                "success": False,
                "message": "Pedido não encontrado"
            }), 400

        if pedido.get("status") == "paid":
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
            logger.warning(
                f"[WEBHOOK_VALOR_DIVERGENTE] order_nsu={order_nsu} esperado={valor_esperado} recebido={valor_recebido}"
            )
            return jsonify({
                "success": False,
                "message": "Valor divergente"
            }), 400

        plano = PLANOS.get(pedido.get("plano_key"))
        if not plano:
            return jsonify({
                "success": False,
                "message": "Plano inválido"
            }), 400

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
        return jsonify({
            "success": False,
            "message": "Erro interno no webhook"
        }), 400


# =========================================
# HEALTHCHECK
# =========================================
@app.route("/")
def health():
    return "ONLINE", 200


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
