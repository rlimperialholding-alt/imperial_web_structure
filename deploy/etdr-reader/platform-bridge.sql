\set ON_ERROR_STOP on

BEGIN;

DO $$
DECLARE
    v_parent name;
    v_member name;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etdr_bridge_owner') THEN
        CREATE ROLE etdr_bridge_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    ALTER ROLE etdr_bridge_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOINHERIT NOREPLICATION NOBYPASSRLS;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etdr_lead_bridge') THEN
        RAISE EXCEPTION 'etdr_lead_bridge_role_missing';
    END IF;
    ALTER ROLE etdr_lead_bridge LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
        NOINHERIT NOREPLICATION NOBYPASSRLS;
    FOR v_parent, v_member IN
        SELECT parent.rolname, member.rolname
        FROM pg_auth_members AS membership
        JOIN pg_roles AS parent ON parent.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE parent.rolname IN ('etdr_bridge_owner', 'etdr_lead_bridge')
           OR member.rolname IN ('etdr_bridge_owner', 'etdr_lead_bridge')
    LOOP
        EXECUTE format('REVOKE %I FROM %I', v_parent, v_member);
    END LOOP;
END;
$$;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM etdr_bridge_owner, etdr_lead_bridge;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM etdr_bridge_owner, etdr_lead_bridge;
REVOKE CREATE ON SCHEMA public FROM etdr_bridge_owner, etdr_lead_bridge;

DO $$
DECLARE
    v_owner name;
BEGIN
    SELECT owner.rolname INTO v_owner
    FROM pg_namespace AS namespace
    JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
    WHERE namespace.nspname = 'etdr_bridge';
    IF v_owner IS NULL THEN
        CREATE SCHEMA etdr_bridge AUTHORIZATION etdr_bridge_owner;
    ELSIF v_owner <> 'etdr_bridge_owner' THEN
        RAISE EXCEPTION 'etdr_bridge_schema_owner_mismatch';
    END IF;
END;
$$;
REVOKE ALL ON SCHEMA etdr_bridge FROM PUBLIC, etdr_lead_bridge;

-- Remove every pre-0003 callable overload before installing the hardened contract. A changed
-- PostgreSQL signature creates an overload; CREATE OR REPLACE alone would leave the old entrypoint.
DROP FUNCTION IF EXISTS etdr_bridge.upsert_growth_signal(
    text,text,text,text,text,text,timestamptz,text,text,text,integer,integer,text,text
);
DROP FUNCTION IF EXISTS etdr_bridge.upsert_growth_signal(
    text,text,text,text,text,text,timestamptz,text,text,text,integer,integer,text,text,text
);
DROP FUNCTION IF EXISTS etdr_bridge.installation_status();

CREATE TABLE IF NOT EXISTS etdr_bridge.schema_versions (
    version text PRIMARY KEY,
    function_definition_md5 char(32) NOT NULL,
    constraint_definition_md5 char(32) NOT NULL,
    installed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    installed_by text NOT NULL DEFAULT session_user,
    active boolean NOT NULL DEFAULT true
);
ALTER TABLE etdr_bridge.schema_versions OWNER TO etdr_bridge_owner;

