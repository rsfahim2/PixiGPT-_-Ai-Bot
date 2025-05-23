import os
import sqlite3 # SQLite কোড রাখা হয়েছে তবে Firebase ব্যবহার করা হবে
import asyncio
from datetime import datetime, timedelta

# টেলিগ্রাম বট লাইব্রেরি
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)

# গুগল জেমিনি এপিআই লাইব্রেরি
import google.generativeai as genai

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# --- আপনার প্রয়োজনীয় তথ্য (এনভায়রনমেন্ট ভেরিয়েবল থেকে নেওয়া হবে) ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = int(os.environ.get("TELEGRAM_CHANNEL_ID", "-1002161374444")) # আপনার চ্যানেলের আইডি
TELEGRAM_CHANNEL_LINK = os.environ.get("TELEGRAM_CHANNEL_LINK", "https://t.me/pixigpt") # আপনার চ্যানেলের সম্পূর্ণ লিঙ্ক

# কোটা সেটিংস
FREE_MESSAGE_LIMIT = 15 # প্রতিদিন ফ্রি প্ল্যানে ১৫টি মেসেজ
PREMIUM_MESSAGE_LIMIT = 999999999 # প্রিমিয়াম প্ল্যানে আনলিমিটেড মেসেজ

# --- API কনফিগারেশন ---
GOOGLE_GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 

# নিশ্চিত করুন প্রয়োজনীয় পরিবেশ ভেরিয়েবল সেট করা আছে
if not TELEGRAM_BOT_TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN environment variable not set.")
    exit(1)
if not GOOGLE_GEMINI_API_KEY:
    print("Error: GEMINI_API_KEY environment variable not set.")
    exit(1)

