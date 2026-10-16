-- Bootstrap for an empty database. Do not run over an existing leads table.
BEGIN;

CREATE TABLE public.leads (
    "id" bigint GENERATED ALWAYS AS IDENTITY NOT NULL,
    "created_at" timestamp with time zone DEFAULT now() NOT NULL,
    "name" text NOT NULL,
    "contact" text NOT NULL,
    "service" text NOT NULL,
    "budget" bigint,
    "message" text NOT NULL,
    "timeline" text,
    "lead_score" smallint,
    "intent" text,
    "urgency" text,
    "reason" text,
    "lead_status" text NOT NULL,
    "request_id" uuid,
    "telegram_status" text DEFAULT 'pending'::text NOT NULL,
    "telegram_error" text,
    "telegram_sent_at" timestamp with time zone,
    "processing_status" text DEFAULT 'completed'::text NOT NULL,
    "processing_attempts" integer DEFAULT 0 NOT NULL,
    "processing_token" bigint DEFAULT 0 NOT NULL,
    "processing_started_at" timestamp with time zone,
    "processing_lease_until" timestamp with time zone,
    "processing_next_at" timestamp with time zone DEFAULT now() NOT NULL,
    "processing_error" text,
    "processed_at" timestamp with time zone,
    "telegram_delivery_enabled" boolean DEFAULT false NOT NULL,
    "telegram_attempts" integer DEFAULT 0 NOT NULL,
    "telegram_token" bigint DEFAULT 0 NOT NULL,
    "telegram_lease_until" timestamp with time zone,
    "telegram_next_at" timestamp with time zone DEFAULT now() NOT NULL,
    "telegram_message_id" bigint,
    CONSTRAINT "leads_pkey" PRIMARY KEY (id),
    CONSTRAINT "leads_processing_attempts_v1" CHECK ((processing_attempts >= 0)),
    CONSTRAINT "leads_processing_state_v1" CHECK ((processing_status = ANY (ARRAY['queued'::text, 'processing'::text, 'retry'::text, 'completed'::text, 'needs_review'::text]))),
    CONSTRAINT "leads_request_id_key" UNIQUE (request_id),
    CONSTRAINT "leads_telegram_attempts_v1" CHECK ((telegram_attempts >= 0)),
    CONSTRAINT "leads_worker_tokens_v1" CHECK (((processing_token >= 0) AND (telegram_token >= 0)))
);

CREATE INDEX leads_ai_queue_v1 ON public.leads USING btree (processing_next_at, id) WHERE (processing_status = ANY (ARRAY['queued'::text, 'retry'::text, 'processing'::text]));
CREATE INDEX leads_tg_queue_v1 ON public.leads USING btree (telegram_next_at, id) WHERE (telegram_delivery_enabled AND (telegram_status = ANY (ARRAY['pending'::text, 'retry'::text, 'sending'::text])));

CREATE OR REPLACE FUNCTION public.enqueue_lead_v1(p jsonb)
 RETURNS TABLE(outcome text, out_request_id uuid)
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_id uuid := (p->>'request_id')::uuid;
    v_new uuid;
    v_old public.leads%ROWTYPE;
    v_payload jsonb;
BEGIN

    IF v_id IS NULL THEN
        RAISE EXCEPTION 'request_id required';
    END IF;

    INSERT INTO public.leads AS l (
        request_id,
        name,
        contact,
        service,
        budget,
        message,
        timeline,
        lead_score,
        intent,
        urgency,
        reason,
        lead_status,
        processing_status,
        telegram_status,
        telegram_delivery_enabled
    )
    VALUES (
        v_id,
        p->>'name',
        p->>'contact',
        p->>'service',
        (p->>'budget')::bigint,
        p->>'message',
        p->>'timeline',
        NULL,
        NULL,
        NULL,
        NULL,
        'pending',
        'queued',
        'pending',
        true
    )
    ON CONFLICT ON CONSTRAINT leads_request_id_key
    DO NOTHING
    RETURNING l.request_id INTO v_new;

    IF v_new IS NOT NULL THEN
        RETURN QUERY
        SELECT 'accepted'::text, v_id;
        RETURN;
    END IF;

    SELECT l.*
    INTO STRICT v_old
    FROM public.leads AS l
    WHERE l.request_id = v_id;

    v_payload := jsonb_build_object(
        'request_id', v_old.request_id,
        'name', v_old.name,
        'contact', v_old.contact,
        'service', v_old.service,
        'budget', v_old.budget,
        'message', v_old.message,
        'timeline', v_old.timeline
    );

    RETURN QUERY
    SELECT
        CASE
            WHEN v_payload = p THEN 'duplicate'
            ELSE 'conflict'
        END,
        v_id;

END;
$function$
;

-- Access is through the server-side database connection, not the public browser role.
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
REVOKE EXECUTE ON FUNCTION public.enqueue_lead_v1(jsonb) FROM PUBLIC;

COMMIT;
