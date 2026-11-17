import logging
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from cryptography.fernet import Fernet
from config import config
from voice_bridge import VoiceBridge
from custom_emoji import telethon_entities

log = logging.getLogger("flexible_vc")


class HostedManager:
    def __init__(self, storage):
        self.storage = storage
        self.hosted = {}
        self.fernet = Fernet(config.session_encryption_key.encode())

    def encrypt_session(self, session: str) -> str:
        return self.fernet.encrypt(session.encode()).decode()

    def decrypt_session(self, token: str) -> str:
        return self.fernet.decrypt(token.encode()).decode()

    async def restore_all(self):
        for row in await self.storage.all_users():
            try:
                session = self.decrypt_session(row["session_encrypted"])
                client = TelegramClient(StringSession(session), config.api_id, config.api_hash)
                await client.connect()
                if not await client.is_user_authorized():
                    log.warning("Hosted session for %s is no longer authorized", row["user_id"])
                    await client.disconnect()
                    continue
                await self._register(row["user_id"], client, row)
                if row.get("active") and row.get("source_group_id") and row.get("target_group_id"):
                    try:
                        await self.start_bridge(
                            int(row["user_id"]),
                            int(row["source_group_id"]),
                            int(row["target_group_id"]),
                        )
                    except Exception:
                        log.exception("Could not restore active bridge for %s", row["user_id"])
                        await self.storage.save_user(
                            int(row["user_id"]),
                            active=False,
                            source_group_id=None,
                            target_group_id=None,
                        )
            except Exception:
                log.exception("Could not restore hosted user %s", row.get("user_id"))

    async def _register(self, user_id, client, row):
        me = await client.get_me()
        # Prime Telethon's peer/access-hash cache so numeric -100... chat IDs
        # supplied by commands can be resolved by the call engine.
        try:
            await client.get_dialogs(limit=None)
        except Exception:
            log.warning("Could not preload all dialogs for hosted account %s", user_id)
        item = {
            "premium": bool(getattr(me, "premium", False)),
            "client": client,
            "me": me,
            "bridge": None,
            "row": row,
        }
        self.hosted[int(user_id)] = item

        @client.on(events.NewMessage(outgoing=True))
        async def dot_commands(event):
            await self.handle_dot_command(int(user_id), event)

    async def add_authenticated_client(self, user_id: int, client):
        me = await client.get_me()
        session = client.session.save()
        row = {
            "user_id": int(user_id),
            "telegram_user_id": int(me.id),
            "telegram_name": me.first_name or "",
            "session_encrypted": self.encrypt_session(session),
            "effects": {},
            "private_group_id": None,
            "source_group_id": None,
            "target_group_id": None,
            "active": False,
        }
        await self.storage.save_user(user_id, **{k: v for k, v in row.items() if k != "user_id"})
        await self._register(user_id, client, row)

    async def get(self, user_id: int):
        return self.hosted.get(int(user_id))

    async def start_bridge(self, owner_id: int, source_id: int, target_id: int):
        item = self.hosted.get(int(owner_id))
        if not item:
            raise RuntimeError("Pehle /host se account host karo.")
        if int(source_id) == int(target_id):
            raise RuntimeError("Source aur target group alag hone chahiye.")
        bridge = item.get("bridge")
        if bridge and bridge.connected:
            if bridge.source_id == int(source_id) and bridge.target_id == int(target_id):
                return
            try:
                target_entity = await item["client"].get_entity(bridge.target_id)
                target_name = getattr(target_entity, "title", None) or str(bridge.target_id)
            except Exception:
                target_name = str(bridge.target_id)
            raise RuntimeError(
                f"Already connected. Current target: {target_name} ({bridge.target_id}). Pehle /leave karo."
            )

        # Check both voice chats before creating either connection. If a call
        # is off, PyTgCalls may start it only when Telegram grants manage_call.
        source_active, source_can_start = await self._call_status(
            item["client"], int(source_id)
        )
        target_active, target_can_start = await self._call_status(
            item["client"], int(target_id)
        )
        if not source_active and not source_can_start:
            raise RuntimeError(f"Source VC ({source_id}) band hai. Admin se VC start karwao.")
        if not target_active and not target_can_start:
            raise RuntimeError(f"Target VC ({target_id}) band hai. Admin se VC start karwao.")

        effects = (await self.storage.get_user(owner_id) or {}).get("effects", {})
        if bridge is None:
            bridge = VoiceBridge(item["client"], source_id, target_id, effects)
            item["bridge"] = bridge
        else:
            bridge.configure(source_id, target_id, effects)
        await bridge.connect(
            source_auto_start=not source_active,
            target_auto_start=not target_active,
        )
        await self.storage.save_user(
            owner_id,
            source_group_id=int(source_id),
            target_group_id=int(target_id),
            active=True,
        )

    async def _call_status(self, client, chat_id):
        from telethon import functions, types

        entity = await client.get_entity(chat_id)
        if isinstance(entity, types.Channel):
            full = await client(functions.channels.GetFullChannelRequest(channel=entity))
            active = bool(getattr(full.full_chat, "call", None))
            can_start = False
            try:
                participant = await client(
                    functions.channels.GetParticipantRequest(
                        channel=entity,
                        participant=types.InputPeerSelf(),
                    )
                )
                part = participant.participant
                can_start = bool(
                    getattr(part, "creator", False)
                    or getattr(getattr(part, "admin_rights", None), "manage_call", False)
                )
            except Exception:
                pass
            return active, can_start
        raise RuntimeError("Abhi supergroup/channel voice chats supported hain; basic group check unavailable.")

    async def list_active_voice_chats(self, owner_id: int):
        """Return active group calls visible to the hosted Telegram account."""
        item = self.hosted.get(int(owner_id))
        if not item:
            raise RuntimeError("Hosted account is not connected.")
        from telethon import functions, types
        client = item["client"]
        dialogs = await client.get_dialogs(limit=None)
        active = []
        for dialog in dialogs:
            entity = dialog.entity
            if not isinstance(entity, types.Channel) or not getattr(entity, "megagroup", False):
                continue
            try:
                full = await client(functions.channels.GetFullChannelRequest(channel=entity))
                call = getattr(full.full_chat, "call", None)
                if call:
                    active.append({"id": int(dialog.id), "title": str(dialog.title or dialog.id)})
            except Exception:
                continue
        active.sort(key=lambda row: row["title"].casefold())
        return active

    async def switch_target(self, owner_id: int, target_id: int):
        item = self.hosted.get(int(owner_id))
        if not item:
            raise RuntimeError("Pehle /host se account host karo.")
        row = await self.storage.get_user(owner_id) or {}
        bridge = item.get("bridge")
        if bridge and bridge.connected:
            if int(target_id) == bridge.source_id:
                raise RuntimeError("Source group ko target nahi bana sakte.")
            active, can_start = await self._call_status(item["client"], int(target_id))
            if not active and not can_start:
                raise RuntimeError("Selected group ka VC active nahi hai ya hosted account ko start permission nahi hai.")
            await bridge.switch_target(int(target_id), auto_start=not active)
            await self.storage.save_user(owner_id, target_group_id=int(target_id), active=True)
            return {"id": int(target_id), "source_id": bridge.source_id}
        source_id = row.get("private_group_id") or row.get("source_group_id")
        if not source_id:
            raise RuntimeError("Pehle /privategroup se source group set karo ya /join command use karo.")
        await self.start_bridge(owner_id, int(source_id), int(target_id))
        return {"id": int(target_id), "source_id": int(source_id)}

    async def leave(self, owner_id: int):
        item = self.hosted.get(int(owner_id))
        if not item:
            return
        bridge = item.get("bridge")
        if bridge:
            await bridge.disconnect()
        await self.storage.save_user(
            owner_id, active=False, source_group_id=None, target_group_id=None
        )

    async def reset_effects(self, owner_id: int):
        item = self.hosted.get(int(owner_id))
        if not item:
            raise RuntimeError("Account hosted nahi hai.")
        from audio import AudioProcessor, DEFAULT_EFFECTS
        if item.get("bridge"):
            item["bridge"].processor.reset()
        effects = dict(DEFAULT_EFFECTS)
        await self.storage.save_user(owner_id, effects=effects)
        return effects

    async def set_effect(self, owner_id: int, name: str, value: float):
        item = self.hosted.get(int(owner_id))
        if not item:
            raise RuntimeError("Account hosted nahi hai.")
        row = await self.storage.get_user(owner_id) or {}
        if item.get("bridge"):
            actual = item["bridge"].set_effect(name, value)
            effects = dict(item["bridge"].processor.settings)
        else:
            from audio import AudioProcessor
            processor = AudioProcessor(row.get("effects", {}))
            actual = processor.update(name, value)
            effects = dict(processor.settings)
        await self.storage.save_user(owner_id, effects=effects)
        return actual

    async def unhost(self, owner_id: int):
        item = self.hosted.pop(int(owner_id), None)
        try:
            if item:
                if item.get("bridge"):
                    try:
                        await item["bridge"].disconnect()
                    except Exception:
                        log.exception("Bridge cleanup failed during unhost for %s", owner_id)
                try:
                    # Revoke only this hosted Telegram authorization, then close its client.
                    await item["client"].log_out()
                except Exception:
                    log.exception("Telegram logout failed during unhost for %s", owner_id)
                    try:
                        await item["client"].disconnect()
                    except Exception:
                        log.exception("Telegram client disconnect failed for %s", owner_id)
        finally:
            await self.storage.delete_user(owner_id)


    async def _reply_custom(self, event, text, owner_id):
        item = self.hosted.get(int(owner_id)) or {}
        # Every dot-command response starts with a random-pool emoji.
        # Premium hosted accounts render it as a custom animated emoji;
        # non-Premium accounts keep the normal fallback emoji.
        text = "✨ " + str(text)
        entities = telethon_entities(text, bool(item.get("premium")))
        await event.reply(text, formatting_entities=entities or None)

    async def handle_dot_command(self, owner_id: int, event):
        import re
        match = re.match(
            r"^\.(join|leave|reset|level|db|gain|bass|treble|echo|distortion"
            r"|presence|air|loudmax|stereowide|bitcrush|dominant|hostboost)(?:\s+(.+))?$",
            event.raw_text.strip(), re.I,
        )
        if not match:
            return
        command, argument = match.group(1).lower(), (match.group(2) or "").strip()
        row = await self.storage.get_user(owner_id) or {}
        try:
            if command == "join":
                if argument:
                    target_id = int(argument.split()[0])
                else:
                    target_id = int(event.chat_id)
                    if target_id > 0:
                        raise RuntimeError("DM/Saved Messages mein .join <target_group_id> use karo.")
                source_id = row.get("private_group_id") or row.get("source_group_id")
                if not source_id:
                    raise RuntimeError("Pehle bot DM mein /privategroup <source_group_id> ya /join <target_id> <source_id> set karo.")
                await self.start_bridge(owner_id, int(source_id), target_id)
                await self._reply_custom(event, f"🔊 𝐕𝐂 𝐁𝐑𝐈𝐃𝐆𝐄 𝐀𝐂𝐓𝐈𝐕𝐄\nSource: {source_id}\nTarget: {target_id}", owner_id)
            elif command == "leave":
                await self.leave(owner_id)
                await self._reply_custom(event, "🛑 𝐒𝐎𝐔𝐑𝐂𝐄 & 𝐓𝐀𝐑𝐆𝐄𝐓 VC se disconnect ho gaya.", owner_id)
            elif command == "reset":
                await self.reset_effects(owner_id)
                await self._reply_custom(event, "♻️ 𝐀𝐋𝐋 𝐄𝐅𝐅𝐄𝐂𝐓𝐒 𝐑𝐄𝐒𝐄𝐓\nAll audio controls original defaults par aa gaye.", owner_id)
            elif command == "dominant":
                bridge = self.hosted.get(owner_id, {}).get("bridge")
                if not bridge:
                    raise RuntimeError("Bridge not active.")
                enabled = argument.lower() not in ("0", "off", "false") if argument else True
                bridge.set_dominant(enabled)
                await self._reply_custom(event, f"👑 𝐃𝐎𝐌𝐈𝐍𝐀𝐍𝐓 𝐌𝐎𝐃𝐄: {'ON' if enabled else 'OFF'}\nAapki awaaz target VC pe sabse upar rahegi.", owner_id)
            elif command == "hostboost":
                bridge = self.hosted.get(owner_id, {}).get("bridge")
                if not bridge:
                    raise RuntimeError("Bridge not active.")
                multiplier = float(argument.split()[0]) if argument else bridge.host_boost
                actual = bridge.set_host_boost(multiplier)
                await self._reply_custom(event, f"🚀 𝐇𝐎𝐒𝐓 𝐁𝐎𝐎𝐒𝐓: {actual:g}× (+{20*__import__('math').log10(actual):.1f} dB over others)", owner_id)
            else:
                if not argument:
                    from audio import DEFAULT_EFFECTS
                    current = row.get("effects", {}).get(command, DEFAULT_EFFECTS.get(command, 0))
                    await self._reply_custom(event, f"🎚️ 𝐂𝐮𝐫𝐫𝐞𝐧𝐭 {command.upper()}: {current}\nExample: .{command} 10", owner_id)
                    return
                value = float(argument.split()[0])
                actual = await self.set_effect(owner_id, command, value)
                await self._reply_custom(event, f"✅ 𝐀𝐮𝐝𝐢𝐨 {command.upper()} set: {actual:g}", owner_id)
        except Exception as exc:
            await self._reply_custom(event, f"⚠️ {str(exc)}", owner_id)
