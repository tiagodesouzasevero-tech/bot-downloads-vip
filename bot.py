import os
import telebot
import yt_dlp
import mercadopago
from datetime import datetime
from telebot import types

# --- CONFIGURAÇÕES DO TIAGO (PRESERVADAS) ---
TOKEN_TELEGRAM = "8629536333:AAEV4IcvFt5CTRqQVz5yYXmNOXvcgaZygGE"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"

MEMBROS_VIP = [5130704403] 
LIMITE_GRATIS = 5
uso_usuarios = {}

bot = telebot.TeleBot(TOKEN_TELEGRAM)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- FUNÇÃO DO MERCADO PAGO (CORRIGIDA) ---
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

# --- INTERFACE VISUAL (EXATAMENTE COMO VOCÊ CONFIGUROU) ---
def exibir_menu_planos(user_id):
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user_id not in uso_usuarios or uso_usuarios.get(user_id, {}).get('last_date') != hoje:
        uso_usuarios[user_id] = {'count': 0, 'last_date': hoje}
    
    saldo = LIMITE_GRATIS - uso_usuarios[user_id]['count']
    
    if user_id in MEMBROS_VIP:
        texto = "👏 **Bot de Downloads VIP**\n\n📊 Plano: VIP Ilimitado\n📅 Validade: Vitalícia\n💡 Saldo: ∞ hoje."
    else:
        texto = f"👏 **Bot de Downloads VIP**\n\n📊 Plano: Gratuito\n📅 Validade: Nunca\n💡 Saldo: {saldo} hoje."

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
        msg = (
            f"✅ **Pix Gerado com Sucesso!**\n\n"
            f"Valor: R$ {valor_str}\n\n"
            f"Copie o código abaixo para pagar:\n\n"
            f"`{pix_copia_cola}`\n\n"
            f"💡 *O acesso é liberado após a confirmação.*"
        )
        bot.send_message(call.message.chat.id, msg, parse_mode="Markdown")
    else:
        bot.send_message(call.message.chat.id, "❌ **Erro ao gerar Pix.**\nVerifique se o token do Mercado Pago está ativo.")

@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user_id = message.from_user.id
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    if user_id not in MEMBROS_VIP:
        if user_id not in uso_usuarios or uso_usuarios[user_id]['last_date'] != hoje:
            uso_usuarios[user_id] = {'count': 0, 'last_date': hoje}
        if uso_usuarios[user_id]['count'] >= LIMITE_GRATIS:
            bot.reply_to(message, "🚫 **Limite diário atingido! Use /planos para baixar ilimitado.**")
            return

    msg_status = bot.reply_to(message, "⏳ **Baixando vídeo original...**")

    try:
        ydl_opts = {'format': 'best', 'outtmpl': 'video_%(id)s.%(ext)s', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(message.text, download=True)
            filename = ydl.prepare_filename(info)
            with open(filename, 'rb') as video:
                bot.send_video(message.chat.id, video, caption="✅ **Vídeo Original Baixado!**")
            os.remove(filename)
            bot.delete_message(message.chat.id, msg_status.message_id)
            if user_id not in MEMBROS_VIP:
                uso_usuarios[user_id]['count'] += 1
    except:
        bot.edit_message_text("❌ Erro ao baixar. O link pode ser privado ou inválido.", message.chat.id, msg_status.message_id)

print("✅ Bot de Downloads VIP Online!")
bot.infinity_polling()
