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

# --- PROCESSAMENTO DE VÍDEO (PADRONIZAÇÃO 9:16) ---
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
    
    markup = types.InlineKeyboardMarkup()
    if not vip:
        markup.add(types.InlineKeyboardButton("💎 Ativar VIP Ilimitado", callback_data="upgrade_vip"))
    
    bot.send_message(message.chat.id, texto, parse_mode="HTML", reply_markup=markup)

# --- CORREÇÃO DO BOTÃO VIP (EXIBIR PLANOS) ---
@bot.callback_query_handler(func=lambda call: call.data == "upgrade_vip")
def show_plans(call):
    markup = types.InlineKeyboardMarkup()
    # Links de pagamento integrados ao seu external_reference (ID do usuário)
    # Nota: Certifique-se de que as URLs de pagamento do Mercado Pago estejam corretas
    btn_mensal = types.InlineKeyboardButton("💎 VIP Mensal - R$ 19,90", url=f"https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=SEU_PREF_ID_MENSAL&external_reference={call.from_user.id}")
    btn_vitalicio = types.InlineKeyboardButton("🔥 VIP Vitalício - R$ 49,90", url=f"https://www.mercadopago.com.br/checkout/v1/redirect?pref_id=SEU_PREF_ID_VITALICIO&external_reference={call.from_user.id}")
    
    markup.add(btn_mensal)
    markup.add(btn_vitalicio)
    
    texto_vip = (
        "💎 <b>Escolha seu Plano VIP</b>\n\n"
        "✅ Downloads Ilimitados\n"
        "✅ Sem filas de espera\n"
        "✅ Suporte Prioritário\n"
        "✅ Acesso Vitalício opcional\n\n"
        "Selecione uma das opções abaixo para ativar agora via PIX ou Cartão:"
    )
    
    bot.edit_message_text(texto_vip, call.message.chat.id, call.message.message_id, parse_mode="HTML", reply_markup=markup)

# --- DOWNLOADER (MANTIDO) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": user["_id"]}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
        
    if not vip:
        downloads_atuais = user.get("downloads_hoje", 0)
        if downloads_atuais >= 5:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💎 Ativar VIP Ilimitado", callback_data="upgrade_vip"))
            return bot.reply_to(message, "⚠️ <b>Limite atingido! (5/5)</b>\n\nVocê já usou seus 5 downloads gratuitos de hoje. Assine o VIP para continuar baixando sem limites!", parse_mode="HTML", reply_markup=markup)
        
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

# --- WEBHOOK E SERVIDOR (MANTIDOS) ---
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
                bot.send_message(user_id, "✅ <b>VIP Ativado!</b> Aproveite downloads ilimitados.")
    return "OK", 200

@app.route('/')
def health(): return "AfiliadoClip Pro Online", 200

def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
