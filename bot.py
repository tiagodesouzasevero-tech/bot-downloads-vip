import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime
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

# Rota para a Railway confirmar que o bot está ativo (Health Check)
@app.route('/')
def health_check():
    return "Bot Downloader VIP está rodando!", 200

# --- FUNÇÕES DE DADOS (SISTEMA VIP) ---
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
    try:
        return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

# --- COMANDOS ---
@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "✅ **Bot Downloader VIP Online!**\n\nEnvie links do TikTok, Pinterest ou Rednote para baixar agora.")

@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        dados = carregar_dados()
        user = obter_usuario(MY_ID, dados)
        user["vip_ate"] = "Vitalício"
        salvar_dados(dados)
        bot.reply_to(message, "👑 **Olá, Tiago!** Você agora tem acesso Vitalício como administrador.")

# --- DOWNLOADER (Tiktok, Pinterest, Rednote) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    dados = carregar_dados()
    user_id = message.from_user.id
    vip = is_vip(user_id, dados)
    user = obter_usuario(user_id, dados)
    
    # Reset diário de downloads para não-vips
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user["ultima_data"] != hoje:
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje
        salvar_dados(dados)

    if not vip and user["downloads_hoje"] >= 5:
        return bot.reply_to(message, "🚫 **Limite diário atingido!**\n\nUsuários gratuitos podem baixar 5 vídeos por dia. Digite /vip para assinar.")

    msg = bot.reply_to(message, "⏳ **Processando...** aguarde um instante.")
    url = message.text.split()[0]
    file_id = f"dl_{user_id}_{message.message_id}"

    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f'{file_id}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0'}
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption=f"✅ **Vídeo baixado com sucesso!**\n💬 Suporte: {SUPORTE_USER}")
                os.remove(files[0])
                
                if not vip:
                    user["downloads_hoje"] += 1
                    salvar_dados(dados)
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text("❌ Não foi possível encontrar o vídeo nesse link.", message.chat.id, msg.message_id)

    except Exception:
        bot.edit_message_text("❌ **Erro:** Este link é privado ou não suportado no momento.", message.chat.id, msg.message_id)

# --- INICIALIZAÇÃO ---
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start() # Inicia o servidor Flask
    bot.remove_webhook() # Limpa conexões antigas
    print("Bot rodando...")
    bot.infinity_polling(skip_pending=True) # Ignora mensagens enviadas enquanto o bot estava offline
