import os, telebot, yt_dlp, mercadopago, json
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES DE CRICIAIS ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority"

# Inicializa SDK Mercado Pago
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# Conexão Banco de Dados
client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
pagamentos_col = db["pagamentos"]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

# --- FUNÇÕES DE CONTROLE DE USUÁRIO ---
def obter_usuario(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    if not user:
        hoje = datetime.now().strftime('%Y-%m-%d')
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": hoje}
        usuarios_col.insert_one(user)
    return user

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try:
        return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

def liberar_vip(user_id, plano_valor):
    hoje = datetime.now()
    # Define a validade baseada no valor pago
    if "10.00" in str(plano_valor):
        nova_data = (hoje + timedelta(days=30)).strftime('%Y-%m-%d')
    elif "69.90" in str(plano_valor):
        nova_data = (hoje + timedelta(days=365)).strftime('%Y-%m-%d')
    else:
        nova_data = "Vitalício"
    
    usuarios_col.update_one({"_id": str(user_id)}, {"$set": {"vip_ate": nova_data}})
    bot.send_message(user_id, f"✅ **PAGAMENTO CONFIRMADO!**\nSeu plano VIP ({nova_data}) foi ativado. Agora você tem downloads ilimitados! 🚀")

# --- COMANDOS E INTERFACE ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 **STATUS: VIP PRO**" if vip else f"👤 **STATUS: GRÁTIS** ({user.get('downloads_hoje', 0)}/5)"
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, f"🚀 **AfiliadoClip Pro**\n\n{status}\n\n🔗 Envie um link do TikTok, Reels ou Pinterest para baixar em HD!", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💎 Planos VIP")
def mostrar_planos(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 VIP Mensal - R$ 10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💳 VIP Anual - R$ 69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 VIP Vitalício - R$ 197,00", callback_data="pay_197.00")
    )
    bot.send_message(message.chat.id, "Escolha o melhor plano para você:", reply_markup=markup)

# --- SISTEMA DE PAGAMENTO (PIX AUTOMÁTICO) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def gerar_pix(call):
    valor = float(call.data.split("_")[1])
    user_id = call.from_user.id
    bot.answer_callback_query(call.id, "Gerando Pix...")

    payment_data = {
        "transaction_amount": valor,
        "description": f"VIP AfiliadoClip - User {user_id}",
        "payment_method_id": "pix",
        "payer": {"email": "cliente_bot@email.com"}
    }

    result = sdk.payment().create(payment_data)
    payment = result["response"]

    if "point_of_interaction" in payment:
        pix_copia_cola = payment["point_of_interaction"]["transaction_data"]["qr_code"]
        pagamentos_col.insert_one({
            "pagamento_id": str(payment["id"]), 
            "user_id": user_id, 
            "valor": valor, 
            "status": "pending"
        })

        msg = (
            f"✅ **PIX GERADO COM SUCESSO!**\n\n"
            f"💰 **Valor:** R$ {valor:.2f}\n\n"
            f"📌 **Copia e Cola:**\n`{pix_copia_cola}`\n\n"
            "⚠️ O VIP será liberado **automaticamente** assim que você pagar. Não precisa enviar comprovante!"
        )
        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")
    else:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar Pix. Tente novamente em instantes.")

# --- WEBHOOK (Ouvinte de Confirmação do Mercado Pago) ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if data and data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        payment_info = sdk.payment().get(payment_id)["response"]
        
        if payment_info.get("status") == "approved":
            # Localiza o pagamento pendente no banco
            pg = pagamentos_col.find_one({"pagamento_id": str(payment_id), "status": "pending"})
            if pg:
                liberar_vip(pg["user_id"], pg["valor"])
                pagamentos_col.update_one({"_id": pg["_id"]}, {"$set": {"status": "approved"}})
    return "", 200

# --- DOWNLOADER (Configuração HD 720p Otimizada) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    
    # Verificação de Limite + Oferta de Planos
    if not is_vip(message.from_user.id) and user.get("downloads_hoje", 0) >= 5:
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("💳 VIP Mensal - R$ 10,00", callback_data="pay_10.00"),
            types.InlineKeyboardButton("💳 VIP Anual - R$ 69,90", callback_data="pay_69.90"),
            types.InlineKeyboardButton("💎 VIP Vitalício - R$ 197,00", callback_data="pay_197.00")
        )
        return bot.reply_to(message, "⚠️ **Limite atingido!**\n\nVocê já usou seus 5 downloads grátis de hoje. Escolha um plano abaixo para baixar agora:", reply_markup=markup, parse_mode="Markdown")

    status_msg = bot.reply_to(message, "⏳ Processando link em HD...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"

    try:
        # Configuração que garante os 720p leves que você testou
        ydl_opts = {
            'format': 'best[height<=1280][width<=1280][ext=mp4]/best[height<=1280]/best',
            'outtmpl': file_name,
            'nocheckcertificate': True,
            'quiet': True
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(file_name):
            with open(file_name, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Vídeo HD pronto!")
            
            # Contabiliza download se não for VIP
            if not is_vip(message.from_user.id):
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            bot.edit_message_text("❌ Falha ao processar o arquivo.", message.chat.id, status_msg.message_id)

    except Exception:
        bot.edit_message_text("❌ Erro no download. Link inválido ou instabilidade.", message.chat.id, status_msg.message_id)
    
    finally:
        if os.path.exists(file_name): os.remove(file_name)
        try: bot.delete_message(message.chat.id, status_msg.message_id)
        except: pass

# --- INICIALIZAÇÃO ---
@app.route('/')
def health(): return "SYSTEM_ACTIVE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
