import os
import telebot
import yt_dlp
import mercadopago
import json
from datetime import datetime, timedelta
from telebot import types
from flask import Flask, request
from threading import Thread

# --- CONFIGURAÇÕES DO TIAGO (MANTIDAS) ---
TOKEN_TELEGRAM = "8629536333:AAHw2zcugsOXPpOJaXsz1ZVA30T1VypiMlQ"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
DB_FILE = "database.json"

bot = telebot.TeleBot(TOKEN_TELEGRAM)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
app = Flask(__name__)

# --- BANCO DE DADOS (MANTIDO) ---
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
        return datetime.now() < expira
    except:
        return False

# --- WEBHOOK MERCADO PAGO ---
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
                
                if int(dias) >= 3650:
                    user["vip_ate"] = "Vitalício"
                else:
                    nova_data = datetime.now() + timedelta(days=int(dias))
                    user["vip_ate"] = nova_data.strftime('%Y-%m-%d')
                
                salvar_dados(dados)
                bot.send_message(user_id, "💎 **PAGAMENTO APROVADO!** Seu VIP foi liberado.")
    return "", 200

# --- COMANDO ADM (ID DO TIAGO: 493336271) ---
@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == "493336271":
        dados = carregar_dados()
        user = obter_usuario(message.from_user.id, dados)
        user["vip_ate"] = "Vitalício"
        salvar_dados(dados)
        bot.reply_to(message, "👑 **Acesso Vitalício Ativado, Tiago!**")
    else:
        bot.reply_to(message, "❌ Comando restrito ao proprietário.")

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
    status = "💎 VIP" if vip else "🆓 Gratuito"
    vencimento = user["vip_ate"] if user["vip_ate"] else "Sem plano"
    limite = "∞" if vip else (5 - user["downloads_hoje"])
    
    texto = (f"👏 **Downloader VIP**\n\n"
             f"📊 Status: {status}\n"
             f"📅 Expira em: {vencimento}\n"
             f"💡 Restante hoje: {limite}")
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10.0_30"),
        types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_365"),
        types.InlineKeyboardButton("💎 Vitalício - R$1.900,00", callback_data="buy_1900.0_3650")
    )
    bot.send_message(message.chat.id, texto, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_pay(call):
    _, valor, dias = call.data.split("_")
    bot.answer_callback_query(call.id, "Gerando seu Pix...")
    
    pay_data = {
        "transaction_amount": float(valor),
        "description": f"Plano {dias} dias - Downloader",
        "payment_method_id": "pix",
        "external_reference": str(call.from_user.id),
        "metadata": {"dias": dias},
        "payer": {"email": "cliente@bot.com", "first_name": "Tiago"}
    }
    
    res = sdk.payment().create(pay_data)
    if "response" in res and "point_of_interaction" in res["response"]:
        pix = res["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
        bot.send_message(call.message.chat.id, f"✅ **Pix Gerado!**\n\n`{pix}`", parse_mode="Markdown")
    else:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar Pix. Tente novamente.")

# --- SISTEMA DE DOWNLOAD (TikTok, Instagram, Pinterest) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    dados = carregar_dados()
    user_id = message.from_user.id
    user = obter_usuario(user_id, dados)
    
    if not is_vip(user_id, dados) and user["downloads_hoje"] >= 5:
        bot.reply_to(message, "🚫 Limite diário atingido! Seja VIP em /planos.")
        return

    msg = bot.reply_to(message, "⏳ **Baixando vídeo...**")
    
    ydl_opts = {
        'format': 'best',
        'outtmpl': 'v_%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.google.com/',
        'nocheckcertificate': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(message.text, download=True)
            path = ydl.prepare_filename(info)
            
            # Garante que encontrou o arquivo mesmo se o nome mudar levemente
            if not os.path.exists(path):
                import glob
                base_name = f"v_{info['id']}.*"
                files = glob.glob(base_name)
                if files:
                    path = files[0]

            if not is_vip(user_id, dados):
                user["downloads_hoje"] += 1
            salvar_dados(dados)
            
            with open(path, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Vídeo baixado!")
            
            os.remove(path)
            bot.delete_message(message.chat.id, msg.message_id)
    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text(f"❌ Erro no download. Verifique se o link é público.", message.chat.id, msg.message_id)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    # Rodar o bot e o flask juntos
    Thread(target=lambda: app.run(host="0.0.0.0", port=port, use_reloader=False)).start()
    bot.infinity_polling()
