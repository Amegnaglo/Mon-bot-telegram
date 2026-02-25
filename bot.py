import os
import logging
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)
import yt_dlp

# ==========================
# CONFIG
# ==========================
TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.environ.get("PORT", 5000))
COOKIE_CONTENT = os.getenv("YOUTUBE_COOKIES")  # Cookies YouTube en variable d'environnement

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

user_state = {}

# ==========================
# /start
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🇫🇷 Français", callback_data='fr')],
        [InlineKeyboardButton("🇬🇧 English", callback_data='en')]
    ]
    await update.message.reply_text(
        "Choisissez votre langue / Choose your language :",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================
# Choix langue
# ==========================
async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = query.data
    user_state[query.from_user.id] = {'lang': lang, 'history': []}
    await query.answer()
    await go_menu(query, lang=lang)

# ==========================
# Menu principal
# ==========================
async def go_menu(query, lang=None):
    if lang is None:
        user_id = query.from_user.id
        lang = user_state.get(user_id, {}).get('lang', 'fr')

    keyboard = [
        [InlineKeyboardButton("🎵 Audio", callback_data='audio')],
        [InlineKeyboardButton("🎥 Vidéo", callback_data='video')],
        [InlineKeyboardButton("📜 Historique", callback_data='history')]
    ]
    msg = "Que voulez-vous faire ?" if lang == 'fr' else "What would you like to do?"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================
# Gestion des boutons
# ==========================
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_state.get(user_id, {})
    data = query.data

    if data == 'menu':
        await go_menu(query)
        return

    if data == 'history':
        await show_history(query, state)
        return

    if data.startswith('select_'):
        index = int(data.split('_')[1])
        if 'search_results' in state and index < len(state['search_results']):
            state['query'] = state['search_results'][index]['webpage_url']
            user_state[user_id] = state
            await handle_message_after_search(query, state)
        return

    state['mode'] = data
    user_state[user_id] = state
    msg = {
        'audio': "Entrez le titre ou l’artiste 🎶 :" if state['lang'] == 'fr' else "Enter title or artist 🎶:",
        'video': "Entrez le lien, titre ou nom de vidéo 🎬 :" if state['lang'] == 'fr' else "Enter link, title or name 🎬:"
    }
    if data in ['audio', 'video']:
        await query.edit_message_text(msg[data])

# ==========================
# Historique
# ==========================
async def show_history(query, state):
    history = state.get('history', [])
    if not history:
        msg = "Aucun téléchargement pour le moment." if state.get('lang') == 'fr' else "No downloads yet."
    else:
        msg_lines = [f"{i+1}. [{h['title']}]({h['url']}) ({h['type']})" for i, h in enumerate(history)]
        msg = "\n".join(msg_lines)
    await query.edit_message_text(msg, parse_mode='Markdown')

# ==========================
# Gestion des messages
# ==========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = user_state.get(user_id, {})
    state['query'] = update.message.text
    user_state[user_id] = state

    if update.message.text.startswith("http://") or update.message.text.startswith("https://"):
        await handle_message_after_search(update.message, state)
        return

    await do_search(update.message, state)

# ==========================
# Recherche YouTube avec cookies
# ==========================
async def do_search(message, state):
    query_text = state['query']

    # Crée un fichier temporaire pour les cookies
    with tempfile.NamedTemporaryFile(delete=False) as tmp_cookie:
        tmp_cookie.write(COOKIE_CONTENT.encode())
        tmp_cookie_path = tmp_cookie.name

    ydl_opts = {
        'quiet': True,
        'noplaylist': True,
        'cookiefile': tmp_cookie_path
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{query_text}", download=False)
            videos = info['entries'][:5]
            state['search_results'] = videos
            user_state[message.from_user.id] = state

            keyboard = [[InlineKeyboardButton(f"{i+1}. {v['title'][:50]}", callback_data=f'select_{i}')] for i, v in enumerate(videos)]
            keyboard.append([InlineKeyboardButton("⬅️ Menu", callback_data='menu')])
            text = "Résultats trouvés : choisissez la vidéo :" if state['lang'] == 'fr' else "Results found: choose the video:"
            await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        await message.reply_text("Erreur lors de la recherche : " + str(e))
    finally:
        os.unlink(tmp_cookie_path)

# ==========================
# Boutons qualité dynamiques
# ==========================
async def handle_message_after_search(obj, state):
    query_text = state.get('query')
    mode = state.get('mode')

    with tempfile.NamedTemporaryFile(delete=False) as tmp_cookie:
        tmp_cookie.write(COOKIE_CONTENT.encode())
        tmp_cookie_path = tmp_cookie.name

    ydl_opts = {'quiet': True, 'noplaylist': True, 'cookiefile': tmp_cookie_path}
    buttons = []

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query_text, download=False)

            if mode == 'audio':
                buttons = [[InlineKeyboardButton("MP3", callback_data='bestaudio')]]
            else:
                # Vidéo : récupérer toutes les résolutions disponibles
                video_formats = [
                    f for f in info.get('formats', [])
                    if f.get('vcodec') != 'none' and f.get('height') is not None
                ]
                unique_res = {}
                for f in video_formats:
                    if f['height'] not in unique_res:
                        unique_res[f['height']] = f['format_id']

                for height in sorted(unique_res.keys(), reverse=True):
                    buttons.append([InlineKeyboardButton(f"{height}p", callback_data=f"format_{unique_res[height]}")])

            buttons.append([InlineKeyboardButton("⬅️ Menu", callback_data='menu')])

            text = "Choisissez la qualité :" if state.get('lang') == 'fr' else "Choose quality:"
            if hasattr(obj, 'reply_text'):
                await obj.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
            else:
                await obj.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons))

    except Exception as e:
        await obj.reply_text("Erreur : " + str(e))
    finally:
        os.unlink(tmp_cookie_path)

