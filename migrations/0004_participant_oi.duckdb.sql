-- 0004_participant_oi.duckdb.sql
-- F&O participant-wise open interest — the only long-history institutional
-- positioning signal carried in the seed and never loaded.
--
-- WHY THIS EXISTS. sources.yml has carried this since 0027, HAVE status,
-- 15,359 rows, 2014-01-01 -> 2026-06-25, ported from the V1 export as
-- participant_oi.parquet. Nothing ever created a table for it or loaded it —
-- one of 109 seed tables an earlier audit found unread by any code.
--
-- IT IS NOT FII/DII CASH FLOW, AND sources.yml SAYS SO IN CAPITALS: "This is
-- F&O participant-wise open interest — DERIVATIVES POSITIONING, NOT
-- CASH-MARKET FLOW. A different measure, and every study using it must say so
-- rather than calling it FII/DII flow." The column names below preserve that
-- distinction (oi_, not flow_) so a query cannot accidentally read a position
-- as a trade.
--
-- CATEGORY IS FII, DII, PRO, CLIENT OR TOTAL. TOTAL is a computed sum row in
-- the source, not a sixth participant — kept, not dropped, because dropping it
-- silently would make "SELECT SUM(...) GROUP BY date" wrong by a factor of two
-- for anyone who forgets to exclude it. A CHECK constraint makes the five
-- values closed rather than whatever the next load happens to contain.

CREATE TABLE participant_oi (
    session_date        DATE NOT NULL,
    category            VARCHAR NOT NULL
                           CHECK (category IN ('FII','DII','Pro','Client','TOTAL')),
    index_fut_long       DOUBLE,
    index_fut_short      DOUBLE,
    index_fut_net        DOUBLE,
    index_call_long      DOUBLE,
    index_call_short     DOUBLE,
    index_put_long       DOUBLE,
    index_put_short      DOUBLE,
    stock_fut_long        DOUBLE,
    stock_fut_short       DOUBLE,
    stock_fut_net         DOUBLE,
    stock_call_long       DOUBLE,
    stock_put_long        DOUBLE,
    source               VARCHAR NOT NULL DEFAULT 'v1_export',
    loaded_at            TIMESTAMP NOT NULL DEFAULT current_timestamp,
    UNIQUE (session_date, category)
);
