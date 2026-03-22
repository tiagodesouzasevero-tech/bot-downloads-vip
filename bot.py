import os, telebot, yt_dlp, mercadopago, json, glob, subprocess
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

# --- FUNÇÃO OBRIGATÓRIA DE PROCESSAMENTO (FFMPEG DIRETO) ---
def process_video(input_path, output_path):
    print(f"🎬 Iniciando processamento: {input_path}")
    
    # Comando FFmpeg: 
    # if(gt(ih,720),720,ih) -> Se altura > 720, fixa em 720. Senão, mantém.
    # -2 -> Mantém a proporção da largura automaticamente.
    # -r 30 -> Força 30 FPS.
    cmd = [
        'ffmpeg', '-y', '-i', input_path,
        '-vf', "scale='if(gt(ih,720),-2,iw)':'if(gt(ih,720),720,ih)',fps=30",
        '-c:v', 'libx264', '-crf', '23', '-preset', 'veryfast',
        '-c:a', 'copy', output_path
    ]
    
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"✅ Processamento concluído: {output_path}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Erro no FFmpeg: {e.stderr.decode()}")
        return False

# --- DOWNLOADER v1.1.5 (FLUXO SEPARADO) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_dl(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    
    # Verificação de limites e VIP (Mantido)
    hoje = datetime.now().strftime('%Y-%m-%d')
    if user.get("ultima_data") != hoje:
        usuarios_col.update_one({"_id": user["_id"]}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
    if not vip and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ Limite diário atingido!")

    msg_p = bot.reply_to(message, "✅ Seu link foi adicionado à fila! Processando vídeo...")
    
    url = message.text.split()[0]
    raw_file = f"raw_{message.from_user.id}_{message.message_id}.mp4"
    final_file = f"final_{message.from_user.id}_{message.message_id}.mp4"
    
    # 1. DOWNLOAD (BAIXA O ORIGINAL)
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': raw_file,
        'merge_output_format': 'mp4',
        'quiet': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            duracao = info.get('duration', 0)
            
            if duracao and duracao > 90:
                if os.path.exists(raw_file): os.remove(raw_file)
                return bot.edit_message_text("❌ Vídeo acima de 90 segundos.", message.chat.id, msg_p.message_id)

        # 2. PROCESSAMENTO OBRIGATÓRIO (RESIZE E FPS)
        if process_video(raw_file, final_file):
            # 3. ENVIO (APENAS O ARQUIVO PROCESSADO)
            with open(final_file, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="Vídeo baixado com sucesso🤝")
            
            # Limpeza
            if os.path.exists(raw_file): os.remove(raw_file)
            if os.path.exists(final_file): os.remove(final_file)
            
            if not vip:
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
            bot.delete_message(message.chat.id, msg_p.message_id)
        else:
            raise Exception("Erro no processamento")
                
    except Exception as e:
        print(f"Erro Final: {e}")
        bot.edit_message_text("❌ Erro ao processar vídeo.", message.chat.id, msg_p.message_id)
        if os.path.exists(raw_file): os.remove(raw_file)

# --- FUNÇÕES DE SUPORTE E SERVER (MANTIDAS) ---
def obter_usuario(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    if not user:
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": datetime.now().strftime('%Y-%m-%d')}
        usuarios_col.insert_one(user)
    return user

def is_vip(user_id):
    user = obter_usuario(user_id)
    if user.get("vip_ate") == "Vitalício": return True
    if not user.get("vip_ate"): return False
    try: return datetime.now() < datetime.strptime(user["vip_ate"], '%Y-%m-%d')
    except: return False

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

@app.route('/')
def health(): return "Bot Online", 200
def run_flask(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    Thread(target=run_flask).start()
    bot.infinity_polling(skip_pending=True)
