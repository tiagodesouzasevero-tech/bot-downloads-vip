import os
import re
import glob
import uuid
import time
import logging
import telebot
import yt_dlp
import requests

from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient
from requests.exceptions import RequestException, Timeout

# =========================================
# CONFIGURAÇÕES
# =========================================
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority"
CHAVE_PIX_INFINITE = "dc359b2c-d52f-48b5-b022-3c4fb3a8ddb5"

LINK_SUPORTE = "https://t.me/suporteafiliadoclippro"
ADMIN_ID = 493336271

DOWNLOAD_DIR = "downloads_temp"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# =========================================
# LOGS
# =========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("afiliadoclippro")

# =========================================
# DB / BOT / APP
# =========================================
client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

# =========================================
# FUNÇÕES AUXILIARES
# =========================================
def hoje_str():
    return datetime.now().strftime("%Y-%m-%d")


def extrair_primeira_url(texto):
    if not texto:
        return None
    match = re.search(r"(https?://[^\s]+)", texto.strip())
    return match.group(1).strip() if match else None


def cleanup_prefix(prefix):
    try:
        for arq in glob.glob(f"{prefix}*"):
            try:
                os.remove(arq)
            except Exception as e:
                logger.warning(f"[CLEANUP] Falha ao remover {arq}: {e}")
    except Exception as e:
        logger.warning(f"[CLEANUP] Falha geral no prefixo {prefix}: {e}")


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
        logger.warning(f"[SEND_VIDEO] Falhou, tentando como documento. erro={e_video}")

    try:
        with open(arquivo, "rb") as f:
            bot.send_document(chat_id, f, caption="👉 Download concluído! Aqui está seu arquivo 👊")
        return True
    except Exception as e_doc:
        logger.error(f"[SEND_DOCUMENT] Também falhou. erro={e_doc}")
        return False


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


