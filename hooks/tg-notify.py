#!/usr/bin/env python3
# Claude Code Stop hook (asyncRewake): push Claude's last message to Telegram,
# then wait for a reply. A reply (typed, reply-to, or button tap) wakes the matching session.
#
# Per-session routing: Telegram getUpdates is single-consumer, so among all waiting sessions
# one becomes the "leader" (flock) that polls Telegram and dispatches each reply to the right
# session's inbox; the others wait on their inbox. Reply-to and button taps route by the
# message_id you acted on; a plain message goes to the most-recently-active session.
#
# Config via plugin userConfig (passed as args) or env fallback:
#   --token / TELEGRAM_BOT_TOKEN   from @BotFather (required)
#   --chat-id / TELEGRAM_CHAT_ID   optional; auto-detected from your first message to the bot
#   TG_WAIT                        idle wait seconds before giving up (default 3600)
#
# Choices: end a message with a line "::buttons:: A | B | C" to render tap buttons.
# Stdlib only, no dependencies.
import argparse, json, os, sys, fcntl, time, urllib.parse, urllib.request


def clean(v):  # empty, or an unsubstituted ${user_config.*} placeholder -> treat as unset
    v = (v or "").strip()
    return "" if v.startswith("${") else v


ap = argparse.ArgumentParser()
ap.add_argument("--token", default=os.environ.get("TELEGRAM_BOT_TOKEN", ""))
ap.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID", ""))
ap.add_argument("--selftest", action="store_true")
ARGS, _ = ap.parse_known_args()

STATE = os.path.expanduser("~/.cache/claude-telegram-notify")
OFFSET_FILE = os.path.join(STATE, "offset")
LOCK_FILE = os.path.join(STATE, "poll.lock")
REG_FILE = os.path.join(STATE, "registry.json")
REG_LOCK = os.path.join(STATE, "registry.lock")
CHAT_FILE = os.path.join(STATE, "chat_id")
INBOX = os.path.join(STATE, "inbox")
WAIT = int(os.environ.get("TG_WAIT", "3600"))
TOKEN = clean(ARGS.token)
API = f"https://api.telegram.org/bot{TOKEN}"
CHAT_ID = None  # resolved in main()


# ---------- routing primitives (pure-ish; covered by --selftest) ----------

def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def msg_id_of(update):
    cq = update.get("callback_query")
    if cq:
        return (cq.get("message") or {}).get("message_id")
    rt = (update.get("message") or {}).get("reply_to_message")
    return rt.get("message_id") if rt else None


def route(update, reg, my_session):
    # -> target session_id (may be a dead one for an explicit reply-to/tap), or None if nobody
    mid = msg_id_of(update)
    if mid is not None:
        for sid, info in reg.items():
            if mid in info.get("mids", []):
                return sid
    live = [(info.get("ts", 0), sid) for sid, info in reg.items() if alive(info.get("pid"))]
    if live:
        return max(live)[1]
    return my_session if reg.get(my_session) else None


def parse_buttons(text):
    # split off a trailing "::buttons:: A | B | C" line -> (body, [labels])
    kept, buttons = [], None
    for ln in text.splitlines():
        if ln.strip().lower().startswith("::buttons::"):
            opts = [o.strip() for o in ln.split("::", 2)[-1].split("|") if o.strip()]
            if opts:
                buttons = opts
            continue
        kept.append(ln)
    return "\n".join(kept).strip(), buttons


