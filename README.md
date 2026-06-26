# claude-telegram-notify

A Claude Code plugin that pings you on **Telegram** when Claude finishes a turn — and lets you
**reply back** (typed message or tap a button) to wake the session with your next prompt. Remote-control
Claude from your phone.

- Stdlib Python only, **no dependencies**.
- One-way notification **and** two-way reply via a single `Stop` hook (`asyncRewake`).
- Also pings you when Claude needs you **mid-turn** (permission prompt / waiting for input) via the `Notification` hook — a one-way heads-up (a permission gate can't be answered through the wake mechanism).
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

## Multiple sessions

Run several Claude sessions at once and replies route to the right one:

- **Reply to a specific message** (Telegram → long-press → Reply) → wakes the session that sent it.
- **Tap a button** → wakes the session that offered it.
- **Plain message** (no reply-to) → goes to the most-recently-active session.

When more than one session is active, each notification is prefixed with a `📁 <repo> · <id>` label
so you can tell them apart. Under the hood, Telegram's `getUpdates` is single-consumer, so one waiting
session is elected leader (via a lock) and dispatches each reply to the correct session's inbox — no
extra daemon, and leadership hands off automatically when a session wakes or times out.

## Notes & limits

- **Owner-only:** the hook ignores messages from any chat id other than yours.
- **Ended sessions:** replying to a message whose session has since exited gets a "session has ended" notice.
- State (offset, lock, registry, inbox, detected chat id) lives in `~/.cache/claude-telegram-notify/`.
- Requires Python 3 on `PATH`.

## Uninstall

```text
/plugin uninstall telegram-notify@telegram-notify
```

## License

MIT
