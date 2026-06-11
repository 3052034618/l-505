from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from typing import Dict, Set, List, Optional
import json
import asyncio
import threading
from datetime import datetime
from sqlalchemy.orm import Session
from database import get_db
import models
from auth import get_current_user
from jose import JWTError, jwt
from config import settings

router_ws = APIRouter(tags=["实时推送"])

_ws_event_loop: Optional[asyncio.AbstractEventLoop] = None
_ws_loop_thread: Optional[threading.Thread] = None


def _ensure_event_loop():
    global _ws_event_loop, _ws_loop_thread
    if _ws_event_loop is not None and _ws_event_loop.is_running():
        return _ws_event_loop

    def _run_loop():
        global _ws_event_loop
        _ws_event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_ws_event_loop)
        _ws_event_loop.run_forever()

    if _ws_loop_thread is None or not _ws_loop_thread.is_alive():
        _ws_loop_thread = threading.Thread(target=_run_loop, daemon=True, name="ws-dispatch")
        _ws_loop_thread.start()
        import time as _t
        for _ in range(50):
            if _ws_event_loop is not None:
                break
            _t.sleep(0.05)
    return _ws_event_loop


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.lab_connections: Dict[int, Set[int]] = {}
        self.role_connections: Dict[str, Set[int]] = {}

    async def connect(self, websocket: WebSocket, user_id: int, lab_id: Optional[int] = None, role: Optional[str] = None):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        if lab_id:
            if lab_id not in self.lab_connections:
                self.lab_connections[lab_id] = set()
            self.lab_connections[lab_id].add(user_id)
        if role:
            if role not in self.role_connections:
                self.role_connections[role] = set()
            self.role_connections[role].add(user_id)

    def disconnect(self, user_id: int, lab_id: Optional[int] = None, role: Optional[str] = None):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        if lab_id and lab_id in self.lab_connections:
            self.lab_connections[lab_id].discard(user_id)
        if role and role in self.role_connections:
            self.role_connections[role].discard(user_id)

    async def send_personal_message(self, message: dict, user_id: int):
        if user_id in self.active_connections:
            try:
                ws = self.active_connections[user_id]
                await ws.send_text(json.dumps(message, ensure_ascii=False, default=str))
            except Exception:
                pass

    async def send_to_users(self, message: dict, user_ids: List[int]):
        for uid in user_ids:
            await self.send_personal_message(message, uid)

    async def send_to_lab(self, message: dict, lab_id: int):
        if lab_id in self.lab_connections:
            user_ids = list(self.lab_connections[lab_id])
            await self.send_to_users(message, user_ids)

    async def send_to_roles(self, message: dict, roles: List[str]):
        all_user_ids = set()
        for role in roles:
            if role in self.role_connections:
                all_user_ids.update(self.role_connections[role])
        await self.send_to_users(message, list(all_user_ids))

    async def broadcast(self, message: dict):
        for user_id in list(self.active_connections.keys()):
            await self.send_personal_message(message, user_id)


manager = ConnectionManager()


def get_user_from_token(token: str, db: Session):
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None, None, None
        user = db.query(models.User).filter(models.User.username == username).first()
        if user and user.is_active:
            role = payload.get("role")
            return user, user.lab_id, role
    except JWTError:
        pass
    return None, None, None


@router_ws.websocket("/ws/notifications")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token"),
    db: Session = Depends(get_db)
):
    _ensure_event_loop()
    user, lab_id, role = get_user_from_token(token, db)
    if not user:
        await websocket.close(code=1008, reason="Invalid or expired token")
        return

    user_id = user.id
    lab_id = lab_id
    role = role

    await manager.connect(websocket, user_id, lab_id, role)

    try:
        hello_msg = {
            "type": "system",
            "event": "connected",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "user_id": user_id,
                "username": user.username,
                "role": role,
                "lab_id": lab_id,
                "message": "实时推送连接已建立"
            }
        }
        await manager.send_personal_message(hello_msg, user_id)

        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await manager.send_personal_message({
                        "type": "system",
                        "event": "pong",
                        "timestamp": datetime.utcnow().isoformat()
                    }, user_id)
                elif msg.get("type") == "subscribe":
                    topics = msg.get("topics", [])
                    await manager.send_personal_message({
                        "type": "system",
                        "event": "subscribed",
                        "topics": topics,
                        "timestamp": datetime.utcnow().isoformat()
                    }, user_id)
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(user_id, lab_id, role)


async def push_notification(notification_type: str, event: str, data: dict, user_ids: Optional[List[int]] = None, lab_id: Optional[int] = None, roles: Optional[List[str]] = None):
    message = {
        "type": notification_type,
        "event": event,
        "timestamp": datetime.utcnow().isoformat(),
        "data": data
    }

    if user_ids:
        await manager.send_to_users(message, user_ids)
    if lab_id:
        await manager.send_to_lab(message, lab_id)
    if roles:
        await manager.send_to_roles(message, roles)


def dispatch_ws_event(notification_type: str, event: str, data: dict,
                      user_ids: Optional[List[int]] = None,
                      lab_id: Optional[int] = None,
                      roles: Optional[List] = None):
    try:
        loop = _ensure_event_loop()
        if loop is None:
            return
        role_strs = [r.value if hasattr(r, 'value') else str(r) for r in (roles or [])]
        user_id_ints = [int(uid) for uid in (user_ids or [])]
        lab_int = int(lab_id) if lab_id is not None else None
        asyncio.run_coroutine_threadsafe(
            push_notification(notification_type, event, data, user_id_ints, lab_int, role_strs),
            loop
        )
    except Exception:
        pass
