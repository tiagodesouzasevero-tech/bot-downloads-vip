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

# --- FUNÇÕES DE USUÁRIO ---
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

# --- COMANDOS ADMIN ---
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
            bot.send_message(alvo_id, f"🎉 **PAGAMENTO CONFIRMADO!**\nSeu acesso VIP foi liberado. Aproveite! 🚀")
        except:
            bot.reply_to(message, "❌ Use: `/darvip ID DIAS`", parse_mode="Markdown")

# --- INTERFACE ---
@bot.message_handler(commands=['start', 'perfil'])
def start(message):
    user = obter_usuario(message.from_user.id)
    vip = is_vip(message.from_user.id)
    status = "💎 **STATUS: VIP PRO**" if vip else f"👤 **STATUS: GRÁTIS** ({user.get('downloads_hoje', 0)}/5)"
    
    texto_welcome = (
        f"🚀 **Bem-vindo ao AfiliadoClip Pro!**\n\n"
        f"Baixe vídeos em **HD** do:\n"
        f"🔹 **TikTok**\n🔹 **Pinterest**\n🔹 **RedNote**\n\n"
        f"⚡️ **Regras do Bot:**\n"
        f"• Limite de duração: **90 segundos**\n"
        f"• Sua ID: `{message.from_user.id}`\n\n"
        f"{status}\n\n"
        f"🔗 Envie o link do vídeo para começar!"
    )
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("💎 Planos VIP", "🛠 Suporte")
    bot.send_message(message.chat.id, texto_welcome, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "💎 Planos VIP")
def mostrar_planos(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("💳 VIP Mensal - R$ 10,00", callback_data="pay_10.00"),
        types.InlineKeyboardButton("💳 VIP Anual - R$ 69,90", callback_data="pay_69.90"),
        types.InlineKeyboardButton("💎 VIP Vitalício - R$ 197,00", callback_data="pay_197.00")
    )
    bot.send_message(message.chat.id, "Escolha o melhor plano para você:", reply_markup=markup)

@bot.message_handler(func=lambda m: m.text == "🛠 Suporte")
def suporte_link(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Chamar no Suporte", url=LINK_SUPORTE))
    bot.send_message(message.chat.id, "👋 Precisa de ajuda ou ativação?\nClique abaixo:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def pagamento_manual(call):
    valor = call.data.split("_")[1]
    bot.answer_callback_query(call.id)
    msg = (f"💎 **Plano: R$ {valor}**\n\nPix Copia e Cola:\n`{CHAVE_PIX_INFINITE}`\n\n"
           f"⚠️ Envie o comprovante e sua ID: `{call.from_user.id}`")
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 Enviar Comprovante", url=LINK_SUPORTE))
    bot.send_message(call.message.chat.id, msg, parse_mode="Markdown", reply_markup=markup)

# --- DOWNLOADER (RESTAURADO + AJUSTE PINTEREST) ---
@bot.message_handler(func=lambda message: "http" in message.text)
def handle_download(message):
    user = obter_usuario(message.from_user.id)
    
    if not is_vip(message.from_user.id) and user.get("downloads_hoje", 0) >= 5:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💎 Ver Planos VIP", callback_data="mostrar_planos_bt"))
        return bot.reply_to(message, "⚠️ **Limite atingido!**\nUse um dos planos para continuar.", reply_markup=markup, parse_mode="Markdown")

    status_msg = bot.reply_to(message, "⏳ Analisando vídeo...")
    url = message.text.split()[0]
    file_name = f"v_{message.from_user.id}.mp4"
    deve_apagar_status = True 

    try:
        # Extração de informações básica
        with yt_dlp.YoutubeDL({'quiet': True, 'nocheckcertificate': True}) as ydl:
            info = ydl.extract_info(url, download=False)
            duration = info.get('duration', 0)

            if duration > 90:
                deve_apagar_status = False 
                bot.edit_message_text(f"⚠️ **Vídeo muito longo!**\nO limite é de 90s. Este vídeo tem {int(duration)}s.", message.chat.id, status_msg.message_id, parse_mode="Markdown")
                return

        bot.edit_message_text("📥 Baixando vídeo...", message.chat.id, status_msg.message_id)

        # Configuração de Formato com Prioridade (Resolve erro do Pinterest)
        ydl_opts = {
            'format': 'bestvideo[height<=1280][ext=mp4]+bestaudio[ext=m4a]/best[height<=1280][ext=mp4]/best[ext=mp4]/best',
            'outtmpl': file_name,
            'nocheckcertificate': True, 
            'quiet': True,
            'noplaylist': True,
            'merge_output_format': 'mp4'
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception:
            # Fallback final se for Pinterest
            if "pin.it" in url or "pinterest" in url:
                bot.edit_message_text("📥 Otimizando formato...", message.chat.id, status_msg.message_id)
                ydl_opts['format'] = 'best'
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
            else:
                raise

        if os.path.exists(file_name):
            with open(file_name, 'rb') as f:
                bot.send_video(message.chat.id, f, caption="✅ Enviado com AfiliadoClip Pro!")
            if not is_vip(message.from_user.id):
                usuarios_col.update_one({"_id": user["_id"]}, {"$inc": {"downloads_hoje": 1}})
        else:
            bot.edit_message_text("❌ Erro ao processar arquivo.", message.chat.id, status_msg.message_id)
            deve_apagar_status = False
    except Exception as e:
        print(f"Erro: {e}")
        bot.edit_message_text("❌ Link inválido ou formato não suportado.", message.chat.id, status_msg.message_id)
        deve_apagar_status = False
    finally:
        if os.path.exists(file_name): os.remove(file_name)
        if deve_apagar_status:
            try: bot.delete_message(message.chat.id, status_msg.message_id)
            except: pass

@bot.callback_query_handler(func=lambda call: call.data == "mostrar_planos_bt")
def callback_planos(call):
    mostrar_planos(call.message)

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))).start()
    bot.infinity_polling(skip_pending=True)
