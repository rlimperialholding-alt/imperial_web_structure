"""Global rolling recipient e-mail guard shared by every delivery engine."""

# ruff: noqa: E501

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260828_0085"
down_revision = "20260827_0084"
branch_labels = None
depends_on = None


CLAIM_FUNCTION = r"""
CREATE OR REPLACE FUNCTION public.claim_global_email_recipient_guard(
    p_recipients text[],
    p_identity_sha256 text,
    p_message_type text,
    p_tenant_scope text,
    p_now timestamptz
) RETURNS TABLE(decision text, claim_token text, provider_message_id text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_recipients text[];
    v_recipient text;
    v_state public.global_email_recipient_guards%ROWTYPE;
    v_claim_token text;
    v_provider_message_id text;
    v_same_sent boolean := true;
BEGIN
    SELECT array_agg(value ORDER BY value)
      INTO v_recipients
      FROM (
          SELECT DISTINCT lower(btrim(value)) AS value
          FROM unnest(p_recipients) AS supplied(value)
      ) normalized;
    IF v_recipients IS NULL
       OR cardinality(v_recipients) <> cardinality(p_recipients)
       OR cardinality(v_recipients) > 20
       OR EXISTS (
           SELECT 1 FROM unnest(v_recipients) AS checked(value)
           WHERE value = '' OR length(value) > 320 OR value !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$'
       ) THEN
        RAISE EXCEPTION 'global_email_guard_recipient_set_invalid';
    END IF;
    IF p_identity_sha256 !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'global_email_guard_identity_invalid';
    END IF;

    INSERT INTO public.global_email_recipient_guards(
        recipient_normalized, status, created_at, updated_at
    )
    SELECT value, 'idle', p_now, p_now
    FROM unnest(v_recipients) AS items(value)
    ON CONFLICT (recipient_normalized) DO NOTHING;

    PERFORM recipient_normalized
    FROM public.global_email_recipient_guards
    WHERE recipient_normalized = ANY(v_recipients)
    ORDER BY recipient_normalized
    FOR UPDATE;

    FOREACH v_recipient IN ARRAY v_recipients LOOP
        SELECT * INTO STRICT v_state
        FROM public.global_email_recipient_guards
        WHERE recipient_normalized = v_recipient;
        IF v_state.sent_at IS NOT NULL AND v_state.sent_at > p_now - interval '24 hours' THEN
            IF v_state.identity_sha256 <> p_identity_sha256 THEN
                RETURN QUERY SELECT 'blocked_rolling_24h'::text, NULL::text, NULL::text;
                RETURN;
            END IF;
            IF v_provider_message_id IS NULL THEN
                v_provider_message_id := v_state.provider_message_id;
            ELSIF v_provider_message_id IS DISTINCT FROM v_state.provider_message_id THEN
                v_provider_message_id := NULL;
            END IF;
        ELSE
            v_same_sent := false;
            IF v_state.status IN ('claimed', 'sending') THEN
                IF v_state.lease_expires_at IS NOT NULL AND v_state.lease_expires_at > p_now THEN
                    RETURN QUERY SELECT
                        CASE WHEN v_state.identity_sha256 = p_identity_sha256
                             THEN 'in_progress' ELSE 'blocked_active_claim' END,
                        NULL::text,
                        NULL::text;
                    RETURN;
                END IF;
                IF v_state.identity_sha256 = p_identity_sha256 THEN
                    RETURN QUERY SELECT 'reconcile_required'::text,
                        v_state.claim_token, v_state.provider_message_id;
                ELSE
                    RETURN QUERY SELECT 'blocked_stale_claim'::text, NULL::text, NULL::text;
                END IF;
                RETURN;
            END IF;
            IF v_state.status = 'accepted_unverified' THEN
                IF v_state.identity_sha256 = p_identity_sha256 THEN
                    RETURN QUERY SELECT 'reconcile_required'::text,
                        v_state.claim_token, v_state.provider_message_id;
                ELSE
                    RETURN QUERY SELECT 'blocked_ambiguous'::text, NULL::text, NULL::text;
                END IF;
                RETURN;
            END IF;
        END IF;
    END LOOP;

    IF v_same_sent THEN
        RETURN QUERY SELECT 'already_sent'::text, NULL::text, v_provider_message_id;
        RETURN;
    END IF;

    v_claim_token := 'GERG-' || upper(md5(random()::text || clock_timestamp()::text || p_identity_sha256));
    UPDATE public.global_email_recipient_guards
       SET identity_sha256 = p_identity_sha256,
           message_type = left(p_message_type, 120),
           tenant_scope = left(p_tenant_scope, 120),
           status = 'claimed',
           claim_token = v_claim_token,
           claimed_at = p_now,
           lease_expires_at = p_now + interval '5 minutes',
           sent_at = NULL,
           provider_message_id = NULL,
           last_error = NULL,
           updated_at = p_now
     WHERE recipient_normalized = ANY(v_recipients);
    INSERT INTO public.global_email_guard_events(
        recipient_normalized, identity_sha256, event_type, claim_token, created_at
    )
    SELECT value, p_identity_sha256, 'claimed', v_claim_token, p_now
    FROM unnest(v_recipients) AS items(value);
    RETURN QUERY SELECT 'claimed'::text, v_claim_token, NULL::text;
END;
$$;
"""


