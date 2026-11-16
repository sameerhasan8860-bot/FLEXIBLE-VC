import asyncio
import logging
import re
import html
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneCodeExpiredError, PasswordHashInvalidError, PhoneNumberInvalidError
from telethon.sessions import StringSession
from config import config, validate_config
from storage import Storage
from custom_emoji import bot_send
from manager import HostedManager

validate_config()

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("flexible_vc")
bot = Bot(config.bot_token)
dp = Dispatcher()
storage = Storage()
manager = HostedManager(storage)
pending = {}
EFFECTS = {"db": "Volume in decibels", "gain": "Linear output gain", "bass": "Low-frequency EQ", "treble": "High-frequency EQ", "echo": "Short feedback echo", "distortion": "Soft saturation effect", "level": "Combined master audio profile"}

def home_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="𝐇𝐎𝐒𝐓 𝐀𝐂𝐂𝐎𝐔𝐍𝐓", callback_data="host", style="success", icon_custom_emoji_id="6328067014195684470")],
        [InlineKeyboardButton(text="𝐇𝐄𝐋𝐏 & 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒", callback_data="help", style="primary", icon_custom_emoji_id="5411513635950325417")],
        [InlineKeyboardButton(text="𝐄𝐐𝐔𝐀𝐋𝐈𝐙𝐄𝐑", callback_data="eq", style="primary", icon_custom_emoji_id="5411636351755905742"), InlineKeyboardButton(text="𝐕𝐎𝐋𝐔𝐌𝐄", callback_data="vol", style="success", icon_custom_emoji_id="5411218262459445111")],
        [InlineKeyboardButton(text="𝐀𝐔𝐃𝐈𝐎 𝐄𝐅𝐅𝐄𝐂𝐓𝐒", callback_data="fx", style="danger", icon_custom_emoji_id="5411210419849163902")],
        [InlineKeyboardButton(text="𝐃𝐄𝐕𝐄𝐋𝐎𝐏𝐄𝐑", url="https://t.me/SAREEF_FUCKER", style="danger", icon_custom_emoji_id="6091123254842366873")],
    ])


