import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ESSENCIAIS (MANTIDAS v1.0.0) ---
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
        salvar_usuario(user)
    return user

def salvar_usuario(user):
    usuarios_col.replace_one({"_id": user["_id"]}, user)

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try: return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

# --- MENUS (VALORES MANTIDOS APENAS NOS BOTÕES) ---
def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$190,00 🔥", callback_data="buy_190_Vitalicio"))
    return markup

# --- COMANDOS (TEXTOS SEM VALORES v1.2.0) ---
@bot.message_handler(commands=['meuadm'])
def cmd_adm(message):
    if str(message.from_user.id) == MY_ID:
        user = obter_usuario(MY_ID)
        user["vip_ate"] = "Vitalício"
        salvar_usuario(user)
        bot.reply_to(message, "👑 <b>Admin: Plano Vitalício Ativado!</b>", parse_mode="HTML")

@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    nome = message.from_user.first_name
    
    if vip:
        expira = user["vip_ate"]
        texto = (
            f"🚀 <b>Bem-vindo ao ViralClip Pro – Downloader HD</b>\n\n"
            f"👋 Olá, {nome}!\n💎 <b>Status: VIP ({expira})</b>\n"
            f"🚀 Benefícios liberados:\n• Downloads ILIMITADOS\n• Prioridade no servidor\n\n"
            f"Pode enviar o link do vídeo e aproveitar 👇"
        )
        markup = None
    else:
        texto = (
            f"🚀 <b>Bem-vindo ao ViralClip Pro – Downloader HD</b>\n\n"
            f"Baixe vídeos do TikTok, Pinterest e Rednote em segundos 👇\n\n"
            f"🎁 <b>Plano GRATUITO:</b>\n• 5 downloads por dia\n\n"
            f"💎 <b>Plano VIP:</b>\n• Downloads ILIMITADOS\n• Sem fila\n• Alta velocidade\n\n"
            f"💰 <b>Planos:</b>\n• Mensal\n• Anual\n"
            f"• Vitalício 🔥 Oferta por tempo limitado\n\n"
            f"👇 Escolha uma opção abaixo:"
        )
        markup = menu_planos()
    bot.reply_to(message, texto, reply_markup=markup, parse_mode="HTML")

# --- WEBHOOK (MANTIDO v1.0.0) ---
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
            if "Mensal" in plano: nova_data = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
            elif "Anual" in plano: nova_data = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
            else: nova_data = "Vitalício"
            user["vip_ate"] = nova_data
            salvar_usuario(user)
            
            confirmacao = (
                "✅ <b>Pagamento confirmado!</b>\n\n"
                "Agora você é VIP 🎉\n\n"
                "🚀 <b>Benefícios liberados:</b>\n"
                "• Downloads ILIMITADOS\n"
                "• Prioridade no servidor\n"
                "• Sem restrições\n\n"
                "Pode enviar o link do vídeo e aproveitar 👇"
            )
            bot.send_message(user_id, confirmacao, parse_mode="HTML")
    return "OK", 200

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def callback_buy(call):
    _, valor, plano = call.data.split("_")
    user_id = str(call.from_user.id)
    pref_data = {
        "items": [{"title": f"Plano {plano}", "quantity": 1, "unit_price": float(valor), "currency_id": "BRL"}],
        "external_reference": user_id,
        "notification_url": "https://bot-downloads-vip-production.up.railway.app/webhook"
    }
    result = sdk.preference().create(pref_data)
    url_pag = result["response"]["init_point"]
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 Pagar Agora", url=url_pag))
    
    texto_compra = (
        f"💳 <b>Assinatura {plano}</b>\n\n"
        f"👉 Clique abaixo e libere agora"
    )
    bot.edit_message_text(texto_compra, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")

# --- DOWNLOADER (LÓGICA DE LIMITE v1.2.0) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    downloads_atuais = user.get("downloads_hoje", 0)

    # Nova regra: Bloqueia apenas se já tiver atingido 5 (6º link em diante)
    if not vip and downloads_atuais >= 5:
        msg_excedeu = (
            "⚠️ <b>Você atingiu o limite de downloads gratuitos hoje.</b>\n\n"
            "🔥 <b>Libere acesso ilimitado para continuar:</b>\n"
            "• Baixe quantos vídeos quiser\n"
            "• Sem espera\n"
            "• Muito mais rápido\n\n"
            "💎 <b>Escolha um plano abaixo 👇</b>"
        )
        return bot.reply_to(message, msg_excedeu, reply_markup=menu_planos(), parse_mode="HTML")

    # Mensagem de fila com contador (v1.2.0)
    # Mostramos o número atual (ex: 0/5, 1/5... até 4/5 antes de processar o 5º)
    fila_msg = (
        "✅ Seu link foi adicionado à fila de download! Por favor, aguarde alguns instantes!\n\n"
        f"📊 Hoje: {downloads_atuais}/5"
    )
    msg_processando = bot.reply_to(message, fila_msg, parse_mode="HTML")
    
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'format_sort': ['res:720', 'fps:30', 'vcodec:h264'],
        'outtmpl': f'{file_id}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get('duration', 0) > 90:
                bot.edit_message_text("⚠️ <b>Vídeo muito longo!</b> O limite é 90 segundos.", message.chat.id, msg_processando.message_id, parse_mode="HTML")
                for f in glob.glob(f"{file_id}.*"): os.remove(f)
                return

            files = glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    # Legenda simplificada após download (v1.2.0)
                    bot.send_video(
                        message.chat.id, 
                        f, 
                        caption="Vídeo baixado com sucesso🤝", 
                        parse_mode="HTML"
                    )
                for f in files: os.remove(f)
                
                # Incrementa contador
                if not vip:
                    user["downloads_hoje"] += 1
                    salvar_usuario(user)
                    
                    # Se acabou de completar o 5º download, envia oferta VIP automática
                    if user["downloads_hoje"] == 5:
                        msg_oferta = (
                            "⚠️ <b>Você atingiu o limite de downloads gratuitos hoje.</b>\n\n"
                            "🔥 <b>Libere acesso ilimitado para continuar:</b>\n"
                            "• Baixe quantos vídeos quiser\n"
                            "• Sem espera\n"
                            "• Muito mais rápido\n\n"
                            "💎 <b>Escolha um plano abaixo 👇</b>"
                        )
                        bot.send_message(message.chat.id, msg_oferta, reply_markup=menu_planos(), parse_mode="HTML")

                bot.delete_message(message.chat.id, msg_processando.message_id)
            else:
                raise Exception("Arquivo não encontrado")
    except Exception as e:
        bot.edit_message_text("❌ <b>Erro ao baixar.</b> Verifique o link.", message.chat.id, msg_processando.message_id, parse_mode="HTML")

# --- SERVIDOR (MANTIDO v1.0.1) ---
@app.route('/')
def health(): return "Online", 200

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