CREATE TABLE IF NOT EXISTS etdr_bridge.delivery_ledger (
    revision_id text PRIMARY KEY,
    source_id text NOT NULL,
    external_key text NOT NULL,
    source_payload_hash char(64) NOT NULL,
    delivery_payload_hash char(64) NOT NULL,
    dedupe_hash char(64) NOT NULL,
    revision_no integer NOT NULL,
    signal_type text NOT NULL,
    detected_at timestamptz NOT NULL,
    location text NOT NULL,
    summary text NOT NULL,
    evidence_url text NOT NULL,
    brand_id text NOT NULL,
    confidence integer NOT NULL,
    urgency integer NOT NULL,
    superseded boolean NOT NULL DEFAULT false,
    signal_id text NOT NULL,
    delivered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT uq_etdr_bridge_delivery_payload
        UNIQUE (source_id, external_key, source_payload_hash),
    CONSTRAINT uq_etdr_bridge_delivery_revision_no
        UNIQUE (source_id, external_key, revision_no),
    CONSTRAINT ck_etdr_bridge_revision_id
        CHECK (revision_id ~ '^etdrd-[0-9a-f]{32}$'),
    CONSTRAINT ck_etdr_bridge_source
        CHECK (source_id = 'authority:etdr_public'),
    CONSTRAINT ck_etdr_bridge_external_key
        CHECK (external_key ~ '^[0-9]{6,40}$'),
    CONSTRAINT ck_etdr_bridge_payload_hash
        CHECK (source_payload_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_etdr_bridge_delivery_hash
        CHECK (delivery_payload_hash ~ '^[0-9a-f]{64}$')
);
ALTER TABLE etdr_bridge.delivery_ledger OWNER TO etdr_bridge_owner;

-- Fail-closed upgrade path for pre-release 0001/0002 installs. Those versions never carried
-- enough information to reconstruct a full payload or revision order, so only empty ledgers can
-- be upgraded automatically.
ALTER TABLE etdr_bridge.schema_versions
    ADD COLUMN IF NOT EXISTS constraint_definition_md5 char(32);
UPDATE etdr_bridge.schema_versions
SET constraint_definition_md5 = repeat('0', 32), active = false
WHERE constraint_definition_md5 IS NULL;
ALTER TABLE etdr_bridge.schema_versions
    ALTER COLUMN constraint_definition_md5 SET NOT NULL;

ALTER TABLE etdr_bridge.delivery_ledger
    ADD COLUMN IF NOT EXISTS delivery_payload_hash char(64),
    ADD COLUMN IF NOT EXISTS dedupe_hash char(64),
    ADD COLUMN IF NOT EXISTS revision_no integer,
    ADD COLUMN IF NOT EXISTS signal_type text,
    ADD COLUMN IF NOT EXISTS detected_at timestamptz,
    ADD COLUMN IF NOT EXISTS location text,
    ADD COLUMN IF NOT EXISTS summary text,
    ADD COLUMN IF NOT EXISTS evidence_url text,
    ADD COLUMN IF NOT EXISTS brand_id text,
    ADD COLUMN IF NOT EXISTS confidence integer,
    ADD COLUMN IF NOT EXISTS urgency integer,
    ADD COLUMN IF NOT EXISTS superseded boolean;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM etdr_bridge.delivery_ledger
        WHERE delivery_payload_hash IS NULL OR dedupe_hash IS NULL
           OR revision_no IS NULL OR signal_type IS NULL
           OR detected_at IS NULL OR location IS NULL OR summary IS NULL OR evidence_url IS NULL
           OR brand_id IS NULL OR confidence IS NULL OR urgency IS NULL OR superseded IS NULL
    ) THEN
        RAISE EXCEPTION 'etdr_bridge_legacy_delivery_requires_manual_migration';
    END IF;
END;
$$;
ALTER TABLE etdr_bridge.delivery_ledger
    ALTER COLUMN delivery_payload_hash SET NOT NULL,
    ALTER COLUMN dedupe_hash SET NOT NULL,
    ALTER COLUMN revision_no SET NOT NULL,
    ALTER COLUMN signal_type SET NOT NULL,
    ALTER COLUMN detected_at SET NOT NULL,
    ALTER COLUMN location SET NOT NULL,
    ALTER COLUMN summary SET NOT NULL,
    ALTER COLUMN evidence_url SET NOT NULL,
    ALTER COLUMN brand_id SET NOT NULL,
    ALTER COLUMN confidence SET NOT NULL,
    ALTER COLUMN urgency SET NOT NULL,
    ALTER COLUMN superseded SET DEFAULT false,
    ALTER COLUMN superseded SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'etdr_bridge.delivery_ledger'::regclass
          AND conname = 'uq_etdr_bridge_delivery_revision_no'
    ) THEN
        ALTER TABLE etdr_bridge.delivery_ledger
            ADD CONSTRAINT uq_etdr_bridge_delivery_revision_no
            UNIQUE (source_id, external_key, revision_no);
    END IF;
END;
$$;
REVOKE ALL ON ALL TABLES IN SCHEMA etdr_bridge FROM PUBLIC, etdr_lead_bridge;

ALTER TABLE public.growth_signals
    DROP CONSTRAINT ck_growth_signal_subject_type;
ALTER TABLE public.growth_signals
    ADD CONSTRAINT ck_growth_signal_subject_type
    CHECK (subject_type IN ('organization','natural_person','project'));

GRANT SELECT, INSERT, UPDATE ON TABLE public.growth_signals TO etdr_bridge_owner;
DO $$
DECLARE
    v_sequence text;
