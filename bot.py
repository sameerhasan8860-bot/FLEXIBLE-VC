import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession
from config import config, validate_config
from storage import Storage
from manager import HostedManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("flexible_vc")
bot = Bot(config.bot_token)
dp = Dispatcher()
storage = Storage()
manager = HostedManager(storage)
pending = {}
EFFECTS = {"db": "Volume in decibels", "gain": "Linear output gain", "bass": "Low-frequency EQ", "treble": "High-frequency EQ", "echo": "Short feedback echo", "distortion": "Soft saturation effect"}

def home_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪄 𝐇𝐎𝐒𝐓 𝐀𝐂𝐂𝐎𝐔𝐍𝐓", callback_data="host")],
        [InlineKeyboardButton(text="📚 𝐇𝐄𝐋𝐏 & 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒", callback_data="help")],
        [InlineKeyboardButton(text="🎚️ 𝐄𝐐𝐔𝐀𝐋𝐈𝐙𝐄𝐑", callback_data="eq"), InlineKeyboardButton(text="🔊 𝐕𝐎𝐋𝐔𝐌𝐄", callback_data="vol")],
        [InlineKeyboardButton(text="✨ 𝐀𝐔𝐃𝐈𝐎 𝐄𝐅𝐅𝐄𝐂𝐓𝐒", callback_data="fx")],
    ])

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("╭━━〔 ✨ 𝐅𝐋𝐄𝐗𝐈𝐁𝐋𝐄 𝐕𝐂 〕━━╮\n  𝐋𝐢𝐯𝐞 𝐕𝐨𝐢𝐜𝐞 𝐂𝐡𝐚𝐭 𝐁𝐫𝐢𝐝𝐠𝐞\n╰━━━━━━━━━━━━━━━━━━╯\n\n🎧 Source VC ki mixed live audio target VC mein relay karo.\n\n👇 Start karne ke liye option select karo.", reply_markup=home_keyboard())

@dp.callback_query(F.data == "host")
async def host_button(q: CallbackQuery):
    await q.answer()
    await begin_host(q.from_user.id, q.message)

@dp.callback_query(F.data.in_({"help", "eq", "vol", "fx"}))
async def help_button(q: CallbackQuery):
    pages = {
        "help": "📚 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒\n/host — account host\n/unhost — apna session/data delete\n/privategroup <group_id> — source group set\n/join <target_id> — configured source se connect\n/join <target_id> <source_id> — direct connect\n/leave — both VCs se disconnect\n\nDot commands hosted account se kahin bhi chalti hain.",
        "eq": "🎚️ 𝐄𝐐𝐔𝐀𝐋𝐈𝐙𝐄𝐑\n/bass <value> or .bass <value> — low frequencies adjust. Example: .bass 8\n/treble <value> or .treble <value> — high frequencies adjust. Example: .treble 5",
        "vol": "🔊 𝐕𝐎𝐋𝐔𝐌𝐄\n/db <value> or .db <value> — dB volume. Example: .db 6\n/gain <value> or .gain <value> — linear gain. Example: .gain 1.5",
        "fx": "✨ 𝐀𝐔𝐃𝐈𝐎 𝐄𝐅𝐅𝐄𝐂𝐓𝐒\n/echo <value> or .echo <value> — echo amount. Example: .echo 35\n/distortion <value> or .distortion <value> — saturation. Example: .distortion 40",
    }
    await q.message.edit_text(pages[q.data], reply_markup=home_keyboard())
    await q.answer()

async def begin_host(uid, message):
    if await storage.get_user(uid):
        await message.answer("Tumhara account pehle se hosted hai. /unhost use karo.")
        return
    pending[uid] = {"stage": "phone"}
    await message.answer("🪄 Apna phone number international format mein bhejo. Example: +91XXXXXXXXXX\nSirf apna account host karo. OTP/2FA password share karne ke baad message delete kar diya jayega.")

@dp.message(Command("host"))
async def host_cmd(message: Message):
    if message.chat.type != "private":
        await message.reply("/host sirf private bot DM mein use karo.")
        return
    await begin_host(message.from_user.id, message)

@dp.message(Command("unhost"))
async def unhost_cmd(message: Message):
    if message.chat.type != "private":
        await message.reply("/unhost sirf private bot DM mein use karo.")
        return
    pending.pop(message.from_user.id, None)
    await manager.unhost(message.from_user.id)
    await message.reply("🧹 𝐔𝐍𝐇𝐎𝐒𝐓 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄 — tumhara session aur MongoDB user data delete ho gaya.")

async def command_owner(message: Message):
    if message.chat.type == "private":
        row = await storage.get_user(message.from_user.id)
        return message.from_user.id if row else None
    row = await storage.get_by_private_group(message.chat.id)
    if not row:
        return None
    try:
        member = await bot.get_chat_member(message.chat.id, message.from_user.id)
        if member.status not in ("administrator", "creator"):
            return None
    except Exception:
        return None
    return int(row["user_id"])

