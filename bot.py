import os, telebot, yt_dlp, mercadopago, json
from datetime import datetime
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES CRÍTICAS ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

# --- FUNÇÕES DE USUÁRIO ---
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
    except:
        return False

# --- INTERFACE ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 VIP PRO" if vip else f"👤 Grátis: {max(0, 5 - user.get('downloads_hoje', 0))}/5 hoje"
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, f"🚀 <b>AfiliadoClip Pro</b>\n\n{status}\n\n🔗 Envie um link:", parse_mode="HTML", reply_markup=markup)

# --- FLUXO DE DOWNLOAD COM TETO HD ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ Limite diário atingido!")

    msg_status = bot.reply_to(message, "⏳ Baixando em HD 720p...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"

    try:
        # A MÁGICA ESTÁ AQUI: 
        # 'best[height<=1280][width<=1280]' garante que o vídeo não passe de 720p 
        # tanto em pé (vertical) quanto deitado (horizontal).
        ydl_opts = {
            'format': 'best[height<=1280][width<=1280][ext=mp4]/best[height<=1280]/best',
            'outtmpl': file_name,
            'nocheckcertificate': True,
            'quiet': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(file_name):
            with open(file_name, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Vídeo 720p pronto!")
            
            if not vip:
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            bot.edit_message_text("❌ Erro ao baixar arquivo.", message.chat.id, msg_status.message_id)

    except Exception as e:
        print(f"ERRO: {e}")
        bot.edit_message_text("❌ Link não suportado ou erro no download.", message.chat.id, msg_status.message_id)
    
    finally:
        if os.path.exists(file_name):
            os.remove(file_name)
        try:
            bot.delete_message(message.chat.id, msg_status.message_id)
        except:
            pass

# --- WEBHOOK ---
@app.route('/')
def health(): return "Bot Online", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
