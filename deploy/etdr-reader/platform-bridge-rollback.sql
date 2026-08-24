\set ON_ERROR_STOP on

BEGIN;

REVOKE USAGE ON SCHEMA etdr_bridge FROM etdr_lead_bridge;
DROP FUNCTION IF EXISTS etdr_bridge.installation_status();
DROP FUNCTION IF EXISTS etdr_bridge.upsert_growth_signal(
    text,text,text,text,text,text,timestamptz,text,text,text,integer,integer,text,text,integer,text
);
UPDATE etdr_bridge.schema_versions
SET active = false
WHERE version = '20260824_0003';

REVOKE ALL ON TABLE public.growth_signals FROM etdr_bridge_owner, etdr_lead_bridge;
DO $$
DECLARE
    v_sequence text;
BEGIN
    SELECT pg_get_serial_sequence('public.growth_signals', 'id') INTO v_sequence;
    IF v_sequence IS NOT NULL THEN
        EXECUTE format(
            'REVOKE ALL ON SEQUENCE %s FROM etdr_bridge_owner, etdr_lead_bridge',
            v_sequence
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.growth_signals WHERE subject_type = 'project'
    ) THEN
        ALTER TABLE public.growth_signals
            DROP CONSTRAINT ck_growth_signal_subject_type;
        ALTER TABLE public.growth_signals
            ADD CONSTRAINT ck_growth_signal_subject_type
            CHECK (subject_type IN ('organization','natural_person'));
    END IF;
END;
$$;

-- The version and immutable delivery ledgers are intentionally retained for audit/restore.
COMMIT;
