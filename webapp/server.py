import asyncio, json, logging
from pathlib import Path
from aiohttp import web, WSMsgType
from webapp.auth import AuthError, validate_init_data, issue_ticket, verify_ticket

log = logging.getLogger("flexible_vc.webapp")
STATIC = Path(__file__).with_name("static")
EFFECT_LIMITS = {
    "db": (-30, 24), "gain": (0, 8), "level": (0, 1000),
    "bass": (-24, 24), "treble": (-24, 24), "presence": (-24, 24),
    "air": (-24, 24), "echo": (0, 100), "distortion": (0, 100),
    "loudmax": (0, 100), "stereowide": (0, 100), "bitcrush": (0, 100),
}

class MiniAppServer:
    def __init__(self, manager, bot_token: str, secret: str, public_url: str = ""):
        self.manager, self.bot_token, self.secret = manager, bot_token, secret
        self.public_url = public_url.rstrip("/")
        self.runner = None

    async def start(self, host="0.0.0.0", port=8008):
        app = web.Application(client_max_size=65536)
        app.router.add_get("/mini-app", self.index)
        app.router.add_get("/mini-app/", self.index)
        app.router.add_post("/mini-app/api/auth", self.auth)
        app.router.add_get("/mini-app/api/status", self.status)
        app.router.add_get("/mini-app/api/groups", self.groups)
        app.router.add_post("/mini-app/api/effects", self.effects)
        app.router.add_post("/mini-app/api/join", self.join)
        app.router.add_get("/mini-app/api/live", self.live)
        app.router.add_static("/mini-app/static/", STATIC, show_index=False)
        self.runner = web.AppRunner(app, access_log=None)
        await self.runner.setup()
        await web.TCPSite(self.runner, host, port).start()
        log.info("Mini App listening on %s:%s", host, port)

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()
            self.runner = None

    async def index(self, request):
        return web.FileResponse(STATIC / "index.html")

    def bearer(self, request):
        scheme, _, token = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer":
            raise AuthError("Authorization required")
        return verify_ticket(token, self.secret)

    def hosted(self, uid):
        item = self.manager.hosted.get(int(uid))
        if not item:
            raise AuthError("Hosted account is not connected")
        return item

    async def auth(self, request):
        try:
            body = await request.json()
            uid = validate_init_data(str(body.get("initData") or ""), self.bot_token)
            self.hosted(uid)
            return web.json_response({"ok": True, "ticket": issue_ticket(uid, self.secret)})
        except (AuthError, ValueError, TypeError) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=401)

    async def status(self, request):
        try:
            uid = self.bearer(request)
            item = self.hosted(uid)
            row = await self.manager.storage.get_user(uid) or {}
            bridge = item.get("bridge")
            from audio import DEFAULT_EFFECTS
            effects = {**DEFAULT_EFFECTS, **row.get("effects", {})}
            source_id = bridge.source_id if bridge and bridge.connected else row.get("source_group_id")
            target_id = bridge.target_id if bridge and bridge.connected else row.get("target_group_id")
            async def title(cid):
                if not cid: return None
                try:
                    ent = await item["client"].get_entity(int(cid))
                    return getattr(ent, "title", None) or str(cid)
                except Exception: return str(cid)
            return web.json_response({"ok": True, "account": getattr(item.get("me"), "first_name", "Hosted account"),
                "bridge": bool(bridge and bridge.connected),
                "source": {"id": source_id, "name": await title(source_id)},
                "target": {"id": target_id, "name": await title(target_id)},
                "effects": effects,
                "dominant": bridge.dominant if bridge else True,
                "host_boost": bridge.host_boost if bridge else 4.0})
        except (AuthError, Exception) as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=401 if isinstance(exc, AuthError) else 400)

    async def groups(self, request):
        try:
            uid = self.bearer(request)
            return web.json_response({"ok": True, "groups": await self.manager.list_active_voice_chats(uid)})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=401)

    async def effects(self, request):
        try:
            uid = self.bearer(request); self.hosted(uid)
            body = await request.json()
            name = str(body.get("name", "")).lower()
            if name not in EFFECT_LIMITS: raise ValueError("Unknown audio control")
            value = float(body.get("value"))
            low, high = EFFECT_LIMITS[name]
            if not low <= value <= high: raise ValueError(f"{name} must be between {low} and {high}")
            actual = await self.manager.set_effect(uid, name, value)
            return web.json_response({"ok": True, "name": name, "value": actual})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def join(self, request):
        try:
            uid = self.bearer(request); self.hosted(uid)
            body = await request.json()
            target = int(body.get("target_id"))
            result = await self.manager.switch_target(uid, target)
            return web.json_response({"ok": True, "target": result})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)

    async def live(self, request):
        ws = web.WebSocketResponse(heartbeat=25, max_msg_size=4096)
        await ws.prepare(request)
        bridge = None
        try:
            msg = await ws.receive(timeout=10)
            if msg.type != WSMsgType.TEXT: raise AuthError("Authenticate first")
            uid = verify_ticket(json.loads(msg.data).get("ticket", ""), self.secret)
            item = self.hosted(uid)
            bridge = item.get("bridge")
            if not bridge or not bridge.connected: raise RuntimeError("Connect source and target VC first")
            await ws.send_json({"type": "ready"})
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    if len(msg.data) != 960:
                        continue
                    await bridge.send_live_frame(bytes(msg.data))
                elif msg.type == WSMsgType.TEXT:
                    command = json.loads(msg.data)
                    if command.get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        except Exception as exc:
            if not ws.closed:
                await ws.send_json({"type": "error", "message": str(exc)})
        finally:
            if not ws.closed: await ws.close()
        return ws