FINALIZE_FUNCTION = r"""
CREATE OR REPLACE FUNCTION public.finalize_global_email_recipient_guard(
    p_recipients text[],
    p_identity_sha256 text,
    p_claim_token text,
    p_provider_message_id text,
    p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_recipients text[];
    v_valid integer;
BEGIN
    SELECT array_agg(DISTINCT lower(btrim(value)) ORDER BY lower(btrim(value)))
      INTO v_recipients FROM unnest(p_recipients) AS supplied(value);
    PERFORM recipient_normalized FROM public.global_email_recipient_guards
     WHERE recipient_normalized = ANY(v_recipients)
     ORDER BY recipient_normalized FOR UPDATE;
    SELECT count(*) INTO v_valid FROM public.global_email_recipient_guards
     WHERE recipient_normalized = ANY(v_recipients)
       AND identity_sha256 = p_identity_sha256
       AND claim_token = p_claim_token
       AND status IN ('claimed', 'accepted_unverified');
    IF v_valid <> cardinality(v_recipients) THEN RETURN false; END IF;
    UPDATE public.global_email_recipient_guards
       SET status = 'sent', sent_at = p_now, provider_message_id = p_provider_message_id,
           lease_expires_at = NULL, updated_at = p_now
     WHERE recipient_normalized = ANY(v_recipients);
    INSERT INTO public.global_email_guard_events(
        recipient_normalized, identity_sha256, event_type, claim_token,
        provider_message_id, created_at
    ) SELECT value, p_identity_sha256, 'sent', p_claim_token,
             p_provider_message_id, p_now
        FROM unnest(v_recipients) AS items(value);
    RETURN true;
END;
$$;
"""


FAIL_FUNCTION = r"""
CREATE OR REPLACE FUNCTION public.fail_global_email_recipient_guard(
    p_recipients text[],
    p_identity_sha256 text,
    p_claim_token text,
    p_status text,
    p_provider_message_id text,
    p_error text,
    p_now timestamptz
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_recipients text[];
    v_valid integer;
BEGIN
    IF p_status NOT IN ('accepted_unverified', 'failed_pre_send') THEN RETURN false; END IF;
    SELECT array_agg(DISTINCT lower(btrim(value)) ORDER BY lower(btrim(value)))
      INTO v_recipients FROM unnest(p_recipients) AS supplied(value);
    PERFORM recipient_normalized FROM public.global_email_recipient_guards
     WHERE recipient_normalized = ANY(v_recipients)
     ORDER BY recipient_normalized FOR UPDATE;
    SELECT count(*) INTO v_valid FROM public.global_email_recipient_guards
     WHERE recipient_normalized = ANY(v_recipients)
       AND identity_sha256 = p_identity_sha256 AND claim_token = p_claim_token;
    IF v_valid <> cardinality(v_recipients) THEN RETURN false; END IF;
    UPDATE public.global_email_recipient_guards
       SET status = p_status, provider_message_id = p_provider_message_id,
           last_error = left(p_error, 2000), lease_expires_at = NULL, updated_at = p_now
     WHERE recipient_normalized = ANY(v_recipients);
    INSERT INTO public.global_email_guard_events(
        recipient_normalized, identity_sha256, event_type, claim_token,
        provider_message_id, detail, created_at
    ) SELECT value, p_identity_sha256, p_status, p_claim_token,
             p_provider_message_id, left(p_error, 2000), p_now
        FROM unnest(v_recipients) AS items(value);
    RETURN true;
END;
$$;
"""


