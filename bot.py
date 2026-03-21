import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime
from flask import Flask
from threading import Thread
from telebot import types

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
DB_FILE = "database.json"
MY_ID = "493336271"
SUPORTE_USER = "@suportebotvip01"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

@app.route('/')
def health(): return "Bot Online", 200

# --- SISTEMA DE DADOS ---
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

# --- MENUS ---
def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$499,00", callback_data="buy_vitalicio"))
    return markup

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'planos'])
def cmd_start(message):
    dados = carregar_dados()
    user_id = message.from_user.id
    user = obter_usuario(user_id, dados)
    vip = is_vip(user_id, dados)
    
    status = "💎 VIP" if vip else "🆓 Gratuito"
    restantes = "∞" if vip else (5 - user["downloads_hoje"])
    
    texto = (
        f"👋 **Bem-vindo ao Downloader!**\n(TikTok, Pinterest e Rednote)\n\n"
        f"📊 **Status:** {status}\n"
        f"💡 **Restantes hoje:** {restantes}/5\n\n"
        f"Escolha um plano para baixar sem limites:"
    )
    bot.reply_to(message, texto, reply_markup=menu_planos(), parse_mode="Markdown")

@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        dados = carregar_dados()
        user = obter_usuario(MY_ID, dados)
        user["vip_ate"] = "Vitalício"
        salvar_dados(dados)
        bot.reply_to(message, "👑 **Acesso Vitalício de Administrador Ativado!**")

# --- DOWNLOADER (TikTok & Pinterest Corrigido) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    dados = carregar_dados()
    user_id = message.from_user.id
    user = obter_usuario(user_id, dados)
    vip = is_vip(user_id, dados)
    
    # Reset diário
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user["ultima_data"] != hoje:
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje
        salvar_dados(dados)

    if not vip and user["downloads_hoje"] >= 5:
        return bot.reply_to(message, "🚫 **Limite de 5 downloads atingido!**\nTorne-se VIP para baixar sem limites.", reply_markup=menu_planos())

    msg = bot.reply_to(message, "⏳ **Processando link...**")
    url = message.text.split()[0]
    file_id = f"dl_{user_id}_{message.message_id}"

    try:
        # Configuração aprimorada para Pinterest
        ydl_opts = {
            'format': 'best',
            'outtmpl': f'{file_id}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption=f"✅ **Vídeo baixado!**\n💬 Suporte: {SUPORTE_USER}")
                os.remove(files[0])
                
                if not vip:
                    user["downloads_hoje"] += 1
                    salvar_dados(dados)
                
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text("❌ Não consegui extrair o vídeo deste link.", message.chat.id, msg.message_id)

    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text("❌ **Erro ao processar este link.** Verifique se o link está correto ou tente outro.", message.chat.id, msg.message_id)

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
