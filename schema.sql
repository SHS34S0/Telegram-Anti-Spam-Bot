-- 1. Глобальний профіль (тут лише 1 рядок на кожного юзера)
CREATE TABLE "users_global" (
    "user_id" INTEGER PRIMARY KEY, -- Telegram ID
    "name" TEXT,
    "username" TEXT
);

-- 2. Історія (сюди пише ТІЛЬКИ ТРИГЕР, коли міняється ім'я)
CREATE TABLE "name_history" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "user_id" INTEGER,
    "old_name" TEXT,
    "old_username" TEXT,
    "change_date" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Статистика в чаті (тут дані для боротьби зі спамом)
CREATE TABLE "chat_stats" (
    "id" INTEGER PRIMARY KEY AUTOINCREMENT,
    "user_id" INTEGER,
    "channel_id" INTEGER,
    -- якщо дата не відома по замовчуванню присвоюємо стасус "Старічок"
    "join_date" TIMESTAMP DEFAULT '2000-12-31', 
    "msg_count" INTEGER DEFAULT 0,
    UNIQUE("user_id", "channel_id") -- щоб не було дублікатів юзера в одному чаті
);

CREATE TABLE "chat_links" (
    "chat_id" INTEGER PRIMARY KEY,   -- ID групи (коментарів)
    "channel_id" INTEGER NOT NULL    -- ID каналу (основного)
);

CREATE TABLE "votings" (
    "chat_id" INTEGER,
    "message_id" INTEGER,
    "user_id" INTEGER,
    "work_m_id" INTEGER,
    "bot" INTEGER DEFAULT 0,
    "human" INTEGER DEFAULT 0,
    UNIQUE("chat_id", "message_id")
);

CREATE TABLE "votes_log" (
    "voting_m_id" INTEGER, -- ID повідомлення з кнопками
    "voter_id" INTEGER,    -- ID того, хто натиснув кнопку
    UNIQUE("voting_m_id", "voter_id")
);
---
CREATE TRIGGER "track_name_changes"
BEFORE UPDATE ON "users_global"
FOR EACH ROW
WHEN (OLD.name IS NOT NEW.name OR OLD.username IS NOT NEW.username)
BEGIN
    INSERT INTO "name_history" ("user_id", "old_name", "old_username")
    VALUES (OLD.user_id, OLD.name, OLD.username);
END;




