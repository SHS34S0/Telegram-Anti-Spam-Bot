# Anti-Spam Bot

A production Telegram bot for automated spam protection in groups. Currently active in ~100 groups with a combined audience of 3M+ members. Built under real production load from day one — detection logic evolved from live spam campaigns targeting Ukrainian Telegram communities.

Built on **aiogram v3** with async SQLite storage. Implements layered filtering: cheap checks (in-memory lookups, regex) run first; expensive ones (Telegram API calls, ML inference) only fire when necessary.

## Features

- **Global ban list** — instant ban for known spammers across all served chats
- **Weird character detection** — catches IPA/small-caps Unicode used to bypass filters
- **Bank card filter** — Luhn algorithm validation on 16-digit sequences
- **Link filter** — blocks URLs and mentions with escalating mute on repeat offence
- **Anonymous channel filter** — blocks messages sent on behalf of Telegram channels
- **Emoji ratio filter** — detects emoji-heavy spam messages
- **Russian language filter** — per-chat toggle to block Russian-language messages
- **Account origin check** — heuristic based on account metadata; triggers mute for suspicious profiles
- **Avatar nudity detection** — NudeNet ML model scans new users' profile photos
- **Spam avatar hash matching** — perceptual hash comparison against known spam avatars
- **Bio pattern matching** — regex for spam keywords and invite links in user bio
- **AI spam classification** — HuggingFace LLM, applied only to premium accounts with high user IDs
- **Reaction spam** — bans users with no messages whose first action is reacting with a spam avatar

## Architecture

```
bot.py              ← entry point, main message handler, polling setup
filters.py          ← all spam detection logic and in-memory state
utils.py            ← Telegram API wrappers (ban, mute, delete, notify)
database.py         ← DatabaseManager singleton (aiosqlite connection lifecycle)
messages.py         ← all user-facing text strings
handlers/
  admin_panel.py    ← /start, /my_settings, /add_admin — private chat UI
  root.py           ← superadmin commands (manual ban, cache stats, chat list)
  members_status.py ← chat_member events, tracks manual bans
  new_users.py      ← join events, registers user in DB
  reaction.py       ← message_reaction events, checks avatar hash
  reports.py        ← report handling
db/
  schema.sql        ← database schema (auto-applied on first run)
  anti_spam.db      ← SQLite database (not committed)
```

### Filter pipeline (per message)

```
message arrives
    │
    ├─ sender is Telegram system (777000)?  → skip
    ├─ user in GLOBAL_BANNED set?           → delete + ban
    ├─ settings loaded?  no                 → register new chat, stop
    │
    ├─ message from anonymous channel?      → delete
    ├─ has weird Unicode chars?             → delete + ban
    ├─ contains bank card number (Luhn)?    → delete (skip for admins)
    ├─ emoji ratio too high?                → delete (+ mute if very high)
    ├─ contains link / mention?             → delete (+ mute on 3rd offence)
    │
    ├─ first message in this chat?
    │   ├─ account origin check → delete + mute / ban
    │   ├─ bio pattern check → delete + ban / alert
    │   ├─ avatar nudity check → alert for manual review
    │   └─ premium + high user ID? → AI spam check → delete + ban
    │
    └─ returning user?
        └─ Russian language filter (if enabled) → delete
```

### In-memory state (`filters.py`)

| Variable | Type | Description |
|---|---|---|
| `GLOBAL_BANNED` | `set` | Banned user IDs, loaded from DB at startup |
| `PHOTO_HASH` | `dict` | Perceptual hashes of known spam avatars (last 3 months) |
| `LINKS_HISTORY` | `dict` | Sliding 3-minute window of link posts per user |

### Database schema

| Table | Purpose |
|---|---|
| `users_global` | Global user registry with ban status |
| `chat_links` | Per-chat settings (all filter toggles as 0/1 columns) |
| `chat_stats` | Per-user per-chat message count and join date |
| `photo_hash` | Perceptual hashes of known spam avatars |
| `admins` | Users granted admin access to bot settings |
| `name_history` | Tracks username/display name changes (trigger-based) |
| `report_mutes` | Per-chat report notification mute state |

## Setup

### Requirements

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configuration

Create `config.py` (not committed) with:

```python
TOKEN = "..."           # main bot token
help_token = "..."      # secondary bot token for remote action logs
root = 123456789        # Telegram user ID of the superadmin
HF_TOKEN = "..."        # HuggingFace API token
MODEL = "..."           # HuggingFace model name
API_URL = "..."         # HuggingFace inference endpoint
TIMEOUT = 10            # request timeout in seconds
```

### Running

```bash
source venv/bin/activate
python bot.py
```

The database file is created automatically from `db/schema.sql` on first run if it does not exist.

### Production (systemd)

```bash
sudo cp antispam.service /etc/systemd/system/
sudo systemctl enable antispam
sudo systemctl start antispam
```

## Testing

```bash
pytest tests/
```

Tests are pure unit tests for filter functions in `filters.py`. They do not require a running bot or database connection.

```bash
# single file
pytest tests/test_check_card.py
```

## Superadmin panel

The superadmin (user ID matching `config.root`) receives inline photo alerts for suspicious users with three actions:

- **Bot** — adds avatar hash to `photo_hash` table + bans across all chats
- **Human** — unbans across all chats
- **Add photo** — saves perceptual hash to the database

Text commands in private chat:

| Input | Action |
|---|---|
| Any number | Manual ban by user ID |
| `cache` | Print cache stats for all `@alru_cache` functions |
| `chats` | List all active chats seen since last restart |

## Admin panel

Chat owners can manage bot settings via `/my_settings` in private chat. Each filter can be toggled per chat. Owners can also delegate settings access to other admins via `/add_admin`.

**Filters with defaults:**

| Filter | Default |
|---|---|
| Block links | ON |
| Block anonymous channels | ON |
| Bank card filter | ON |
| Reaction spam | ON |
| Russian language | OFF |
| Emoji checker | OFF |