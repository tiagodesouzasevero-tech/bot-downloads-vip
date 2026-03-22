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

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
transacoes_col = db["transacoes"] # Nova coleção para controle SaaS

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- LÓGICA DE USUÁRIO & VIP (MANTIDA) ---
def obter_usuario(user_id):
    uid = str(user_id)
    hoje = datetime.now().strftime('%Y-%m-%d')
    user = usuarios_col.find_one({"_id": uid})
    if not user:
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": hoje}
        usuarios_col.insert_one(user)
    return user

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try: return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

def liberar_vip_logic(user_id, plano):
    user = obter_usuario(user_id)
    if "Mensal" in plano: nova_data = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    elif "Anual" in plano: nova_data = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
    else: nova_data = "Vitalício"
    
    usuarios_col.update_one({"_id": str(user_id)}, {"$set": {"vip_ate": nova_data}})
    
    confirmacao = (
        "✅ <b>Pagamento confirmado!</b>\n"
        "Agora você é VIP 🎉\n\n"
        "🚀 <b>Benefícios liberados:</b>\n"
        "• Downloads ILIMITADOS\n"
        "• Sem restrições\n\n"
        "Pode enviar o link do vídeo e aproveitar 👇"
    )
    bot.send_message(user_id, confirmacao, parse_mode="HTML")

# --- NOVO SISTEMA DE PAGAMENTO PIX (v1.3.0) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def callback_pix_gerador(call):
    _, valor, plano = call.data.split("_")
    user_id = str(call.from_user.id)
    ref_unica = str(uuid.uuid4())

    # Criar pagamento via API Pix do Mercado Pago
    payment_data = {
        "transaction_amount": float(valor),
        "description": f"Plano {plano} - ViralClip",
        "payment_method_id": "pix",
        "external_reference": ref_unica,
        "payer": {
            "email": f"user_{user_id}@telegram.com",
            "first_name": call.from_user.first_name or "Usuario",
            "last_name": "Telegram"
        }
    }
    
    try:
        payment_response = sdk.payment().create(payment_data)
        pix_code = payment_response["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
        payment_id = payment_response["response"]["id"]

        # Registrar transação pendente no Banco
        transacoes_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "payment_id": payment_id,
                "status": "pending",
                "plano": plano,
                "ref": ref_unica,
                "data": datetime.now()
            }},
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
            f"<i>Após pagar, clique no botão abaixo para ativar instantaneamente:</i>"
        )
        bot.edit_message_text(texto_pix, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
    
    except Exception as e:
        bot.answer_callback_query(call.id, "❌ Erro ao gerar Pix. Tente novamente.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("check_"))
def callback_verificar_manual(call):
    payment_id = call.data.split("_")[1]
    
    payment_info = sdk.payment().get(payment_id)
    status = payment_info["response"]["status"]
    
    if status == "approved":
        transacao = transacoes_col.find_one({"payment_id": int(payment_id)})
        if transacao and transacao["status"] == "pending":
            transacoes_col.update_one({"payment_id": int(payment_id)}, {"$set": {"status": "pago"}})
            liberar_vip_logic(call.from_user.id, transacao["plano"])
            bot.delete_message(call.message.chat.id, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "✅ Seu VIP já está ativo!")
    else:
        bot.answer_callback_query(call.id, "⏳ Pagamento ainda não identificado. Aguarde um instante.", show_alert=True)

# --- WEBHOOK SaaS (v1.3.0) ---
@app.route('/webhook/pagamento', methods=['POST'])
def webhook_saas():
    data = request.get_json()
    if data and data.get("type") == "payment":
        payment_id = data["data"]["id"]
        payment_info = sdk.payment().get(payment_id)
        
        if payment_info["response"]["status"] == "approved":
            user_id = payment_info["response"]["external_reference"] # Usamos a REF vinculada ao ID do banco
            transacao = transacoes_col.find_one({"payment_id": int(payment_id)})
            
            if transacao and transacao["status"] == "pending":
                transacoes_col.update_one({"payment_id": int(payment_id)}, {"$set": {"status": "pago"}})
                liberar_vip_logic(transacao["user_id"], transacao["plano"])
                
    return "OK", 200

# --- LÓGICA DE DOWNLOADS (MANTIDA INTEGRALMENTE) ---
# [O código de handle_dl permanece exatamente igual às versões anteriores]

# ... (restante do código handle_dl e infraestrutura Flask)
