import os, telebot, yt_dlp, json
from datetime import datetime, timedelta
from flask import Flask
from threading import Thread
from telebot import types
from pymongo import MongoClient

# --- CONFIGURAÇÕES ---
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

# --- FUNÇÕES DE USUÁRIO (COM RESET DIÁRIO) ---
def obter_usuario(user_id):
    uid = str(user_id)
    user = usuarios_col.find_one({"_id": uid})
    hoje = datetime.now().strftime('%Y-%m-%d')
    
    if not user:
        user = {"_id": uid, "vip_ate": None, "downloads_hoje": 0, "ultima_data": hoje}
        usuarios_col.insert_one(user)
    elif user.get("ultima_data") != hoje:
        # Reseta o contador se mudou o dia
        usuarios_col.update_one({"_id": uid}, {"$set": {"downloads_hoje": 0, "ultima_data": hoje}})
        user["downloads_hoje"] = 0
    return user

def is_vip(user_id):
    user = obter_usuario(user_id)
    v_ate = user.get("vip_ate")
    if v_ate == "Vitalício": return True
    if not v_ate: return False
    try:
        return datetime.now() < datetime.strptime(v_ate, '%Y-%m-%d')
    except: return False

# --- COMANDOS ADMIN ---
@bot.message_handler(commands=['darvip'])
def dar_vip_manual(message):
    if message.from_user.id == ADMIN_ID:
        try:
            args = message.text.split()
            alvo_id, dias = args[1], int(args[2])
            nova_data = "Vitalício" if dias >= 3650 else (datetime.now() + timedelta(days=dias)).strftime('%Y-%m-%d')
            usuarios_col.update_one({"_id": str(alvo_id)}, {"$set": {"vip_ate": nova_data}})
            bot.reply_to(message, f"✅ VIP liberado para {alvo_id} até {nova_data}!")
            bot.send_message(alvo_id, f"🎉 **PAGAMENTO CONFIRMADO!**\nSeu acesso VIP foi liberado.")
        except: bot.reply_to(message, "❌ Use: `/darvip ID DIAS`")

@bot.message_handler(commands=['avisogeral'])
def aviso_geral(message):
    if message.from_user.id == ADMIN_ID:
        msg_texto = message.text.replace('/avisogeral', '').strip()
        if not msg_texto: return bot.reply_to(message, "❌ Digite a mensagem após o comando.")
        usuarios = usuarios_col.find({}, {"_id": 1})
        cont = 0
        for u in usuarios:
            try:
                bot.send_message(u["_id"], msg_texto, parse_mode="Markdown")
                cont += 1
            except: pass
        bot.reply_to(message, f"📢 Enviado para {cont} usuários!")

# --- INTERFACE ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 **STATUS: VIP PRO**" if vip else f"👤 **STATUS: GRÁTIS** ({user.get('downloads_hoje', 0)}/5)"
    
    texto = (f"🚀 **AfiliadoClip Pro**\n\nBaixe do TikTok, Pinterest e RedNote em HD.\n\n"
             f"• Duração máx: 90s\n• Sua ID: `{message.from_user.id}`\n\n{status}")
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, texto, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💎 Planos VIP")
def mostrar_planos(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 VIP Mensal - R$ 10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💳 VIP Anual - R$ 69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 VIP Vitalício - R$ 197,00", callback_data="pay_197.00")
    )
    bot.send_message(message.chat.id, "Escolha seu plano:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛠 Suporte")
def suporte(message):
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("Chamar no Suporte", url=LINK_SUPORTE))
    bot.send_message(message.chat.id, "👋 Precisa de ajuda?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def pag_manual(call):
    valor = call.data.split("_")[1]
    msg = (f"💎 **Plano: R$ {valor}**\n\nPix Copia e Cola:\n`{CHAVE_PIX_INFINITE}`\n\n"
           f"⚠️ Envie o comprovante e sua ID: `{call.from_user.id}`")
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("📤 Enviar Comprovante", url=LINK_SUPORTE))
    bot.send_message(call.message.chat.id, msg, parse_mode="Markdown", reply_markup=markup)

# --- DOWNLOADER (REGRAS DE VÍDEO VERTICAL) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    if not is_vip(message.from_user.id) and user.get("downloads_hoje", 0) >= 5:
        return bot.reply_to(message, "⚠️ **Limite atingido!** Adquira o VIP.")

    status_msg = bot.reply_to(message, "⏳ Analisando...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"

    try:
        with yt_dlp.YoutubeDL({'quiet': True, 'nocheckcertificate': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get('duration', 0) > 90:
                return bot.edit_message_text("⚠️ Vídeo muito longo (máx 90s).", message.chat.id, status_msg.message_id)

        bot.edit_message_text("📥 Baixando vídeo...", message.chat.id, status_msg.message_id)
        
        # PRIORIDADE: 1280x720 Vertical e MP4
        ydl_opts = {
            'format': 'bestvideo[height=1280][width=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height>=1024][width>=576][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': file_name, 'nocheckcertificate': True, 'quiet': True, 'noplaylist': True, 'merge_output_format': 'mp4'
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
        except:
            if "pin" in url or "pinterest" in url:
                ydl_opts['format'] = 'best'
                with yt_dlp.YoutubeDL(ydl_opts) as ydl: ydl.download([url])
            else: raise Exception

        if os.path.exists(file_name):
            with open(file_name, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Enviado por @AfiliadoClipProBot")
            if not is_vip(message.from_user.id):
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        bot.delete_message(message.chat.id, status_msg.message_id)
    except:
        bot.edit_message_text("❌ Erro no link ou formato.", message.chat.id, status_msg.message_id)
    finally:
        if os.path.exists(file_name): os.remove(file_name)

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
