"""
Chatbot Client API
==================
API proxy don gian de team ky thuat chat truc tiep voi Chatbot Service.
Chay doc lap o port 8002, khong phu thuoc vao Performance API.

Cach dung:
    cd tests/
    python chatbot_client_api.py

Sau do mo: http://localhost:8002/docs
"""

import asyncio
import json
import uuid
import httpx
import uvicorn
import websockets as ws_lib

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional, Any
from pathlib import Path
from datetime import datetime

# ─── CONFIG ─────────────────────────────────────────────────────────────────
TARGET_HOST   = "http://139.59.126.158:8000"
WS_SERVER     = "ws://139.59.126.158:8000/ws/chat"   # WebSocket streaming endpoint
CHAT_ENDPOINT = f"{TARGET_HOST}/api/v1/chat"

# ─── DEBUG FLAG ─────────────────────────────────────────────────────────────
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chatbot-client")

# Profile fix cung: luon dung 2 file nay
DATA_DIR     = Path(__file__).parent.parent / "data" / "test"
HOLLAND_FILE = DATA_DIR / "Real_Holland.json"
PROFILE_FILE = DATA_DIR / "Real_Profile.json"

# Luu session trong memory (reset khi restart API)
sessions: dict[str, list[dict]] = {}

# ─── APP ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Chatbot Client API",
    description=f"""
## API client de tuong tac voi Chatbot Service nhu nguoi dung thuc

**Target Chatbot Server:** `{TARGET_HOST}`

---

### Cach su dung:

1. Goi `POST /chat/new` de bat dau phien hoi thoai moi → nhan duoc `session_id`
2. Goi `POST /chat` voi `session_id` va `message` de chat
3. Goi `GET /sessions/{{session_id}}/history` de xem lai lich su
4. Goi `DELETE /sessions/{{session_id}}` de xoa phien va bat dau moi

---

### Luu y:
- Moi `session_id` tuong ung voi 1 cuoc hoi thoai rieng biet
- Server hien tai: `{TARGET_HOST}`
- Lich su phien chi ton tai trong RAM, reset khi API khoi dong lai
""",
    version="1.0.0",
)


# ─── SCHEMAS ────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        min_length=1, max_length=5000,
        description="Noi dung tin nhan gui cho chatbot",
        examples=["Chao bot, em can tu van ve nghe nghiep phu hop voi em?"]
    )
    session_id: Optional[str] = Field(
        None,
        description="ID phien hoi thoai. Neu khong truyen, tu dong tao moi.",
        examples=["my-test-session-001"]
    )
    user_id: Optional[str] = Field(
        None,
        description="User ID (tuy chon, dung cho long-term memory neu server ho tro)",
        examples=["test-user-01"]
    )
    use_profile: bool = Field(
        True,
        description="Co gui kem Holland test + User Profile (Real_Holland.json / Real_Profile.json) hay khong. "
                    "Mac dinh: True. Tat di (False) de test chatbot khong co du lieu nguoi dung."
    )


class NewSessionResponse(BaseModel):
    session_id: str
    message: str
    created_at: str


class ChatResponse(BaseModel):
    session_id: str
    message: str
    reply: str
    turn: int
    timestamp: str
    server: str


# --- HELPER: LOAD FIXED PROFILE -----------------------------------------------
def _load_real_profile() -> dict:
    """Load co dinh Real_Holland.json va Real_Profile.json."""
    result = {"profile_test": None, "test_json": None, "test_id": None}
    if HOLLAND_FILE.exists():
        data = json.loads(HOLLAND_FILE.read_text(encoding="utf-8"))
        result["test_json"] = data
        result["test_id"]   = data.get("test_id", "holland_v1")
    if PROFILE_FILE.exists():
        result["profile_test"] = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    return result


