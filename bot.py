import os, telebot, yt_dlp, json
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority"

CHAVE_PIX_INFINITE = "dc359b2c-d52f-48b5-b022-3c4fb3a8ddb5" 
LINK_SUPORTE = "https://t.me/suporteafiliadoclippro"
ADMIN_ID = 493336271

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

def obter_usuario(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    if not user:
        hoje = datetime.now().strftime('%Y-%m-%d')
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": hoje}
        usuarios_col.insert_one(user)
    return user

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try:
        return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 **STATUS: VIP PRO**" if vip else f"👤 **STATUS: GRÁTIS** ({user.get('downloads_hoje', 0)}/5)"
    texto_welcome = (
        f"🚀 **Bem-vindo ao AfiliadoClip Pro!**\n\n"
        f"Baixe vídeos do:\n🔹 **TikTok**\n🔹 **Pinterest**\n🔹 **RedNote**\n\n"
        f"⚡️ Limite: 90s por vídeo.\n{status}\n\n🔗 Envie o link!"
    )
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, texto_welcome, parse_mode="Markdown", reply_markup=markup)

# --- DOWNLOADER COM FALLBACK PARA PINTEREST ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    if not is_vip(message.from_user.id) and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ Limite atingido! Adquira o VIP.")

    status_msg = bot.reply_to(message, "⏳ Analisando...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"
    deve_apagar_status = True 

    # Configuração Padrão (HD)
    ydl_opts = {
        'format': 'best[height<=1280][ext=mp4]/best[height<=1280]/best',
        'outtmpl': file_name,
        'nocheckcertificate': True, 
        'quiet': True,
        'noplaylist': True
    }

    try:
        with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('duration', 0) > 90:
                bot.edit_message_text("⚠️ Vídeo muito longo (limite 90s).", message.chat.id, status_msg.message_id)
                return

        bot.edit_message_text("📥 Baixando...", message.chat.id, status_msg.message_id)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            # FALLBACK: Se falhar o formato HD (comum no Pinterest), tenta o melhor disponível
            bot.edit_message_text("📥 Otimizando formato...", message.chat.id, status_msg.message_id)
            ydl_opts['format'] = 'best'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

        if os.path.exists(file_name):
            with open(file_name, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Enviado com AfiliadoClip Pro!")
            if not is_vip(message.from_user.id):
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            raise Exception

    except Exception:
        bot.edit_message_text("❌ Erro no link ou formato indisponível.", message.chat.id, status_msg.message_id)
        deve_apagar_status = False
    finally:
        if os.path.exists(file_name): os.remove(file_name)
        if deve_apagar_status:
            try: bot.delete_message(message.chat.id, status_msg.message_id)
            except: pass

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