@dp.message(Command("privategroup"))
async def privategroup_cmd(message: Message):
    if message.chat.type != "private":
        await message.reply("Is command ko bot ke private DM mein use karo.")
        return
    row = await storage.get_user(message.from_user.id)
    parts = (message.text or "").split()
    if not row or len(parts) != 2:
        await message.reply("Usage: /privategroup <group_id> — pehle /host karo aur private bot ko group mein admin banao.")
        return
    try:
        gid = int(parts[1])
        me = await bot.get_me()
        member = await bot.get_chat_member(gid, me.id)
        if member.status not in ("administrator", "creator"):
            raise RuntimeError("Private bot ko source group mein admin banao.")
        await manager.hosted[message.from_user.id]["client"].get_entity(gid)
        await storage.save_user(message.from_user.id, private_group_id=gid, source_group_id=gid)
        await message.reply("🔐 𝐏𝐑𝐈𝐕𝐀𝐓𝐄 𝐆𝐑𝐎𝐔𝐏 𝐒𝐄𝐓\nSource: " + str(gid))
    except Exception as exc:
        await message.reply("⚠️ " + str(exc))

@dp.message(Command("join"))
async def join_cmd(message: Message):
    owner = await command_owner(message)
    parts = (message.text or "").split()
    if owner is None or len(parts) not in (2, 3):
        await message.reply("Usage: /join <target_id> [source_id]. Privategroup mein sirf admins use kar sakte hain.")
        return
    try:
        row = await storage.get_user(owner) or {}
        target = int(parts[1])
        source = int(parts[2]) if len(parts) == 3 else (row.get("private_group_id") or row.get("source_group_id"))
        if not source:
            raise RuntimeError("Pehle /privategroup <source_id> set karo ya /join <target_id> <source_id> use karo.")
        if len(parts) == 3 and not row.get("private_group_id"):
            await storage.save_user(owner, source_group_id=source)
        await manager.start_bridge(owner, source, target)
        await message.reply("🔊 𝐕𝐂 𝐁𝐑𝐈𝐃𝐆𝐄 𝐀𝐂𝐓𝐈𝐕𝐄\nSource: " + str(source) + "\nTarget: " + str(target))
    except Exception as exc:
        await message.reply("⚠️ " + str(exc))

@dp.message(Command("leave"))
async def leave_cmd(message: Message):
    owner = await command_owner(message)
    if owner is None:
        await message.reply("Hosted user ya privategroup admin access required.")
        return
    await manager.leave(owner)
    await message.reply("🛑 Source aur target dono VC se leave ho gaya.")

@dp.message()
async def text_router(message: Message):
    if message.chat.type != "private" or not message.from_user or not message.text:
        return
    uid = message.from_user.id
    state = pending.get(uid)
    if state:
        text = message.text.strip()
        try:
            await message.delete()
        except Exception:
            pass
        try:
            if state["stage"] == "phone":
                if not re.fullmatch(r"\+?[1-9]\d{7,14}", text):
                    await bot.send_message(uid, "Phone format invalid. Example: +91XXXXXXXXXX")
                    return
                client = TelegramClient(StringSession(), config.api_id, config.api_hash)
                await client.connect()
                sent = await client.send_code_request(text)
                pending[uid] = {"stage": "code", "client": client, "phone": text, "hash": sent.phone_code_hash}
                await bot.send_message(uid, "📩 Telegram login code bhejo. Code private rakho.")
                return
            if state["stage"] == "code":
                try:
                    await state["client"].sign_in(phone=state["phone"], code=text, phone_code_hash=state["hash"])
                except SessionPasswordNeededError:
                    state["stage"] = "password"
                    await bot.send_message(uid, "🔐 2-Step Verification password bhejo.")
                    return
                client = state["client"]
            else:
                await state["client"].sign_in(password=text)
                client = state["client"]
            await manager.add_authenticated_client(uid, client)
            pending.pop(uid, None)
            await bot.send_message(uid, "✅ 𝐀𝐂𝐂𝐎𝐔𝐍𝐓 𝐇𝐎𝐒𝐓𝐄𝐃 — ab /privategroup ya /join use karo.")
        except Exception as exc:
            log.warning("Host flow failed for user %s: %s", uid, type(exc).__name__)
            pending.pop(uid, None)
            await bot.send_message(uid, "Login fail hua. /host se dobara start karo.")
        return
    match = re.match(r"^/(db|gain|bass|treble|echo|distortion)(?:\s+(.+))?$", message.text.strip(), re.I)
    if not match:
        return
    owner = await command_owner(message)
    if owner is None:
        await message.reply("Pehle /host karo; privategroup mein sirf admins commands use kar sakte hain.")
        return
    name, arg = match.group(1).lower(), (match.group(2) or "").strip()
    try:
        if not arg:
            row = await storage.get_user(owner) or {}
            value = row.get("effects", {}).get(name, "default")
            await message.reply(name.upper() + " current: " + str(value) + "\nExample: /" + name + " 10")
            return
        value = await manager.set_effect(owner, name, float(arg.split()[0]))
        await message.reply("✅ " + name.upper() + " set: " + str(value))
    except Exception as exc:
        await message.reply("⚠️ " + str(exc))

async def main():
    validate_config()
    await storage.initialize()
    await manager.restore_all()
    log.info("FLEXIBLE-VC started")
    try:
        await dp.start_polling(bot)
    finally:
        for uid in list(manager.hosted):
            try:
                await manager.leave(uid)
                await manager.hosted[uid]["client"].disconnect()
            except Exception:
                log.exception("Shutdown cleanup failed for %s", uid)
        await storage.close()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