# ─── ENDPOINTS ──────────────────────────────────────────────────────────────
@app.get("/", tags=["Info"])
async def root():
    return {
        "service": "Chatbot Client API",
        "target_server": TARGET_HOST,
        "swagger": "http://localhost:8002/docs",
        "active_sessions": len(sessions),
        "session_list": list(sessions.keys()),
    }


@app.get("/ping", tags=["Info"], summary="Kiem tra chatbot server con song khong")
async def ping():
    """Ping toi chatbot server de xac nhan ket noi truoc khi chat."""
    import time
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{TARGET_HOST}/health")
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"server": TARGET_HOST, "reachable": True,
                "status_code": r.status_code, "latency_ms": ms}
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"server": TARGET_HOST, "reachable": False,
                "error": str(e), "latency_ms": ms}


@app.get("/chat/ui", tags=["Chat"], summary="Giao dien chat WebSocket real-time (mo bang browser)")
async def chat_ui():
    """
    Mo trang chat giao dien dark-mode truc tiep tren browser.

    URL: http://localhost:8002/chat/ui

    - Thay bot go tung chu real-time (WebSocket streaming)
    - Tu dong gui kem Holland test + User Profile
    - Ho tro nhieu luot chat trong cung phien
    """
    html = """
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Chatbot Client — Live Chat</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0d1117;
      color: #e6edf3;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: #161b22;
      border-bottom: 1px solid #30363d;
      padding: 12px 20px;
      display: flex;
      align-items: center;
      gap: 12px;
    }
    header h1 { font-size: 15px; font-weight: 600; color: #f0f6fc; }
    #server-tag {
      font-size: 11px;
      background: #1f6feb22;
      color: #58a6ff;
      border: 1px solid #1f6feb44;
      border-radius: 20px;
      padding: 2px 10px;
    }
    #status-dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: #3fb950;
      box-shadow: 0 0 6px #3fb950;
      animation: pulse 2s infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.4; }
    }
    #session-bar {
      background: #161b22;
      border-bottom: 1px solid #21262d;
      padding: 6px 20px;
      font-size: 11px;
      color: #8b949e;
      display: flex;
      align-items: center;
      gap: 16px;
    }
    #session-bar span { color: #58a6ff; font-family: monospace; }
    #profile-toggle {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 6px;
      cursor: pointer;
    }
    #profile-toggle input { cursor: pointer; accent-color: #1f6feb; }
    #messages {
      flex: 1;
      overflow-y: auto;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      scroll-behavior: smooth;
    }
    .msg {
      max-width: 72%;
      display: flex;
      flex-direction: column;
      gap: 4px;
      animation: fadeIn 0.2s ease;
    }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; } }
    .msg.user { align-self: flex-end; align-items: flex-end; }
    .msg.bot  { align-self: flex-start; align-items: flex-start; }
    .bubble {
      padding: 10px 16px;
      border-radius: 16px;
      font-size: 14px;
      line-height: 1.6;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .user .bubble {
      background: #1f6feb;
      color: #fff;
      border-bottom-right-radius: 4px;
    }
    .bot .bubble {
      background: #1c2128;
      color: #e6edf3;
      border: 1px solid #30363d;
      border-bottom-left-radius: 4px;
    }
    .label { font-size: 11px; color: #8b949e; padding: 0 4px; }
    .tool-badge {
      font-size: 11px;
      background: #2d3142;
      color: #c9d1d9;
      border: 1px solid #444c56;
      border-radius: 4px;
      padding: 2px 8px;
      margin-bottom: 4px;
      font-family: monospace;
    }
    #typing {
      display: none;
      align-self: flex-start;
      align-items: center;
      gap: 8px;
      font-size: 13px;
      color: #8b949e;
      padding: 8px 0;
    }
    #typing.visible { display: flex; }
    .dot { width: 6px; height: 6px; background: #58a6ff; border-radius: 50%; animation: bounce 1s infinite; }
    .dot:nth-child(2) { animation-delay: 0.15s; }
    .dot:nth-child(3) { animation-delay: 0.30s; }
    @keyframes bounce { 0%,60%,100% { transform: none; } 30% { transform: translateY(-5px); } }
    #input-area {
      background: #161b22;
      border-top: 1px solid #30363d;
      padding: 16px 20px;
      display: flex;
      gap: 10px;
      align-items: flex-end;
    }
    #msg-input {
      flex: 1;
      background: #0d1117;
      border: 1px solid #30363d;
      border-radius: 10px;
      color: #e6edf3;
      padding: 10px 14px;
      font-size: 14px;
      resize: none;
      min-height: 44px;
      max-height: 140px;
      outline: none;
      transition: border-color 0.2s;
    }
    #msg-input:focus { border-color: #1f6feb; }
    #msg-input::placeholder { color: #484f58; }
    #send-btn {
      background: #1f6feb;
      border: none;
      border-radius: 10px;
      color: #fff;
      width: 44px;
      height: 44px;
      cursor: pointer;
      font-size: 18px;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background 0.2s, transform 0.1s;
      flex-shrink: 0;
    }
    #send-btn:hover:not(:disabled) { background: #388bfd; }
    #send-btn:active:not(:disabled) { transform: scale(0.95); }
    #send-btn:disabled { background: #21262d; color: #484f58; cursor: not-allowed; }
    #new-session-btn {
      background: transparent;
      border: 1px solid #30363d;
      border-radius: 8px;
      color: #8b949e;
      padding: 4px 10px;
      font-size: 11px;
      cursor: pointer;
      transition: border-color 0.2s, color 0.2s;
    }
    #new-session-btn:hover { border-color: #58a6ff; color: #58a6ff; }
  </style>
</head>
<body>
  <header>
    <div id="status-dot"></div>
    <h1>Chatbot Client — Live Chat</h1>
    <span id="server-tag">__TARGET__</span>
  </header>
  <div id="session-bar">
    Session: <span id="session-id-display">--</span>
    <button id="new-session-btn" onclick="newSession()">+ New Session</button>
    <span id="ws-status" style="font-size:11px;color:#d29922">WS: Dang ket noi...</span>
    <label id="profile-toggle">
      <input type="checkbox" id="use-profile" checked>
      Gửi kèm Profile (Holland + User)
    </label>
  </div>
  <div id="messages"></div>
  <div id="typing">
    <div class="dot"></div><div class="dot"></div><div class="dot"></div>
    <span id="typing-label">Bot đang trả lời...</span>
  </div>
  <div id="input-area">
    <textarea id="msg-input" rows="1" placeholder="Nhập tin nhắn... (Enter để gửi, Shift+Enter xuống dòng)"></textarea>
    <button id="send-btn" onclick="sendMessage()">&#9658;</button>
  </div>

  <script>
    const WS_BASE = 'ws://' + location.host + '/ws/chat';
    let ws = null;
    let sessionId = generateId();
    let currentBotBubble = null;
    let currentBotText = '';
    let isStreaming = false;

    function generateId() {
      return 'sess-' + Math.random().toString(36).slice(2, 8);
    }

    function updateSessionDisplay() {
      document.getElementById('session-id-display').textContent = sessionId;
    }

    function newSession() {
      if (ws) { ws.close(); ws = null; }
      sessionId = generateId();
      updateSessionDisplay();
      document.getElementById('messages').innerHTML = '';
      addSystemMsg('Phiên mới bắt đầu: ' + sessionId);
      connectWS();
    }

    function addSystemMsg(text) {
      const el = document.createElement('div');
      el.style.cssText = 'text-align:center;font-size:11px;color:#484f58;padding:4px 0';
      el.textContent = text;
      document.getElementById('messages').appendChild(el);
      scrollBottom();
    }

    function addUserBubble(text) {
      const wrap = document.createElement('div');
      wrap.className = 'msg user';
      wrap.innerHTML = `<div class="label">Bạn</div><div class="bubble">${escHtml(text)}</div>`;
      document.getElementById('messages').appendChild(wrap);
      scrollBottom();
    }

    function createBotBubble() {
      const wrap = document.createElement('div');
      wrap.className = 'msg bot';
      wrap.innerHTML = '<div class="label">Bot</div><div class="bubble" id="bot-bubble-current"></div>';
      document.getElementById('messages').appendChild(wrap);
      scrollBottom();
      return document.getElementById('bot-bubble-current');
    }

    function addToolBadge(tool) {
      const el = document.createElement('div');
      el.className = 'tool-badge';
      el.textContent = ' Tool: ' + tool;
      document.getElementById('messages').appendChild(el);
    }

    function escHtml(s) {
      var nl = String.fromCharCode(10);
      return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(new RegExp(nl,'g'),'<br>');
    }

    function scrollBottom() {
      const m = document.getElementById('messages');
      m.scrollTop = m.scrollHeight;
    }

    function setStreaming(v) {
      isStreaming = v;
      document.getElementById('send-btn').disabled = v;
      document.getElementById('typing').className = v ? 'visible' : '';
      document.getElementById('msg-input').disabled = v;
    }

    function connectWS() {
      const url = WS_BASE + '?session_id=' + sessionId;
      try {
        ws = new WebSocket(url);
        ws.onopen = () => {
          addSystemMsg('[WS] Ket noi WebSocket thanh cong — streaming bat dau');
          document.getElementById('ws-status').textContent = 'WS: Connected';
          document.getElementById('ws-status').style.color = '#3fb950';
        };
        ws.onmessage = (evt) => {
          const data = JSON.parse(evt.data);
          if (data.type === 'connected') { sessionId = data.session_id; updateSessionDisplay(); return; }
          if (data.type === 'token') {
            if (!currentBotBubble) {
              setStreaming(true);
              currentBotText = '';
              currentBotBubble = createBotBubble();
              currentBotBubble.removeAttribute('id');
            }
            currentBotText += data.content;
            currentBotBubble.innerHTML = escHtml(currentBotText);
            scrollBottom();
            return;
          }
          if (data.type === 'tool_start') { addToolBadge(data.tool || data.content); return; }
          if (data.type === 'end') { currentBotBubble = null; currentBotText = ''; setStreaming(false); return; }
          if (data.type === 'error') {
            if (currentBotBubble) { currentBotBubble.style.color = '#f85149'; currentBotBubble = null; }
            addSystemMsg('[WS Loi] ' + data.content);
            setStreaming(false);
          }
        };
        ws.onerror = () => {
          document.getElementById('ws-status').textContent = 'WS: Fallback HTTP';
          document.getElementById('ws-status').style.color = '#d29922';
        };
        ws.onclose = () => {
          document.getElementById('ws-status').textContent = 'WS: Dong - dung HTTP';
          document.getElementById('ws-status').style.color = '#8b949e';
          setStreaming(false);
        };
      } catch(e) {
        document.getElementById('ws-status').textContent = 'WS: Loi - dung HTTP';
      }
    }

    async function sendViaHttp(text, useProfile) {
      setStreaming(true);
      const bubble = createBotBubble();
      bubble.removeAttribute('id');
      bubble.textContent = 'Dang cho phan hoi...';
      try {
        const r = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message: text, session_id: sessionId, use_profile: useProfile})
        });
        const data = await r.json();
        if (r.ok) {
          bubble.innerHTML = escHtml(data.reply || JSON.stringify(data));
          sessionId = data.session_id || sessionId;
          updateSessionDisplay();
        } else {
          bubble.style.color = '#f85149';
          bubble.textContent = 'Loi: ' + (data.detail || r.status);
        }
      } catch(e) {
        bubble.style.color = '#f85149';
        bubble.textContent = 'Loi ket noi: ' + e.message;
      }
      setStreaming(false);
    }

    function sendMessage() {
      const input = document.getElementById('msg-input');
      const text = input.value.trim();
      if (!text || isStreaming) return;
      input.value = '';
      input.style.height = 'auto';
      addUserBubble(text);
      const useProfile = document.getElementById('use-profile').checked;
      // WS neu san sang, HTTP neu khong
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({message: text, use_profile: useProfile}));
        setStreaming(true);
      } else {
        sendViaHttp(text, useProfile);
      }
    }

    // Enter → gui, Shift+Enter → xuong dong
    const inputEl = document.getElementById('msg-input');
    inputEl.onkeydown = function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        e.stopPropagation();
        sendMessage();
      }
    };
    inputEl.oninput = function() {
      this.style.height = 'auto';
      this.style.height = Math.min(this.scrollHeight, 140) + 'px';
    };

    // Init
    updateSessionDisplay();
    connectWS();
  </script>
</body>
</html>
    """.replace("__TARGET__", TARGET_HOST)
    return HTMLResponse(html)


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """
    WebSocket proxy: nhan message tu browser, forward len chatbot server kem profile,
    stream tung token ve browser.
    """
    await websocket.accept()
    # Doc query param thu cong — an toan hon tren moi version FastAPI
    thread_id = websocket.query_params.get("session_id") or str(uuid.uuid4())[:12]

    # Bao hieu session cho browser
    await websocket.send_json({"type": "connected", "session_id": thread_id})

    # Luu lich su phien
    if thread_id not in sessions:
        sessions[thread_id] = []

    try:
        while True:
            # Cho message tu browser
            raw = await websocket.receive_text()
            msg = json.loads(raw)

            message    = msg.get("message", "").strip()
            use_prof   = msg.get("use_profile", True)

            if not message:
                continue

            # Load profile
            profile_data = _load_real_profile() if use_prof else \
                           {"profile_test": None, "test_json": None, "test_id": None}

            upstream_url = f"{WS_SERVER}/{thread_id}"
            payload = json.dumps({
                "message":      message,
                "profile_json": profile_data["profile_test"],
                "test_json":    profile_data["test_json"],
                "history":      [],
                "user_id":      thread_id,
            })

            full_reply = ""

            logger.info(f"[WS] Connecting upstream: {upstream_url}")

            try:
                # websockets v14+ — khong dung close_timeout trong connect()
                async with ws_lib.connect(
                    upstream_url,
                    ping_timeout=60,
                    open_timeout=15,
                ) as upstream:
                    logger.info(f"[WS] Upstream connected, sending payload...")
                    await upstream.send(payload)

                    while True:
                        try:
                            raw_resp = await asyncio.wait_for(upstream.recv(), timeout=120)
                        except asyncio.TimeoutError:
                            await websocket.send_json({"type": "error", "content": "Timeout 120s cho phan hoi tu server"})
                            break

                        token_data = json.loads(raw_resp)
                        await websocket.send_text(raw_resp)  # Forward nguyen xi ve browser

                        if token_data.get("type") == "token":
                            full_reply += token_data.get("content", "")

                        if token_data.get("type") in ("end", "error"):
                            logger.info(f"[WS] Stream ended. Full reply length: {len(full_reply)}")
                            break

            except ws_lib.exceptions.InvalidURI as e:
                err = f"[WS] URL upstream sai dinh dang: {upstream_url} — {e}"
                logger.error(err)
                await websocket.send_json({"type": "error", "content": err})
                continue
            except ws_lib.exceptions.WebSocketException as e:
                err = f"[WS] Khong ket noi duoc upstream ({upstream_url}): {type(e).__name__}: {e}"
                logger.error(err)
                # Fallback: thu HTTP thay the
                await websocket.send_json({"type": "error", "content": err})
                await websocket.send_json({"type": "error", "content": "Dang thu fallback qua HTTP..."})
                try:
                    http_payload = {
                        "message":      message,
                        "thread_id":    thread_id,
                        "user_id":      thread_id,
                        "profile_test": profile_data["profile_test"],
                        "test_id":      profile_data.get("test_id"),
                        "test_json":    profile_data["test_json"],
                    }
                    async with httpx.AsyncClient(timeout=60) as hclient:
                        resp = await hclient.post(CHAT_ENDPOINT, json=http_payload)
                        resp.raise_for_status()
                        data = resp.json()
                        reply_text = (
                            data.get("response") or data.get("message")
                            or data.get("answer") or data.get("reply") or str(data)
                        )
                        full_reply = reply_text
                        await websocket.send_json({"type": "token", "content": reply_text})
                        await websocket.send_json({"type": "end"})
                except Exception as http_err:
                    await websocket.send_json({"type": "error", "content": f"HTTP fallback also failed: {http_err}"})
                continue
            except Exception as e:
                err = f"[WS] Loi khong xac dinh: {type(e).__name__}: {e}"
                logger.error(err)
                await websocket.send_json({"type": "error", "content": err})
                continue

            # Luu lich su
            sessions[thread_id].append({
                "turn":      len(sessions[thread_id]) + 1,
                "user":      message,
                "bot":       full_reply,
                "timestamp": datetime.now().isoformat(),
            })

    except WebSocketDisconnect:
        pass  # Browser dong tab — binh thuong


