import os, telebot, yt_dlp, mercadopago, json, subprocess
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient
import static_ffmpeg  # Biblioteca para FFmpeg leve

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"
ID_ADM = 493336271 

# Inicializa o FFmpeg no ambiente da Railway
static_ffmpeg.add_paths()

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

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

# --- MOTOR DE VÍDEO OTIMIZADO ---
def process_video_optimized(input_path, output_path):
    # Scale: Teto de 720p mantendo proporção
    # libx264 + ultrafast: Menor uso de CPU possível
    # ac 1: Áudio Mono para reduzir peso do arquivo
    cmd = [
        'ffmpeg', '-y', '-i', input_path, 
        '-vf', "scale='if(gt(ih,720),-2,iw)':'min(ih,720)',fps=min(30,fps)", 
        '-c:v', 'libx264', '-crf', '32', '-preset', 'ultrafast', 
        '-ac', '1', '-ar', '22050', '-b:a', '64k', 
        '-movflags', '+faststart',
        output_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=100)
        return result.returncode == 0
    except Exception as e:
        print(f"Erro FFmpeg: {e}")
        return False

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 VIP PRO" if vip else f"👤 Grátis: {max(0, 5 - user.get('downloads_hoje', 0))}/5 hoje"
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    
    bot.send_message(message.chat.id, f"🚀 <b>AfiliadoClip Pro</b>\n\n{status}\n\n🔗 Envie um link do TikTok, Pinterest ou RedNote:", parse_mode="HTML", reply_markup=markup)

# --- DOWNLOAD E CONVERSÃO ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ Limite diário atingido! Assine o VIP para downloads ilimitados.")

    msg_status = bot.reply_to(message, "⏳ Baixando...")
    url = message.text.split()[0]
    raw_name = f"r_{message.from_user.id}.mp4"
    out_name = f"v_{message.from_user.id}.mp4"

    try:
        # 1. Download via yt-dlp
        ydl_opts = {'format': 'bestvideo+bestaudio/best', 'outtmpl': raw_name, 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get('duration', 0) > 95:
                os.remove(raw_name) if os.path.exists(raw_name) else None
                return bot.edit_message_text("❌ Vídeo muito longo (Máx 90s).", message.chat.id, msg_status.message_id)

        # 2. Processamento via FFmpeg
        bot.edit_message_text("🎬 Otimizando formato...", message.chat.id, msg_status.message_id)
        if process_video_optimized(raw_name, out_name):
            with open(out_name, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Vídeo pronto para Afiliados!")
            
            if not vip:
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            bot.edit_message_text("❌ Erro ao converter vídeo.", message.chat.id, msg_status.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Falha no link. Verifique e tente novamente.", message.chat.id, msg_status.message_id)
    
    finally:
        # Limpeza
        for f in [raw_name, out_name]:
            if os.path.exists(f): os.remove(f)
        try: bot.delete_message(message.chat.id, msg_status.message_id)
        except: pass

# --- SERVIDOR FLASK (WEBHOOK) ---
@app.route('/')
def health(): return "Bot Online", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
