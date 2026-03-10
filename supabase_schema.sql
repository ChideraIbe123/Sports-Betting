-- Run this in your Supabase Dashboard SQL Editor

-- ============================================================
-- predictions: one row per prop prediction
-- ============================================================
CREATE TABLE IF NOT EXISTS predictions (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT now(),
    game_date       DATE NOT NULL,
    event_id        TEXT,
    home_team       TEXT,
    away_team       TEXT,
    player_name     TEXT NOT NULL,
    player_id       INT,
    stat_type       TEXT NOT NULL,
    stat_column     TEXT NOT NULL,
    line            FLOAT NOT NULL,
    market_key      TEXT,
    over_odds       FLOAT,
    under_odds      FLOAT,
    bookmaker       TEXT DEFAULT 'draftkings',
    prediction      TEXT NOT NULL,
    confidence      TEXT NOT NULL,
    confidence_pct  INT NOT NULL,
    predicted_value FLOAT NOT NULL,
    reasoning       TEXT,
    detailed_reasoning TEXT,
    key_factors_over   JSONB DEFAULT '[]',
    key_factors_under  JSONB DEFAULT '[]',
    risk_factors       JSONB DEFAULT '[]',
    status          TEXT DEFAULT 'pending',
    actual_value    FLOAT,
    result          TEXT,
    graded_at       TIMESTAMPTZ,
    instruction_version_id UUID,
    pipeline_run_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status);
CREATE INDEX IF NOT EXISTS idx_predictions_game_date ON predictions(game_date);
CREATE INDEX IF NOT EXISTS idx_predictions_player ON predictions(player_name, stat_type);

-- ============================================================
-- performance_log: daily/weekly accuracy rollups
-- ============================================================
CREATE TABLE IF NOT EXISTS performance_log (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT now(),
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    period_type     TEXT NOT NULL,
    total_predictions INT NOT NULL DEFAULT 0,
    hits            INT NOT NULL DEFAULT 0,
    misses          INT NOT NULL DEFAULT 0,
    pushes          INT NOT NULL DEFAULT 0,
    hit_rate        FLOAT,
    high_conf_total INT DEFAULT 0,
    high_conf_hits  INT DEFAULT 0,
    medium_conf_total INT DEFAULT 0,
    medium_conf_hits INT DEFAULT 0,
    low_conf_total  INT DEFAULT 0,
    low_conf_hits   INT DEFAULT 0,
    stat_breakdown  JSONB DEFAULT '{}',
    avg_predicted_value FLOAT,
    avg_actual_value FLOAT,
    avg_error       FLOAT,
    over_predictions INT DEFAULT 0,
    under_predictions INT DEFAULT 0,
    over_hit_rate   FLOAT,
    under_hit_rate  FLOAT,
    instruction_version_id UUID
);

CREATE INDEX IF NOT EXISTS idx_perf_period ON performance_log(period_type, period_start);

-- ============================================================
-- instruction_versions: track changes to prediction agent
-- ============================================================
CREATE TABLE IF NOT EXISTS instruction_versions (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT now(),
    version_number  INT NOT NULL,
    instructions_text TEXT NOT NULL,
    extracted_params  JSONB NOT NULL DEFAULT '{}',
    change_reason   TEXT,
    triggered_by    TEXT DEFAULT 'manual',
    predictions_count INT DEFAULT 0,
    hit_rate        FLOAT,
    is_active       BOOLEAN DEFAULT FALSE
);

-- ============================================================
-- credit_usage: track The Odds API credit consumption
-- ============================================================
CREATE TABLE IF NOT EXISTS credit_usage (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at      TIMESTAMPTZ DEFAULT now(),
    month           TEXT NOT NULL,
    credits_used    INT NOT NULL DEFAULT 0,
    event_id        TEXT,
    markets         JSONB DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_credit_month ON credit_usage(month);

-- Enable Row Level Security but allow all access with anon key
ALTER TABLE predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE performance_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE instruction_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_usage ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all for anon" ON predictions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON performance_log FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON instruction_versions FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON credit_usage FOR ALL USING (true) WITH CHECK (true);
