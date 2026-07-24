CREATE TABLE IF NOT EXISTS daily_totals (
    day TEXT PRIMARY KEY CHECK (length(day) = 10),
    page_views INTEGER NOT NULL DEFAULT 0 CHECK (page_views >= 0),
    visits INTEGER NOT NULL DEFAULT 0 CHECK (visits >= 0),
    engaged_30s INTEGER NOT NULL DEFAULT 0 CHECK (engaged_30s >= 0),
    scroll_75 INTEGER NOT NULL DEFAULT 0 CHECK (scroll_75 >= 0)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS daily_pages (
    day TEXT NOT NULL CHECK (length(day) = 10),
    page TEXT NOT NULL CHECK (length(page) BETWEEN 1 AND 80),
    page_views INTEGER NOT NULL DEFAULT 0 CHECK (page_views >= 0),
    visits INTEGER NOT NULL DEFAULT 0 CHECK (visits >= 0),
    engaged_30s INTEGER NOT NULL DEFAULT 0 CHECK (engaged_30s >= 0),
    scroll_75 INTEGER NOT NULL DEFAULT 0 CHECK (scroll_75 >= 0),
    PRIMARY KEY (day, page)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS daily_dimensions (
    day TEXT NOT NULL CHECK (length(day) = 10),
    dimension TEXT NOT NULL CHECK (dimension IN ('source', 'country', 'device')),
    value TEXT NOT NULL CHECK (length(value) BETWEEN 1 AND 32),
    count INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0),
    PRIMARY KEY (day, dimension, value)
) WITHOUT ROWID;
