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

# --- MERCADO PAGO (PIX + WEBHOOK) ---
def gerar_pix(valor, descricao, user_id, plano):
    payment_data = {
        "transaction_amount": float(valor),
        "description": descricao,
        "payment_method_id": "pix",
        "payer": {"email": f"user_{user_id}@bot.com"},
        "external_reference": f"{user_id}:{plano}" # Vincula ID e Plano ao pagamento
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
            user = obter_usuario(user_id, dados)
            hoje = datetime.now()

            # Lógica de ativação conforme o plano
            if plano == "Mensal":
                nova_data = (hoje + timedelta(days=30)).strftime('%Y-%m-%d')
            elif plano == "Anual":
                nova_data = (hoje + timedelta(days=365)).strftime('%Y-%m-%d')
            else: # Vitalício
                nova_data = "Vitalício"

            user["vip_ate"] = nova_data
            salvar_dados(dados)
            
            bot.send_message(user_id, f"✅ **Pagamento Confirmado!**\n\nSeu plano **{plano}** foi ativado com sucesso. Agora você é um usuário **VIP**!\n\nAproveite os downloads ilimitados! 🚀")
            
    return "OK", 200

@app.route('/')
def health(): return "Bot Online", 200

# --- MENUS ---
def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$499,00", callback_data="buy_499_Vitalicio"))
    return markup

# --- COMANDOS E CALLBACKS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def handle_payment(call):
    _, valor, plano = call.data.split("_")
    bot.answer_callback_query(call.id, "Gerando PIX...")
    pix = gerar_pix(valor, f"Plano {plano} - Bot VIP", call.from_user.id, plano)
    
    if pix:
        texto = (
            f"✅ **PIX Gerado com Sucesso!**\n\n"
            f"📦 **Plano:** {plano}\n"
            f"💰 **Valor:** R$ {valor}\n\n"
            f"Copie o código abaixo e pague no seu banco:\n\n"
            f"`{pix}`\n\n"
            f"⚡ **A ativação é automática logo após o pagamento!**"
        )
        bot.send_message(call.message.chat.id, texto, parse_mode="Markdown")
    else:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar PIX. Tente novamente.")

@bot.message_handler(commands=['start', 'planos'])
def cmd_start(message):
    dados = carregar_dados()
    user = obter_usuario(message.from_user.id, dados)
    vip = is_vip(message.from_user.id, dados)
    
    status = "💎 VIP" if vip else "🆓 Gratuito"
    restantes = "∞" if vip else (5 - user["downloads_hoje"])
    
    texto = (
        f"👋 **Bem-vindo ao Downloader VIP!**\n\n"
        f"📊 **Status:** {status}\n"
        f"💡 **Downloads hoje:** {restantes}/5\n\n"
        f"Escolha um plano abaixo para liberar acesso ilimitado:"
    )
    bot.reply_to(message, texto, reply_markup=menu_planos(), parse_mode="Markdown")

@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        dados = carregar_dados()
        user = obter_usuario(MY_ID, dados)
        user["vip_ate"] = "Vitalício"
        salvar_dados(dados)
        bot.reply_to(message, "👑 **Admin Ativado!**")

# --- DOWNLOADER (TikTok, Pinterest, Rednote) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    dados = carregar_dados()
    user = obter_usuario(message.from_user.id, dados)
    vip = is_vip(message.from_user.id, dados)
    
    # Reset diário de downloads
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user["ultima_data"] != hoje:
        user["downloads_hoje"] = 0
        user["ultima_data"] = hoje
        salvar_dados(dados)

    if not vip and user["downloads_hoje"] >= 5:
        return bot.reply_to(message, "🚫 **Limite de 5 downloads diários atingido!**", reply_markup=menu_planos())

    msg = bot.reply_to(message, "⏳ **Processando vídeo...**")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"

    try:
        ydl_opts = {
            'format': 'best',
            'outtmpl': f'{file_id}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption=f"✅ **Baixado com sucesso!**\n💬 Suporte: {SUPORTE_USER}")
                os.remove(files[0])
                if not vip:
                    user["downloads_hoje"] += 1
                    salvar_dados(dados)
                bot.delete_message(message.chat.id, msg.message_id)
            else:
                bot.edit_message_text("❌ Não consegui baixar este vídeo.", message.chat.id, msg.message_id)
    except Exception:
        bot.edit_message_text("❌ Link inválido ou não suportado.", message.chat.id, msg.message_id)

# --- EXECUÇÃO ---
def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.remove_webhook()
    print("Bot rodando...")
    bot.infinity_polling(skip_pending=True)
