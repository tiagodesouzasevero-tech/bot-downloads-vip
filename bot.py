import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

MY_ID = "493336271"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- FUNÇÕES DE USUÁRIO (VIP PERSISTENTE) ---
def obter_usuario(user_id):
    uid = str(user_id)
    hoje = datetime.now().strftime('%Y-%m-%d')
    user = usuarios_col.find_one({"_id": uid})
    
    if not user:
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": hoje}
        usuarios_col.insert_one(user)
    
    if user.get("ultima_data") != hoje:
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje
        salvar_usuario(user)
        
    return user

def salvar_usuario(user):
    usuarios_col.replace_one({"_id": user["_id"]}, user)

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try: 
        return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: 
        return False

# --- MENUS ---
def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$499,00", callback_data="buy_499_Vitalicio"))
    return markup

# --- COMANDOS ---
@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        user = obter_usuario(MY_ID)
        user["vip_ate"] = "Vitalício"
        salvar_usuario(user)
        bot.reply_to(message, "👑 **Admin: Plano Vitalício Ativado!**")

@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    nome = message.from_user.first_name
    
    if vip:
        expira = user["vip_ate"]
        texto = f"👋 Olá, {nome}!\n💎 **Status: VIP ({expira})**\n✨ Qualidade: **HD 720p Liberada!**\n\nEnvie o link abaixo 👇"
        markup = None
    else:
        restantes = 5 - user.get("downloads_hoje", 0)
        texto = f"👋 Olá, {nome}!\n📊 **Status: Gratuito**\n📥 Restantes: {restantes}/5 hoje\n\nEnvie o link abaixo ou assine o VIP para HD e downloads ilimitados! 👇"
        markup = menu_planos()

    bot.reply_to(message, texto, reply_markup=markup, parse_mode="Markdown")

# --- WEBHOOK (AUTOMAÇÃO DE PAGAMENTO) ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and data.get("type") == "payment":
        payment_id = data["data"]["id"]
        payment_info = sdk.payment().get(payment_id)
        
        if payment_info["response"]["status"] == "approved":
            user_id = payment_info["response"]["external_reference"]
            plano = payment_info["response"]["description"]
            
            user = obter_usuario(user_id)
            if "Mensal" in plano:
                nova_data = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            elif "Anual" in plano:
                nova_data = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
            else:
                nova_data = "Vitalício"
                
            user["vip_ate"] = nova_data
            salvar_usuario(user)
            bot.send_message(user_id, f"🎉 **PAGAMENTO APROVADO!**\n\nPlano: {plano}\nValidade: {nova_data}\n\nAproveite seus downloads em HD! 🚀")
            
    return "OK", 200

# --- COMPRA ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def callback_buy(call):
    _, valor, plano = call.data.split("_")
    user_id = str(call.from_user.id)
    
    preference_data = {
        "items": [{"title": f"Plano {plano}", "quantity": 1, "unit_price": float(valor), "currency_id": "BRL"}],
        "external_reference": user_id,
        "notification_url": "https://bot-downloads-vip-production.up.railway.app/webhook"
    }
    
    result = sdk.preference().create(preference_data)
    url_pagamento = result["response"]["init_point"]
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 Pagar no PIX/Cartão", url=url_pagamento))
    bot.edit_message_text(f"💳 **Assinatura {plano}**\nValor: R$ {valor}\n\nClique no botão abaixo para concluir:", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")

# --- DOWNLOADER (LIMITADO A 90 SEGUNDOS) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "🚫 **Limite atingido!**\nVolte amanhã ou assine o VIP.", reply_markup=menu_planos())

    msg = bot.reply_to(message, "⏳ **Processando em HD...**")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    
    ydl_opts = {
        'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
        'outtmpl': f'{file_id}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            # TRAVA DE 90 SEGUNDOS (Economia de recursos)
            if info.get('duration', 0) > 90:
                bot.edit_message_text("⚠️ **Vídeo muito longo!** O limite permitido é de **90 segundos**.", message.chat.id, msg.message_id, parse_mode="Markdown")
                for f in glob.glob(f"{file_id}.*"): os.remove(f)
                return

            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption="🛍️ **Vídeo pronto em HD!**\nGerado por @AfiliadoClipPro_bot", parse_mode="Markdown")
                
                for f in files: os.remove(f)
                
                if not vip:
                    user["downloads_hoje"] += 1
                    salvar_usuario(user)
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                raise Exception("Erro no arquivo")

    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text("❌ Erro ao processar. Verifique se o link é público.", message.chat.id, msg.message_id)

# --- INICIALIZAÇÃO ---
@app.route('/')
def health(): return "Online", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