@app.get("/profile", tags=["Info"],
         summary="Xem thong tin profile dang duoc fix cung")
async def show_profile():
    """Hien thi noi dung profile dang duoc su dung (Real_Holland.json + Real_Profile.json)."""
    data = _load_real_profile()
    return {
        "holland_file": str(HOLLAND_FILE),
        "profile_file": str(PROFILE_FILE),
        "holland_loaded": data["test_json"] is not None,
        "profile_loaded": data["profile_test"] is not None,
        "holland_data":   data["test_json"],
        "profile_data":   data["profile_test"],
    }


@app.post("/chat/new", tags=["Chat"], summary="Bat dau phien hoi thoai moi",
          response_model=NewSessionResponse)
async def new_session(custom_id: Optional[str] = None):
    """
    Tao mot phien hoi thoai moi va tra ve `session_id`.

    - Neu truyen `custom_id`, su dung id do lam session_id.
    - Neu khong truyen, tu dong tao UUID moi.
    """
    session_id = custom_id if custom_id else str(uuid.uuid4())[:12]
    sessions[session_id] = []
    return NewSessionResponse(
        session_id=session_id,
        message=f"Phien moi tao thanh cong. Su dung session_id nay de chat.",
        created_at=datetime.now().isoformat()
    )


@app.post("/chat", tags=["Chat"], summary="Gui tin nhan toi chatbot",
          response_model=ChatResponse)