def category_keyboard(category):
    commands = {
        "help": [
            ("/host", "cmd:host", "success", "5411218404193363520"),
            ("/unhost", "cmd:unhost", "danger", "5409326166156799980"),
            ("/privategroup", "cmd:privategroup", "primary", "5411077907223180693"),
            ("/join", "cmd:join", "success", "5411370291416820975"),
            ("/leave", "cmd:leave", "danger", "5411387780523649678"),
            ("/cancel", "cmd:cancel", "danger", "5409326166156799980"),
            ("/reset", "cmd:reset", "danger", "5411472846645914012"),
            ("/level", "cmd:level", "success", "5411200584374056500"),
            (".join", "cmd:dotjoin", "success", "5411311574918919629"),
            (".leave", "cmd:dotleave", "danger", "5411448605850496427"),
        ],
        "eq": [
            ("/bass", "cmd:bass", "primary", "5411534067109751385"),
            ("/treble", "cmd:treble", "primary", "5411558368034712251"),
        ],
        "vol": [
            ("/db", "cmd:db", "success", "5408854995359524419"),
            ("/gain", "cmd:gain", "success", "5411249589950902826"),
            ("/level", "cmd:level", "danger", "5411200584374056500"),
        ],
        "fx": [
            ("/echo", "cmd:echo", "primary", "5411472846645914012"),
            ("/distortion", "cmd:distortion", "danger", "5411316015915102848"),
        ],
    }
    rows = [[InlineKeyboardButton(text=label, callback_data=data, style=style, icon_custom_emoji_id=emoji_id)] for label, data, style, emoji_id in commands.get(category, [])]
    rows.append([InlineKeyboardButton(text="𝐇𝐎𝐌𝐄", callback_data="home", style="primary", icon_custom_emoji_id="5411077907223180693")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

COMMAND_DETAILS = {
    "host": ("👤 𝐇𝐎𝐒𝐓 𝐀𝐂𝐂𝐎𝐔𝐍𝐓", "/host", "Start your own Telegram account login flow in the private bot DM.", "Open bot DM and send /host, then follow phone, login-code and optional 2FA prompts."),
    "unhost": ("🧹 𝐔𝐍𝐇𝐎𝐒𝐓", "/unhost", "Disconnect your hosted account and delete only your encrypted session and settings from MongoDB.", "Send /unhost in the private bot DM."),
    "cancel": ("🛑 𝐂𝐀𝐍𝐂𝐄𝐋", "/cancel", "Stop an active account login/hosting process and disconnect its temporary login session.", "Send /cancel any time during /host."),
    "reset": ("♻️ 𝐑𝐄𝐒𝐄𝐓 𝐄𝐅𝐅𝐄𝐂𝐓𝐒", "/reset", "Restore db, gain, level, bass, treble, echo and distortion to their original defaults together.", "Send /reset. To reset only one control, use /db 0, /gain 0, /level 0, etc."),
    "privategroup": ("🔐 𝐏𝐑𝐈𝐕𝐀𝐓𝐄𝐆𝐑𝐎𝐔𝐏", "/privategroup <group_id>", "Set the source group. Add this bot as an administrator in that group first.", "Example: /privategroup -1001234567890"),
    "join": ("🔗 𝐉𝐎𝐈𝐍 𝐕𝐂", "/join <target_id> [source_id]", "Connect the hosted account to source and target voice chats. If source_id is omitted, the configured source is used.", "Examples: /join -1002222222222  OR  /join -1002222222222 -1001111111111"),
    "leave": ("🛑 𝐋𝐄𝐀𝐕𝐄 𝐕𝐂", "/leave", "Leave both source and target voice chats.", "Example: /leave"),
    "dotjoin": ("⚡ 𝐃𝐎𝐓 𝐉𝐎𝐈𝐍", ".join", "In a group, the current group becomes the target. In a DM or Saved Messages, provide a target group ID. The source is your configured source group.", "Examples: send .join in the target group, or .join -1002222222222 in Saved Messages."),
    "dotleave": ("🚪 𝐃𝐎𝐓 𝐋𝐄𝐀𝐕𝐄", ".leave", "The hosted Telegram account leaves both the source and target voice chats from any chat.", "Example: send .leave in any chat."),
    "db": ("🔊 𝐃𝐁", "/db <value>", "Adjust output loudness in decibels. Positive values boost; negative values reduce.", "Example: /db 6  or  .db -3"),
    "gain": ("📈 𝐆𝐀𝐈𝐍", "/gain <value>", "Set the linear output multiplier. 1 is normal gain; higher values increase amplitude.", "Example: /gain 1.5"),
    "bass": ("🎚️ 𝐁𝐀𝐒𝐒", "/bass <value>", "Boost or reduce low-frequency energy in the relayed audio.", "Example: /bass 8"),
    "treble": ("🎛️ 𝐓𝐑𝐄𝐁𝐋𝐄", "/treble <value>", "Boost or reduce high-frequency energy for a brighter or softer sound.", "Example: /treble 5"),
    "echo": ("🔁 𝐄𝐂𝐇𝐎", "/echo <value>", "Add a short feedback echo. Set 0 to disable.", "Example: /echo 35"),
    "distortion": ("⚡ 𝐃𝐈𝐒𝐓𝐎𝐑𝐓𝐈𝐎𝐍", "/distortion <value>", "Add soft saturation/distortion to the relayed audio.", "Example: /distortion 40"),
    "level": ("🚀 𝐌𝐀𝐒𝐓𝐄𝐑 𝐋𝐄𝐕𝐄𝐋", "/level <number>", "Set a combined master profile that adjusts loudness, gain, bass, treble, echo and distortion together. Higher values produce a stronger profile; the audio engine keeps the actual signal within safe output bounds.", "Examples: /level 1  |  /level 100  |  /level 1000"),
}


@dp.callback_query(F.data.startswith("cmd:"))
async def command_detail_button(q: CallbackQuery):
    key = q.data.split(":", 1)[1]
    detail = COMMAND_DETAILS.get(key)
    if not detail:
        await q.answer("Command detail not found", show_alert=True)
        return
    title, syntax, purpose, example = detail
    text = title + "\n\n<b>Syntax:</b> <code>" + html.escape(syntax) + "</code>\n\n<b>Use:</b> " + html.escape(purpose) + "\n\n<b>Example:</b> <code>" + html.escape(example) + "</code>"
    category = "help" if key in ("host", "unhost", "cancel", "reset", "privategroup", "join", "leave", "dotjoin", "dotleave", "level") else ("eq" if key in ("bass", "treble") else ("vol" if key in ("db", "gain") else "fx"))
    await bot_send(q.message.edit_text, text, reply_markup=category_keyboard(category), parse_mode="HTML")
    await q.answer()

HOME_TEXT = "╭━━〔 ✨ 𝐅𝐋𝐄𝐗𝐈𝐁𝐋𝐄 𝐕𝐂 〕━━╮\n  𝐋𝐢𝐯𝐞 𝐕𝐨𝐢𝐜𝐞 𝐂𝐡𝐚𝐭 𝐁𝐫𝐢𝐝𝐠𝐞\n╰━━━━━━━━━━━━━━━━━━╯\n\n🎧 Source VC ki mixed live audio target VC mein relay karo.\n\n👇 Start karne ke liye option select karo."


@dp.message(Command("start"))
async def start(message: Message):
    await bot_send(message.answer, HOME_TEXT, reply_markup=home_keyboard())


@dp.callback_query(F.data == "home")
async def home_button(q: CallbackQuery):
    await bot_send(q.message.edit_text, HOME_TEXT, reply_markup=home_keyboard())
    await q.answer()


@dp.callback_query(F.data == "host")
async def host_button(q: CallbackQuery):
    if q.message.chat.type != "private":
        await q.answer("Account hosting ke liye bot ka private DM open karo.", show_alert=True)
        return
    await q.answer()
    await begin_host(q.from_user.id, q.message)

@dp.callback_query(F.data.in_({"help", "eq", "vol", "fx"}))
async def help_button(q: CallbackQuery):
    pages = {
                "help": "📚 𝐂𝐎𝐌𝐌𝐀𝐍𝐃𝐒\n/emoji_pack &lt;package&gt; — fetch all custom emoji details\n/host — account host\n/unhost — apna session/data delete\n/privategroup &lt;group_id&gt; — source group set\n/join &lt;target_id&gt; — configured source se connect\n/join &lt;target_id&gt; &lt;source_id&gt; — direct connect\n/leave — both VCs se disconnect\n\nDot commands hosted account se kahin bhi chalti hain.",
        "eq": "🎚️ 𝐄𝐐𝐔𝐀𝐋𝐈𝐙𝐄𝐑\n/bass &lt;value&gt; or .bass &lt;value&gt; — low frequencies adjust. Example: .bass 8\n/treble &lt;value&gt; or .treble &lt;value&gt; — high frequencies adjust. Example: .treble 5",
        "vol": "🔊 𝐕𝐎𝐋𝐔𝐌𝐄\n/db &lt;value&gt; or .db &lt;value&gt; — dB volume. Example: .db 6\n/gain &lt;value&gt; or .gain &lt;value&gt; — linear gain. Example: .gain 1.5\n/level &lt;number&gt; or .level &lt;number&gt; — combined master profile for all audio effects. Example: /level 100",
        "fx": "✨ 𝐀𝐔𝐃𝐈𝐎 𝐄𝐅𝐅𝐄𝐂𝐓𝐒\n/echo &lt;value&gt; or .echo &lt;value&gt; — echo amount. Example: .echo 35\n/distortion &lt;value&gt; or .distortion &lt;value&gt; — saturation. Example: .distortion 40",
    }
    await bot_send(q.message.edit_text, pages[q.data], reply_markup=category_keyboard(q.data))
    await q.answer()

async def begin_host(uid, message):
    if await storage.get_user(uid):
        await bot_send(message.answer, "Tumhara account pehle se hosted hai. /unhost use karo.")
        return
    pending[uid] = {"stage": "phone"}
    await bot_send(message.answer, "✦ 𝐇𝐎𝐒𝐓 𝐀𝐂𝐂𝐎𝐔𝐍𝐓\nApna number bhejo.\nExample: +91XXXXXXXXXX\n\nSirf apna account login karo.")

@dp.message(Command("emoji_pack"))
async def emoji_pack_cmd(message: Message):
    """Fetch every custom emoji and its metadata from a Telegram addemoji pack."""
    if message.chat.type != "private":
        await bot_send(message.reply, "🔒 /emoji_pack sirf private bot DM mein use karo.")
        return

    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) != 2:
        await bot_send(message.reply, 
            "Usage: <code>/emoji_pack https://t.me/addemoji/Hlo674</code>\n"
            "Pack ka addemoji link ya short name bhejo.",
            parse_mode="HTML",
        )
        return

    raw_pack = parts[1].strip()
    match = re.fullmatch(
        r"(?:https?://)?(?:www\.)?t\.me/addemoji/([A-Za-z0-9_]+)(?:/)?(?:\?.*)?|([A-Za-z][A-Za-z0-9_]{0,63})",
        raw_pack,
        re.IGNORECASE,
    )
    if not match:
        await bot_send(message.reply, 
            "⚠️ Invalid pack. Example: <code>/emoji_pack https://t.me/addemoji/Hlo674</code>",
            parse_mode="HTML",
        )
        return

    pack_name = match.group(1) or match.group(2)
    status = await bot_send(message.answer, f"🔎 <b>{html.escape(pack_name)}</b> pack fetch ho raha hai...", parse_mode="HTML")
    try:
        sticker_set = await bot.get_sticker_set(name=pack_name)
        all_stickers = sticker_set.stickers or []
        custom_stickers = [
            sticker for sticker in all_stickers
            if getattr(sticker, "type", None) == "custom_emoji"
            and getattr(sticker, "custom_emoji_id", None)
        ]

        if not custom_stickers:
            await bot_send(status.edit_text, 
                f"⚠️ <b>{html.escape(sticker_set.title or pack_name)}</b> mein koi Custom Emoji nahi mila. "
                f"Pack type: <code>{html.escape(str(sticker_set.sticker_type))}</code>",
                parse_mode="HTML",
            )
            return

        lines = [
            "🎨 <b>CUSTOM EMOJI PACK DETAILS</b>",
            f"📦 Title: <b>{html.escape(sticker_set.title or pack_name)}</b>",
            f"🔗 <a href=\"https://t.me/addemoji/{html.escape(pack_name)}\">Open pack</a>",
            f"📊 Total stickers: <b>{len(all_stickers)}</b>",
            f"✨ Custom emojis found: <b>{len(custom_stickers)}</b>",
            f"🏷 Pack type: <code>{html.escape(str(sticker_set.sticker_type))}</code>",
            "",
        ]

        for index, sticker in enumerate(custom_stickers, start=1):
            emoji = html.escape(sticker.emoji or "▫️")
            custom_id = html.escape(str(sticker.custom_emoji_id))
            file_id = html.escape(str(sticker.file_id))
            unique_id = html.escape(str(sticker.file_unique_id))
            fmt = "VIDEO" if sticker.is_video else ("ANIMATED" if sticker.is_animated else "STATIC")
            size = getattr(sticker, "file_size", None)
            size_text = f"{size} bytes" if size is not None else "not provided"
            repaint = "Yes" if getattr(sticker, "needs_repainting", False) else "No"
            lines.extend([
                f"<b>{index}. {emoji} — {fmt}</b>",
                f"Custom Emoji ID: <code>{custom_id}</code>",
                f"File ID: <code>{file_id}</code>",
                f"Unique ID: <code>{unique_id}</code>",
                f"Dimensions: <code>{sticker.width} × {sticker.height}</code>",
                f"File size: <code>{size_text}</code> | Repainting: <code>{repaint}</code>",
                "",
            ])

        pages = []
        page = ""
        for line in lines:
            candidate = f"{page}\n{line}" if page else line
            if len(candidate) > 3500 and page:
                pages.append(page)
                page = line
            else:
                page = candidate
        if page:
            pages.append(page)

        await status.delete()
        for page_text in pages:
            await bot_send(message.answer, page_text, parse_mode="HTML", disable_web_page_preview=True)

    except Exception as exc:
        log.warning("Emoji pack lookup failed for %s: %s", pack_name, type(exc).__name__)
        await bot_send(status.edit_text, 
            "⚠️ Pack fetch nahi hua. Link/name check karo aur ensure karo ki pack public hai."
        )


@dp.message(Command("host"))
async def host_cmd(message: Message):
    if message.chat.type != "private":
        await bot_send(message.reply, "/host sirf private bot DM mein use karo.")
        return
    await begin_host(message.from_user.id, message)


@dp.message(Command("cancel"))
async def cancel_host(message: Message):
    if message.chat.type != "private":
        return
    state = pending.pop(message.from_user.id, None)
    if state and state.get("client"):
        try:
            await state["client"].disconnect()
        except Exception:
            pass
    await bot_send(message.reply, "🛑 𝐇𝐎𝐒𝐓 𝐂𝐀𝐍𝐂𝐄𝐋𝐋𝐄𝐃\\nLogin process stopped. /host se dobara start karo." )

@dp.message(Command("unhost"))
async def unhost_cmd(message: Message):
    if message.chat.type != "private":
        await bot_send(message.reply, "/unhost sirf private bot DM mein use karo.")
        return
    pending_state = pending.pop(message.from_user.id, None)
    if pending_state and pending_state.get("client"):
        try:
            await pending_state["client"].disconnect()
        except Exception:
            log.debug("Pending login client was already closed")
    await manager.unhost(message.from_user.id)
    await bot_send(message.reply, "🧹 𝐔𝐍𝐇𝐎𝐒𝐓 𝐂𝐎𝐌𝐏𝐋𝐄𝐓𝐄 — tumhara session aur MongoDB user data delete ho gaya.")

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
        await bot_send(message.reply, "Is command ko bot ke private DM mein use karo.")
        return
    row = await storage.get_user(message.from_user.id)
    parts = (message.text or "").split()
    if not row or len(parts) != 2:
        await bot_send(message.reply, "Usage: /privategroup <group_id> — pehle /host karo aur private bot ko group mein admin banao.")
        return
    try:
        gid = int(parts[1])
        me = await bot.get_me()
        member = await bot.get_chat_member(gid, me.id)
        if member.status not in ("administrator", "creator"):
            raise RuntimeError("Private bot ko source group mein admin banao.")
        await manager.hosted[message.from_user.id]["client"].get_entity(gid)
        await storage.save_user(message.from_user.id, private_group_id=gid, source_group_id=gid)
        await bot_send(message.reply, "🔐 𝐏𝐑𝐈𝐕𝐀𝐓𝐄 𝐆𝐑𝐎𝐔𝐏 𝐒𝐄𝐓\nSource: " + str(gid))
    except Exception as exc:
        await bot_send(message.reply, "⚠️ " + str(exc))

@dp.message(Command("join"))
async def join_cmd(message: Message):
    owner = await command_owner(message)
    parts = (message.text or "").split()
    if owner is None or len(parts) not in (2, 3):
        await bot_send(message.reply, "Usage: /join <target_id> [source_id]. Privategroup mein sirf admins use kar sakte hain.")
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
        await bot_send(message.reply, "🔊 𝐕𝐂 𝐁𝐑𝐈𝐃𝐆𝐄 𝐀𝐂𝐓𝐈𝐕𝐄\nSource: " + str(source) + "\nTarget: " + str(target))
    except Exception as exc:
        await bot_send(message.reply, "⚠️ " + str(exc))

@dp.message(Command("leave"))
async def leave_cmd(message: Message):
    owner = await command_owner(message)
    if owner is None:
        await bot_send(message.reply, "Hosted user ya privategroup admin access required.")
        return
    await manager.leave(owner)
    await bot_send(message.reply, "🛑 Source aur target dono VC se leave ho gaya.")

@dp.message()
async def text_router(message: Message):
    if not message.from_user or not message.text:
        return
    uid = message.from_user.id
    state = pending.get(uid) if message.chat.type == "private" else None
    if state:
        value = message.text.strip()
        stage = state.get("stage")

        # Keep the phone number message visible. OTP/2FA values are processed
        # only in memory and are never written to logs or persistent storage.
        try:
            if stage == "phone":
                if not re.fullmatch(r"\+?[1-9]\d{7,14}", value):
                    await bot_send(bot.send_message, uid, "⚠️ 𝐈𝐧𝐯𝐚𝐥𝐢𝐝 𝐍𝐮𝐦𝐛𝐞𝐫\nCountry code ke saath number bhejo.")
                    return
                client = TelegramClient(StringSession(), config.api_id, config.api_hash)
                await client.connect()
                try:
                    sent = await client.send_code_request(value)
                except Exception:
                    await client.disconnect()
                    log.warning("Telegram code request failed for user %s", uid)
                    await bot_send(bot.send_message, uid, "⚠️ 𝐎𝐓𝐏 𝐒𝐄𝐍𝐃 𝐍𝐎𝐓 𝐒𝐄𝐍𝐓\nNumber check karke dobara bhejo.")
                    return
                pending[uid] = {
                    "stage": "code", "client": client, "phone": value,
                    "hash": sent.phone_code_hash, "attempts": 0,
                }
                await bot_send(bot.send_message, uid, "✉️ 𝐄𝐍𝐓𝐄𝐑 𝐎𝐓𝐏\nTelegram par aaya login code bhejo. (3 attempts)")
                return

            if stage == "code":
                try:
                    await state["client"].sign_in(
                        phone=state["phone"], code=value,
                        phone_code_hash=state["hash"],
                    )
                except SessionPasswordNeededError:
                    state["stage"] = "password"
                    state["attempts"] = 0
                    await bot_send(bot.send_message, uid, "🔐 𝐄𝐍𝐓𝐄𝐑 𝟐𝐅𝐀\nAccount password bhejo. (3 attempts)")
                    return
                except PhoneCodeInvalidError:
                    state["attempts"] = state.get("attempts", 0) + 1
                    left = 3 - state["attempts"]
                    if left <= 0:
                        await state["client"].disconnect()
                        pending.pop(uid, None)
                        await bot_send(bot.send_message, uid, "⛔ 𝐋𝐎𝐆𝐈𝐍 𝐂𝐋𝐎𝐒𝐄𝐃\n3 wrong OTP attempts. /host se restart karo.")
                    else:
                        await bot_send(bot.send_message, uid, f"⚠️ 𝐖𝐑𝐎𝐍𝐆 𝐎𝐓𝐏\n{left} attempts left. Dobara bhejo.")
                    return
                except PhoneCodeExpiredError:
                    await state["client"].disconnect()
                    pending.pop(uid, None)
                    await bot_send(bot.send_message, uid, "⌛ 𝐎𝐓𝐏 𝐄𝐗𝐏𝐈𝐑𝐄𝐃\n/host se dobara start karo.")
                    return
                client = state["client"]

            elif stage == "password":
                try:
                    await state["client"].sign_in(password=value)
                except PasswordHashInvalidError:
                    state["attempts"] = state.get("attempts", 0) + 1
                    left = 3 - state["attempts"]
                    if left <= 0:
                        await state["client"].disconnect()
                        pending.pop(uid, None)
                        await bot_send(bot.send_message, uid, "⛔ 𝐋𝐎𝐆𝐈𝐍 𝐂𝐋𝐎𝐒𝐄𝐃\n3 wrong 2FA attempts. /host se restart karo.")
                    else:
                        await bot_send(bot.send_message, uid, f"⚠️ 𝐖𝐑𝐎𝐍𝐆 𝟐𝐅𝐀\n{left} attempts left. Dobara bhejo.")
                    return
                client = state["client"]
            else:
                pending.pop(uid, None)
                await bot_send(bot.send_message, uid, "⚠️ Login state reset. /host se restart karo.")
                return

            await manager.add_authenticated_client(uid, client)
            pending.pop(uid, None)
            await bot_send(bot.send_message, uid, "✅ 𝐀𝐂𝐂𝐎𝐔𝐍𝐓 𝐇𝐎𝐒𝐓𝐄𝐃\nAb /privategroup ya /join use karo.")

        except PhoneNumberInvalidError:
            await bot_send(bot.send_message, uid, "⚠️ 𝐈𝐍𝐕𝐀𝐋𝐈𝐃 𝐍𝐔𝐌𝐁𝐄𝐑\nCountry code ke saath dobara bhejo.")
        except Exception as exc:
            log.warning("Host flow error for user %s at stage %s: %s", uid, stage, type(exc).__name__)
            # Keep the active login state for recoverable errors; never log
            # phone, OTP, or 2FA input values.
            await bot_send(bot.send_message, uid, "⚠️ 𝐋𝐎𝐆𝐈𝐍 𝐄𝐑𝐑𝐎𝐑\nThodi der baad retry karo ya /cancel use karo.")
        return
    match = re.match(r"^/(reset|level|db|gain|bass|treble|echo|distortion)(?:\s+(.+))?$", message.text.strip(), re.I)
    if not match:
        return
    owner = await command_owner(message)
    if owner is None:
        await bot_send(message.reply, "Pehle /host karo; privategroup mein sirf admins commands use kar sakte hain.")
        return
    name, arg = match.group(1).lower(), (match.group(2) or "").strip()
    try:
        if name == "reset":
            if arg:
                await bot_send(message.reply, "Usage: /reset")
                return
            await manager.reset_effects(owner)
            await bot_send(message.reply, "♻️ 𝐀𝐋𝐋 𝐄𝐅𝐅𝐄𝐂𝐓𝐒 𝐑𝐄𝐒𝐄𝐓\\nAll audio controls original defaults par aa gaye.")
            return
        if not arg:
            row = await storage.get_user(owner) or {}
            from audio import DEFAULT_EFFECTS
            value = row.get("effects", {}).get(name, DEFAULT_EFFECTS[name])
            await bot_send(message.reply, name.upper() + " current: " + str(value) + "\nExample: /" + name + " 10")
            return
        value = await manager.set_effect(owner, name, float(arg.split()[0]))
        await bot_send(message.reply, "✅ " + name.upper() + " set: " + str(value))
    except Exception as exc:
        await bot_send(message.reply, "⚠️ " + str(exc))

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
