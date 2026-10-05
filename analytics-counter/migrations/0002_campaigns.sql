CREATE TABLE IF NOT EXISTS daily_campaigns (
    day TEXT NOT NULL CHECK (length(day) = 10),
    source TEXT NOT NULL CHECK (source IN ('linkedin', 'google', 'bing', 'newsletter', 'partner')),
    medium TEXT NOT NULL CHECK (medium IN ('social', 'organic', 'cpc', 'email', 'referral')),
    campaign TEXT NOT NULL CHECK (
        length(campaign) BETWEEN 4 AND 64
        AND substr(campaign, 1, 3) = 'dp-'
        AND campaign NOT GLOB '*[^a-z0-9-]*'
        AND substr(campaign, -1) <> '-'
        AND campaign NOT LIKE '%--%'
    ),
    count INTEGER NOT NULL DEFAULT 0 CHECK (count >= 0),
    PRIMARY KEY (day, source, medium, campaign)
) WITHOUT ROWID;
