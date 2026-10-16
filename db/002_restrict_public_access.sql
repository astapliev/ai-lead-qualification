-- Backend-only access. Apply after 001_init.sql or to the existing project table.
BEGIN;
ALTER TABLE public.leads ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.leads FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.enqueue_lead_v1(jsonb) FROM PUBLIC;
DO $$
DECLARE role_name text;
BEGIN
    FOR role_name IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')
    LOOP
        EXECUTE format('REVOKE ALL ON TABLE public.leads FROM %I', role_name);
        EXECUTE format('REVOKE EXECUTE ON FUNCTION public.enqueue_lead_v1(jsonb) FROM %I', role_name);
    END LOOP;
END $$;
COMMIT;