genai.configure(api_key=GOOGLE_GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-pro')

# --- Firebase সেটআপ ---
FIREBASE_SERVICE_ACCOUNT_KEY = os.environ.get("FIREBASE_SERVICE_ACCOUNT_KEY")

if not FIREBASE_SERVICE_ACCOUNT_KEY:
    print("Error: FIREBASE_SERVICE_ACCOUNT_KEY environment variable not set.")
    print("Please add your Firebase service account JSON content as an environment variable.")
    exit(1)

try:
    # Service Account Key একটি স্ট্রিং হিসেবে আসবে, এটিকে JSON অবজেক্টে রূপান্তর করতে হবে
    import json
    cred_json = json.loads(FIREBASE_SERVICE_ACCOUNT_KEY)
    cred = credentials.Certificate(cred_json)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully.")
except Exception as e:
    print(f"Error initializing Firebase: {e}")
    exit(1)

# --- ইউটিলিটি ফাংশন (Firebase ব্যবহার করে) ---

# SQLite ফাংশনগুলো রাখা হয়েছে, তবে Firebase এর সমতুল্য ফাংশন ব্যবহার হবে
# ডেটাবেজ স্ট্রাকচার: users/user_id -> {telegram_name, language, plan_type, daily_message_count, last_message_date, referral_code, referred_by_id, referral_points}

async def get_user_data(user_id):
    doc_ref = db.collection('users').document(str(user_id))
    doc = await doc_ref.get() # await ব্যবহার করতে হলে কোডের বাকি অংশ async হতে হবে
    if doc.exists:
        return doc.to_dict()
    return None

async def update_user_data(user_id, **kwargs):
    doc_ref = db.collection('users').document(str(user_id))
    await doc_ref.set(kwargs, merge=True)

async def create_user_if_not_exists(user_id, telegram_name):
    user_data = await get_user_data(user_id)
    if not user_data:
        initial_data = {
            'telegram_name': telegram_name,
            'language': 'en',
            'plan_type': 'free',
            'daily_message_count': 0,
            'last_message_date': datetime.now().strftime('%Y-%m-%d'),
            'referral_code': f"REF{user_id}", # ইনিশিয়াল রেফারেল কোড
            'referred_by_id': None,
            'referral_points': 0
        }
        await db.collection('users').document(str(user_id)).set(initial_data)

async def reset_daily_counts_firebase():
    # Firestore এ সমস্ত ব্যবহারকারীর জন্য দৈনিক কাউন্টার রিসেট করা
    # এটি প্রতিদিন মধ্যরাতে একবার কল করতে হবে
    today_str = datetime.now().strftime('%Y-%m-%d')
    users_ref = db.collection('users')
    
    # Firestore query for users whose last_message_date is not today
    # Note: Firestore does not support 'not equal to' queries directly on indexed fields.
    # A more robust solution for large databases involves periodically running a Cloud Function
    # to reset counts, or handling it on per-user basis upon their first message of the day.
    # For now, we'll keep it simple for illustration.
    
    # Simpler approach: update only when user sends message on new day
    # This function would mainly be for a general reset if needed for admin purposes
    # For this bot, the reset logic is handled in handle_message for each user.
    print("Firebase daily counts will be reset per user activity or via Cloud Function.")

# --- হ্যান্ডলার ফাংশন ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or update.effective_user.username or "User"
    await create_user_if_not_exists(user_id, user_name)

    if context.args:
        referrer_code = context.args[0]
        referrer_doc = await db.collection('users').where('referral_code', '==', referrer_code).get()
        
        referrer_id = None
        for doc in referrer_doc:
            referrer_id = int(doc.id)
            break
        
        user_data = await get_user_data(user_id) # গেট লেটেস্ট ইউজার ডেটা
        
        if referrer_id and user_id != referrer_id and (user_data['referred_by_id'] is None):
            await update_user_data(user_id, referred_by_id=referrer_id)
            referrer_current_points = (await get_user_data(referrer_id)).get('referral_points', 0)
            await update_user_data(referrer_id, referral_points=referrer_current_points + 2)
            await update.message.reply_text(f"আপনি সফলভাবে `{referrer_code}` দ্বারা রেফার হয়েছেন! এবং আপনার রেফারারকে 2 পয়েন্ট দেওয়া হয়েছে।", parse_mode='Markdown')

    await send_welcome_message(update, context)


async def send_welcome_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name or update.effective_user.username or "User"
    user_data = await get_user_data(user_id) # async call
    user_lang = user_data.get('language', 'en')

    messages = {
        'en': (
            f"🌟 **Welcome to PixiGPT, {user_name}!** 🌟\n\n"
            "I'm your personal AI assistant, ready to chat and help you with anything you need.\n\n"
            "To unlock my full potential and start exploring, please join our official Telegram channel:\n"
            f"👉 {TELEGRAM_CHANNEL_LINK}\n\n"
            "Once you've joined, just type anything, and we'll get started! Let's create something amazing together. ✨"
        ),
        'bn': (
            f"🌟 **PixiGPT-তে আপনাকে স্বাগতম, {user_name}!** 🌟\n\n"
            "আমি আপনার ব্যক্তিগত এআই সহকারী, আপনার প্রয়োজন অনুযায়ী চ্যাট করতে এবং সাহায্য করতে প্রস্তুত।\n\n"
            "আমার সম্পূর্ণ ক্ষমতা আনলক করতে এবং এক্সপ্লোর করা শুরু করতে, অনুগ্রহ করে আমাদের অফিসিয়াল টেলিগ্রাম চ্যানেলে যোগ দিন:\n"
            f"👉 {TELEGRAM_CHANNEL_LINK}\n\n"
            "একবার যোগদানের পর, যেকোনো কিছু টাইপ করুন, এবং আমরা শুরু করব! চলুন একসাথে অসাধারণ কিছু তৈরি করি। ✨"
        ),
        'es': (
            f"🌟 **¡Bienvenido a PixiGPT, {user_name}!** 🌟\n\n"
            "Soy tu asistente personal de IA, lista para chatear y ayudarte con todo lo que necesites.\n\n"
            "Para desbloquear todo mi potencial y empezar a explorar, por favor únete a nuestro canal oficial de Telegram:\n"
            f"👉 {TELEGRAM_CHANNEL_LINK}\n\n"
            "Una vez que te hayas unido, ¡simplemente escribe algo y empezaremos! Creemos algo increíble juntos. ✨"
        ),
        'id': (
            f"🌟 **Selamat datang di PixiGPT, {user_name}!** 🌟\n\n"
            "Saya asisten AI pribadi Anda, siap untuk mengobrol dan membantu Anda dengan apa pun yang Anda butuhkan.\n\n"
            "Untuk membuka potensi penuh saya dan mulai menjelajah, silakan bergabung dengan saluran Telegram resmi kami:\n"
            f"👉 {TELEGRAM_CHANNEL_LINK}\n\n"
            "Setelah Anda bergabung, cukup ketik apa saja, dan kita akan mulai! Mari ciptakan sesuatu yang luar biasa bersama. ✨"
        )
    }
    
    keyboard = [[InlineKeyboardButton("Join Channel", url=TELEGRAM_CHANNEL_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await (update.message or update.callback_query).reply_text(
        messages.get(user_lang, messages['en']), reply_markup=reply_markup, parse_mode='Markdown'
    )


async def check_channel_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    
    try:
        chat_member = await context.bot.get_chat_member(TELEGRAM_CHANNEL_ID, user_id)
        if chat_member.status in ["member", "administrator", "creator"]:
            return True
        else:
            await send_welcome_message(update, context)
            return False
    except Exception as e:
        print(f"Error checking channel membership for user {user_id}: {e}")
        # চ্যানেল খুঁজে না পেলে বা অন্য সমস্যা হলে ধরে নেওয়া হয় সদস্য নয়
        await send_welcome_message(update, context) 
        return False

async def language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_data = await get_user_data(update.effective_user.id)
    user_lang = user_data.get('language', 'en')
    
    keyboard = [
        [InlineKeyboardButton("English 🇬🇧", callback_data='lang_en')],
        [InlineKeyboardButton("বাংলা 🇧🇩", callback_data='lang_bn')],
        [InlineKeyboardButton("Español 🇪🇸", callback_data='lang_es')],
        [InlineKeyboardButton("Bahasa Indonesia 🇮🇩", callback_data='lang_id')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    messages = {
        'en': "Please choose your language:",
        'bn': "আপনার ভাষা নির্বাচন করুন:",
        'es': "Por favor, elige tu idioma:",
        'id': "Silakan pilih bahasa Anda:"
    }
    
    await (update.message or update.callback_query).reply_text(
        messages.get(user_lang, messages['en']), reply_markup=reply_markup
    )

async def handle_language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user_id = query.from_user.id
    lang_code = query.data.split('_')[1]

    await update_user_data(user_id, language=lang_code)
    
    messages = {
        'en': "Language set to English. Now, let's explore PixiGPT!",
        'bn': "ভাষা বাংলাতে সেট করা হয়েছে। এবার চলুন PixiGPT এক্সপ্লোর করি!",
        'es': "Idioma configurado a Español. ¡Ahora, exploremos PixiGPT!",
        'id': "Bahasa diatur ke Bahasa Indonesia. Sekarang, mari jelajahi PixiGPT!"
    }
    await query.answer()
    await query.edit_message_text(messages.get(lang_code, messages['en']))
    await set_bot_commands(context.bot) # কমান্ড সেট করা হয়েছে
    await send_main_menu(update, context)


async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    user_lang = user_data.get('language', 'en')

    messages = {
        'en': "What would you like to do?",
        'bn': "আপনি কি করতে চান?",
        'es': "¿Qué te gustaría hacer?",
        'id': "Apa yang ingin Anda lakukan?"
    }

    keyboard = [
        [InlineKeyboardButton("💬 Chat with AI", callback_data='chat_ai')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await (update.message or update.callback_query).reply_text(
        messages.get(user_lang, messages['en']), reply_markup=reply_markup
    )


async def handle_main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    # context.user_data ব্যবহার করার আগে নিশ্চিত করুন user_data লোড হয়েছে
    # user_data = await get_user_data(user_id) # যদি এখানে দরকার হয়

    if query.data == 'chat_ai':
        chat_messages = {
            'en': "You can now chat with PixiGPT. Type your message:",
            'bn': "এখন আপনি PixiGPT-এর সাথে চ্যাট করতে পারবেন। আপনার মেসেজ টাইপ করুন:",
            'es': "Ahora puedes chatear con PixiGPT. Escribe tu mensaje:",
            'id': "Anda sekarang dapat mengobrol dengan PixiGPT. Ketik pesan Anda:"
        }
        await query.edit_message_text(chat_messages.get('en', chat_messages['en'])) # ভাষা নির্দিষ্ট করে দেওয়া হয়েছে
        context.user_data['current_mode'] = 'chat_ai'


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await check_channel_membership(update, context):
        return

    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    user_lang = user_data.get('language', 'en')
    current_plan = user_data.get('plan_type', 'free')
    daily_msg_count = user_data.get('daily_message_count', 0)
    last_msg_date_str = user_data.get('last_message_date', datetime.now().strftime('%Y-%m-%d'))
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    if last_msg_date_str != today_str:
        daily_msg_count = 0
        await update_user_data(user_id, daily_message_count=0, last_message_date=today_str)

    message_limit = FREE_MESSAGE_LIMIT if current_plan == 'free' else PREMIUM_MESSAGE_LIMIT

    if 'current_mode' in context.user_data and context.user_data['current_mode'] == 'chat_ai':
        if daily_msg_count >= message_limit:
            quota_messages = {
                'en': (
                    "You have reached your daily message limit. "
                    "Upgrade to premium for unlimited messages, or wait until tomorrow!"
                ),
                'bn': (
                    "আপনার দৈনিক মেসেজ সীমা পৌঁছে গেছে। "
                    "আনলিমিটেড মেসেজের জন্য প্রিমিয়ামে আপগ্রেড করুন, অথবা আগামীকালের জন্য অপেক্ষা করুন!"
                ),
                'es': (
                    "Has alcanzado tu límite diario de mensajes. "
                    "¡Actualiza a premium para mensajes ilimitados, o espera hasta mañana!"
                ),
                'id': (
                    "Anda telah mencapai batas pesan harian Anda. "
                    "Tingkatkan ke premium untuk pesan tanpa batas, atau tunggu sampai besok!"
                )
            }
            await update.message.reply_text(quota_messages.get(user_lang, quota_messages['en']))
            return

        user_message = update.message.text
        processing_messages = {
            'en': "Thinking...",
            'bn': "ভাবছি...",
            'es': "Pensando...",
            'id': "Sedang berpikir..."
        }
        await update.message.reply_text(processing_messages.get(user_lang, processing_messages['en']))

        try:
            response = gemini_model.generate_content(user_message)
            ai_response = response.text
        except Exception as e:
            print(f"Error calling Gemini API: {e}")
            error_messages = {
                'en': "Sorry, I couldn't process your request right now. Please try again later.",
                'bn': "দুঃখিত, আমি এই মুহূর্তে আপনার অনুরোধ প্রক্রিয়া করতে পারিনি। অনুগ্রহ করে পরে আবার চেষ্টা করুন।",
                'es': "Lo siento, no pude procesar tu solicitud en este momento. Por favor, inténtalo de nuevo más tarde.",
                'id': "Maaf, saya tidak dapat memproses permintaan Anda saat ini. Silakan coba lagi nanti."
            }
            ai_response = error_messages.get(user_lang, error_messages['en'])
        
        await update.message.reply_text(ai_response)
        
        await update_user_data(user_id, daily_message_count=daily_msg_count + 1)

    else:
        await send_main_menu(update, context)

async def account_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    if not user_data:
        await update.message.reply_text("আপনার অ্যাকাউন্ট তথ্য পাওয়া যায়নি। /start দিয়ে শুরু করুন।")
        return

    user_name = user_data.get('telegram_name', 'User')
    user_lang = user_data.get('language', 'en')
    plan_type = user_data.get('plan_type', 'free')
    daily_msg_count = user_data.get('daily_message_count', 0)
    last_msg_date_str = user_data.get('last_message_date', datetime.now().strftime('%Y-%m-%d'))
    referral_code = user_data.get('referral_code', f"REF{user_id}")
    referred_by_id = user_data.get('referred_by_id')
    referral_points = user_data.get('referral_points', 0)

    today_str = datetime.now().strftime('%Y-%m-%d')
    if last_msg_date_str != today_str:
        daily_msg_count = 0
        await update_user_data(user_id, daily_message_count=0, last_message_date=today_str)

    message_limit = FREE_MESSAGE_LIMIT if plan_type == 'free' else PREMIUM_MESSAGE_LIMIT
    
    messages = {
        'en': (
            "**Account Information:**\n"
            f"Telegram Name: `{user_name}`\n"
            f"Current Plan: `{plan_type.capitalize()}`\n"
            f"Messages Used Today: `{daily_msg_count}/{message_limit}`\n"
            f"Referral Points: `{referral_points}`\n\n"
            "To upgrade to premium for unlimited messages, contact admin: @rs_fahim_crypto"
        ),
        'bn': (
            "**অ্যাকাউন্ট তথ্য:**\n"
            f"টেলিগ্রাম নাম: `{user_name}`\n"
            f"বর্তমান প্ল্যান: `{plan_type.capitalize()}`\n"
            f"আজকের ব্যবহৃত মেসেজ: `{daily_msg_count}/{message_limit}`\n"
            f"রেফারেল পয়েন্ট: `{referral_points}`\n\n"
            "আনলিমিটেড মেসেজের জন্য প্রিমিয়ামে আপগ্রেড করতে, অ্যাডমিনের সাথে যোগাযোগ করুন: @rs_fahim_crypto"
        ),
        'es': (
            "**Información de la cuenta:**\n"
            f"Nombre de Telegram: `{user_name}`\n"
            f"Plan actual: `{plan_type.capitalize()}`\n"
            f"Mensajes usados hoy: `{daily_msg_count}/{message_limit}`\n"
            f"Puntos de referencia: `{referral_points}`\n\n"
            "Para actualizar a premium para mensajes ilimitados, contacta al administrador: @rs_fahim_crypto"
        ),
        'id': (
            "**Informasi Akun:**\n"
            f"Nama Telegram: `{user_name}`\n"
            f"Paket Saat Ini: `{plan_type.capitalize()}`\n"
            f"Pesan yang Digunakan Hari Ini: `{daily_msg_count}/{message_limit}`\n"
            f"Poin Referral: `{referral_points}`\n\n"
            "Untuk meningkatkan ke premium untuk pesan tak terbatas, hubungi admin: @rs_fahim_crypto"
        )
    }
    await update.message.reply_text(messages.get(user_lang, messages['en']), parse_mode='Markdown')

async def generate_referral_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_data = await get_user_data(user_id)
    user_lang = user_data.get('language', 'en')

    if not user_data:
        await update.message.reply_text("আপনার অ্যাকাউন্ট তথ্য পাওয়া যায়নি। /start দিয়ে শুরু করুন।")
        return

    referral_code = user_data.get('referral_code', f"REF{user_id}")
    # যদি রেফারেল কোড না থাকে, তাহলে তৈরি করুন
    if user_data.get('referral_code') is None:
        await update_user_data(user_id, referral_code=referral_code)
        
    referral_link = f"https://t.me/{context.bot.username}?start={referral_code}"

    messages = {
        'en': (
            "**Your Referral System:**\n"
            "Share this link with your friends to earn points!\n"
            f"Your Referral Link: `{referral_link}`\n"
            f"Your Referral Code: `{referral_code}`\n\n"
            "You get 2 points for each successful referral."
        ),
        'bn': (
            "**আপনার রেফারেল সিস্টেম:**\n"
            "পয়েন্ট অর্জনের জন্য আপনার বন্ধুদের সাথে এই লিঙ্কটি শেয়ার করুন!\n"
            f"আপনার রেফারেল লিঙ্ক: `{referral_link}`\n"
            f"আপনার রেফারেল কোড: `{referral_code}`\n\n"
            "প্রতিটি সফল রেফারে আপনি 2 পয়েন্ট পাবেন।"
        ),
        'es': (
            "**Tu sistema de referidos:**\n"
            "¡Comparte este enlace con tus amigos para ganar puntos!\n"
            f"Tu enlace de referid