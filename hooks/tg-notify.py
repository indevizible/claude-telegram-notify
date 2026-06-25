#!/usr/bin/env python3
# Claude Code Stop hook (asyncRewake): push Claude's last message to Telegram,
# then background-poll for a reply. A reply (typed or button tap) wakes Claude with it.
#
# Config comes from the plugin's userConfig (prompted on enable) via args, or env as a fallback:
#   --token / TELEGRAM_BOT_TOKEN   from @BotFather (required)
#   --chat-id / TELEGRAM_CHAT_ID   optional; auto-detected from your first message to the bot
#   TG_WAIT                        idle wait seconds before the poller gives up (default 3600)
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
ARGS, _ = ap.parse_known_args()

TOKEN = clean(ARGS.token)
if not TOKEN:
    sys.exit(0)  # not configured -> do nothing, never break the session

API = f"https://api.telegram.org/bot{TOKEN}"
STATE = os.path.expanduser("~/.cache/claude-telegram-notify")
os.makedirs(STATE, exist_ok=True)
OFFSET_FILE = os.path.join(STATE, "offset")
LOCK_FILE = os.path.join(STATE, "poll.lock")
CHAT_FILE = os.path.join(STATE, "chat_id")
WAIT = int(os.environ.get("TG_WAIT", "3600"))  # bounded idle wait; async hook so it's free
CHAT_ID = None  # resolved in main()


def post(method, **params):
    try:
        data = urllib.parse.urlencode(params).encode()
        urllib.request.urlopen(f"{API}/{method}", data=data, timeout=15)
    except Exception:
        pass


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


def send(text, buttons=None):
    params = {"chat_id": CHAT_ID, "text": (text or "✅ Claude finished the task")[:3500]}
    if buttons:  # callback_data capped at Telegram's 64-byte hard limit
        kb = [[{"text": b, "callback_data": b[:60]}] for b in buttons]
        params["reply_markup"] = json.dumps({"inline_keyboard": kb})
    post("sendMessage", **params)


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
    # wait out the transcript flush race: return once the last message stops changing (fast when already flushed)
    prev = None
    for _ in range(tries):
        cur = last_assistant_text(path)
        if cur == prev:
            return cur
        prev = cur
        time.sleep(settle)
    return prev


def main():
    global CHAT_ID
    try:
        hook = json.load(sys.stdin)
    except Exception:
        hook = {}

    CHAT_ID = resolve_chat_id()
    if not CHAT_ID:
        sys.exit(0)  # nobody has messaged the bot yet; nothing to notify

    body, buttons = parse_buttons(stable_last_text(hook.get("transcript_path", "")))
    send(body, buttons)

    lock = open(LOCK_FILE, "w")  # one poller at a time; flock auto-releases on exit
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0

    try:
        offset = int(open(OFFSET_FILE).read().strip())
    except Exception:  # first run: baseline past the backlog so old messages don't replay
        try:
            ids = [u["update_id"] for u in get_updates(timeout=0)]
            offset = max(ids) + 1 if ids else 0
        except Exception:
            offset = 0
        open(OFFSET_FILE, "w").write(str(offset))

    deadline = time.time() + WAIT
    while time.time() < deadline:
        try:
            updates = get_updates(offset=offset, timeout=50)
        except Exception:
            time.sleep(3)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            open(OFFSET_FILE, "w").write(str(offset))
            cq = u.get("callback_query")
            if cq:  # button tap
                if str(cq.get("from", {}).get("id")) != CHAT_ID:
                    continue
                post("answerCallbackQuery", callback_query_id=cq.get("id"))  # dismiss the spinner
                if cq.get("data"):
                    print(cq["data"])
                    return 2
                continue
            msg = u.get("message", {})
            if str(msg.get("chat", {}).get("id")) != CHAT_ID:  # only obey the owner
                continue
            if msg.get("text"):
                print(msg["text"])
                return 2
    return 0


sys.exit(main())
