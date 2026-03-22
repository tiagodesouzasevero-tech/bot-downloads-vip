import os, telebot, yt_dlp, mercadopago, json, glob, uuid
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES (MANTIDAS) ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

MY_ID = "493336271"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
transacoes_col = db["transacoes"]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- GESTÃO DE USUÁRIOS ---
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
        usuarios_col.replace_one({"_id": uid}, user)
    return user

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try: return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

def liberar_vip_logic(user_id, plano):
    uid = str(user_id)
    if "Mensal" in plano: nova_data = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    elif "Anual" in plano: nova_data = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
    else: nova_data = "Vitalício"
    
    usuarios_col.update_one({"_id": uid}, {"$set": {"vip_ate": nova_data}})
    
    confirmacao = (
        "✅ <b>Pagamento confirmado!</b>\n"
        "Agora você é VIP 🎉\n\n"
        "🚀 <b>Benefícios liberados:</b>\n"
        "• Downloads ILIMITADOS\n"
        "• Sem restrições\n\n"
        "Pode enviar o link do vídeo e aproveitar 👇"
    )
    bot.send_message(user_id, confirmacao, parse_mode="HTML")

# --- MENUS ---
def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$190,00 🔥", callback_data="buy_190_Vitalicio"))
    return markup

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    nome = message.from_user.first_name
    
    if vip:
        expira = user["vip_ate"]
        texto = (
            f"🚀 <b>Bem-vindo ao ViralClip Pro</b>\n\n"
            f"👋 Olá, {nome}!\n💎 <b>Status: VIP ({expira})</b>\n"
            f"Pode enviar o link do vídeo e aproveitar 👇"
        )
        markup = None
    else:
        texto = (
            f"🚀 <b>Bem-vindo ao ViralClip Pro</b>\n\n"
            f"🎁 <b>Plano GRATUITO:</b>\n• 5 downloads por dia\n\n"
            f"💰 <b>Planos VIP:</b>\n• Mensal\n• Anual\n• Vitalício 🔥\n\n"
            f"👇 Escolha uma opção abaixo:"
        )
        markup = menu_planos()
    bot.reply_to(message, texto, reply_markup=markup, parse_mode="HTML")

# --- SISTEMA PIX CORRIGIDO (v1.3.1) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def callback_pix_gerador(call):
    try:
        _, valor, plano = call.data.split("_")
        user_id = str(call.from_user.id)
        
        payment_data = {
            "transaction_amount": float(valor),
            "description": f"Plano {plano} - ViralClip",
            "payment_method_id": "pix",
            "external_reference": user_id,
            "payer": {
                "email": f"u{user_id}@telegram.com",
                "first_name": "Usuario",
                "last_name": "Telegram"
            }
        }
        
        payment_response = sdk.payment().create(payment_data)
        
        if "response" not in payment_response or "point_of_interaction" not in payment_response["response"]:
            return bot.answer_callback_query(call.id, "❌ Erro na API. Tente novamente.")

        pix_code = payment_response["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
        payment_id = payment_response["response"]["id"]

        transacoes_col.update_one(
            {"user_id": user_id},
            {"$set": {"payment_id": payment_id, "status": "pending", "plano": plano, "data": datetime.now()}},
            upsert=True
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✅ Já paguei / Verificar", callback_data=f"check_{payment_id}"))
        
        texto_pix = (
            f"💰 <b>Pagamento via Pix</b>\n\n"
            f"<b>Plano:</b> {plano}\n"
            f"<b>Valor:</b> R$ {valor}\n\n"
            f"📋 <b>Código Pix (Copia e Cola):</b>\n"
            f"<code>{pix_code}</code>\n\n"
            f"<i>Após pagar, clique no botão para ativar:</i>"
        )
        bot.edit_message_text(texto_pix, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Erro temporário. Tente novamente.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("check_"))
def callback_verificar_manual(call):
    payment_id = call.data.split("_")[1]
    payment_info = sdk.payment().get(payment_id)
    if payment_info["response"].get("status") == "approved":
        transacao = transacoes_col.find_one({"payment_id": int(payment_id)})
        if transacao and transacao["status"] == "pending":
            transacoes_col.update_one({"payment_id": int(payment_id)}, {"$set": {"status": "pago"}})
            liberar_vip_logic(call.from_user.id, transacao["plano"])
            bot.delete_message(call.message.chat.id, call.message.message_id)
    else:
        bot.answer_callback_query(call.id, "⏳ Pagamento ainda não identificado.", show_alert=True)

# --- WEBHOOK ---
@app.route('/webhook/pagamento', methods=['POST'])
def webhook_saas():
    data = request.get_json()
    if data and data.get("type") == "payment":
        payment_id = data["data"]["id"]
        payment_info = sdk.payment().get(payment_id)
        if payment_info["response"].get("status") == "approved":
            transacao = transacoes_col.find_one({"payment_id": int(payment_id)})
            if transacao and transacao["status"] == "pending":
                transacoes_col.update_one({"payment_id": int(payment_id)}, {"$set": {"status": "pago"}})
                liberar_vip_logic(transacao["user_id"], transacao["plano"])
    return "OK", 200

# --- DOWNLOADER (MANTIDO) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    downloads_atuais = user.get("downloads_hoje", 0)

    if not vip and downloads_atuais >= 5:
        return bot.reply_to(message, "⚠️ Limite atingido. Torne-se VIP para continuar!", reply_markup=menu_planos())

    fila_msg = f"✅ Adicionado à fila!\n📊 Hoje: {downloads_atuais}/5"
    msg_p = bot.reply_to(message, fila_msg)
    
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    ydl_opts = {'format': 'bestvideo+bestaudio/best', 'outtmpl': f'{file_id}.%(ext)s', 'merge_output_format': 'mp4', 'quiet': True}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption="Vídeo baixado com sucesso🤝")
                for f in files: os.remove(f)
                if not vip:
                    user["downloads_hoje"] += 1
                    usuarios_col.replace_one({"_id": user["_id"]}, user)
                bot.delete_message(message.chat.id, msg_p.message_id)
    except:
        bot.edit_message_text("❌ Erro ao baixar.", message.chat.id, msg_p.message_id)

# --- INFRA ---
@app.route('/')
def health(): return "Online", 200
def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
