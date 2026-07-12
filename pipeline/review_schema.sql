-- Project ORIENT - W5 review-agent tables (Track A, A2).
-- Idempotent: safe to run repeatedly (CREATE TABLE IF NOT EXISTS).
-- Created in the default (public) schema. Applier: pipeline/review_store.py --create-tables.
-- UUIDs are allocated application-side (no DB default), so no extension is required.

CREATE TABLE IF NOT EXISTS review_session (
    session_id   uuid PRIMARY KEY,
    property_id  uuid NOT NULL,
    floor        text NOT NULL,
    status       text NOT NULL DEFAULT 'open',   -- open | committed | abandoned
    created_by   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    committed_at timestamptz,
    n_pending    integer NOT NULL DEFAULT 0,
    n_approved   integer NOT NULL DEFAULT 0,
    n_rejected   integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_action (
    action_id   uuid PRIMARY KEY,
    session_id  uuid NOT NULL REFERENCES review_session (session_id),
    item_type   text NOT NULL,                   -- equipment | relationship | discrepancy | zone | point
    item_key    text NOT NULL,                   -- natural key, e.g. canonical_name or child|ref_type|parent
    action      text NOT NULL,                   -- approve | edit | reject
    payload     jsonb,                           -- edited fields (for edit) or null
    source_item jsonb,                           -- typed source for engineer-drawn proposals
    confidence  numeric,
    reviewer    text,
    reason      text,                            -- required for edit/reject by API contract
    applied     boolean NOT NULL DEFAULT false,  -- flipped true at session commit
    applied_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, item_type, item_key)     -- one live decision per item per session
);

-- Existing installations predate durable engineer-drawn proposals.  CREATE
-- TABLE IF NOT EXISTS does not add columns, so keep this migration idempotent.
ALTER TABLE review_action ADD COLUMN IF NOT EXISTS source_item jsonb;

CREATE TABLE IF NOT EXISTS correction_log (
    correction_id  uuid PRIMARY KEY,
    session_id     uuid NOT NULL REFERENCES review_session (session_id),
    item_type      text NOT NULL,
    item_key       text NOT NULL,
    original       jsonb NOT NULL,               -- the LLM/pipeline value
    corrected      jsonb,                        -- the engineer value (null on pure reject)
    reason         text,
    reviewer       text,
    fed_to_fewshot boolean NOT NULL DEFAULT false,
    created_at     timestamptz NOT NULL DEFAULT now()
);
