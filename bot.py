import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
# URI com correções para Railway (SSL e Timeout)
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

MY_ID = "493336271"
SUPORTE_USER = "@suportebotvip01"

# Conexão Robusta com o Banco de Dados
try:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client.get_default_database()
    usuarios_col = db["usuarios"]
    # Força um teste de conexão
    client.admin.command('ping')
    print("Conexão com MongoDB estabelecida com sucesso!")
except Exception as e:
    print(f"Erro na conexão com Banco de Dados: {e}")

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- FUNÇÕES DE BANCO DE DADOS ---
def obter_usuario(user_id):
    uid = str(user_id)
    try:
        user = usuarios_col.find_one({"_id": uid})
        if not user:
            user = {
                "_id": uid, 
                "vip_ate": None, 
                "downloads_hoje": 0, 
                "ultima_data": datetime.now().strftime('%Y-%m-%d')
            }
            usuarios_col.insert_one(user)
        return user
    except Exception as e:
        print(f"Erro ao buscar usuário: {e}")
        return {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": ""}

def salvar_usuario(user):
    try:
        usuarios_col.replace_one({"_id": user["_id"]}, user)
    except Exception as e:
        print(f"Erro ao salvar: {e}")

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try:
        return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

# --- MENUS ---
def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$499,00", callback_data="buy_499_Vitalicio"))
    return markup

# --- WEBHOOK MERCADO PAGO ---
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.args.get("type") == "payment":
        payment_id = request.args.get("data.id")
        payment_info = sdk.payment().get(payment_id)
        if payment_info["response"]["status"] == "approved":
            ref = payment_info["response"]["external_reference"]
            user_id, plano = ref.split(":")
            user = obter_usuario(user_id)
            hoje = datetime.now()
            if plano == "Mensal": nova_data = (hoje + timedelta(days=30)).strftime('%Y-%m-%d')
            elif plano == "Anual": nova_data = (hoje + timedelta(days=365)).strftime('%Y-%m-%d')
            else: nova_data = "Vitalício"
            user["vip_ate"] = nova_data
            salvar_usuario(user)
            bot.send_message(user_id, f"🌟 **PAGAMENTO CONFIRMADO!**\n\nSeu plano **{plano}** foi ativado!")
    return "OK", 200

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    if vip:
        status = "💎 Vitalício" if user["vip_ate"] == "Vitalício" else f"⏳ Expira em: {user['vip_ate']}"
        bot.reply_to(message, f"👋 **Olá, {message.from_user.first_name}!**\n👑 VIP Ativo\n✅ {status}", parse_mode="Markdown")
    else:
        restantes = 5 - user.get("downloads_hoje", 0)
        bot.reply_to(message, f"📊 Status: Gratuito\n💡 Downloads: {restantes}/5", reply_markup=menu_planos(), parse_mode="Markdown")

@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        user = obter_usuario(MY_ID)
        user["vip_ate"] = "Vitalício"
        salvar_usuario(user)
        bot.reply_to(message, "👑 **Admin Vitalício Ativado!**")

# --- DOWNLOADER ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "🚫 Limite diário atingido!", reply_markup=menu_planos())

    msg = bot.reply_to(message, "⏳ **Processando vídeo...**")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    
    try:
        with yt_dlp.YoutubeDL({'format': 'best', 'outtmpl': f'{file_id}.%(ext)s', 'quiet': True}) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption="✅ Concluído!")
                os.remove(files[0])
                if not vip:
                    user["downloads_hoje"] = user.get("downloads_hoje", 0) + 1
                    salvar_usuario(user)
                bot.delete_message(message.chat.id, msg.message_id)
    except:
        bot.edit_message_text("❌ Erro no download.", message.chat.id, msg.message_id)

# --- INICIALIZAÇÃO ---
@app.route('/')
def health(): return "Bot Online", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
