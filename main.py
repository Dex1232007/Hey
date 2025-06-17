
import os
import re
import json
import asyncio
import aiohttp
from fastapi import FastAPI, Request, HTTPException
from telethon import TelegramClient
from telethon.sessions import MemorySession
from telethon.tl.types import InputMediaUploadedDocument
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import UserNotParticipantError
from telethon.tl.types import ChannelParticipant, ChannelParticipantCreator, ChannelParticipantAdmin
from dotenv import load_dotenv
from datetime import datetime
import base64
from urllib.parse import quote

load_dotenv()

app = FastAPI()

# Configuration
CONFIG = {
    "required_channels": ["@Yagami_xlight", "@movie_mmsb"],
    "admin_chat_id": 6468293575,
    "cooldown_time": 10,  # seconds
    "max_search_results": 10
}

# Telegram Client Setup
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_NAME = "bot_session"

# Use MemorySession instead of SQLite
client = TelegramClient(MemorySession(), API_ID, API_HASH)

# File paths for storage
COOLDOWN_FILE = "cooldowns.json"
ERROR_LOG_FILE = "error_log.txt"

# Ensure files exist
if not os.path.exists(COOLDOWN_FILE):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump({}, f)

if not os.path.exists(ERROR_LOG_FILE):
    with open(ERROR_LOG_FILE, "w") as f:
        pass

# Utility Functions
async def log_error(error: str):
    timestamp = datetime.utcnow().isoformat()
    log_entry = f"{timestamp} - {error}\n"
    with open(ERROR_LOG_FILE, "a") as f:
        f.write(log_entry)

async def send_message(chat_id: int, text: str, reply_markup=None, parse_mode="html"):
    try:
        await client.send_message(
            chat_id,
            text,
            parse_mode=parse_mode,
            link_preview=False,
            buttons=reply_markup
        )
    except Exception as e:
        await log_error(f"Send Message Error: {str(e)}")

async def edit_message(chat_id: int, message_id: int, text: str, reply_markup=None):
    try:
        await client.edit_message(
            chat_id,
            message_id,
            text,
            parse_mode="html",
            buttons=reply_markup
        )
    except Exception as e:
        await log_error(f"Edit Message Error: {str(e)}")

async def answer_callback(callback_id: str, text: str, show_alert: bool = False):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
            params = {"callback_query_id": callback_id, "text": text, "show_alert": show_alert}
            async with session.post(url, json=params) as resp:
                if not resp.ok:
                    await log_error(f"Answer Callback Failed: {resp.status}")
    except Exception as e:
        await log_error(f"Answer Callback Error: {str(e)}")

async def send_chat_action(chat_id: int, action: str):
    try:
        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendChatAction"
            async with session.post(url, json={"chat_id": chat_id, "action": action}) as resp:
                if not resp.ok:
                    await log_error(f"Send Chat Action Failed: {resp.status}")
    except Exception as e:
        await log_error(f"Send Chat Action Error: {str(e)}")

# Core Functions
async def is_member_of_channels(user_id: int):
    for channel in CONFIG["required_channels"]:
        try:
            participant = await client(GetParticipantRequest(channel, user_id))
            if not isinstance(participant.participant, (ChannelParticipant, ChannelParticipantCreator, ChannelParticipantAdmin)):
                return False
        except UserNotParticipantError:
            return False
        except Exception as e:
            await log_error(f"Membership Check Error for {user_id} in {channel}: {str(e)}")
            return False
    return True

def validate_youtube_url(url: str) -> bool:
    pattern = r"^(https?://)?(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[\w-]{11}"
    return bool(re.match(pattern, url))

def extract_youtube_url_only(text: str) -> str | None:
    url_match = re.search(r"(https?://[^\s]+)", text)
    if url_match:
        url = url_match.group(1).strip()
        if validate_youtube_url(url):
            return url
    return None

async def get_audio_info(youtube_url: str) -> dict:
    try:
        api_url = f"https://yt.zaw-myo.workers.dev/?action=generate&url={quote(youtube_url)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if not resp.ok:
                    raise Exception(f"API request failed with status {resp.status}")
                if not resp.content_type.startswith("application/json"):
                    raise Exception("Expected JSON response")
                data = await resp.json()
                if not data.get("success"):
                    raise Exception(f"Invalid API response: {json.dumps(data)}")
                video_id = re.search(r"(?:v=|/)([\w-]{11})", youtube_url).group(1) if re.search(r"(?:v=|/)([\w-]{11})", youtube_url) else ""
                return {
                    "ok": True,
                    "title": data.get("title", "Unknown Title"),
                    "image": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                    "duration": data.get("duration", "Unknown"),
                    "download_url": data.get("download_url", "")
                }
    except Exception as e:
        await log_error(f"getAudioInfo Error: {str(e)}")
        return {"ok": False, "error": str(e)}

async def search_youtube(query: str) -> list:
    try:
        api_url = f"https://zawmyo123.serv00.net/api/ytsearch.php?query={quote(query)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if not resp.ok:
                    raise Exception(f"Search API failed with status {resp.status}")
                results = await resp.json()
                return results if isinstance(results, list) else []
    except Exception as e:
        await log_error(f"searchYouTube Error: {query} - {str(e)}")
        return []

