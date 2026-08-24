\set ON_ERROR_STOP on

BEGIN;

CREATE ROLE etdr_owner_membership_probe LOGIN;
GRANT etdr_bridge_owner TO etdr_owner_membership_probe;
SET LOCAL ROLE etdr_lead_bridge;
DO $$
DECLARE
    v_status record;
BEGIN
    IF to_regprocedure(
        'etdr_bridge.upsert_growth_signal(text,text,text,text,text,text,timestamptz,'
        'text,text,text,integer,integer,text,text)'
    ) IS NOT NULL OR to_regprocedure(
        'etdr_bridge.upsert_growth_signal(text,text,text,text,text,text,timestamptz,'
        'text,text,text,integer,integer,text,text,text)'
    ) IS NOT NULL THEN
        RAISE EXCEPTION 'legacy_bridge_function_still_callable';
    END IF;
    SELECT * INTO v_status FROM etdr_bridge.installation_status();
    IF v_status.owner_role_valid THEN
        RAISE EXCEPTION 'bridge_owner_outbound_membership_not_detected';
    END IF;
END;
$$;
RESET ROLE;
REVOKE etdr_bridge_owner FROM etdr_owner_membership_probe;
DROP ROLE etdr_owner_membership_probe;

SET LOCAL ROLE etdr_lead_bridge;
DO $$
DECLARE
    v_status record;
BEGIN
    SELECT * INTO v_status FROM etdr_bridge.installation_status();
    IF v_status.schema_version <> '20260824_0003'
       OR v_status.recorded_definition_md5 <> v_status.actual_definition_md5
       OR v_status.recorded_constraint_md5 <> v_status.actual_constraint_md5
       OR v_status.function_owner <> 'etdr_bridge_owner'
       OR NOT v_status.security_definer
       OR NOT v_status.owner_role_valid
       OR v_status.schema_owner <> 'etdr_bridge_owner'
       OR NOT ('search_path=pg_catalog, public' = ANY(v_status.function_config))
       OR NOT ('row_security=on' = ANY(v_status.function_config))
    THEN
        RAISE EXCEPTION 'bridge_installation_status_assertion_failed';
    END IF;
END;
$$;
DO $$
DECLARE
    v_blocked boolean := false;
BEGIN
    BEGIN
        PERFORM 1 FROM public.growth_signals LIMIT 1;
    EXCEPTION WHEN insufficient_privilege THEN
        v_blocked := true;
    END;
    IF NOT v_blocked THEN
        RAISE EXCEPTION 'bridge_direct_table_access_not_blocked';
    END IF;
END;
$$;

DO $$
DECLARE
    v_result record;
BEGIN
    SELECT * INTO v_result FROM etdr_bridge.upsert_growth_signal(
        'SIG-ETDR-PROBE0000000001', 'authority:etdr_public', '209900000001',
        'construction_project', 'Synthetic bridge probe',
        'Synthetic ETDR bridge contract probe; rolled back after verification.',
        '2026-01-01T00:00:00Z'::timestamptz,
        'https://www.etdr.gov.hu/nyilvanos-adatok/209900000001',
        'bautica', repeat('a', 64), 90, 60, repeat('b', 64),
        'etdrd-' || repeat('c', 32), 1, repeat('7', 64)
    );
    IF v_result.signal_id <> 'SIG-ETDR-PROBE0000000001' OR v_result.idempotent THEN
        RAISE EXCEPTION 'bridge_first_delivery_assertion_failed';
    END IF;
END;
$$;

DO $$
DECLARE
    v_blocked boolean := false;
BEGIN
    BEGIN
        PERFORM 1 FROM etdr_bridge.upsert_growth_signal(
            'SIG-ETDR-PROBE9999999999', 'authority:etdr_public', '209900000001',
            'construction_project', 'Synthetic bridge probe',
            'Synthetic ETDR bridge contract probe; rolled back after verification.',
            '2026-01-01T00:00:00Z'::timestamptz,
            'https://www.etdr.gov.hu/nyilvanos-adatok/209900000001',
            'bautica', repeat('d', 64), 90, 60, repeat('b', 64),
            'etdrd-' || repeat('c', 32), 1, repeat('7', 64)
        );
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'etdr_revision_payload_conflict' THEN
            v_blocked := true;
        ELSE
            RAISE;
        END IF;
    END;
    IF NOT v_blocked THEN
        RAISE EXCEPTION 'bridge_revision_conflict_was_not_blocked';
    END IF;
END;
$$;

DO $$
DECLARE
    v_result record;
BEGIN
    SELECT * INTO v_result FROM etdr_bridge.upsert_growth_signal(
        'SIG-ETDR-PROBE9999999999', 'authority:etdr_public', '209900000001',
        'construction_project', 'Synthetic bridge probe',
        'Synthetic ETDR bridge contract probe; rolled back after verification.',
        '2026-01-01T00:00:00Z'::timestamptz,
        'https://www.etdr.gov.hu/nyilvanos-adatok/209900000001',
        'bautica', repeat('a', 64), 90, 60, repeat('b', 64),
        'etdrd-' || repeat('c', 32), 1, repeat('7', 64)
    );
    IF v_result.signal_id <> 'SIG-ETDR-PROBE0000000001' OR NOT v_result.idempotent THEN
        RAISE EXCEPTION 'bridge_replay_assertion_failed';
    END IF;
