import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime
from telebot import types
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
DB_FILE = "database.json"
MY_ID = "493336271"
SUPORTE_USER = "@suportebotvip01"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

# --- FUNÇÕES DE DADOS ---
def carregar_dados():
    if not os.path.exists(DB_FILE): return {"usuarios": {}}
    try:
        with open(DB_FILE, "r") as f: return json.load(f)
    except: return {"usuarios": {}}

def salvar_dados(dados):
    with open(DB_FILE, "w") as f: json.dump(dados, f, indent=4)

def obter_usuario(user_id, dados):
    uid = str(user_id)
    if uid not in dados["usuarios"]:
        dados["usuarios"][uid] = {"vip_ate": None, "downloads_hoje": 0, "ultima_data": datetime.now().strftime('%Y-%m-%d')}
    return dados["usuarios"][uid]

def is_vip(user_id, dados):
    user = obter_usuario(user_id, dados)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try: return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

# --- COMANDO START ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "✅ Bot Online! Envie um link do TikTok, Pinterest ou Rednote.")

# --- DOWNLOADER ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    dados = carregar_dados()
    user = obter_usuario(message.from_user.id, dados)
    
    msg = bot.reply_to(message, "⏳ Processando link...")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"

    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f'{file_id}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'http_headers': {'User-Agent': 'Mozilla/5.0'}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption=f"✅ Suporte: {SUPORTE_USER}")
                os.remove(files[0])
                bot.delete_message(message.chat.id, msg.message_id)
    except Exception:
        bot.edit_message_text("❌ Erro no link ou instabilidade.", message.chat.id, msg.message_id)

# --- INICIALIZAÇÃO ---
if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
