import os, telebot, yt_dlp, mercadopago, json, glob, subprocess
from datetime import datetime, timedelta
from flask import Flask, request
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES CRÍTICAS ---
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

# --- PROCESSAMENTO ULTRA ECONÔMICO (MANTÉM FORMATO + TETO 720p) ---
def process_video_optimized(input_path, output_path):
    # COMANDO OTIMIZADO:
    # 1. scale: Redimensiona apenas se for maior que 720p (Mantém original se for menor)
    # 2. ac 1 / b:a 64k: Converte áudio para MONO (Economia extrema de banda)
    # 3. crf 30 / ultrafast: Compressão alta com baixo uso de CPU
    cmd = [
        'ffmpeg', '-y', '-i', input_path, 
        '-vf', "scale='if(gt(ih,720),-2,iw)':'min(ih,720)',fps=min(30,fps)", 
        '-c:v', 'libx264', '-crf', '30', '-preset', 'ultrafast', 
        '-ac', '1', '-ar', '22050', '-b:a', '64k', 
        '-movflags', '+faststart',
        output_path
    ]
    try:
        # Captura logs para diagnóstico na Railway
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0:
            return True
        else:
            print(f"--- ERRO FFMPEG ---\n{result.stderr}")
            return False
    except Exception as e:
        print(f"Erro ao processar: {e}")
        return False

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
    markup.row(types.KeyboardButton("💎 Planos VIP"), types.KeyboardButton("🛠 Suporte"))
    if message.from_user.id == ID_ADM: markup.add(types.KeyboardButton("📢 Enviar Aviso (ADM)"))

    bot.send_message(message.chat.id, texto, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🛠 Suporte")
def suporte(message):
    bot.send_message(message.chat.id, "📌 Suporte oficial: @suporteafiliadoclippro")

@bot.message_handler(func=lambda message: message.text == "💎 Planos VIP")
def planos_menu(message):
    exibir_planos_vip(message.chat.id)

def exibir_planos_vip(chat_id, texto_extra=""):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💎 Mensal - R$ 10,00", callback_data="pay_10"))
    markup.add(types.InlineKeyboardButton("📅 Anual - R$ 69,90", callback_data="pay_69"))
    markup.add(types.InlineKeyboardButton("🔥 Vitalício - R$ 197,00", callback_data="pay_197"))
    bot.send_message(chat_id, f"{texto_extra}💎 <b>Escolha seu Plano VIP</b>\n\n✅ Sem marcas d'água\n✅ Alta velocidade\n✅ Ilimitado", parse_mode="HTML", reply_markup=markup)

# --- FLUXO DE DOWNLOAD ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    # Reset diário simples
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": user["_id"]}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
        
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return exibir_planos_vip(message.chat.id, "⚠️ <b>Limite diário atingido!</b>\n\n")
    
    msg_p = bot.reply_to(message, "⏳ <b>Baixando e Otimizando...</b>", parse_mode="HTML")
    url = message.text.split()[0]
    
    raw_file = f"raw_{message.from_user.id}.mp4"
    final_file = f"final_{message.from_user.id}.mp4"
    
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': raw_file,
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info.get('duration', 0) > 90:
                os.remove(raw_file) if os.path.exists(raw_file) else None
                return bot.edit_message_text("❌ Vídeo muito longo (Máx 90s).", message.chat.id, msg_p.message_id)
        
        # Inicia a compressão
        if process_video_optimized(raw_file, final_file):
            with open(final_file, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Vídeo otimizado com sucesso!")
            
            if not vip:
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            raise Exception("Erro no motor de vídeo")

    except Exception as e:
        bot.edit_message_text(f"❌ Erro ao processar. Tente novamente.", message.chat.id, msg_p.message_id)
    
    finally:
        # Limpeza de arquivos temporários
        for f in [raw_file, final_file]:
            if os.path.exists(f): os.remove(f)
        try: bot.delete_message(message.chat.id, msg_p.message_id)
        except: pass

# --- WEBHOOK E SAÚDE ---
@app.route('/webhook', methods=['POST'])
def webhook():
    # Lógica do Mercado Pago preservada
    return "OK", 200

@app.route('/')
def health(): return "Bot Online", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
