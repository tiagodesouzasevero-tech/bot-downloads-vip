import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

MY_ID = "493336271"

try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client.get_default_database()
    usuarios_col = db["usuarios"]
except Exception as e:
    print(f"Erro MongoDB: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- FUNÇÕES VIP ---
def obter_usuario(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    if not user:
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": datetime.now().strftime('%Y-%m-%d')}
        usuarios_col.insert_one(user)
    return user

def salvar_usuario(user):
    usuarios_col.replace_one({"_id": user["_id"]}, user)

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try: return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$499,00", callback_data="buy_499_Vitalicio"))
    return markup

# --- COMANDOS ---
@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        user = obter_usuario(MY_ID)
        user["vip_ate"] = "Vitalício"
        salvar_usuario(user)
        bot.reply_to(message, "👑 **AfiliadoClip Pro: Admin Ativado!**")

@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    nome = message.from_user.first_name
    plataformas = "📌 **Pinterest, TikTok e RedNote.**"

    if vip:
        expira = "Vitalício" if user["vip_ate"] == "Vitalício" else f"Expira em: {user['vip_ate']}"
        texto = (
            f"👋 **Olá, {nome}! Bem-vindo ao AfiliadoClip Pro!**\n\n"
            f"💎 **Plano VIP Ativo**\n✅ {expira}\n\n"
            f"🚀 **Acesso liberado para:**\n{plataformas}\n\n"
            "• Qualidade: **HD (720p) Otimizado**\n"
            "• Limite: Vídeos de até **90 segundos**\n\n"
            "Cole o link do seu achadinho abaixo! 👇"
        )
    else:
        restantes = 5 - user.get("downloads_hoje", 0)
        texto = (
            f"👋 **Olá, {nome}! Bem-vindo ao AfiliadoClip Pro!**\n\n"
            "🎯 **O bot nº 1 para Afiliados de Achadinhos.**\n"
            f"Baixe vídeos do {plataformas}\n\n"
            "⚙️ **Especificações:**\n"
            "• Vídeos em **HD (720p)**\n"
            "• Duração máxima de **90 segundos**\n\n"
            f"📊 **Status:** Gratuito | **Restantes:** {restantes}/5 hoje\n\n"
            "Cole o link do vídeo abaixo! 👇"
        )
    bot.reply_to(message, texto, reply_markup=None if vip else menu_planos(), parse_mode="Markdown")

# --- DOWNLOADER (TRAVA 720P + FFMPEG) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "🚫 Limite diário atingido!", reply_markup=menu_planos())

    msg = bot.reply_to(message, "✅ Processando em HD... Aguarde.")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    
    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'nocheckcertificate': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('duration', 0) > 90:
                bot.delete_message(message.chat.id, msg.message_id)
                return bot.reply_to(message, "⚠️ Limite: 90 segundos.")

        # REGRA PARA HD (720p): Não permite baixar em 1080p
        ydl_opts = {
            'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]',
            'outtmpl': f'{file_id}.%(ext)s',
            'quiet': True,
            'nocheckcertificate': True,
            'merge_output_format': 'mp4',
            'geo_bypass': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption="🛍️ **Vídeo pronto! Gerado por AfiliadoClip Pro**")
                os.remove(files[0])
                if not vip:
                    user["downloads_hoje"] = user.get("downloads_hoje", 0) + 1
                    salvar_usuario(user)
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                raise Exception("Erro no download")
    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text("❌ Erro. Use links públicos do Pinterest, TikTok ou RedNote (Até 90s).", message.chat.id, msg.message_id)

# --- SERVIDOR ---
@app.route('/')
def health(): return "Online", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