def upgrade() -> None:
    op.create_table(
        "global_email_recipient_guards",
        sa.Column("recipient_normalized", sa.String(320), primary_key=True),
        sa.Column("identity_sha256", sa.String(64)),
        sa.Column("message_type", sa.String(120)),
        sa.Column("tenant_scope", sa.String(120)),
        sa.Column("status", sa.String(32), nullable=False, server_default="idle"),
        sa.Column("claim_token", sa.String(120)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('idle','claimed','sending','sent','accepted_unverified','failed_pre_send')",
            name="ck_global_email_recipient_guard_status",
        ),
        sa.UniqueConstraint("claim_token", name="uq_global_email_recipient_guard_claim_token"),
    )
    for column in (
        "identity_sha256",
        "message_type",
        "tenant_scope",
        "status",
        "claimed_at",
        "sent_at",
    ):
        op.create_index(
            f"ix_global_email_recipient_guards_{column}", "global_email_recipient_guards", [column]
        )
    op.create_table(
        "global_email_guard_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("recipient_normalized", sa.String(320), nullable=False),
        sa.Column("identity_sha256", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("claim_token", sa.String(120)),
        sa.Column("provider_message_id", sa.String(500)),
        sa.Column("detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("recipient_normalized", "identity_sha256", "event_type", "claim_token"):
        op.create_index(
            f"ix_global_email_guard_events_{column}", "global_email_guard_events", [column]
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(CLAIM_FUNCTION)
        op.execute(FINALIZE_FUNCTION)
        op.execute(FAIL_FUNCTION)
        op.execute(
            "REVOKE ALL ON FUNCTION public.claim_global_email_recipient_guard(text[],text,text,text,timestamptz) FROM PUBLIC"
        )
        op.execute(
            "REVOKE ALL ON FUNCTION public.finalize_global_email_recipient_guard(text[],text,text,text,timestamptz) FROM PUBLIC"
        )
        op.execute(
            "REVOKE ALL ON FUNCTION public.fail_global_email_recipient_guard(text[],text,text,text,text,text,timestamptz) FROM PUBLIC"
        )
        op.execute(
            """
            DO $$ BEGIN
              IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etdr_lead_bridge') THEN
                GRANT EXECUTE ON FUNCTION public.claim_global_email_recipient_guard(text[],text,text,text,timestamptz) TO etdr_lead_bridge;
                GRANT EXECUTE ON FUNCTION public.finalize_global_email_recipient_guard(text[],text,text,text,timestamptz) TO etdr_lead_bridge;
                GRANT EXECUTE ON FUNCTION public.fail_global_email_recipient_guard(text[],text,text,text,text,text,timestamptz) TO etdr_lead_bridge;
              END IF;
            END $$
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP FUNCTION IF EXISTS public.fail_global_email_recipient_guard(text[],text,text,text,text,text,timestamptz)"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS public.finalize_global_email_recipient_guard(text[],text,text,text,timestamptz)"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS public.claim_global_email_recipient_guard(text[],text,text,text,timestamptz)"
        )
    op.drop_table("global_email_guard_events")
    op.drop_table("global_email_recipient_guards")