BEGIN
    SELECT pg_get_serial_sequence('public.growth_signals', 'id') INTO v_sequence;
    IF v_sequence IS NULL THEN
        RAISE EXCEPTION 'growth_signals_id_sequence_missing';
    END IF;
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO etdr_bridge_owner', v_sequence);
END;
$$;

CREATE OR REPLACE FUNCTION etdr_bridge.upsert_growth_signal(
    p_signal_id text,
    p_source_id text,
    p_external_key text,
    p_signal_type text,
    p_location text,
    p_summary text,
    p_detected_at timestamptz,
    p_evidence_url text,
    p_brand_id text,
    p_source_payload_hash text,
    p_confidence integer,
    p_urgency integer,
    p_dedupe_hash text,
    p_revision_id text,
    p_revision_no integer,
    p_delivery_payload_hash text
) RETURNS TABLE(signal_id text, idempotent boolean)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = on
AS $$
DECLARE
    v_existing text;
    v_inserted integer;
    v_ledger etdr_bridge.delivery_ledger%ROWTYPE;
    v_latest_revision_no integer;
    v_replay boolean := false;
    v_superseded boolean := false;
    v_rejections constant text :=
        '["authority_source_no_outreach","contact_basis_unknown",'
        '"internal_review_only","recipient_email_missing"]';
