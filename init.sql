-- Olinda Prospector – Schema Initialization
-- Run once against the target PostgreSQL database.

CREATE TABLE IF NOT EXISTS leads_olinda (
    id          SERIAL PRIMARY KEY,
    business_name TEXT        NOT NULL,
    whatsapp      TEXT        UNIQUE NOT NULL,
    neighborhood  TEXT,
    category      TEXT,
    google_rating REAL,
    status        TEXT        NOT NULL DEFAULT 'Pending',
    target_saas   TEXT        CHECK (target_saas IN ('Zappy', 'Lojaky')),
    created_at    TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_leads_status ON leads_olinda (status);
CREATE INDEX IF NOT EXISTS idx_leads_category ON leads_olinda (category);