def selftest():
    me, dead = os.getpid(), 2147480000
    reg = {
        "S1": {"pid": me, "ts": 1, "mids": [10, 11]},
        "S2": {"pid": me, "ts": 2, "mids": [20]},
        "S3": {"pid": dead, "ts": 9, "mids": [30]},
    }
    assert route({"message": {"reply_to_message": {"message_id": 20}}}, reg, "S1") == "S2"
    assert route({"callback_query": {"message": {"message_id": 10}}}, reg, "S2") == "S1"
    assert route({"message": {"text": "hi"}}, reg, "S1") == "S2"  # default = latest LIVE
    assert route({"message": {"reply_to_message": {"message_id": 999}}}, reg, "S1") == "S2"
    assert route({"message": {"reply_to_message": {"message_id": 30}}}, reg, "S1") == "S3"  # dead, explicit
    assert not alive(dead) and alive(me)
    assert parse_buttons("pick\n::buttons:: A | B") == ("pick", ["A", "B"])
    assert parse_buttons("no buttons here") == ("no buttons here", None)
    print("selftest ok")


if ARGS.selftest:
    selftest()
    sys.exit(0)

if not TOKEN:
    sys.exit(0)  # not configured -> do nothing, never break the session
os.makedirs(STATE, exist_ok=True)


# ---------- telegram + state ----------

def post(method, **params):
    try:
        data = urllib.parse.urlencode(params).encode()
        urllib.request.urlopen(f"{API}/{method}", data=data, timeout=15)
    except Exception:
        pass


def send(text, buttons=None):
    params = {"chat_id": CHAT_ID, "text": (text or "✅ Claude finished the task")[:3500]}
    if buttons:  # callback_data capped at Telegram's 64-byte hard limit
        kb = [[{"text": b, "callback_data": b[:60]}] for b in buttons]
        params["reply_markup"] = json.dumps({"inline_keyboard": kb})
    try:
        data = urllib.parse.urlencode(params).encode()
        with urllib.request.urlopen(f"{API}/sendMessage", data=data, timeout=15) as r:
            return json.load(r).get("result", {}).get("message_id")
    except Exception:
        return None


def get_updates(**params):
    url = f"{API}/getUpdates?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r).get("result", [])


def resolve_chat_id():
    cid = clean(ARGS.chat_id)
    if cid:
        return cid
    try:
        cid = open(CHAT_FILE).read().strip()
        if cid:
            return cid
    except Exception:
        pass
    try:  # auto-detect: most recent chat that messaged the bot, then cache it
        for u in reversed(get_updates(timeout=0)):
            chat = (u.get("message") or u.get("callback_query", {}).get("message") or {}).get("chat", {})
            if chat.get("id") is not None:
                cid = str(chat["id"])
                open(CHAT_FILE, "w").write(cid)
                return cid
    except Exception:
        pass
    return None


def with_reg_lock(fn):
    l = open(REG_LOCK, "w")
    fcntl.flock(l, fcntl.LOCK_EX)
    try:
        return fn()
    finally:
        fcntl.flock(l, fcntl.LOCK_UN)
        l.close()


def load_registry():
    try:
        return json.load(open(REG_FILE))
    except Exception:
        return {}


def save_registry(reg):
    tmp = REG_FILE + ".tmp"
    json.dump(reg, open(tmp, "w"))
    os.replace(tmp, REG_FILE)


def register(session, mid):
    def rmw():
        reg = load_registry()
        e = reg.get(session, {})
        e["pid"] = os.getpid()
        e["ts"] = time.time()
        e["mids"] = (e.get("mids", []) + ([mid] if mid is not None else []))[-5:]
        reg[session] = e
        for sid in list(reg):  # prune dead/stale others
            o = reg[sid]
            if sid != session and (not alive(o.get("pid")) or time.time() - o.get("ts", 0) > 7200):
                del reg[sid]
        save_registry(reg)
    with_reg_lock(rmw)


def deregister(session):
    with_reg_lock(lambda: _drop(session))


def _drop(session):
    reg = load_registry()
    if reg.pop(session, None) is not None:
        save_registry(reg)


def inbox_path(session):
    return os.path.join(INBOX, session.replace("/", "_"))


def deliver(session, text):
    os.makedirs(INBOX, exist_ok=True)
    tmp = inbox_path(session) + ".tmp"
    open(tmp, "w").write(text)
    os.replace(tmp, inbox_path(session))