async def chat(req: ChatRequest):
    """
    Gui tin nhan toi Chatbot Service va nhan cau tra loi.

    - Neu `session_id` chua ton tai, tu dong tao moi.
    - Neu truyen `profile_name`, tu dong load Holland test + User Profile tu `data/test/`.
    - Khong truyen `profile_name` → chatbot tra loi khong co nguon context profile.
    """
    session_id = req.session_id or str(uuid.uuid4())[:12]
    if session_id not in sessions:
        sessions[session_id] = []

    turn = len(sessions[session_id]) + 1

    # Load profile neu use_profile = True (mac dinh)
    profile_data = {"profile_test": None, "test_json": None, "test_id": None}
    if req.use_profile:
        profile_data = _load_real_profile()

    payload = {
        "message":      req.message,
        "thread_id":    session_id,
        "user_id":      req.user_id or session_id,
        "profile_test": profile_data["profile_test"],
        "test_id":      profile_data["test_id"],
        "test_json":    profile_data["test_json"],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(CHAT_ENDPOINT, json=payload)
            response.raise_for_status()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504,
                            detail="Chatbot server khong phan hoi (timeout 60s). "
                                   "Co the LLM dang xu ly cham, thu lai sau.")
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code,
                            detail=f"Chatbot server tra loi loi: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=503,
                            detail=f"Khong ket noi duoc toi chatbot server: {str(e)}")

    data = response.json()
    # Lay phan reply tu response (thuong la field 'response' hoac 'message' hoac 'answer')
    reply = (
        data.get("response")
        or data.get("message")
        or data.get("answer")
        or data.get("reply")
        or str(data)
    )

    # Luu vao lich su
    record = {
        "turn":      turn,
        "user":      req.message,
        "bot":       reply,
        "timestamp": datetime.now().isoformat(),
    }
    sessions[session_id].append(record)

    return ChatResponse(
        session_id=session_id,
        message=req.message,
        reply=reply,
        turn=turn,
        timestamp=record["timestamp"],
        server=TARGET_HOST,
    )


