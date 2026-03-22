import os, telebot, yt_dlp, mercadopago, json
from datetime import datetime
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)

# --- FUNÇÕES DE SUPORTE ---
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

def menu_pagamento_direto():
    """Gera os 3 botões de planos com os novos valores"""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 Mensal - R$ 10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💳 Anual - R$ 69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 Vitalício - R$ 197,00", callback_data="pay_197.00")
    )
    return markup

# --- COMANDOS ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    status = f"💎 **STATUS: VIP PRO**" if vip else f"👤 **STATUS: GRÁTIS** ({user.get('downloads_hoje', 0)}/5)"
    msg = f"🚀 **AfiliadoClip Pro**\n\n{status}\n\n🔗 Envie um link para baixar em HD!"
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, msg, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💎 Planos VIP")
def mostrar_planos(message):
    bot.send_message(message.chat.id, "Escolha seu plano para liberar downloads ilimitados:", reply_markup=menu_pagamento_direto())

# --- CALLBACK DE PAGAMENTO (PIX COPIA E COLA) ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def handle_payment(call):
    valor = call.data.split("_")[1]
    bot.answer_callback_query(call.id)
    
    texto_pix = (
        f"✅ **Plano de R$ {valor} selecionado!**\n\n"
        "Para ativar seu VIP agora, pague via **PIX Copia e Cola** abaixo:\n\n"
        "`SEU_CODIGO_PIX_AQUI`\n\n"
        " após o pagamento, envie o comprovante no suporte."
    )
    # Aqui você deve substituir 'SEU_CODIGO_PIX_AQUI' pelo código gerado no seu Mercado Pago
    bot.send_message(call.message.chat.id, texto_pix, parse_mode="Markdown")

# --- FLUXO DE DOWNLOAD (TRAVA 720p + NOVOS BOTÕES) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    # Bloqueio com os 3 botões de planos diretamente
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(
            message, 
            "⚠️ **Limite atingido!**\n\nEscolha um plano abaixo para continuar baixando agora:", 
            parse_mode="Markdown", 
            reply_markup=menu_pagamento_direto()
        )

    msg_status = bot.reply_to(message, "⏳ Processando link em HD...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"

    try:
        # Mantida a configuração de 720p que gerou o arquivo de 1.20MB
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
                bot.send_video(message.chat.id, f, caption="✅ Vídeo HD (720p) pronto!")
            
            if not vip:
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            bot.edit_message_text("❌ Erro ao gerar vídeo.", message.chat.id, msg_status.message_id)

    except Exception:
        bot.edit_message_text("❌ Erro no download.", message.chat.id, msg_status.message_id)
    
    finally:
        if os.path.exists(file_name): os.remove(file_name)
        try: bot.delete_message(message.chat.id, msg_status.message_id)
        except: pass

# --- SERVER ---
@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
