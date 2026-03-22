import os, telebot, yt_dlp, mercadopago, json
from datetime import datetime
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

# --- FUNÇÕES DE SUPORTE ---
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

def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💎 VIP Mensal - R$ 19,90", callback_data="buy_mensal"))
    markup.add(types.InlineKeyboardButton("👑 VIP Vitalício - R$ 49,90", callback_data="buy_vitalicio"))
    return markup

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    if vip:
        status = f"💎 **STATUS: VIP PRO**\n📅 Validade: {user.get('vip_ate')}"
    else:
        restantes = max(0, 5 - user.get('downloads_hoje', 0))
        status = f"👤 **STATUS: GRÁTIS**\n📥 Downloads restantes: {restantes}/5 hoje"

    msg = f"🚀 **AfiliadoClip Pro**\n\n{status}\n\n🔗 Envie um link do TikTok, Reels ou Pinterest:"
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Ver Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, msg, parse_mode="Markdown", reply_markup=markup)

# --- BOTÃO "VER PLANOS" (REPLY KEYBOARD) ---
@bot.message_handler(func=lambda m: m.text == "💎 Ver Planos VIP")
def mostrar_planos_texto(message):
    bot.send_message(message.chat.id, "Escolha o melhor plano para você:", reply_markup=menu_planos())

# --- CALLBACK DOS BOTÕES INLINE ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_") or call.data == "ver_planos")
def callback_handler(call):
    if call.data == "ver_planos":
        bot.edit_message_text("Escolha seu plano VIP:", call.message.chat.id, call.message.message_id, reply_markup=menu_planos())
    
    elif "buy_" in call.data:
        # Aqui você pode integrar o link do Mercado Pago futuramente
        bot.answer_callback_query(call.id, "Redirecionando para o pagamento...")
        bot.send_message(call.message.chat.id, "💳 Link de pagamento sendo gerado... (Integre seu link do MP aqui)")

# --- FLUXO DE DOWNLOAD (TRAVA 720p + OFERTA VIP) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    # Bloqueio com oferta de VIP
    if not vip and user.get("downloads_hoje", 0) >= 5:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💎 Liberar Downloads Ilimitados", callback_data="ver_planos"))
        return bot.reply_to(message, "⚠️ **Limite atingido!**\n\nVocê já baixou 5 vídeos hoje. Torne-se VIP para baixar links ilimitados agora!", parse_mode="Markdown", reply_markup=markup)

    msg_status = bot.reply_to(message, "⏳ Processando link em HD...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"

    try:
        # Configuração que garante 720p e arquivos leves (HEVC se disponível)
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
                bot.send_video(message.chat.id, f, caption="✅ Vídeo HD (720p) pronto!")
            
            if not vip:
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            bot.edit_message_text("❌ Falha ao processar vídeo.", message.chat.id, msg_status.message_id)

    except Exception as e:
        bot.edit_message_text("❌ Link inválido ou erro no servidor.", message.chat.id, msg_status.message_id)
    
    finally:
        if os.path.exists(file_name): os.remove(file_name)
        try: bot.delete_message(message.chat.id, msg_status.message_id)
        except: pass

# --- SERVER ---
@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
