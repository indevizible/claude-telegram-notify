# claude-telegram-notify

A Claude Code plugin that pings you on **Telegram** when Claude finishes a turn — and lets you
**reply back** (typed message or tap a button) to wake the session with your next prompt. Remote-control
Claude from your phone.

- Stdlib Python only, **no dependencies**.
- One-way notification **and** two-way reply via a single `Stop` hook (`asyncRewake`).
- Your terminal is never blocked — the poller runs in the background.
- Token lives in your **OS keychain**, never in plaintext. Does nothing until configured.

## How it works

1. Claude finishes a turn → the `Stop` hook sends Claude's last message to your Telegram chat.
2. A background poller waits (up to 1h) for your reply.
3. You reply on Telegram → the hook exits with code 2, waking Claude with your text as the next prompt.

No daemon, nothing to start — it lives entirely inside Claude Code sessions and survives reboots.

## Install

```text
/plugin marketplace add indevizible/claude-telegram-notify
/plugin install telegram-notify@telegram-notify
```

When you enable it, Claude Code **prompts you for your bot token** (stored in your OS keychain).
That's the only required field.

## Setup (1 minute)

1. **Create a bot:** message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Paste the token into the prompt when you enable the plugin.
3. **Send any message to your bot** (e.g. `hi`). The chat id is auto-detected from it — no need to
   find it yourself. (Optional: set it explicitly in the plugin config if you prefer.)

Done. Next time Claude stops, you get a message.

## Usage

- Work normally. When Claude stops, you get its message on Telegram.
- **Reply** with anything → it becomes Claude's next prompt.
- **Buttons:** when Claude offers choices, it ends a message with a line like:

  ```text
  ::buttons:: Yes | No | Maybe
  ```

  These render as tappable Telegram buttons; the line is stripped from the displayed text and a
  tap sends the label back. (Typed replies still work alongside buttons.)

## Config

Configured via the plugin's config prompt (`/plugin` → telegram-notify), or env vars as a fallback:

| Field / env | Default | Meaning |
|---|---|---|
| `bot_token` / `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather (required, keychain) |
| `chat_id` / `TELEGRAM_CHAT_ID` | auto | Your chat id; blank = auto-detect + cache |
| `TG_WAIT` | `3600` | Seconds the poller waits for a reply before giving up |

If you raise `TG_WAIT`, also raise the hook `timeout` in `.claude-plugin/plugin.json` to stay above it.

## Notes & limits

- **Owner-only:** the hook ignores messages from any chat id other than yours.
- **One session at a time:** all sessions share one chat and one poller lock, so replies wake the
  most-recently-listening session. Two-way works cleanly for one active session at a time.
- State (offset, lock, detected chat id) lives in `~/.cache/claude-telegram-notify/`.
- Requires Python 3 on `PATH`.

## Uninstall

```text
/plugin uninstall telegram-notify@telegram-notify
```

## License

MIT
