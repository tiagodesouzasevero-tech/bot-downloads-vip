import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime
from telebot import types
from flask import Flask
from threading import Thread

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHw2zcugsOXPpOJaXsz1ZVA30T1VypiMlQ"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
DB_FILE = "database.json"
MY_ID = "493336271"
SUPORTE_USER = "@suportebotvip01"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
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

# --- DOWNLOADER (Tiktok, Pinterest, Rednote) ---
@bot.message_handler(func=lambda message: "http" in message.text and not message.text.startswith('/'))
def handle_dl(message):
    if message.from_user.is_bot: return

    dados = carregar_dados()
    user_id = message.from_user.id
    vip = is_vip(user_id, dados)
    user = obter_usuario(user_id, dados)
    
    if not vip and user["downloads_hoje"] >= 5:
        return bot.send_message(message.chat.id, "🚫 Limite diário de 5 downloads atingido!")

    msg = bot.reply_to(message, "⏳ Aguarde, processando link...")
    url = message.text.split()[0]
    file_id = f"file_{user_id}_{message.message_id}"

    try:
        ydl_opts = {
            'format': 'best', # Busca o melhor formato disponível sem frescura
            'outtmpl': f'{file_id}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption=f"✅ Suporte: {SUPORTE_USER}")
                os.remove(files[0])
                
                if not vip:
                    user["downloads_hoje"] += 1
                    salvar_dados(dados)
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text("❌ Não encontrei vídeo nesse link.", message.chat.id, msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"❌ Erro ao baixar. O link pode ser privado ou instável.", message.chat.id, msg.message_id)

@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        dados = carregar_dados()
        user = obter_usuario(MY_ID, dados)
        user["vip_ate"] = "Vitalício"
        salvar_dados(dados)
        bot.reply_to(message, "👑 Sucesso! Você agora é Vitalício.")

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=20, skip_pending=True) # skip_pending limpa os logs travados
