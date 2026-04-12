CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nickname VARCHAR(20) NOT NULL,
    session_sid VARCHAR(64) UNIQUE,
    rating INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    CHECK (length(nickname) >= 2),
    CHECK (length(nickname) <= 20)
);

CREATE INDEX IF NOT EXISTS ix_players_nickname ON players(nickname);
CREATE INDEX IF NOT EXISTS ix_players_rating ON players(rating);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code VARCHAR(6) NOT NULL UNIQUE,
    owner_player_id INTEGER NOT NULL REFERENCES players(id),
    status VARCHAR(20) NOT NULL DEFAULT 'lobby',
    created_at DATETIME NOT NULL,
    closed_at DATETIME,
    CHECK (length(code) = 6),
    CHECK (status IN ('lobby', 'in_game', 'closed'))
);

CREATE INDEX IF NOT EXISTS ix_rooms_code ON rooms(code);

CREATE TABLE IF NOT EXISTS room_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    session_sid VARCHAR(64) NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    joined_at DATETIME NOT NULL,
    left_at DATETIME,
    is_owner BOOLEAN NOT NULL DEFAULT 0,
    UNIQUE(room_id, session_sid)
);

CREATE INDEX IF NOT EXISTS ix_room_sessions_room_id ON room_sessions(room_id);
CREATE INDEX IF NOT EXISTS ix_room_sessions_sid ON room_sessions(session_sid);
CREATE INDEX IF NOT EXISTS ix_room_sessions_player_id ON room_sessions(player_id);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    game_type VARCHAR(20) NOT NULL,
    started_at DATETIME NOT NULL,
    ended_at DATETIME,
    winner_player_id INTEGER REFERENCES players(id),
    metadata_json TEXT,
    CHECK (game_type IN ('tic_tac_toe', 'guess_word', 'battleship'))
);

CREATE INDEX IF NOT EXISTS ix_games_room_id ON games(room_id);
CREATE INDEX IF NOT EXISTS ix_games_game_type ON games(game_type);
CREATE INDEX IF NOT EXISTS ix_games_ended_at ON games(ended_at);

CREATE TABLE IF NOT EXISTS game_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL REFERENCES games(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    result VARCHAR(10),
    score_delta INTEGER NOT NULL DEFAULT 0,
    UNIQUE(game_id, player_id),
    CHECK (result IS NULL OR result IN ('win', 'loss', 'draw'))
);

CREATE INDEX IF NOT EXISTS ix_game_participants_game_id ON game_participants(game_id);
CREATE INDEX IF NOT EXISTS ix_game_participants_player_id ON game_participants(player_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id INTEGER NOT NULL REFERENCES rooms(id),
    player_id INTEGER REFERENCES players(id),
    sender_name VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    is_system BOOLEAN NOT NULL DEFAULT 0,
    sent_at DATETIME NOT NULL,
    CHECK (length(sender_name) >= 2 AND length(sender_name) <= 20)
);

CREATE INDEX IF NOT EXISTS ix_chat_messages_room_id ON chat_messages(room_id);
CREATE INDEX IF NOT EXISTS ix_chat_messages_player_id ON chat_messages(player_id);
CREATE INDEX IF NOT EXISTS ix_chat_messages_sent_at ON chat_messages(sent_at);
