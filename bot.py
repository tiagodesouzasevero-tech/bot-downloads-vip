import os, telebot, yt_dlp, mercadopago, json, glob
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES MANTIDAS ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

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

def menu_planos():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="buy_10_Mensal"))
    markup.add(types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="buy_69.9_Anual"))
    markup.add(types.InlineKeyboardButton("💎 Vitalício - R$190,00 🔥", callback_data="buy_190_Vitalicio"))
    return markup

@bot.message_handler(commands=['start', 'perfil'])
def cmd_start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = user.get("vip_ate", "Grátis") if vip else "Grátis"
    bot.reply_to(message, f"🚀 <b>ViralClip Pro</b>\n\n💎 Status: <b>{status}</b>\n\nEnvie o link do vídeo 👇", 
                 reply_markup=None if vip else menu_planos(), parse_mode="HTML")

# --- WEBHOOK E PIX MANTIDOS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def callback_buy(call):
    try:
        bot.answer_callback_query(call.id, "⏳ Gerando Pix...")
        _, valor, plano = call.data.split("_")
        user_id = str(call.from_user.id)
        payment_data = {
            "transaction_amount": float(valor),
            "description": f"Plano {plano} - ViralClip",
            "payment_method_id": "pix",
            "external_reference": user_id,
            "payer": {"email": f"u{user_id}@telegram.com", "first_name": "Usuario"}
        }
        res = sdk.payment().create(payment_data)
        if "response" in res and "point_of_interaction" in res["response"]:
            pix_code = res["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
            bot.edit_message_text(f"💰 <b>Pix Copia e Cola:</b>\n\n<code>{pix_code}</code>", call.message.chat.id, call.message.message_id, parse_mode="HTML")
    except: bot.answer_callback_query(call.id, "❌ Erro.")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.args.to_dict() or request.json or {}
    if data.get("type") == "payment":
        payment_id = data.get("data", {}).get("id")
        if payment_id:
            payment_info = sdk.payment().get(payment_id)
            if payment_info.get("response", {}).get("status") == "approved":
                user_id = payment_info["response"]["external_reference"]
                desc = payment_info["response"]["description"]
                expira = "Vitalício" if "Vitalicio" in desc else (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
                usuarios_col.update_one({"_id": str(user_id)}, {"$set": {"vip_ate": expira}})
                bot.send_message(user_id, "✅ <b>VIP Ativado!</b>")
    return "OK", 200

# --- DOWNLOADER v1.0.6 (FIX TIKTOK/PINTEREST) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": user["_id"]}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ Limite diário atingido!", reply_markup=menu_planos())

    msg_p = bot.reply_to(message, "⏳ Processando em HD 720p...")
    url = message.text.split()[0]
    file_id = f"dl_{message.from_user.id}_{message.message_id}"
    
    ydl_opts = {
        # 'best' resolve o erro do Pinterest de formato não disponível
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': f'{file_id}.%(ext)s',
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        # Força reprocessamento total para garantir 720p/30fps
        'postprocessor_args': [
            '-vf', 'scale=-2:720,fps=30',
            '-c:v', 'libx264',
            '-preset', 'veryfast'
        ],
        'postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'}],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duracao = info.get('duration', 0)
            
            # Trava de 90s: RedNote costuma vir com 0 ou None, então ele passa direto.
            # Pinterest e TikTok agora são identificados corretamente.
            if duracao and duracao > 90:
                return bot.edit_message_text("❌ Vídeo acima de 90 segundos.", message.chat.id, msg_p.message_id)

            ydl.download([url])
            
            files = glob.glob(f"{file_id}.mp4") or glob.glob(f"{file_id}.*")
            if files:
                with open(files[0], 'rb') as f:
                    bot.send_video(message.chat.id, f, caption="Vídeo pronto em HD 720p 🤝")
                for f in files: os.remove(f)
                if not vip:
                    usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
                bot.delete_message(message.chat.id, msg_p.message_id)
            else:
                raise Exception("Erro ao gerar arquivo")
                
    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text("❌ Erro ao baixar ou vídeo acima de 90s.", message.chat.id, msg_p.message_id)

@app.route('/')
def health(): return "Bot Online", 200
def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
