import os, telebot, yt_dlp, mercadopago, json, glob, instaloader
from datetime import datetime, timedelta
from telebot import types
from flask import Flask, request
from threading import Thread

# --- CONFIGURAÇÕES ORIGINAIS ---
TOKEN_TELEGRAM = "8629536333:AAHw2zcugsOXPpOJaXsz1ZVA30T1VypiMlQ"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
DB_FILE = "database.json"
MY_ID = "493336271"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)
app = Flask(__name__)
L = instaloader.Instaloader()

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
    
    hoje = datetime.now().strftime('%Y-%m-%d')
    if dados["usuarios"][uid]["ultima_data"] != hoje:
        dados["usuarios"][uid]["downloads_hoje"] = 0
        dados["usuarios"][uid]["ultima_data"] = hoje
    return dados["usuarios"][uid]

def is_vip(user_id, dados):
    user = obter_usuario(user_id, dados)
    if user["vip_ate"] == "Vitalício": return True
    if not user["vip_ate"]: return False
    try: return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

# --- INTERFACE DE PLANOS ---
def enviar_menu_planos(chat_id, texto_extra=""):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10.0_30"),
        types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_365"),
        types.InlineKeyboardButton("💎 Vitalício - R$1.900,00", callback_data="buy_1900.0_3650")
    )
    bot.send_message(chat_id, f"{texto_extra}\n\nEscolha um plano para baixar sem limites:", reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(commands=['start', 'planos'])
def cmd_planos(message):
    dados = carregar_dados()
    user = obter_usuario(message.from_user.id, dados)
    vip = is_vip(message.from_user.id, dados)
    texto = f"👏 **Downloader VIP**\n\n📊 Status: {'💎 VIP' if vip else '🆓 Gratuito'}\n💡 Restantes hoje: {'∞' if vip else (5 - user['downloads_hoje'])}"
    enviar_menu_planos(message.chat.id, texto)

# --- WEBHOOK MERCADO PAGO ---
@app.route("/webhook", methods=['POST'])
def webhook():
    data = request.json
    if data and data.get("type") == "payment":
        payment_info = sdk.payment().get(data.get("data", {}).get("id"))
        if payment_info["status"] in [200, 201]:
            res = payment_info["response"]
            if res["status"] == "approved":
                user_id = res["external_reference"]
                dias = int(res["metadata"]["dias"])
                dados = carregar_dados()
                user = obter_usuario(user_id, dados)
                user["vip_ate"] = "Vitalício" if dias >= 3650 else (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')
                salvar_dados(dados)
                bot.send_message(user_id, "💎 **VIP ATIVADO!**")
    return "", 200

# --- MOTOR DE DOWNLOAD (ANTIBLOQUEIO INSTAGRAM) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    dados = carregar_dados()
    user_id = message.from_user.id
    user = obter_usuario(user_id, dados)
    
    if not is_vip(user_id, dados) and user["downloads_hoje"] >= 5:
        return enviar_menu_planos(message.chat.id, "🚫 **Limite diário atingido!**")

    msg = bot.reply_to(message, "⏳ **Processando...**")
    file_id = f"vid_{message.message_id}"
    url = message.text
    sucesso = False

    try:
        # Lógica especial para Instagram
        if "instagram.com" in url:
            shortcode = url.split("reel/")[1].split("/")[0] if "reel/" in url else url.split("p/")[1].split("/")[0]
            post = instaloader.Post.from_shortcode(L.context, shortcode)
            if post.is_video:
                bot.send_video(message.chat.id, post.video_url, caption="✅ @Tss_Downloader_bot")
                sucesso = True
        else:
            # Lógica para TikTok e Pinterest (yt-dlp)
            ydl_opts = {'format': 'best', 'outtmpl': f'{file_id}.%(ext)s', 'quiet': True, 'nocheckcertificate': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
                files = glob.glob(f"{file_id}.*")
                if files:
                    with open(files[0], 'rb') as f:
                        bot.send_video(message.chat.id, f, caption="✅ @Tss_Downloader_bot")
                    os.remove(files[0])
                    sucesso = True

        if sucesso:
            bot.delete_message(message.chat.id, msg.message_id)
            if not is_vip(user_id, dados):
                user["downloads_hoje"] += 1
                salvar_dados(dados)
        else:
            raise Exception("Erro no processamento")

    except Exception as e:
        bot.edit_message_text("❌ Link instável, privado ou inválido.", message.chat.id, msg.message_id)

# --- ADM E PAGAMENTOS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_pay(call):
    _, valor, dias = call.data.split("_")
    res = sdk.payment().create({
        "transaction_amount": float(valor), "description": f"Plano {dias} dias", "payment_method_id": "pix",
        "external_reference": str(call.from_user.id), "metadata": {"dias": dias},
        "payer": {"email": "cliente@bot.com", "first_name": "Tiago"}
    })
    if "response" in res and "point_of_interaction" in res["response"]:
        pix = res["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
        bot.send_message(call.message.chat.id, f"✅ **Pix Gerado!**\n\n`{pix}`", parse_mode="Markdown")

@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        dados = carregar_dados()
        user = obter_usuario(MY_ID, dados)
        user["vip_ate"] = "Vitalício"
        salvar_dados(dados)
        bot.reply_to(message, "👑 **Acesso Vitalício Ativado, Tiago!**")

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.remove_webhook()
    bot.infinity_polling(timeout=20)
