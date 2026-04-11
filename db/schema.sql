CREATE TABLE "users_global"
(
    "user_id"  INTEGER PRIMARY KEY, -- Telegram ID
    "name"     TEXT,
    "username" TEXT,
    "status"   INTEGER DEFAULT 0 CHECK ("status" IN (0, 1))

);

CREATE TABLE "name_history"
(
    "id"           INTEGER PRIMARY KEY AUTOINCREMENT,
    "user_id"      INTEGER,
    "old_name"     TEXT,
    "old_username" TEXT,
    "change_date"  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE "chat_stats"
(
    "id"         INTEGER PRIMARY KEY AUTOINCREMENT,
    "user_id"    INTEGER,
    -- channels or groups
    "channel_id" INTEGER,
    -- if the date is not known, by default we assign the status "Old Man"
    "join_date"  TIMESTAMP DEFAULT '2000-12-31',
    "msg_count"  INTEGER   DEFAULT 0,
    UNIQUE ("user_id", "channel_id")
);

CREATE TABLE "chat_links"
(
    "chat_id"        INTEGER PRIMARY KEY,
    "owner_id"       INTEGER,
    "voting_buttons" INTEGER DEFAULT 0 CHECK ("voting_buttons" IN (0, 1)),
    "rus_language"   INTEGER DEFAULT 0 CHECK ("rus_language" IN (0, 1)),
    "stop_word"      INTEGER DEFAULT 0 CHECK ("stop_word" IN (0, 1)),

    "stop_channel"   INTEGER DEFAULT 1 CHECK ("stop_channel" IN (0, 1)),
    "stop_links"     INTEGER DEFAULT 1 CHECK ("stop_links" IN (0, 1)),
    "card_number"    INTEGER DEFAULT 1 CHECK ("card_number" IN (0, 1)),
    "emoji_checker"  INTEGER DEFAULT 0 CHECK ("emoji_checker" IN (0, 1)),
    "reaction_spam"  INTEGER DEFAULT 1 CHECK ("reaction_spam" IN (0, 1))
);

CREATE TABLE "photo_hash"
(
    "id"   INTEGER PRIMARY KEY AUTOINCREMENT,
    "hash" TEXT UNIQUE
);

CREATE TABLE "admins"
(
    "id"       INTEGER PRIMARY KEY AUTOINCREMENT,
    "chat_id"  INTEGER NOT NULL,
    "admin_id" INTEGER NOT NULL,
    "status"   INTEGER DEFAULT 0 CHECK ("status" IN (0, 1)),
    UNIQUE ("chat_id", "admin_id")
);

CREATE TABLE "votings"
(
    "chat_id"    INTEGER,
    "message_id" INTEGER,
    "user_id"    INTEGER,
    "work_m_id"  INTEGER,
    "bot"        INTEGER DEFAULT 0,
    "human"      INTEGER DEFAULT 0,
    UNIQUE ("chat_id", "message_id")
);

CREATE TABLE "votes_log"
(
    "voting_m_id" INTEGER, -- Message ID with buttons
    "voter_id"    INTEGER, -- ID of the person who pressed the button
    UNIQUE ("voting_m_id", "voter_id")
);

CREATE TABLE IF NOT EXISTS "report_mutes"
(
    "admin_id" INTEGER NOT NULL,
    "chat_id"  INTEGER NOT NULL,
    "status"   INTEGER NOT NULL DEFAULT 1 CHECK ("status" IN (0, 1)),
    UNIQUE ("admin_id", "chat_id")
);

--- this may come in handy later
CREATE TRIGGER "track_name_changes"
    BEFORE UPDATE
    ON "users_global"
    FOR EACH ROW
    WHEN (OLD.name IS NOT NEW.name OR OLD.username IS NOT NEW.username)
BEGIN
    INSERT INTO "name_history" ("user_id", "old_name", "old_username")
    VALUES (OLD.user_id, OLD.name, OLD.username);
END;