@app.get("/sessions", tags=["Sessions"], summary="Danh sach tat ca phien dang hoat dong")
async def list_sessions():
    """Hien thi tat ca session dang co, so luot chat trong moi phien."""
    return {
        "total": len(sessions),
        "sessions": [
            {
                "session_id": sid,
                "turns": len(history),
                "last_message": history[-1]["user"] if history else None,
            }
            for sid, history in sessions.items()
        ]
    }


@app.get("/sessions/{session_id}/history", tags=["Sessions"],
         summary="Xem lich su hoi thoai cua 1 phien")
async def get_history(session_id: str):
    """
    Xem toan bo lich su hoi thoai cua mot phien.

    Tra ve danh sach cac luot chat theo thu tu thoi gian.
    """
    if session_id not in sessions:
        raise HTTPException(status_code=404,
                            detail=f"Khong tim thay session '{session_id}'. "
                                   "Goi POST /chat/new de tao moi.")
    history = sessions[session_id]
    return {
        "session_id": session_id,
        "total_turns": len(history),
        "history": history,
    }


@app.delete("/sessions/{session_id}", tags=["Sessions"],
            summary="Xoa phien va bat dau hoi thoai moi")
async def clear_session(session_id: str):
    """Xoa lich su cua mot phien. Cac lan chat tiep theo tren session nay se bat dau tu dau."""
    if session_id not in sessions:
        raise HTTPException(status_code=404,
                            detail=f"Khong tim thay session '{session_id}'.")
    del sessions[session_id]
    return {"message": f"Da xoa phien '{session_id}'. Tao moi: POST /chat/new"}