END;
$$;

DO $$
DECLARE
    v_blocked boolean := false;
BEGIN
    BEGIN
        PERFORM 1 FROM etdr_bridge.upsert_growth_signal(
            'SIG-ETDR-PROBE9999999999', 'authority:etdr_public', '209900000001',
            'construction_project', 'Altered location must conflict',
            'Synthetic ETDR bridge contract probe; rolled back after verification.',
            '2026-01-01T00:00:00Z'::timestamptz,
            'https://www.etdr.gov.hu/nyilvanos-adatok/209900000001',
            'bautica', repeat('a', 64), 90, 60, repeat('b', 64),
            'etdrd-' || repeat('c', 32), 1, repeat('7', 64)
        );
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'etdr_revision_payload_conflict' THEN
            v_blocked := true;
        ELSE
            RAISE;
        END IF;
    END;
    IF NOT v_blocked THEN
        RAISE EXCEPTION 'bridge_delivery_payload_conflict_was_not_blocked';
    END IF;
END;
$$;

DO $$
DECLARE
    v_result record;
BEGIN
    SELECT * INTO v_result FROM etdr_bridge.upsert_growth_signal(
        'SIG-ETDR-MONO00000000001', 'authority:etdr_public', '209900000003',
        'construction_project', 'Newest synthetic revision',
        'Newest synthetic ETDR revision must remain current after an older retry.',
        '2026-01-02T00:00:00Z'::timestamptz,
        'https://www.etdr.gov.hu/nyilvanos-adatok/209900000003',
        'bautica', repeat('3', 64), 91, 61, repeat('4', 64),
        'etdrd-' || repeat('2', 32), 2, repeat('5', 64)
    );
    IF v_result.idempotent THEN
        RAISE EXCEPTION 'bridge_newest_revision_marked_idempotent';
    END IF;

    SELECT * INTO v_result FROM etdr_bridge.upsert_growth_signal(
        'SIG-ETDR-MONO99999999999', 'authority:etdr_public', '209900000003',
        'construction_project', 'Older synthetic revision',
        'Older synthetic ETDR revision must be recorded without regressing current data.',
        '2026-01-01T00:00:00Z'::timestamptz,
        'https://www.etdr.gov.hu/nyilvanos-adatok/209900000003',
        'bautica', repeat('6', 64), 80, 50, repeat('4', 64),
        'etdrd-' || repeat('3', 32), 1, repeat('7', 64)
    );
    IF NOT v_result.idempotent THEN
        RAISE EXCEPTION 'bridge_stale_revision_not_superseded';
    END IF;
END;
$$;

RESET ROLE;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.growth_signals
        WHERE signal_id = 'SIG-ETDR-PROBE0000000001'
          AND subject_type = 'project'
          AND status = 'blocked'
          AND recipient_email IS NULL
          AND contact_basis = 'unknown'
    ) OR NOT EXISTS (
        SELECT 1 FROM etdr_bridge.delivery_ledger
        WHERE revision_id = 'etdrd-' || repeat('c', 32)
          AND signal_id = 'SIG-ETDR-PROBE0000000001'
    ) THEN
        RAISE EXCEPTION 'bridge_persisted_contract_assertion_failed';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.growth_signals
        WHERE external_key = '209900000003'
          AND summary = 'Newest synthetic ETDR revision must remain current after an older retry.'
          AND source_payload_hash = repeat('3', 64)
    ) OR NOT EXISTS (
        SELECT 1 FROM etdr_bridge.delivery_ledger
        WHERE external_key = '209900000003' AND revision_no = 1 AND superseded
    ) THEN
        RAISE EXCEPTION 'bridge_revision_monotonicity_assertion_failed';
    END IF;
END;
$$;

UPDATE public.growth_signals
SET recipient_email = 'unsafe@example.invalid'
WHERE signal_id = 'SIG-ETDR-PROBE0000000001';
SET LOCAL ROLE etdr_lead_bridge;
DO $$
DECLARE
    v_blocked boolean := false;
BEGIN
    BEGIN
        PERFORM 1 FROM etdr_bridge.upsert_growth_signal(
            'SIG-ETDR-PROBE9999999999', 'authority:etdr_public', '209900000001',
            'construction_project', 'Synthetic bridge probe',
            'Synthetic ETDR bridge contract probe; rolled back after verification.',
            '2026-01-01T00:00:00Z'::timestamptz,
            'https://www.etdr.gov.hu/nyilvanos-adatok/209900000001',
            'bautica', repeat('a', 64), 90, 60, repeat('b', 64),
            'etdrd-' || repeat('c', 32), 1, repeat('7', 64)
        );
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'etdr_existing_signal_invariant_violation' THEN
            v_blocked := true;
        ELSE
            RAISE;
        END IF;
    END;
    IF NOT v_blocked THEN
        RAISE EXCEPTION 'bridge_tamper_was_not_blocked';
    END IF;
END;
$$;

ROLLBACK;
