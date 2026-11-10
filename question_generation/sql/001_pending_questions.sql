BEGIN;

CREATE SCHEMA IF NOT EXISTS question_generation;
REVOKE ALL ON SCHEMA question_generation FROM PUBLIC;

CREATE TABLE IF NOT EXISTS question_generation.pending_questions (
    question_id text NOT NULL,
    version integer NOT NULL CHECK (version > 0),
    request_id text NOT NULL,
    question_json jsonb NOT NULL,
    queued_at timestamptz NOT NULL DEFAULT now(),
    superseded_at timestamptz,
    PRIMARY KEY (question_id, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS pending_questions_one_current
    ON question_generation.pending_questions (question_id)
    WHERE superseded_at IS NULL;

CREATE OR REPLACE VIEW question_generation.current_pending_questions AS
SELECT question_id, version, request_id, question_json, queued_at
FROM question_generation.pending_questions
WHERE superseded_at IS NULL;

CREATE OR REPLACE FUNCTION question_generation.enqueue_question(
    package jsonb, source_request_id text, previous_package jsonb DEFAULT NULL
)
RETURNS text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    item_id text := package->>'question_id';
    item_version integer := (package->>'version')::integer;
    existing question_generation.pending_questions%ROWTYPE;
BEGIN
    IF item_id IS NULL OR btrim(item_id) = '' OR item_version IS NULL OR item_version < 1
       OR source_request_id IS NULL OR btrim(source_request_id) = ''
       OR package->>'review_status' IS DISTINCT FROM 'PENDING'
       OR package #>> '{self_check,status}' IS DISTINCT FROM 'PASSED' THEN
        RAISE EXCEPTION 'Invalid generated question package' USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended('question-generation:' || item_id, 0));
    SELECT * INTO existing FROM question_generation.pending_questions
    WHERE question_id = item_id AND version = item_version;

    IF FOUND THEN
        IF existing.question_json IS DISTINCT FROM package THEN
            RETURN 'VERSION_CONFLICT';
        END IF;
        IF existing.superseded_at IS NOT NULL THEN
            RETURN 'SUPERSEDED';
        END IF;
        RETURN 'ALREADY_QUEUED';
    END IF;

    IF item_version > 1 THEN
        UPDATE question_generation.pending_questions
        SET superseded_at = clock_timestamp()
        WHERE question_id = item_id AND version = item_version - 1
          AND superseded_at IS NULL AND question_json = previous_package;
        IF NOT FOUND THEN
            RETURN 'VERSION_CONFLICT';
        END IF;
    END IF;

    INSERT INTO question_generation.pending_questions (question_id, version, request_id, question_json)
    VALUES (item_id, item_version, source_request_id, package);
    RETURN 'QUEUED';
END;
$$;

REVOKE ALL ON FUNCTION question_generation.enqueue_question(jsonb, text, jsonb) FROM PUBLIC;
REVOKE ALL ON TABLE question_generation.pending_questions, question_generation.current_pending_questions FROM PUBLIC;

COMMIT;