BEGIN
    IF p_signal_id IS NULL OR p_signal_id !~ '^SIG-ETDR-[A-Z0-9]{15}$'
       OR p_source_id IS NULL OR p_source_id <> 'authority:etdr_public'
       OR p_external_key IS NULL OR p_external_key !~ '^[0-9]{6,40}$'
       OR p_signal_type IS NULL
       OR p_signal_type NOT IN (
           'construction_project', 'residential_construction', 'renovation',
           'extension', 'fitout', 'hall'
       )
       OR p_location IS NULL OR length(p_location) NOT BETWEEN 1 AND 500
       OR p_summary IS NULL OR length(p_summary) NOT BETWEEN 10 AND 5000
       OR p_detected_at IS NULL OR p_detected_at > clock_timestamp()
       OR p_evidence_url IS NULL OR length(p_evidence_url) > 1500
       OR p_evidence_url <> 'https://www.etdr.gov.hu/nyilvanos-adatok/' || p_external_key
       OR p_brand_id IS NULL OR p_brand_id NOT IN ('bautica', 'prefab')
       OR (p_signal_type = 'hall') <> (p_brand_id = 'prefab')
       OR p_source_payload_hash IS NULL OR p_source_payload_hash !~ '^[0-9a-f]{64}$'
       OR p_dedupe_hash IS NULL OR p_dedupe_hash !~ '^[0-9a-f]{64}$'
       OR p_revision_id IS NULL OR p_revision_id !~ '^etdrd-[0-9a-f]{32}$'
       OR p_revision_no IS NULL OR p_revision_no < 1
       OR p_delivery_payload_hash IS NULL OR p_delivery_payload_hash !~ '^[0-9a-f]{64}$'
       OR p_confidence IS NULL OR p_confidence NOT BETWEEN 0 AND 100
       OR p_urgency IS NULL OR p_urgency NOT BETWEEN 0 AND 100
    THEN
        RAISE EXCEPTION 'etdr_lead_contract_blocked';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(p_source_id || ':' || p_external_key, 0)
    );
    SELECT max(ledger.revision_no) INTO v_latest_revision_no
    FROM etdr_bridge.delivery_ledger AS ledger
    WHERE ledger.source_id = p_source_id AND ledger.external_key = p_external_key;

    SELECT * INTO v_ledger
    FROM etdr_bridge.delivery_ledger AS ledger
    WHERE ledger.revision_id = p_revision_id;
    IF FOUND THEN
        IF v_ledger.source_id <> p_source_id
           OR v_ledger.external_key <> p_external_key
           OR v_ledger.source_payload_hash <> p_source_payload_hash
           OR v_ledger.delivery_payload_hash <> p_delivery_payload_hash
           OR v_ledger.dedupe_hash <> p_dedupe_hash
           OR v_ledger.revision_no <> p_revision_no
           OR v_ledger.signal_type <> p_signal_type
           OR v_ledger.detected_at <> p_detected_at
           OR v_ledger.location <> p_location
           OR v_ledger.summary <> p_summary
           OR v_ledger.evidence_url <> p_evidence_url
           OR v_ledger.brand_id <> p_brand_id
           OR v_ledger.confidence <> p_confidence
           OR v_ledger.urgency <> p_urgency
        THEN
            RAISE EXCEPTION 'etdr_revision_payload_conflict';
        END IF;
        v_existing := v_ledger.signal_id;
        v_replay := true;
        v_superseded := v_ledger.superseded OR COALESCE(
            v_latest_revision_no > p_revision_no, false
        );
    ELSE
        IF v_latest_revision_no = p_revision_no THEN
            RAISE EXCEPTION 'etdr_revision_sequence_conflict';
        END IF;
        v_superseded := COALESCE(v_latest_revision_no > p_revision_no, false);
        SELECT gs.signal_id INTO v_existing
        FROM public.growth_signals AS gs
        WHERE gs.source_id = p_source_id AND gs.external_key = p_external_key;
    END IF;

    IF v_existing IS NULL THEN
        INSERT INTO public.growth_signals (
            signal_id, run_id, motor_key, source_id, source_bucket, external_key,
            signal_type, detected_at, company_name, company_registration_id,
            subject_type, recipient_email, recipient_email_type, contact_basis,
            consent_evidence_id, public_contact_url, location, summary, evidence_url,
            brand_id, score, urgency, confidence, dedupe_hash, source_payload_hash,
            status, rejection_reasons_json, first_seen_at, last_seen_at, created_at,
            updated_at
        ) VALUES (
            p_signal_id, NULL, 'construction', p_source_id, 'etdr', p_external_key,
            p_signal_type, p_detected_at, NULL, NULL, 'project', NULL, 'none', 'unknown',
            NULL, NULL, p_location, p_summary, p_evidence_url, p_brand_id, p_confidence,
            p_urgency, p_confidence, p_dedupe_hash, p_source_payload_hash, 'blocked',
            v_rejections, clock_timestamp(), clock_timestamp(), clock_timestamp(),
            clock_timestamp()
        )
        ON CONFLICT (source_id, external_key) DO NOTHING;
        GET DIAGNOSTICS v_inserted = ROW_COUNT;
        IF v_inserted = 1 THEN
            v_existing := p_signal_id;
        ELSE
            SELECT gs.signal_id INTO v_existing
            FROM public.growth_signals AS gs
            WHERE gs.source_id = p_source_id AND gs.external_key = p_external_key;
        END IF;
        IF v_existing IS NULL THEN
            RAISE EXCEPTION 'etdr_lead_idempotency_failure';
        END IF;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.growth_signals AS gs
        WHERE gs.signal_id = v_existing
          AND gs.source_id = p_source_id
          AND gs.external_key = p_external_key
          AND gs.motor_key = 'construction'
          AND gs.source_bucket = 'etdr'
          AND gs.subject_type = 'project'
          AND gs.company_name IS NULL
          AND gs.company_registration_id IS NULL
          AND gs.recipient_email IS NULL
          AND gs.recipient_email_type = 'none'
          AND gs.contact_basis = 'unknown'
          AND gs.consent_evidence_id IS NULL
          AND gs.public_contact_url IS NULL
          AND gs.status IN ('blocked', 'rejected')
          AND gs.rejection_reasons_json = v_rejections
    ) THEN
        RAISE EXCEPTION 'etdr_existing_signal_invariant_violation';
    END IF;

    IF NOT v_replay AND NOT v_superseded THEN
        UPDATE public.growth_signals AS gs
        SET last_seen_at = clock_timestamp(),
            updated_at = clock_timestamp(),
            signal_type = p_signal_type,
            location = p_location,
            summary = p_summary,
            evidence_url = p_evidence_url,
            brand_id = p_brand_id,
            score = p_confidence,
            urgency = p_urgency,
            confidence = p_confidence,
            source_payload_hash = p_source_payload_hash
        WHERE gs.signal_id = v_existing;
    END IF;

    IF NOT v_replay THEN
        INSERT INTO etdr_bridge.delivery_ledger (
            revision_id, source_id, external_key, source_payload_hash,
            delivery_payload_hash, dedupe_hash, revision_no, signal_type, detected_at,
            location, summary, evidence_url, brand_id, confidence, urgency, superseded, signal_id
        ) VALUES (
            p_revision_id, p_source_id, p_external_key, p_source_payload_hash,
            p_delivery_payload_hash, p_dedupe_hash, p_revision_no, p_signal_type, p_detected_at,
            p_location, p_summary, p_evidence_url, p_brand_id, p_confidence, p_urgency,
            v_superseded, v_existing
        );
    END IF;
    RETURN QUERY SELECT v_existing, (v_replay OR v_superseded);