@app.delete("/sessions", tags=["Sessions"], summary="Xoa tat ca cac phien")
async def clear_all_sessions():
    """Reset toan bo tat ca phien hoi thoai."""
    count = len(sessions)
    sessions.clear()
    return {"message": f"Da xoa {count} phien. Server sach se, bat dau tu dau."}


# ─── ENTRY POINT ────────────────────────────────────────────────────────────
def _free_port(port: int):
    """Kill bat ky process nao dang giu port nay (Windows)."""
    import subprocess, re
    try:
        out = subprocess.check_output(
            f"netstat -ano | findstr :{port}", shell=True, text=True, stderr=subprocess.DEVNULL
        )
        pids = set(re.findall(r"\s(\d+)\s*$", out, re.MULTILINE)) - {"0"}
        for pid in pids:
            subprocess.call(f"taskkill /PID {pid} /F", shell=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"   [cleanup] Killed old process PID {pid} on port {port}")
    except subprocess.CalledProcessError:
        pass  # findstr tra ve exit 1 khi khong tim thay gi — binh thuong


if __name__ == "__main__":
    PORT = 8002
    _free_port(PORT)   # Auto-kill process cu neu con giu port

    print("=" * 60)
    print("Chatbot Client API")
    print(f"   Target Chatbot : {TARGET_HOST}")
    print(f"   Swagger UI     : http://localhost:{PORT}/docs")
    print(f"   Chat UI        : http://localhost:{PORT}/chat/ui")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