def take_inbox(session):
    try:
        p = inbox_path(session)
        text = open(p).read()
        os.remove(p)
        return text
    except Exception:
        return None


def owner_text(update):
    # returns reply text if from the owner, else None (also dismisses button spinners)
    cq = update.get("callback_query")
    if cq:
        if str((cq.get("from") or {}).get("id")) != CHAT_ID:
            return None
        post("answerCallbackQuery", callback_query_id=cq.get("id"))
        return cq.get("data") or None
    msg = update.get("message") or {}
    if str((msg.get("chat") or {}).get("id")) != CHAT_ID:
        return None
    return msg.get("text") or None


def last_assistant_text(path):
    text = "✅ Claude finished the task"  # fallback when the turn ended on a tool call, not prose
    try:
        with open(path) as f:
            for line in f:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("type") == "assistant":
                    t = " ".join(
                        b.get("text", "")
                        for b in o.get("message", {}).get("content", [])
                        if isinstance(b, dict) and b.get("type") == "text"
                    ).strip()
                    if t:
                        text = t
    except Exception:
        pass
    return text


def stable_last_text(path, settle=0.3, tries=8):
    # wait out the transcript flush race: return once the last message stops changing
    prev = None
    for _ in range(tries):
        cur = last_assistant_text(path)
        if cur == prev:
            return cur
        prev = cur
        time.sleep(settle)
    return prev


def read_offset():
    try:
        return int(open(OFFSET_FILE).read().strip())
    except Exception:  # baseline past the backlog so old messages don't replay
        try:
            ids = [u["update_id"] for u in get_updates(timeout=0)]
            off = max(ids) + 1 if ids else 0
        except Exception:
            off = 0
        open(OFFSET_FILE, "w").write(str(off))
        return off


def wait_loop(my_session):
    lock = open(LOCK_FILE, "w")
    leader, offset = False, 0
    deadline = time.time() + WAIT
    while time.time() < deadline:
        t = take_inbox(my_session)  # dispatched to me by the current leader
        if t is not None:
            print(t)
            return 2
        if not leader:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                leader = True
                offset = read_offset()
                t = take_inbox(my_session)  # catch a delivery that raced the handoff
                if t is not None:
                    print(t)
                    return 2
            except OSError:
                time.sleep(1)
                continue
        try:
            updates = get_updates(offset=offset, timeout=50)
        except Exception:
            time.sleep(3)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            open(OFFSET_FILE, "w").write(str(offset))
            text = owner_text(u)
            if not text:
                continue
            reg = load_registry()
            target = route(u, reg, my_session)
            if target is None or target == my_session:
                print(text)
                return 2
            if alive(reg.get(target, {}).get("pid")):
                deliver(target, text)
            else:  # you replied to a session that has since ended
                post("sendMessage", chat_id=CHAT_ID, text="⚠️ that session has ended; message not delivered.")
    return 0


def main():
    global CHAT_ID
    try:
        hook = json.load(sys.stdin)
    except Exception:
        hook = {}
    my_session = hook.get("session_id") or "default"
    cwd = hook.get("cwd") or ""

    CHAT_ID = resolve_chat_id()
    if not CHAT_ID:
        sys.exit(0)  # nobody has messaged the bot yet; nothing to notify

    body, buttons = parse_buttons(stable_last_text(hook.get("transcript_path", "")))
    others = [s for s, i in load_registry().items() if s != my_session and alive(i.get("pid"))]
    if others:  # label only when more than one session is active, to keep the common case clean
        label = os.path.basename(cwd.rstrip("/")) or "claude"
        body = f"📁 {label} · {my_session[:4]}\n{body}"
    mid = send(body, buttons)
    register(my_session, mid)
    try:
        return wait_loop(my_session)
    finally:
        deregister(my_session)
        take_inbox(my_session)


sys.exit(main())
