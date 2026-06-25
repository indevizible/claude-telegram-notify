# claude-telegram-notify

A Claude Code plugin that pings you on **Telegram** when Claude finishes a turn — and lets you
**reply back** (typed message or tap a button) to wake the session with your next prompt. Remote-control
Claude from your phone.

- Stdlib Python only, **no dependencies**.
- One-way notification **and** two-way reply via a single `Stop` hook (`asyncRewake`).
- Your terminal is never blocked — the poller runs in the background.
- Does nothing until you configure it, so it's safe to install and forget.

## How it works

1. Claude finishes a turn → the `Stop` hook sends Claude's last message to your Telegram chat.
2. A background poller waits (up to 1h) for your reply.
3. You reply on Telegram → the hook exits with code 2, waking Claude with your text as the next prompt.

That's it. No daemon, nothing to start — it lives entirely inside Claude Code sessions and survives reboots.

## Install

```text
/plugin marketplace add indevizible/claude-telegram-notify
/plugin install telegram-notify@telegram-notify
```

## Setup (2 minutes)

1. **Create a bot.** Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. **Get your chat id.** Send any message to your new bot, then run (replace `<TOKEN>`):

   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates" | grep -o '"chat":{"id":[0-9]*'
   ```

3. **Configure env** in `~/.claude/settings.json`:

   ```json
   {
     "env": {
       "TELEGRAM_BOT_TOKEN": "123456:ABC...",
       "TELEGRAM_CHAT_ID": "123456789"
     }
   }
   ```

4. Restart Claude Code (or open `/hooks` once to reload).

## Usage

- Just work normally. When Claude stops, you get its message on Telegram.
- **Reply** with anything → it becomes Claude's next prompt.
- **Buttons:** when Claude offers choices, it ends a message with a line like:

  ```text
  ::buttons:: Yes | No | Maybe
  ```

  These render as tappable Telegram buttons; the line is stripped from the displayed text and a
  tap sends the label back. (Typed replies still work alongside buttons.)

## Config

| Env var | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather (required) |
| `TELEGRAM_CHAT_ID` | — | Your chat id (required) |
| `TG_WAIT` | `3600` | Seconds the poller waits for a reply before giving up |

If you raise `TG_WAIT`, also raise the hook `timeout` in `hooks/hooks.json` to stay above it.

## Notes & limits

- **Owner-only:** the hook ignores messages from any chat id other than yours.
- **One session at a time:** all sessions share one chat and one poller lock, so replies wake the
  most-recently-listening session. Two-way works cleanly for one active session at a time.
- State (offset, lock) lives in `~/.cache/claude-telegram-notify/`.
- Requires Python 3 on `PATH`.

## Uninstall

```text
/plugin uninstall telegram-notify@telegram-notify
```

## License

MIT