async def check_cooldown(user_id: int) -> int | bool:
    try:
        with open(COOLDOWN_FILE, "r") as f:
            cooldowns = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cooldowns = {}
    
    current_time = int(datetime.now().timestamp())
    
    if str(user_id) in cooldowns and (current_time - cooldowns[str(user_id)]) < CONFIG["cooldown_time"]:
        return CONFIG["cooldown_time"] - (current_time - cooldowns[str(user_id)])
    
    return False

async def set_cooldown(user_id: int):
    try:
        with open(COOLDOWN_FILE, "r") as f:
            cooldowns = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cooldowns = {}
    
    cooldowns[str(user_id)] = int(datetime.now().timestamp())
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(cooldowns, f)

async def send_audio_stream(chat_id: int, audio_url: str, title: str, duration: str, thumbnail_url: str, performer: str):
    await send_chat_action(chat_id, "upload_audio")
    
    keyboard = [[{"text": "💐 Join Our Channel", "url": "https://t.me/Yagami_xlight"}]]
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(audio_url) as audio_resp, session.get(thumbnail_url) as thumb_resp:
                if not audio_resp.ok:
                    raise Exception("Failed to fetch audio")
                audio_data = await audio_resp.read()
                thumb_data = await thumb_resp.read()
                
                # Upload audio as document to support up to 1GB
                media = InputMediaUploadedDocument(
                    file=audio_data,
                    mime_type="audio/mpeg",
                    attributes=[
                        {"type": "DocumentAttributeAudio", "duration": int(duration) if duration.isdigit() else 0, "title": title, "performer": performer}
                    ],
                    thumb=thumb_data,
                    caption="Make By @ItachiXCoder",
                    parse_mode=None
                )
                
                await client.send_file(
                    chat_id,
                    file=media,
                    reply_markup=keyboard,
                    progress_callback=lambda current, total: print(f"Uploading: {current}/{total} bytes")
                )
    except Exception as e:
        await log_error(f"sendAudioStream Error: {str(e)}")
        await send_message(chat_id, "Failed to process audio file.")

# Update Handlers
@app.post("/webhook")
async def handle_update(request: Request):
    try:
        update = await request.json()
        if "message" in update:
            await handle_text_message(update["message"])
        elif "callback_query" in update:
            await handle_callback_query(update["callback_query"])
        elif "inline_query" in update:
            await handle_inline_query(update["inline_query"])
        return {"status": "OK"}
    except Exception as e:
        await log_error(f"Handle Update Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

async def handle_callback_query(callback_query: dict):
    callback_id = callback_query["id"]
    message = callback_query["message"]
    chat_id = message["chat"]["id"]
    user_id = callback_query["from"]["id"]
    message_id = message["message_id"]
    data_parts = callback_query["data"].split("|")
    action = data_parts[0]
    param = data_parts[1] if len(data_parts) > 1 else None
    
    if not await is_member_of_channels(user_id):
        await answer_callback(callback_id, "❌ You must join our channels first!", True)
        await edit_message(
            chat_id,
            message_id,
            "🚫 Access Denied\n\nYou need to join our channels to use this bot:\n\n" +
            "1. @Yagami_xlight\n" +
            "2. @movie_mmsb\n\n" +
            "Join them and click the button below to verify:",
            [[{"text": "✅ Verify Membership", "callback_data": "check_membership"}]]
        )
        return
    
    if action == "check_membership":
        if await is_member_of_channels(user_id):
            await edit_message(
                chat_id,
                message_id,
                "✅ Membership Verified!\n\nYou can now use all bot features.\n\n" +
                "Send /start to begin."
            )
            await answer_callback(callback_id, "Membership verified successfully!")
        else:
            await answer_callback(callback_id, "❌ You still need to join all channels!", True)
    
    elif action == "download" and param:
        remaining_cooldown = await check_cooldown(user_id)
        if remaining_cooldown:
            await answer_callback(
                callback_id,
                f"⏳ Please wait {remaining_cooldown} seconds before your next request",
                True
            )
            return
        
        await set_cooldown(user_id)
        await answer_callback(callback_id, "Processing your request...")
        await edit_message(chat_id, message_id, "⏳ Processing your request...")
        
        audio_info = await get_audio_info(param)
        
        if audio_info["ok"] and audio_info["download_url"]:
            video_id = re.search(r"(?:v=|/)([\w-]{11})", param).group(1) if re.search(r"(?:v=|/)([\w-]{11})", param) else ""
            await send_audio_stream(
                chat_id,
                audio_info["download_url"],
                audio_info["title"],
                audio_info["duration"],
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "yt_ygmbot"
            )
        else:
            await edit_message(
                chat_id,
                message_id,
                f"❌ Failed to process this video\n\nError: {audio_info.get('error', 'Unknown error')}\n\nTry again or contact support."
            )

async def handle_inline_query(inline_query: dict):
    inline_id = inline_query["id"]
    query = inline_query["query"].strip()
    user_id = inline_query["from"]["id"]
    
    if not await is_member_of_channels(user_id):
        results = [{
            "type": "article",
            "id": "not_member",
            "title": "❌ Join Required Channels",
            "input_message_content": {
                "message_text": "🚫 You need to join these channels to use the bot:\n\n1. @Yagami_xlight\n2. @movie_mmsb",
                "parse_mode": "HTML"
            }
        }]
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery",
                json={"inline_query_id": inline_id, "results": results, "cache_time": 5}
            )
        return
    
    if not query:
        results = [{
            "type": "article",
            "id": "empty",
            "title": "Type a song name or keyword",
            "input_message_content": {
                "message_text": "🔍 Type a song name to search from YouTube...",
                "parse_mode": "HTML"
            }
        }]
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery",
                json={"inline_query_id": inline_id, "results": results, "cache_time": 5}
            )
        return
    
    results_data = await search_youtube(query)
    results = []
    
    for index, video in enumerate(results_data[:10]):
        video_id = video.get("id", "")
        video_url = video.get("url", "")
        video_title = video.get("title", "Unknown Title")
        video_author = video.get("author", "Unknown Author")
        results.append({
            "type": "article",
            "id": base64.b64encode(video_url.encode()).decode(),
            "title": video_title,
            "description": f"🎧 Author: {video_author}\n🔗 URL: {video_url}",
            "thumb_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "input_message_content": {
                "message_text": f"🎵 <b>{video_title}</b>\n\n🔗URL: {video_url}\n\n<i>🔌 Powered By @itachiXCoder</i>",
                "parse_mode": "HTML"
            },
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "🎧 Download", "url": f"https://t.me/yt_ygmbot?text={video_url}"}],
                    [{"text": "🔍 Search More", "switch_inline_query_current_chat": video_title}]
                ]
            }
        })
    
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/answerInlineQuery",
            json={"inline_query_id": inline_id, "results": results, "cache_time": 5}
        )