END;
$$;
ALTER FUNCTION etdr_bridge.upsert_growth_signal(
    text,text,text,text,text,text,timestamptz,text,text,text,integer,integer,text,text,integer,text
) OWNER TO etdr_bridge_owner;
REVOKE ALL ON FUNCTION etdr_bridge.upsert_growth_signal(
    text,text,text,text,text,text,timestamptz,text,text,text,integer,integer,text,text,integer,text
) FROM PUBLIC, etdr_lead_bridge;

INSERT INTO etdr_bridge.schema_versions (
    version, function_definition_md5, constraint_definition_md5,
    installed_at, installed_by, active
)
SELECT
    '20260824_0003', md5(pg_get_functiondef(function.oid)),
    md5(pg_get_constraintdef(constraint_row.oid)),
    clock_timestamp(), session_user, true
FROM pg_proc AS function
JOIN pg_constraint AS constraint_row
  ON constraint_row.conrelid = 'public.growth_signals'::regclass
 AND constraint_row.conname = 'ck_growth_signal_subject_type'
WHERE function.oid = (
    'etdr_bridge.upsert_growth_signal(text,text,text,text,text,text,timestamptz,'
    'text,text,text,integer,integer,text,text,integer,text)'::regprocedure
)
ON CONFLICT (version) DO UPDATE SET
    function_definition_md5 = EXCLUDED.function_definition_md5,
    constraint_definition_md5 = EXCLUDED.constraint_definition_md5,
    installed_at = EXCLUDED.installed_at,
    installed_by = EXCLUDED.installed_by,
    active = true;

CREATE OR REPLACE FUNCTION etdr_bridge.installation_status()
RETURNS TABLE(
    schema_version text,
    recorded_definition_md5 text,
    actual_definition_md5 text,
    recorded_constraint_md5 text,
    actual_constraint_md5 text,
    function_owner text,
    security_definer boolean,
    function_config text[],
    owner_role_valid boolean,
    schema_owner text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, public
SET row_security = on
AS $$
    SELECT version.version,
           version.function_definition_md5::text,
           md5(pg_get_functiondef(function.oid)),
           version.constraint_definition_md5::text,
           md5(pg_get_constraintdef(constraint_row.oid)),
           pg_get_userbyid(function.proowner),
           function.prosecdef,
           function.proconfig,
           NOT owner.rolsuper
               AND NOT owner.rolinherit
               AND NOT owner.rolcreaterole
               AND NOT owner.rolcreatedb
               AND NOT owner.rolcanlogin
               AND NOT owner.rolreplication
               AND NOT owner.rolbypassrls
               AND NOT EXISTS (
                   SELECT 1 FROM pg_auth_members AS membership
                   WHERE membership.member = owner.oid OR membership.roleid = owner.oid
               ),
           pg_get_userbyid(namespace.nspowner)
    FROM etdr_bridge.schema_versions AS version
    JOIN pg_proc AS function ON function.oid = (
        'etdr_bridge.upsert_growth_signal(text,text,text,text,text,text,timestamptz,'
        'text,text,text,integer,integer,text,text,integer,text)'::regprocedure
    )
    JOIN pg_roles AS owner ON owner.oid = function.proowner
    JOIN pg_namespace AS namespace ON namespace.nspname = 'etdr_bridge'
    JOIN pg_constraint AS constraint_row
      ON constraint_row.conrelid = 'public.growth_signals'::regclass
     AND constraint_row.conname = 'ck_growth_signal_subject_type'
    WHERE version.version = '20260824_0003' AND version.active;
$$;
ALTER FUNCTION etdr_bridge.installation_status() OWNER TO etdr_bridge_owner;
REVOKE ALL ON FUNCTION etdr_bridge.installation_status()
    FROM PUBLIC, etdr_lead_bridge;

GRANT USAGE ON SCHEMA etdr_bridge TO etdr_lead_bridge;
GRANT EXECUTE ON FUNCTION etdr_bridge.upsert_growth_signal(
    text,text,text,text,text,text,timestamptz,text,text,text,integer,integer,text,text,integer,text
) TO etdr_lead_bridge;
GRANT EXECUTE ON FUNCTION etdr_bridge.installation_status() TO etdr_lead_bridge;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM etdr_lead_bridge;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM etdr_lead_bridge;
REVOKE ALL ON ALL TABLES IN SCHEMA etdr_bridge FROM etdr_lead_bridge;

COMMIT;
