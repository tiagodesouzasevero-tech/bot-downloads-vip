import os, telebot, yt_dlp, json
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES DEFINITIVAS ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority"

CHAVE_PIX_INFINITE = "dc359b2c-d52f-48b5-b022-3c4fb3a8ddb5" 
LINK_SUPORTE = "https://t.me/suporteafiliadoclippro"
ADMIN_ID = 493336271

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]

bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

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

@bot.message_handler(commands=['darvip'])
def dar_vip_manual(message):
    if message.from_user.id == ADMIN_ID:
        try:
            args = message.text.split()
            alvo_id = args[1]
            dias = int(args[2])
            nova_data = "Vitalício" if dias >= 3650 else (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')
            usuarios_col.update_one({"_id": str(alvo_id)}, {"$set": {"vip_ate": nova_data}})
            bot.reply_to(message, f"✅ VIP liberado para {alvo_id} até {nova_data}!")
            bot.send_message(alvo_id, f"🎉 **PAGAMENTO CONFIRMADO!**\nVIP liberado até {nova_data}!")
        except:
            bot.reply_to(message, "❌ Use: /darvip ID DIAS")

@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 **STATUS: VIP PRO**" if vip else f"👤 **STATUS: GRÁTIS** ({user.get('downloads_hoje', 0)}/5)"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, f"🚀 **AfiliadoClip Pro**\n\nSua ID: `{message.from_user.id}`\n{status}", parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💎 Planos VIP")
def mostrar_planos(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 VIP Mensal - R$ 10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💳 VIP Anual - R$ 69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 VIP Vitalício - R$ 197,00", callback_data="pay_197.00")
    )
    bot.send_message(message.chat.id, "Escolha o melhor plano para você:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def pagamento_manual(call):
    valor = call.data.split("_")[1]
    msg = f"💎 **Plano: R$ {valor}**\n\nPix Copia e Cola:\n`{CHAVE_PIX_INFINITE}`\n\nEnvie o comprovante e sua ID: `{call.from_user.id}`"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Enviar Comprovante", url=LINK_SUPORTE))
    bot.send_message(call.message.chat.id, msg, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    
    # LINHA 108 CORRIGIDA ABAIXO
    if not is_vip(message.from_user.id) and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ Limite atingido! Adquira um plano VIP.")

    status_msg = bot.reply_to(message, "⏳ Processando link em HD...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"

    try:
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
            if not is_vip(message.from_user.id):
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            bot.edit_message_text("❌ Erro ao processar.", message.chat.id, status_msg.message_id)
    except:
        bot.edit_message_text("❌ Erro no download.", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(file_name): os.remove(file_name)
        try: bot.delete_message(message.chat.id, status_msg.message_id)
        except: pass

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
