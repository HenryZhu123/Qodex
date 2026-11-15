BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS question_generation.generation_tasks (
    task_id uuid PRIMARY KEY,
    request_id text NOT NULL,
    generation_mode text NOT NULL CHECK (
        generation_mode IN ('single', 'batch', 'comprehensive', 'revise', 'author', 'replenishment', 'legacy')
    ),
    status text NOT NULL CHECK (
        status IN ('CREATED', 'GENERATING', 'PENDING_REVIEW', 'COMPLETED', 'FAILED')
    ),
    question_count integer NOT NULL CHECK (question_count >= 0),
    request_json jsonb NOT NULL,
    model_name text,
    prompt_version text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    failure_reason text
);

CREATE INDEX IF NOT EXISTS generation_tasks_request_id
    ON question_generation.generation_tasks (request_id, created_at DESC);

-- The brief-driven `author` and the assembly `replenishment` paths also create tasks.
-- Older installs carry the narrower check, and CREATE TABLE IF NOT EXISTS cannot widen it.
ALTER TABLE question_generation.generation_tasks
    DROP CONSTRAINT IF EXISTS generation_tasks_generation_mode_check;
ALTER TABLE question_generation.generation_tasks
    ADD CONSTRAINT generation_tasks_generation_mode_check CHECK (
        generation_mode IN ('single', 'batch', 'comprehensive', 'revise', 'author', 'replenishment', 'legacy')
    );

ALTER TABLE question_generation.pending_questions
    ADD COLUMN IF NOT EXISTS task_id uuid;

WITH legacy_tasks AS (
    SELECT request_id, gen_random_uuid() AS task_id, count(*)::integer AS question_count
    FROM question_generation.pending_questions
    WHERE task_id IS NULL
    GROUP BY request_id
), inserted AS (
    INSERT INTO question_generation.generation_tasks (
        task_id, request_id, generation_mode, status, question_count, request_json,
        prompt_version, completed_at
    )
    SELECT task_id, request_id, 'legacy', 'PENDING_REVIEW', question_count,
           jsonb_build_object('request_id', request_id), 'pre-task-id', now()
    FROM legacy_tasks
    ON CONFLICT (task_id) DO NOTHING
    RETURNING task_id
)
UPDATE question_generation.pending_questions AS pending
SET task_id = legacy.task_id
FROM legacy_tasks AS legacy
WHERE pending.task_id IS NULL AND pending.request_id = legacy.request_id;

ALTER TABLE question_generation.pending_questions
    ALTER COLUMN task_id SET NOT NULL;

ALTER TABLE question_generation.pending_questions
    DROP CONSTRAINT IF EXISTS pending_questions_pkey;
ALTER TABLE question_generation.pending_questions
    ADD CONSTRAINT pending_questions_pkey PRIMARY KEY (task_id, question_id, version);

DROP INDEX IF EXISTS question_generation.pending_questions_one_current;
CREATE UNIQUE INDEX pending_questions_one_current
    ON question_generation.pending_questions (task_id, question_id)
    WHERE superseded_at IS NULL;

ALTER TABLE question_generation.pending_questions
    DROP CONSTRAINT IF EXISTS fk_pending_questions_task;
ALTER TABLE question_generation.pending_questions
    ADD CONSTRAINT fk_pending_questions_task
    FOREIGN KEY (task_id)
    REFERENCES question_generation.generation_tasks(task_id)
    ON DELETE RESTRICT;

DO $$
BEGIN
    IF to_regclass('public.question_snapshots') IS NOT NULL THEN
        UPDATE public.question_snapshots
        SET generation_task_id = CASE
            WHEN task_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
            THEN task_id::uuid
        END
        WHERE generation_task_id IS NULL
          AND task_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
          AND EXISTS (
              SELECT 1 FROM question_generation.generation_tasks AS task
              WHERE task.task_id = CASE
                  WHEN public.question_snapshots.task_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                  THEN public.question_snapshots.task_id::uuid
              END
          );
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_question_snapshots_generation_task'
              AND conrelid = 'public.question_snapshots'::regclass
        ) THEN
            ALTER TABLE public.question_snapshots
            ADD CONSTRAINT fk_question_snapshots_generation_task
            FOREIGN KEY (generation_task_id)
            REFERENCES question_generation.generation_tasks(task_id)
            ON DELETE RESTRICT;
        END IF;
    END IF;
END;
$$;

DROP VIEW IF EXISTS question_generation.current_pending_questions;
CREATE VIEW question_generation.current_pending_questions AS
SELECT task_id, question_id, version, request_id, question_json, queued_at
FROM question_generation.pending_questions
WHERE superseded_at IS NULL;

DROP FUNCTION IF EXISTS question_generation.enqueue_question(jsonb, text, jsonb);
CREATE OR REPLACE FUNCTION question_generation.enqueue_question(
    source_task_id uuid, package jsonb, source_request_id text,
    previous_package jsonb DEFAULT NULL
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
    IF source_task_id IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM question_generation.generation_tasks WHERE task_id = source_task_id
       )
       OR item_id IS NULL OR btrim(item_id) = '' OR item_version IS NULL OR item_version < 1
       OR source_request_id IS NULL OR btrim(source_request_id) = ''
       OR package->>'review_status' IS DISTINCT FROM 'PENDING'
       OR package #>> '{self_check,status}' IS DISTINCT FROM 'PASSED' THEN
        RAISE EXCEPTION 'Invalid generated question package' USING ERRCODE = '22023';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended('question-generation:' || source_task_id::text || ':' || item_id, 0)
    );
    SELECT * INTO existing FROM question_generation.pending_questions
    WHERE task_id = source_task_id AND question_id = item_id AND version = item_version;

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
        WHERE task_id = source_task_id AND question_id = item_id
          AND version = item_version - 1 AND superseded_at IS NULL
          AND question_json = previous_package;
        IF NOT FOUND THEN
            RETURN 'VERSION_CONFLICT';
        END IF;
    END IF;

    INSERT INTO question_generation.pending_questions (
        task_id, question_id, version, request_id, question_json
    )
    VALUES (source_task_id, item_id, item_version, source_request_id, package);
    RETURN 'QUEUED';
END;
$$;

REVOKE ALL ON FUNCTION question_generation.enqueue_question(uuid, jsonb, text, jsonb) FROM PUBLIC;
REVOKE ALL ON TABLE question_generation.generation_tasks FROM PUBLIC;

COMMIT;
