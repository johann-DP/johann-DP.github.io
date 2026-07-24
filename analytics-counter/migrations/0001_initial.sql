CREATE TABLE IF NOT EXISTS page_views (
    day TEXT NOT NULL CHECK (length(day) = 10),
    page TEXT NOT NULL CHECK (length(page) BETWEEN 1 AND 80),
    count INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0),
    PRIMARY KEY (day, page)
) WITHOUT ROWID;
