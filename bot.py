import os
import telebot
import yt_dlp
import mercadopago
import time
import random
import json
from datetime import datetime, timedelta
from telebot import types
from flask import Flask, request
from threading import Thread

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAEV4IcvFt5CTRqQVz5yYXmNOXvcgaZygGE"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
DB_FILE = "database.json"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
app = Flask(__name__)

# --- SISTEMA DE BANCO DE DADOS ---
def carregar_dados():
    if not os.path.exists(DB_FILE):
        return {"usuarios": {}}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except:
        return {"usuarios": {}}

def salvar_dados(dados):
    with open(DB_FILE, "w") as f:
        json.dump(dados, f, indent=4)

def obter_usuario(user_id, dados):
    uid = str(user_id)
    if uid not in dados["usuarios"]:
        dados["usuarios"][uid] = {
            "vip_ate": None,
            "downloads_hoje": 0,
            "ultima_data": datetime.now().strftime('%Y-%m-%d')
        }
    return dados["usuarios"][uid]

def is_vip(user_id, dados):
    user = obter_usuario(user_id, dados)
    if not user["vip_ate"]: return False
    if user["vip_ate"] == "Vitalício": return True
    try:
        expira = datetime.strptime(user["vip_ate"], '%Y-%m-%d')
        if datetime.now() > expira:
            user["vip_ate"] = None
            salvar_dados(dados)
            return False
        return True
    except:
        return False

# --- WEBHOOK (AUTOMAÇÃO DE PAGAMENTO) ---
@app.route("/webhook", methods=['POST'])
def webhook():
    data = request.json
    if data and data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        payment_info = sdk.payment().get(payment_id)
        if payment_info["status"] in [200, 201]:
            res = payment_info["response"]
            if res["status"] == "approved":
                user_id = res["external_reference"]
                dias = res["metadata"]["dias"]
                dados = carregar_dados()
                user = obter_usuario(user_id, dados)
                nova_data = datetime.now() + timedelta(days=int(dias))
                user["vip_ate"] = "Vitalício" if int(dias) > 1000 else nova_data.strftime('%Y-%m-%d')
                salvar_dados(dados)
                bot.send_message(user_id, "💎 **PAGAMENTO APROVADO!**\nSeu VIP foi ativado. Aproveite!")
    return "", 200

# --- COMANDO SECRETO PARA VOCÊ (TIAGO) ---
@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    # Este comando só funciona para o seu ID
    if str(message.from_user.id) == "7236528892": 
        dados = carregar_dados()
        user = obter_usuario(message.from_user.id, dados)
        user["vip_ate"] = "Vitalício"
        salvar_dados(dados)
        bot.reply_to(message, "👑 **Acesso Vitalício Ativado!**\nAgora você tem downloads ilimitados, Tiago.")

# --- GERADOR DE PIX ---
def gerar_pix_mp(valor, dias, user_id):
    payment_data = {
        "transaction_amount": float(valor),
        "description": f"Plano {dias} dias - Bot Downloader",
        "payment_method_id": "pix",
        "external_reference": str(user_id),
        "metadata": {"user_id": user_id, "dias": dias},
        "payer": {"email": "cliente@afiliados.com", "first_name": "Usuario", "last_name": "Bot"}
    }
    result = sdk.payment().create(payment_data)
    if "response" in result and "point_of_interaction" in result["response"]:
        return result["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
    return None

# --- COMANDOS DE PLANOS ---
@bot.message_handler(commands=['start', 'planos'])
def cmd_planos(message):
    dados = carregar_dados()
    user_id = message.from_user.id
    user = obter_usuario(user_id, dados)
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user["ultima_data"] != hoje:
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje
        salvar_dados(dados)
    vip = is_vip(user_id, dados)
    status = "💎 VIP Ilimitado" if vip else "🆓 Gratuito"
    saldo = "∞" if vip else (5 - user["downloads_hoje"])
    texto = (f"👏 **Bot de Downloads VIP**\n\n📊 Status: {status}\n📅 Expira: {user['vip_ate'] or 'Sem plano'}\n💡 Restante hoje: {saldo}")
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10.0_30"),
        types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_365"),
        types.InlineKeyboardButton("💎 Vitalício - R$1.900,00", callback_data="buy_1900.0_3650")
    )
    bot.send_message(message.chat.id, texto, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_pay_click(call):
    _, valor, dias = call.data.split("_")
    bot.answer_callback_query(call.id, "Gerando seu Pix...")
    pix = gerar_pix_mp(valor, dias, call.from_user.id)
    if pix:
        bot.send_message(call.message.chat.id, f"✅ **Pix Gerado!**\nCopie o código abaixo:\n\n`{pix}`", parse_mode="Markdown")

# --- SISTEMA DE DOWNLOAD ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    dados = carregar_dados()
    user_id = message.from_user.id
    user = obter_usuario(user_id, dados)
    if not is_vip(user_id, dados) and user["downloads_hoje"] >= 5:
        bot.reply_to(message, "🚫 **Limite atingido!** Adquira o VIP em /planos.")
        return
    msg = bot.reply_to(message, "⏳ **Baixando vídeo...**")
    ydl_opts = {'format': 'best', 'outtmpl': 'v_%(id)s.%(ext)s', 'socket_timeout': 60}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(message.text, download=True)
            path = ydl.prepare_filename(info)
            if not is_vip(user_id, dados):
                user["downloads_hoje"] += 1
            salvar_dados(dados)
            with open(path, 'rb') as f:
                bot.send_video(message.chat.id, f, caption=f"✅ Sucesso! Saldo: {user['downloads_hoje']}/5")
            os.remove(path)
            bot.delete_message(message.chat.id, msg.message_id)
    except:
        bot.edit_message_text(f"❌ Erro no download. Tente novamente.", message.chat.id, msg.message_id)

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling()