async def handle_text_message(message: dict):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")
    
    if not await is_member_of_channels(user_id):
        await send_message(
            chat_id,
            "🔒 Restricted Access\n\n" +
            "You must join our channels to use this bot:\n\n" +
            "1. @Yagami_xlight\n" +
            "2. @movie_mmsb\n\n" +
            "Join them and click the button below to verify:",
            [[{"text": "✅ Verify Membership", "callback_data": "check_membership"}]]
        )
        return
    
    if text.startswith("/start"):
        await send_message(
            chat_id,
            "🎵 <b>YouTube Music Bot</b>\n\n" +
            "Send me:\n" +
            "• A song name to search\n" +
            "• A YouTube URL to download\n\n" +
            "<i>Made by @ItachiXCoder</i>",
            [
                [{"text": "🎛️ Mini App", "web_app": {"url": "https://zawmyo123.serv00.net/youtube/index.html"}}],
                [{"text": "🔍 Search Song", "switch_inline_query_current_chat": ""}]
            ]
        )
    elif text.startswith("/admin") and user_id == CONFIG["admin_chat_id"]:
        await send_message(chat_id, "Admin panel coming soon...")
    elif youtube_url := extract_youtube_url_only(text):
        remaining_cooldown = await check_cooldown(user_id)
        if remaining_cooldown:
            await send_message(chat_id, f"⏳ Please wait {remaining_cooldown} seconds before your next request")
            return
        
        await set_cooldown(user_id)
        await send_message(chat_id, "⏳ Processing your YouTube link...")
        
        audio_info = await get_audio_info(youtube_url)
        
        if audio_info["ok"] and audio_info["download_url"]:
            video_id = re.search(r"(?:v=|/)([\w-]{11})", youtube_url).group(1) if re.search(r"(?:v=|/)([\w-]{11})", youtube_url) else ""
            await send_audio_stream(
                chat_id,
                audio_info["download_url"],
                audio_info["title"],
                audio_info["duration"],
                f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                "yt_ygmbot"
            )
        else:
            await send_message(chat_id, f"❌ Failed to process this YouTube URL. Error: {audio_info.get('error', 'Unknown error')}")
    else:
        remaining_cooldown = await check_cooldown(user_id)
        if remaining_cooldown:
            await send_message(chat_id, f"⏳ Please wait {remaining_cooldown} seconds before your next request")
            return
        
        await set_cooldown(user_id)
        await send_message(chat_id, f"🔍 Searching YouTube for \"{text}\"...")
        
        results = await search_youtube(text)
        
        if results:
            message_text = "📋 <b>Search Results:</b>\n\n"
            keyboard = []
            for i, video in enumerate(results[:CONFIG["max_search_results"]]):
                num = i + 1
                message_text += f"{num}. <b>{video.get('title', 'Unknown Title')}</b>\n"
                keyboard.append([{"text": f"{num}. Download", "callback_data": f"download|{video.get('url', '')}"}])
            
            await send_message(chat_id, message_text, keyboard)
        else:
            await send_message(chat_id, f"❌ No results found for \"{text}\"")

# Start Telegram Client
async def start_client():
    await client.start(bot_token=BOT_TOKEN)
    print("Telegram client started")

@app.on_event("startup")
async def startup_event():
    await start_client()
    print("FastAPI server started")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
