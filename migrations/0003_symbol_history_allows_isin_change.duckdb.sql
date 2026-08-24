-- 0003_symbol_history_allows_isin_change.duckdb.sql
-- A symbol CAN begin being valid for two securities on the same day.
--
-- Plan 1 §6.2 specifies:
--
--     UNIQUE (symbol, exchange, valid_from)
--
-- which asserts that a ticker starts one life at a time. Measured against the V1
-- master on 2026-08-24, that is false twice:
--
--     GREENLAM  INE544R01013  2015-03-02 .. 2019-12-02   source: legacy
--     GREENLAM  INE544R01021  2015-03-02 .. (open)       source: equity_l
--
-- Two ISINs, one symbol, the same start date. This is what an ISIN change looks
-- like in the data — typically a face-value split or reorganisation, where the
-- legacy record is closed and a new one opened over the same ticker. Both rows
-- are true, their windows genuinely overlap, and a trade in 2015-2019 genuinely
-- has two candidate securities.
--
-- That overlap is not a problem to be removed. It is exactly what the resolver's
-- LOW confidence grade exists to report: several securities held this symbol on
-- that date. Deleting one to satisfy a constraint would convert a known
-- ambiguity into a silent wrong answer, which is the failure the identity layer
-- exists to prevent.
--
-- HOW THIS SURFACED IS ITSELF WORTH RECORDING. In the raw file the collision is
-- INVISIBLE — zero duplicate (symbol, first_date) pairs — because the two rows
-- store the same date in different formats: '2015-03-02' and '02-MAR-2015'.
-- `isin_master` is two datasets concatenated, and the format predicts the source
-- exactly (2,528 ISO rows with closed windows, 1,207 DD-MON-YYYY rows with open
-- ones). Parsing both formats correctly is what CREATED a collision that a naive
-- single-format CAST would have hidden by discarding a third of the master.
--
-- THE FIX. security_id joins the uniqueness key. The constraint still prevents
-- the same security claiming the same symbol from the same date twice — an
-- actual duplicate — while permitting two securities to share a ticker, which
-- happens.
--
-- symbol_history has no dependent tables, so unlike migration 0002 this rebuilds
-- one table rather than a chain of seven.

CREATE TABLE _bk_sh AS SELECT * FROM symbol_history;

DROP TABLE symbol_history;

CREATE TABLE symbol_history (
    symbol_history_id BIGINT PRIMARY KEY,
    security_id       BIGINT NOT NULL REFERENCES security_master (security_id),
    symbol            TEXT NOT NULL,
    exchange          TEXT NOT NULL,
    series            TEXT,
    valid_from        DATE NOT NULL,
    valid_to          DATE,
    source            TEXT NOT NULL,
    UNIQUE (symbol, exchange, valid_from, security_id)
);

INSERT INTO symbol_history SELECT * FROM _bk_sh;

DROP TABLE _bk_sh;

CREATE INDEX idx_symbol_history_lookup ON symbol_history (symbol, exchange, valid_from);
