-- Portfolio analytics database. Every run appends; nothing is overwritten except
-- reference data (securities) and same-day re-runs (upserts on the primary keys).

CREATE TABLE IF NOT EXISTS securities (
    isin              VARCHAR PRIMARY KEY,
    symbol            VARCHAR,          -- NSE symbol for stocks, AMFI scheme code for funds
    name              VARCHAR,
    type              VARCHAR,          -- 'stock' | 'mf'
    sector            VARCHAR,
    industry          VARCHAR,
    market_cap_bucket VARCHAR,          -- Large | Mid | Small | Multi | Large & Mid
    amc               VARCHAR,
    fund_category     VARCHAR,          -- SEBI category, e.g. 'Equity Scheme - Large Cap Fund'
    asset_class       VARCHAR,          -- Equity | Debt | Hybrid | Gold/Commodity | ...
    updated_at        TIMESTAMP
);

CREATE TABLE IF NOT EXISTS holdings_daily (
    run_date        DATE,
    run_type        VARCHAR,            -- 'close' | 'night'
    isin            VARCHAR,
    type            VARCHAR,
    quantity        DOUBLE,
    avg_cost        DOUBLE,
    cost_value      DOUBLE,
    price           DOUBLE,
    price_date      DATE,
    market_value    DOUBLE,
    day_change_pct  DOUBLE,
    day_change_inr  DOUBLE,
    units_source    VARCHAR,            -- 'groww' | 'cas' | 'cas+projected'
    PRIMARY KEY (run_date, run_type, isin)
);

CREATE TABLE IF NOT EXISTS mf_transactions (
    isin      VARCHAR,
    amfi_code VARCHAR,
    date      DATE,
    type      VARCHAR,
    units     DOUBLE,
    nav       DOUBLE,
    amount    DOUBLE,
    source    VARCHAR,                  -- 'cas' | 'projected'
    PRIMARY KEY (isin, date, type, units, source)
);

-- Mutual fund positions as stated by the most recent CAS (replaced on each new CAS).
CREATE TABLE IF NOT EXISTS mf_positions (
    isin       VARCHAR PRIMARY KEY,
    amfi_code  VARCHAR,
    name       VARCHAR,
    amc        VARCHAR,
    folio      VARCHAR,
    units      DOUBLE,
    cost       DOUBLE,
    as_of      DATE,
    source     VARCHAR                  -- CAS file type, e.g. CAMS, KFINTECH, CDSL
);

-- Demat equity balances from the latest depository CAS, used to cross-check Groww holdings.
CREATE TABLE IF NOT EXISTS cas_equities (
    isin      VARCHAR PRIMARY KEY,
    name      VARCHAR,
    quantity  DOUBLE,
    price     DOUBLE,
    as_of     DATE
);

CREATE TABLE IF NOT EXISTS cas_files (
    filename     VARCHAR PRIMARY KEY,
    imported_at  TIMESTAMP,
    period_to    DATE,
    holdings     INTEGER,
    transactions INTEGER
);

CREATE TABLE IF NOT EXISTS prices_daily (
    date   DATE,
    symbol VARCHAR,                     -- stock symbol or index symbol (e.g. ^NSEI)
    open   DOUBLE,
    high   DOUBLE,
    low    DOUBLE,
    close  DOUBLE,
    volume DOUBLE,
    PRIMARY KEY (date, symbol)
);

CREATE TABLE IF NOT EXISTS nav_daily (
    date       DATE,
    amfi_code  VARCHAR,
    nav        DOUBLE,
    PRIMARY KEY (date, amfi_code)
);

CREATE TABLE IF NOT EXISTS fund_constituents (
    month       DATE,
    fund_isin   VARCHAR,
    stock_isin  VARCHAR,
    stock_name  VARCHAR,
    sector      VARCHAR,
    weight_pct  DOUBLE,
    PRIMARY KEY (month, fund_isin, stock_isin)
);

CREATE TABLE IF NOT EXISTS news_items (
    date        DATE,
    isin        VARCHAR,
    headline    VARCHAR,
    source_url  VARCHAR,
    category    VARCHAR,                -- results | filing | rating | sector | macro | other
    sentiment   VARCHAR,                -- positive | negative | neutral
    summary     VARCHAR,
    PRIMARY KEY (date, isin, source_url)
);

CREATE TABLE IF NOT EXISTS events (
    event_date   DATE,
    isin         VARCHAR,               -- NULL for macro events
    event_type   VARCHAR,
    description  VARCHAR,
    source_url   VARCHAR,
    PRIMARY KEY (event_date, event_type, description)
);

CREATE TABLE IF NOT EXISTS runs (
    run_date    DATE,
    run_type    VARCHAR,
    started_at  TIMESTAMP,
    finished_at TIMESTAMP,
    status      VARCHAR,                -- ok | partial | failed
    notes       VARCHAR,
    PRIMARY KEY (run_date, run_type)
);
