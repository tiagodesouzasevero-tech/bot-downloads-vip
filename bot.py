import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES MANTIDAS ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- FUNÇÕES DE USUÁRIO E VIP (MANTIDAS) ---
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

# --- COMANDOS E PIX (MANTIDOS) ---
@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = user.get("vip_ate", "Grátis") if vip else "Grátis"
    bot.reply_to(message, f"🚀 <b>ViralClip Pro</b>\n\n💎 Status: <b>{status}</b>\n\nEnvie o link do vídeo 👇", 
                 reply_markup=None if vip else types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("💳 Planos VIP", callback_data="buy_menu")), parse_mode="HTML")

# --- DOWNLOADER v1.0.7 (FIX DEFINITIVO TIKTOK/PINTEREST) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    # Controle de limites (Mantido)
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": user["_id"]}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ Limite diário atingido!")

    msg_p = bot.reply_to(message, "⏳ Processando vídeo em HD (720p/30fps)...")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    
    # ESTRATÉGIA: Forçar re-codificação total para garantir os parâmetros exatos
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': f'{file_id}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'postprocessor_args': [
            '-vf', 'scale=-2:720,fps=30', # Garante altura 720 e 30 frames por segundo
            '-c:v', 'libx264',             # Codec compatível
            '-crf', '20',                 # Qualidade alta (HD real)
            '-preset', 'veryfast'         # Rapidez no processamento
        ],
        'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duracao = info.get('duration', 0)
            
            # Trava de 90s: Mantida a lógica flexível para RedNote
            if duracao and duracao > 90:
                return bot.edit_message_text("❌ Vídeo acima de 90 segundos.", message.chat.id, msg_p.message_id)

            ydl.download([url])
            
            # Busca o arquivo final (garantindo que seja o .mp4 processado)
            files = glob.glob(f"{file_id}.mp4") or glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption="Vídeo pronto em 720p 30fps HD 🤝")
                for f in files: os.remove(f)
                if not vip:
                    usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
                bot.delete_message(message.chat.id, msg_p.message_id)
            else:
                raise Exception("Arquivo não encontrado")
                
    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text("❌ Erro ao baixar. Verifique o link e se o vídeo tem menos de 90s.", message.chat.id, msg_p.message_id)

# Servidor Flask e Polling (Mantidos)
@app.route('/')
def health(): return "Bot Online", 200
def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
