import os, telebot, yt_dlp, mercadopago, json, glob, subprocess
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES CRÍTICAS (PRESERVADAS E VALIDADAS) ---
TOKEN_TELEGRAM = "8629536333:AAHjRGGxSm_Fc_WnAv8a2qLItCC_-bMUWqY"
MP_ACCESS_TOKEN = "APP_USR-8179041093511853-031916-7364f07318b6c464600a781433c743f7-384532659"
MONGO_URI = "mongodb+srv://tiagodesouzasevero_db_user:rdS2qlLSlH7eI9jA@cluster0.x3wiavb.mongodb.net/bot_downloader?retryWrites=true&w=majority&tlsAllowInvalidCertificates=true"
ID_ADM = 493336271 

client = MongoClient(MONGO_URI)
db = client.get_default_database()
usuarios_col = db["usuarios"]
bot = telebot.TeleBot(TOKEN_TELEGRAM, threaded=False)
app = Flask(__name__)
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

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
    except:
        return False

# --- PROCESSAMENTO ECONOMIA EXTREMA (MANTÉM FORMATO ORIGINAL + TETO 720p) ---
def process_video_optimized(input_path, output_path):
    # LÓGICA:
    # 1. scale: Se maior que 720p, reduz para 720p. Se menor, mantém original (ECONOMIZA CPU).
    # 2. fps: Trava em no máximo 30fps.
    # 3. Áudio: Converte para Mono (-ac 1) e reduz bitrate para 64k (ECONOMIZA BANDA).
    # 4. Compressão: CRF 30 e Preset Ultrafast (ECONOMIZA DINHEIRO NA RAILWAY).
    cmd = [
        'ffmpeg', '-y', '-i', input_path, 
        '-vf', "scale='if(gt(ih,720),-2,iw)':'min(ih,720)',fps=min(30,fps)", 
        '-c:v', 'libx264', '-crf', '30', '-preset', 'ultrafast', 
        '-ac', '1', '-ar', '22050', '-b:a', '64k', output_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except:
        return False

# --- SISTEMA DE PAGAMENTO ---
def gerar_pix(user_id, valor, titulo):
    payment_data = {
        "transaction_amount": valor, 
        "description": titulo, 
        "payment_method_id": "pix", 
        "external_reference": str(user_id), 
        "payer": {"email": f"user_{user_id}@afiliadoclip.com"}
    }
    payment_response = sdk.payment().create(payment_data)
    return payment_response["response"].get("point_of_interaction", {}).get("transaction_data", {}).get("qr_code")

def exibir_planos_vip(chat_id, texto_extra=""):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💎 Mensal - R$ 10,00", callback_data="pay_10"))
    markup.add(types.InlineKeyboardButton("📅 Anual - R$ 69,90", callback_data="pay_69"))
    markup.add(types.InlineKeyboardButton("🔥 Vitalício - R$ 197,00", callback_data="pay_197"))
    texto_vip = f"{texto_extra}💎 <b>Escolha seu Plano VIP</b>\n\n✅ Downloads Ilimitados\n✅ Alta Velocidade\n✅ Sem Marcas d'Água\n\nSelecione uma opção:"
    bot.send_message(chat_id, texto_vip, parse_mode="HTML", reply_markup=markup)

# --- INTERFACE E COMANDOS ---
@bot.message_handler(commands=['start', 'perfil', 'meuadm'])
def send_welcome(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    if message.text == "/meuadm" and message.from_user.id == ID_ADM:
        return admin_aviso(message)

    status_info = "💎 VIP PRO – Ilimitado" if vip else f"👤 Grátis – {max(0, 5 - user.get('downloads_hoje', 0))}/5 hoje"
    
    texto = f"🚀 <b>AfiliadoClip Pro</b>\n\n{status_info}\n\n🔗 <b>Envie um link do TikTok, Pinterest ou RedNote:</b>"

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_planos = types.KeyboardButton("💎 Planos VIP")
    btn_suporte = types.KeyboardButton("🛠 Suporte")
    markup.row(btn_planos, btn_suporte)
    
    if message.from_user.id == ID_ADM:
        btn_adm = types.KeyboardButton("📢 Enviar Aviso (ADM)")
        markup.add(btn_adm)

    bot.send_message(message.chat.id, texto, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🛠 Suporte")
def suporte(message):
    bot.send_message(message.chat.id, "📌 Suporte oficial: @suporteafiliadoclippro")

@bot.message_handler(func=lambda message: message.text == "💎 Planos VIP")
def planos_menu(message):
    exibir_planos_vip(message.chat.id)

@bot.message_handler(func=lambda message: message.text == "📢 Enviar Aviso (ADM)")
def admin_aviso(message):
    if message.from_user.id == ID_ADM:
        msg = bot.send_message(message.chat.id, "📝 Digite a mensagem para TODOS os usuários:")
        bot.register_next_step_handler(msg, enviar_massa)

def enviar_massa(message):
    usuarios = usuarios_col.find()
    cont = 0
    for u in usuarios:
        try:
            bot.send_message(u["_id"], message.text)
            cont += 1
        except: pass
    bot.send_message(ID_ADM, f"✅ Enviado para {cont} usuários!")

# --- FLUXO DE DOWNLOAD ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    if user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": user["_id"]}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
        
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return exibir_planos_vip(message.chat.id, "⚠️ <b>Limite atingido!</b>\n\n")
    
    msg_p = bot.reply_to(message, "⏳ Processando...", parse_mode="HTML")
    url = message.text.split()[0]
    raw_file = f"raw_{message.from_user.id}_{message.message_id}.mp4"
    final_file = f"final_{message.from_user.id}_{message.message_id}.mp4"
    
    ydl_opts = {'format': 'bestvideo+bestaudio/best', 'outtmpl': raw_file, 'merge_output_format': 'mp4', 'quiet': True}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # TRAVA DE 90 SEGUNDOS PRESERVADA
            if info.get('duration', 0) > 90:
                if os.path.exists(raw_file): os.remove(raw_file)
                return bot.edit_message_text("❌ Máximo 90 segundos.", message.chat.id, msg_p.message_id)
        
        if process_video_optimized(raw_file, final_file):
            with open(final_file, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Vídeo pronto!")
            
            if not vip: 
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
            
            for f in [raw_file, final_file]:
                if os.path.exists(f): os.remove(f)
            bot.delete_message(message.chat.id, msg_p.message_id)
        else: raise Exception()
    except:
        bot.edit_message_text("❌ Erro ao processar.", message.chat.id, msg_p.message_id)
        if os.path.exists(raw_file): os.remove(raw_file)

# --- WEBHOOK ---
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
                expira = "Vitalício" if "Vitalicio" in desc else (datetime.now() + timedelta(days=365 if "Anual" in desc else 30)).strftime('%Y-%m-%d')
                usuarios_col.update_one({"_id": str(user_id)}, {"$set": {"vip_ate": expira}})
                bot.send_message(user_id, "✅ <b>VIP Ativado!</b>")
    return "OK", 200

@app.route('/')
def health(): return "Online", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
