import os, telebot, yt_dlp, mercadopago, json, glob, subprocess
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES CRÍTICAS (MANTIDAS) ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

# --- FUNÇÕES DE SUPORTE (MANTIDAS) ---
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
    except:
        return False

# --- PROCESSAMENTO DE VÍDEO (MANTIDO) ---
def process_video_standard(input_path, output_path):
    video_filter = (
        "scale='min(720,iw)':-2,"
        "scale=-2:'min(1280,ih)',"
        "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,"
        "fps=30"
    )
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-vf', video_filter,
        '-c:v', 'libx264', '-crf', '23', '-preset', 'veryfast',
        '-c:a', 'copy', output_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except Exception as e:
        print(f"Erro FFmpeg: {e}")
        return False

# --- FUNÇÃO PARA GERAR PAGAMENTO PIX ---
def gerar_pix(user_id, valor, titulo):
    payment_data = {
        "transaction_amount": valor,
        "description": titulo,
        "payment_method_id": "pix",
        "external_reference": str(user_id),
        "payer": {
            "email": f"user_{user_id}@afiliadoclip.com"
        }
    }
    payment_response = sdk.payment().create(payment_data)
    return payment_response["response"].get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")

# --- EXIBIÇÃO IMEDIATA DE PLANOS (MENSAGEM REQUISITADA) ---
def exibir_planos_vip(chat_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💎 Mensal - R$ 10,00", callback_data="pay_10"))
    markup.add(types.InlineKeyboardButton("📅 Anual - R$ 69,90", callback_data="pay_69"))
    markup.add(types.InlineKeyboardButton("🔥 Vitalício - R$ 197,00", callback_data="pay_197"))
    
    texto_vip = (
        "⚠️ <b>Limite diário de 5 downloads atingido!</b>\n\n"
        "💎 <b>Escolha seu Plano VIP</b>\n\n"
        "✅ Downloads Ilimitados\n"
        "✅ Sem filas de espera\n"
        "✅ Suporte Prioritário\n"
        "✅ Acesso Vitalício opcional\n\n"
        "Selecione uma das opções abaixo para ativar agora via PIX:"
    )
    bot.send_message(chat_id, texto_vip, parse_mode="HTML", reply_markup=markup)

# --- CALLBACKS DE PAGAMENTO ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def processar_pagamento(call):
    valores = {"pay_10": (10.00, "VIP Mensal"), "pay_69": (69.90, "VIP Anual"), "pay_197": (197.00, "VIP Vitalicio")}
    valor, titulo = valores[call.data]
    
    bot.answer_callback_query(call.id, "Gerando código PIX...")
    pix_code = gerar_pix(call.from_user.id, valor, titulo)
    
    if pix_code:
        msg_pix = (
            f"✅ <b>Pagamento Gerado!</b>\n\n"
            f"Plano: {titulo}\n"
            f"Valor: R$ {valor:.2f}\n\n"
            f"<code>{pix_code}</code>\n\n"
            f"👆 Clique no código acima para copiar.\n"
            f"Após o pagamento, o acesso VIP será liberado automaticamente."
        )
        bot.send_message(call.message.chat.id, msg_pix, parse_mode="HTML")
    else:
        bot.send_message(call.message.chat.id, "❌ Erro ao gerar PIX. Tente novamente.")

# --- COMANDO /START (MANTIDO) ---
@bot.message_handler(commands=['start', 'perfil'])
def send_welcome(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    if vip:
        status_info = "💎 VIP PRO – Download ilimitado"
    else:
        restantes = 5 - user.get('downloads_hoje', 0)
        restantes = max(0, restantes)
        status_info = f"👤 Gratuito – {restantes}/5 downloads disponíveis hoje"
    
    texto = (
        f"🚀 <b>AfiliadoClip Pro</b>\n\n"
        f"{status_info}\n\n"
        f"🔗 <b>Envie um link do TikTok, Pinterest ou RedNote:</b>\n"
        f"⚠️ É suportado vídeos com no máximo 90 segundos"
    )
    bot.send_message(message.chat.id, texto, parse_mode="HTML")

# --- DOWNLOADER (CONTROLE DE LIMITE ALTERADO) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": user["_id"]}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
        
    if not vip and user.get("downloads_hoje", 0) >= 5:
        # Chama imediatamente a nova exibição de planos ao atingir o limite
        return exibir_planos_vip(message.chat.id)
        
    msg_p = bot.reply_to(message, "✅ Seu link foi adicionado à fila de download! Por favor, aguarde alguns instantes!", parse_mode="HTML")
    
    url = message.text.split()[0]
    raw_file = f"raw_{message.from_user.id}_{message.message_id}.mp4"
    final_file = f"final_{message.from_user.id}_{message.message_id}.mp4"
    ydl_opts = {'format': 'bestvideo+bestaudio/best', 'outtmpl': raw_file, 'merge_output_format': 'mp4', 'quiet': True}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get('duration', 0) > 90:
                if os.path.exists(raw_file): os.remove(raw_file)
                return bot.edit_message_text("❌ Vídeo acima de 90 segundos.", message.chat.id, msg_p.message_id)

        if process_video_standard(raw_file, final_file):
            with open(final_file, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="Vídeo baixado com sucesso 🤝")
            
            if not vip:
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
            
            for file in [raw_file, final_file]:
                if os.path.exists(file): os.remove(file)
            bot.delete_message(message.chat.id, msg_p.message_id)
        else:
            raise Exception("Erro FFmpeg")
    except Exception as e:
        bot.edit_message_text("❌ Erro ao processar. Tente outro link.", message.chat.id, msg_p.message_id)
        if os.path.exists(raw_file): os.remove(raw_file)

# --- WEBHOOK (SISTEMA DE PAGAMENTO MANTIDO) ---
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
                # Lógica de expiração baseada no plano
                if "Vitalicio" in desc:
                    expira = "Vitalício"
                elif "Anual" in desc:
                    expira = (datetime.now() + timedelta(days=365)).strftime('%Y-%m-%d')
                else:
                    expira = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
                
                usuarios_col.update_one({"_id": str(user_id)}, {"$set": {"vip_ate": expira}})
                bot.send_message(user_id, "✅ <b>VIP Ativado!</b> Aproveite downloads ilimitados.")
    return "OK", 200

@app.route('/')
def health(): return "AfiliadoClip Pro Online", 200

def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
