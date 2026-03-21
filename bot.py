import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
DB_FILE = "database.json"
MY_ID = "493336271"
SUPORTE_USER = "@suportebotvip01"

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

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

# --- MENUS PROFISSIONAIS ---
def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$499,00", callback_data="buy_499_Vitalicio"))
    return markup

def menu_vip_ativo():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🛠️ Falar com Suporte", url=f"https://t.me/{SUPORTE_USER[1:]}"))
    return markup

# --- MERCADO PAGO E WEBHOOK ---
def gerar_pix(valor, descricao, user_id, plano):
    payment_data = {
        "transaction_amount": float(valor),
        "description": descricao,
        "payment_method_id": "pix",
        "payer": {"email": f"user_{user_id}@bot.com"},
        "external_reference": f"{user_id}:{plano}"
    }
    result = sdk.payment().create(payment_data)
    if result["status"] == 201:
        return result["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
    return None

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.args.get("type") == "payment":
        payment_id = request.args.get("data.id")
        payment_info = sdk.payment().get(payment_id)
        if payment_info["response"]["status"] == "approved":
            ref = payment_info["response"]["external_reference"]
            user_id, plano = ref.split(":")
            dados = carregar_dados()
            if not is_vip(user_id, dados):
                user = obter_usuario(user_id, dados)
                hoje = datetime.now()
                if plano == "Mensal": nova_data = (hoje + timedelta(days=30)).strftime('%Y-%m-%d')
                elif plano == "Anual": nova_data = (hoje + timedelta(days=365)).strftime('%Y-%m-%d')
                else: nova_data = "Vitalício"
                user["vip_ate"] = nova_data
                salvar_dados(dados)
                bot.send_message(user_id, f"🌟 **ACESSO LIBERADO!**\n\nSeu plano **{plano}** foi ativado com sucesso. Agora você tem acesso ilimitado às nossas ferramentas! 🚀", reply_markup=menu_vip_ativo())
    return "OK", 200

@app.route('/')
def health(): return "Bot Online", 200

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    dados = carregar_dados()
    user = obter_usuario(message.from_user.id, dados)
    vip = is_vip(message.from_user.id, dados)
    
    if vip:
        if user["vip_ate"] == "Vitalício":
            validade_txt = "💎 **Eterno (Vitalício)**"
        else:
            dias_restantes = (datetime.strptime(user["vip_ate"], '%Y-%m-%d') - datetime.now()).days
            validade_txt = f"⏳ **{dias_restantes} dias restantes**"
        
        texto = (
            f"👋 **Olá, {message.from_user.first_name}!**\n\n"
            f"👑 **Status:** Usuário VIP\n"
            f"{validade_txt}\n"
            f"🚀 **Downloads:** Ilimitados\n\n"
            f"Pode enviar seus links à vontade! Se precisar de algo, use o botão abaixo."
        )
        bot.reply_to(message, texto, reply_markup=menu_vip_ativo(), parse_mode="Markdown")
    else:
        restantes = 5 - user["downloads_hoje"]
        texto = (
            f"👋 **Bem-vindo ao Downloader VIP!**\n\n"
            f"📊 **Status:** Plano Gratuito\n"
            f"💡 **Limite Diário:** {restantes}/5 restantes\n\n"
            f"Escolha um plano para remover todas as restrições:"
        )
        bot.reply_to(message, texto, reply_markup=menu_planos(), parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_payment(call):
    _, valor, plano = call.data.split("_")
    bot.answer_callback_query(call.id, "Gerando PIX...")
    pix = gerar_pix(valor, f"Plano {plano} - Bot VIP", call.from_user.id, plano)
    if pix:
        texto = (
            f"✅ **PIX Gerado!**\n\n"
            f"📦 **Plano:** {plano}\n"
            f"💰 **Valor:** R$ {valor}\n\n"
            f"Cliquem no código abaixo para copiar:\n\n"
            f"`{pix}`\n\n"
            f"⚡ **A ativação será automática após o pagamento.**"
        )
        bot.send_message(call.message.chat.id, texto, parse_mode="Markdown")

# --- DOWNLOADER (REUTILIZADO DO ANTERIOR) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    dados = carregar_dados()
    user = obter_usuario(message.from_user.id, dados)
    vip = is_vip(message.from_user.id, dados)
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user["ultima_data"] != hoje:
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje
        salvar_dados(dados)
    if not vip and user["downloads_hoje"] >= 5:
        return bot.reply_to(message, "🚫 **Limite atingido!**", reply_markup=menu_planos())
    msg = bot.reply_to(message, "⏳ **Processando...**")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    try:
        ydl_opts = {'format': 'best', 'outtmpl': f'{file_id}.%(ext)s', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption=f"✅ **Sucesso!**\n💬 Suporte: {SUPORTE_USER}")
                os.remove(files[0])
                if not vip:
                    user["downloads_hoje"] += 1
                    salvar_dados(dados)
                bot.delete_message(message.chat.id, msg.message_id)
            else: bot.edit_message_text("❌ Falha no download.", message.chat.id, msg.message_id)
    except: bot.edit_message_text("❌ Link inválido.", message.chat.id, msg.message_id)

def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.remove_webhook()
    bot.infinity_polling(skip_pending=True)
