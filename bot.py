import os
import telebot
import yt_dlp
import mercadopago
from datetime import datetime
from telebot import types

# --- CONFIGURAÇÕES PRESERVADAS ---
TOKEN_TELEGRAM = "8629536333:AAEV4IcvFt5CTRqQVz5yYXmNOXvcgaZygGE"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"

MEMBROS_VIP = [5130704403] 
LIMITE_GRATIS = 5
uso_usuarios = {}

bot = telebot.TeleBot(TOKEN_TELEGRAM)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

def gerar_pix_mp(valor, descricao):
    payment_data = {
        "transaction_amount": float(valor),
        "description": descricao,
        "payment_method_id": "pix",
        "installments": 1,
        "payer": {
            "email": "tiago_afiliados@email.com",
            "first_name": "Assinante",
            "last_name": "VIP"
        }
    }
    result = sdk.payment().create(payment_data)
    if "response" in result and "point_of_interaction" in result["response"]:
        return result["response"]["point_of_interaction"]["transaction_data"]["qr_code"]
    return None

def exibir_menu_planos(user_id):
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user_id not in uso_usuarios or uso_usuarios.get(user_id, {}).get('last_date') != hoje:
        uso_usuarios[user_id] = {'count': 0, 'last_date': hoje}
    
    saldo = LIMITE_GRATIS - uso_usuarios[user_id]['count']
    texto = f"👏 **Bot de Downloads VIP**\n\n📊 Plano: {'VIP Ilimitado' if user_id in MEMBROS_VIP else 'Gratuito'}\n📅 Validade: {'Vitalícia' if user_id in MEMBROS_VIP else 'Nunca'}\n💡 Saldo: {'∞' if user_id in MEMBROS_VIP else saldo} hoje."

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 Mensal - R$10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("🌟 Anual - R$69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 Vitalício - R$1.900,00", callback_data="pay_1900.00")
    )
    return texto, markup

@bot.message_handler(commands=['start', 'planos'])
def send_welcome(message):
    texto, markup = exibir_menu_planos(message.from_user.id)
    bot.send_message(message.chat.id, texto, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def handle_payment(call):
    valor_str = call.data.split("_")[1]
    bot.answer_callback_query(call.id, "Gerando Pix...")
    pix_copia_cola = gerar_pix_mp(valor_str, f"Plano {valor_str} - Downloader Afiliados")
    if pix_copia_cola:
        bot.send_message(call.message.chat.id, f"✅ **Pix Gerado!**\n\n`{pix_copia_cola}`", parse_mode="Markdown")
    else:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar Pix.")

@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user_id = message.from_user.id
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    if user_id not in MEMBROS_VIP:
        if user_id not in uso_usuarios or uso_usuarios[user_id]['last_date'] != hoje:
            uso_usuarios[user_id] = {'count': 0, 'last_date': hoje}
        if uso_usuarios[user_id]['count'] >= LIMITE_GRATIS:
            bot.reply_to(message, "🚫 **Limite diário atingido! Use /planos.**")
            return

    msg_status = bot.reply_to(message, "⏳ **Baixando vídeo original...**")

    # CONFIGURAÇÃO REFORÇADA PARA EVITAR ERROS DE LINKS
    ydl_opts = {
        'format': 'best',
        'outtmpl': 'video_%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(message.text, download=True)
            filename = ydl.prepare_filename(info)
            
            if user_id not in MEMBROS_VIP:
                uso_usuarios[user_id]['count'] += 1
                legenda = f"✅ **Baixado!**\n\n💡 Saldo atual: {uso_usuarios[user_id]['count']}/{LIMITE_GRATIS} hoje."
            else:
                legenda = "✅ **Baixado (VIP Ilimitado)!**"

            with open(filename, 'rb') as video:
                bot.send_video(message.chat.id, video, caption=legenda, parse_mode="Markdown")
            
            os.remove(filename)
            bot.delete_message(message.chat.id, msg_status.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Erro ao baixar. O link pode estar protegido ou ser privado.", message.chat.id, msg_status.message_id)

bot.infinity_polling()