# ==========================
# Téléchargement et envoi
# ==========================
async def quality_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_state.get(user_id, {})
    query_text = state.get('query')
    mode = state.get('mode')

    # Déterminer la qualité choisie
    data = query.data
    if mode == 'audio' and data == 'bestaudio':
        quality = 'bestaudio'
    else:
        quality = data.replace("format_", "")

    with tempfile.TemporaryDirectory() as tmpdir:
        with tempfile.NamedTemporaryFile(delete=False) as tmp_cookie:
            tmp_cookie.write(COOKIE_CONTENT.encode())
            tmp_cookie_path = tmp_cookie.name

        ydl_opts = {
            'outtmpl': f'{tmpdir}/%(title).50s.%(ext)s',
            'format': quality,
            'noplaylist': True,
            'quiet': True,
            'cookiefile': tmp_cookie_path
        }

        if mode == 'audio':
            ydl_opts['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query_text, download=True)
                filename = ydl.prepare_filename(info)
                if mode == 'audio':
                    filename = filename.rsplit('.', 1)[0] + ".mp3"

                # Historique
                history = state.get('history', [])
                history.append({'title': info.get('title', 'No title'), 'url': info.get('webpage_url', query_text), 'type': mode})
                state['history'] = history
                user_state[user_id] = state

            with open(filename, 'rb') as f:
                await query.message.reply_document(f)

        except Exception as e:
            await query.message.reply_text("Erreur : " + str(e))
        finally:
            os.unlink(tmp_cookie_path)

# ==========================
# MAIN
# ==========================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(set_language, pattern='^(fr|en)$'))
    app.add_handler(CallbackQueryHandler(button, pattern='^(audio|video|history|menu|select_\\d)$'))
    app.add_handler(CallbackQueryHandler(quality_choice, pattern='^(bestaudio|format_\\d+)$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Webhook Render
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"https://{os.environ['RENDER_EXTERNAL_URL']}/{TOKEN}"
    )

if __name__ == "__main__":
    main()