def is_vip(user_id):
    user = obter_usuario(user_id)
    v_ate = user.get("vip_ate")

    if v_ate == "Vitalício":
        return True

    if not v_ate:
        return False

    try:
        return datetime.now() < datetime.strptime(v_ate, "%Y-%m-%d")
    except Exception as e:
        logger.warning(f"[IS_VIP] user_id={user_id} vip_ate={v_ate} erro={e}")
        return False


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
    """
    Baixa SOMENTE Pinterest
    - limite rígido: até 720x1280 / até 30 fps
    """
    url = resolver_link_pinterest(url)

    formatos = [
        "bestvideo[ext=mp4][width<=720][height<=1280][fps<=30]+bestaudio[ext=m4a]/bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[ext=mp4][width<=720][height<=1280][fps<=30]/best[width<=720][height<=1280][fps<=30]",
        "bestvideo[ext=mp4][width<=720][height<=1280]+bestaudio[ext=m4a]/bestvideo[width<=720][height<=1280]+bestaudio/best[ext=mp4][width<=720][height<=1280]/best[width<=720][height<=1280]",
        "best[ext=mp4][width<=720][height<=1280][fps<=30]",
        "best[ext=mp4][width<=720][height<=1280]",
        "best[width<=720][height<=1280][fps<=30]",
        "best[width<=720][height<=1280]"
    ]

    common_opts = {
        "outtmpl": f"{prefix}.%(ext)s",
        "nocheckcertificate": True,
        "quiet": True,
        "noplaylist": True,
        "merge_output_format": "mp4",
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 25,
        "http_headers": {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.pinterest.com/",
            "Origin": "https://www.pinterest.com",
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
        }
    }

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
        "✅ Uso liberado para TikTok, Pinterest e RedNote\n\n"
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
            else (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")
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
        total_users = usuarios_col.count_documents({})
        hoje = hoje_str()

        vips_ativos = usuarios_col.count_documents({
            "$or": [
                {"vip_ate": "Vitalício"},
                {"vip_ate": {"$gte": hoje}}
            ]
        })

        pipeline = [{"$group": {"_id": None, "total": {"$sum": "$downloads_hoje"}}}]
        res_downloads = list(usuarios_col.aggregate(pipeline))
        downloads_totais_hoje = res_downloads[0]["total"] if res_downloads else 0

        texto_admin = (
            "🛠 *PAINEL DE CONTROLE ADMIN*\n\n"
            f"👤 Usuários Totais: `{total_users}`\n"
            f"💎 VIPs Ativos: `{vips_ativos}`\n"
            f"📥 Downloads Hoje: `{downloads_totais_hoje}`\n\n"
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
    vip = is_vip(message.from_user.id)

    status = (
        "💎 *STATUS: VIP PRO*"
        if vip else f"👤 *STATUS: GRÁTIS* ({user.get('downloads_hoje', 0)}/5)"
    )

    texto = (
        "🚀 *AfiliadoClip Pro*\n\n"
        "Baixe vídeos em HD do TikTok, Pinterest e RedNote.\n\n"
        "• Duração máx: 90s\n"
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
        "• RedNote\n\n"
        "O bot faz o download automaticamente.\n\n"
        "✅ Sem marca d'água\n"
        "✅ Qualidade em HD\n"
        "✅ Rápido e prático\n\n"
        "*Plano grátis:*\n"
        "• 5 downloads por dia\n\n"
        "*VIP libera:*\n"
        "• Downloads ilimitados\n"
        "• Prioridade no processamento\n"
        "• Sem limite diário\n\n"
        "*Regras:*\n"
        "• Vídeos de até 90 segundos\n"
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
def pag_manual(call):
    try:
        valor = call.data.split("_", 1)[1]

        msg = (
            f"💎 *Plano selecionado: R$ {valor}*\n\n"
            "Faça o pagamento via Pix usando a chave abaixo:\n"
            f"`{CHAVE_PIX_INFINITE}`\n\n"
            f"Depois envie o comprovante junto com sua ID: `{call.from_user.id}`"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📤 Enviar Comprovante", url=LINK_SUPORTE))

        safe_send_message(
            call.message.chat.id,
            msg,
            parse_mode="Markdown",
            reply_markup=markup
        )
    except Exception as e:
        logger.error(f"[PAY_CALLBACK] erro={e}")
        safe_send_message(call.message.chat.id, "❌ Erro ao abrir os dados de pagamento.")
    finally:
        safe_answer_callback(call.id)


# =========================================
# DOWNLOAD
# =========================================
def detectar_plataforma(url_lower):
    is_pinterest = ("pin.it" in url_lower) or ("pinterest" in url_lower)
    is_tiktok = ("tiktok.com" in url_lower) or ("vm.tiktok.com" in url_lower) or ("vt.tiktok.com" in url_lower)
    is_rednote = ("xiaohongshu.com" in url_lower) or ("xhslink.com" in url_lower) or ("rednote" in url_lower)
    return is_pinterest, is_tiktok, is_rednote


def formatos_capados_gerais():
    # Mantido para o fluxo geral
    return [
        "bestvideo[width<=720][height<=1280][fps<=30]+bestaudio/best[width<=720][height<=1280][fps<=30]",
        "bestvideo[width<=720][height<=1280]+bestaudio/best[width<=720][height<=1280]",
        "best[width<=720][height<=1280][fps<=30]",
        "best[width<=720][height<=1280]"
    ]


@bot.message_handler(func=lambda message: message.text and "http" in message.text.lower())
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip_status = is_vip(message.from_user.id)
    prefix = None

    if not vip_status and user.get("downloads_hoje", 0) >= 5:
        safe_reply_to(
            message,
            "⚠️ *Limite diário atingido (5/5)!*\n"
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
        is_pinterest, is_tiktok, is_rednote = detectar_plataforma(url_lower)

        if not (is_pinterest or is_tiktok or is_rednote):
            if status_msg:
                safe_edit_message(
                    message.chat.id,
                    status_msg.message_id,
                    "❌ Link não reconhecido. Envie um link do TikTok, Pinterest ou RedNote."
                )
            else:
                safe_send_message(
                    message.chat.id,
                    "❌ Link não reconhecido. Envie um link do TikTok, Pinterest ou RedNote."
                )
            return

        # =========================================
        # PINTEREST: fluxo separado
        # =========================================
        if is_pinterest:
            prefix = os.path.join(DOWNLOAD_DIR, f"v_{message.from_user.id}_{uuid.uuid4().hex}")

            try:
                with yt_dlp.YoutubeDL({
                    "quiet": True,
                    "nocheckcertificate": True,
                    "noplaylist": True,
                    "socket_timeout": 20,
                    "retries": 2,
                    "http_headers": {
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://www.pinterest.com/",
                        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
                    }
                }) as ydl:
                    info = ydl.extract_info(resolver_link_pinterest(url), download=False)

                duracao = info.get("duration")
                if duracao and duracao > 90:
                    if status_msg:
                        safe_edit_message(
                            message.chat.id,
                            status_msg.message_id,
                            "⚠️ Vídeo muito longo. O limite é de 90 segundos."
                        )
                    else:
                        safe_send_message(message.chat.id, "⚠️ Vídeo muito longo. O limite é de 90 segundos.")
                    return

            except Exception as e:
                logger.warning(f"[PINTEREST_INFO] Falha ao ler metadados: {e}")
                # continua para tentativa de download

            try:
                arquivo_final = baixar_pinterest_capado(url, prefix)

                enviado = enviar_arquivo_com_fallback(message.chat.id, arquivo_final)
                if not enviado:
                    raise Exception("Falha ao enviar arquivo ao Telegram")

                if not vip_status:
                    usuarios_col.update_one(
                        {"_id": user["_id"]},
                        {"$inc": {"downloads_hoje": 1}}
                    )

                    novo_count = user.get("downloads_hoje", 0) + 1
                    safe_send_message(message.chat.id, f"📊 Uso diário: {novo_count}/5")

                    if novo_count >= 5:
                        safe_send_message(
                            message.chat.id,
                            "⚠️ *Você atingiu seu limite diário (5/5)!*\n"
                            "Para continuar baixando de forma ilimitada agora mesmo, libere um plano VIP: 👇",
                            parse_mode="Markdown"
                        )
                        mostrar_planos_chat(message.chat.id, message.from_user.id)

                if status_msg:
                    safe_delete_message(message.chat.id, status_msg.message_id)

                return

            except Exception as e:
                logger.error(f"[ERRO_PINTEREST] user_id={message.from_user.id} url={url} erro={e}")

                texto_erro = "❌ Erro no link ou formato do Pinterest."
                erro_txt = str(e).lower()

                if "unsupported url" in erro_txt:
                    texto_erro = "❌ Esse link do Pinterest não é suportado no momento."
                elif "timed out" in erro_txt:
                    texto_erro = "❌ O Pinterest demorou para responder. Tente novamente."
                elif "403" in erro_txt or "404" in erro_txt or "json metadata" in erro_txt:
                    texto_erro = "❌ O Pinterest bloqueou esse link no momento. Tente outro pin ou tente novamente depois."
                elif "720x1280" in erro_txt or "30fps" in erro_txt:
                    texto_erro = "❌ Não encontrei uma versão do pin compatível com o limite máximo de 720x1280 em até 30 fps."

                if status_msg:
                    safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
                else:
                    safe_send_message(message.chat.id, texto_erro)

                if prefix:
                    cleanup_prefix(prefix)
                return

        # =========================================
        # TIKTOK / REDNOTE / FLUXO GERAL
        # Mantido no fluxo principal
        # =========================================
        prefix = os.path.join(DOWNLOAD_DIR, f"v_{message.from_user.id}_{uuid.uuid4().hex}")

        info_opts = {
            "quiet": True,
            "nocheckcertificate": True,
            "noplaylist": True,
            "socket_timeout": 20,
            "retries": 2
        }

        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        duracao = info.get("duration")
        if duracao and duracao > 90:
            if status_msg:
                safe_edit_message(
                    message.chat.id,
                    status_msg.message_id,
                    "⚠️ Vídeo muito longo. O limite é de 90 segundos."
                )
            else:
                safe_send_message(message.chat.id, "⚠️ Vídeo muito longo. O limite é de 90 segundos.")
            return

        common_opts = {
            "outtmpl": f"{prefix}.%(ext)s",
            "nocheckcertificate": True,
            "quiet": True,
            "noplaylist": True,
            "merge_output_format": "mp4",
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 25,
            "http_headers": {
                "User-Agent": "Mozilla/5.0",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"
            }
        }

        formatos = formatos_capados_gerais()
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
                logger.warning(f"[DOWNLOAD_TENTATIVA] formato={fmt} url={url} erro={e}")

        if not baixou:
            raise Exception(ultimo_erro or "Falha ao baixar dentro do limite 720x1280 30fps")

        arquivo_final = encontrar_arquivo_baixado(prefix)
        if not arquivo_final or not os.path.exists(arquivo_final):
            raise Exception("Arquivo final não encontrado após o download")

        enviado = enviar_arquivo_com_fallback(message.chat.id, arquivo_final)
        if not enviado:
            raise Exception("Falha ao enviar arquivo ao Telegram")

        if not vip_status:
            usuarios_col.update_one(
                {"_id": user["_id"]},
                {"$inc": {"downloads_hoje": 1}}
            )

            novo_count = user.get("downloads_hoje", 0) + 1
            safe_send_message(message.chat.id, f"📊 Uso diário: {novo_count}/5")

            if novo_count >= 5:
                safe_send_message(
                    message.chat.id,
                    "⚠️ *Você atingiu seu limite diário (5/5)!*\n"
                    "Para continuar baixando de forma ilimitada agora mesmo, libere um plano VIP: 👇",
                    parse_mode="Markdown"
                )
                mostrar_planos_chat(message.chat.id, message.from_user.id)

        if status_msg:
            safe_delete_message(message.chat.id, status_msg.message_id)

    except Exception as e:
        logger.error(f"[ERRO_DOWNLOAD] user_id={message.from_user.id} url={url} erro={e}")

        texto_erro = "❌ Erro no link ou formato."
        erro_txt = str(e).lower()

        if "unsupported url" in erro_txt:
            texto_erro = "❌ Esse link não é suportado no momento."
        elif "timed out" in erro_txt:
            texto_erro = "❌ O servidor demorou para responder. Tente novamente."
        elif "video unavailable" in erro_txt:
            texto_erro = "❌ Vídeo indisponível ou privado."
        elif "720x1280" in erro_txt or "30fps" in erro_txt:
            texto_erro = "❌ Não encontrei uma versão compatível com o limite máximo de 720x1280 em até 30 fps."

        if status_msg:
            safe_edit_message(message.chat.id, status_msg.message_id, texto_erro)
        else:
            safe_send_message(message.chat.id, texto_erro)

    finally:
        if prefix:
            cleanup_prefix(prefix)


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
