-- The schema of the pension and GP Fund database, as the live PostgreSQL 16 holds it.
--
-- GENERATED, not edited. The migrations in api/migrations/ are the source of truth; this is a
-- reading copy, because the audit of 13 Oct 2026 had to grep every migration to answer "is this
-- column indexed?" (H-08, M-07). Up to date with migration 0017.
--
-- Regenerate after a migration:
--   docker exec -e PGPASSWORD=... pension-postgres \
--     pg_dump -U pension -d pension --schema-only --no-owner --no-privileges --no-comments \
--     | grep -v '^.restrict ' > docs/SCHEMA.sql
-- (the \restrict guards carry a fresh random token on every dump and are dropped so the file
-- is stable between regenerations; re-add this header afterwards.)
--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: refuse_change(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.refuse_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    RAISE EXCEPTION '%', TG_ARGV[0] USING ERRCODE = 'integrity_constraint_violation';
END $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id text NOT NULL,
    at text NOT NULL,
    actor_id text,
    actor_name text,
    actor_role text,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    before_json text,
    after_json text,
    reason text DEFAULT ''::text NOT NULL,
    ip text
);


--
-- Name: case_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_documents (
    id text NOT NULL,
    case_id text NOT NULL,
    submission_no integer NOT NULL,
    seq integer NOT NULL,
    filename text NOT NULL,
    sha256 text NOT NULL,
    bytes bigint NOT NULL,
    stored_path text NOT NULL,
    uploaded_by text NOT NULL,
    uploaded_at text NOT NULL,
    replaces_document_id text,
    superseded_in_submission integer
);


--
-- Name: case_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_events (
    id text NOT NULL,
    case_id text NOT NULL,
    seq integer NOT NULL,
    action text NOT NULL,
    from_status text,
    to_status text NOT NULL,
    actor_id text,
    actor_name text,
    actor_role text,
    actor_department text,
    remark text DEFAULT ''::text NOT NULL,
    payload_json text DEFAULT '{}'::text NOT NULL,
    run_id text,
    at text NOT NULL
);


--
-- Name: case_round_checks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_round_checks (
    id text NOT NULL,
    case_id text NOT NULL,
    submission_no integer NOT NULL,
    run_id text NOT NULL,
    mode text NOT NULL,
    base_run_id text,
    base_submission_no integer,
    started_by text,
    started_at text NOT NULL,
    finished_at text,
    state text NOT NULL,
    duration_s double precision,
    documents_json text DEFAULT '[]'::text NOT NULL,
    steps_json text DEFAULT '{}'::text NOT NULL,
    findings_json text DEFAULT '[]'::text NOT NULL,
    resolution_json text DEFAULT '[]'::text NOT NULL,
    changes_json text DEFAULT '{}'::text NOT NULL,
    carried_json text DEFAULT '{}'::text NOT NULL,
    issues_json text DEFAULT '{}'::text NOT NULL,
    error text
);


--
-- Name: case_round_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_round_requests (
    id text NOT NULL,
    case_id text NOT NULL,
    from_submission_no integer NOT NULL,
    for_submission_no integer NOT NULL,
    event_id text,
    action text NOT NULL,
    items_json text DEFAULT '[]'::text NOT NULL,
    remark text DEFAULT ''::text NOT NULL,
    requested_by text,
    requested_by_name text,
    run_id text,
    at text NOT NULL
);


--
-- Name: case_rounds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_rounds (
    id text NOT NULL,
    case_id text NOT NULL,
    submission_no integer NOT NULL,
    opened_at text NOT NULL,
    opened_by text,
    opened_via text NOT NULL,
    submitted_at text,
    submitted_by text,
    closed_at text,
    closed_action text
);


--
-- Name: case_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.case_runs (
    id text NOT NULL,
    case_id text NOT NULL,
    run_id text NOT NULL,
    submission_no integer NOT NULL,
    started_by text NOT NULL,
    started_at text NOT NULL,
    finished_at text,
    state text NOT NULL,
    verdict text,
    high_flags integer,
    blocking_flags_json text,
    checklist_result text,
    error text,
    auto_forward integer DEFAULT 0 NOT NULL,
    docs_sha text,
    mode text DEFAULT 'FULL'::text NOT NULL,
    base_run_id text
);


--
-- Name: cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cases (
    id text NOT NULL,
    case_no text NOT NULL,
    department_code text NOT NULL,
    created_via text NOT NULL,
    created_by text NOT NULL,
    status text NOT NULL,
    claimant_name text,
    variant text,
    intake_json text DEFAULT '{}'::text NOT NULL,
    submission_no integer DEFAULT 1 NOT NULL,
    current_run_id text,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    product text DEFAULT 'PENSION'::text NOT NULL,
    gpf_case_id text,
    case_type text,
    case_type_source text,
    detected_case_type text,
    detected_case_type_confidence double precision,
    holder_tier text,
    reached_tier text,
    CONSTRAINT cases_created_via_check CHECK ((created_via = ANY (ARRAY['DEPARTMENT'::text, 'AG_UPLOAD'::text]))),
    CONSTRAINT cases_status_check CHECK ((status = ANY (ARRAY['DRAFT'::text, 'AI_CHECKING'::text, 'AI_FAILED'::text, 'AI_CHECKED'::text, 'FORWARDED'::text, 'UNDER_REVIEW'::text, 'APPROVED'::text, 'REJECTED'::text, 'RETURNED'::text, 'DOCS_REQUESTED'::text])))
);


--
-- Name: departments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.departments (
    code text NOT NULL,
    name text NOT NULL,
    digital integer DEFAULT 0 NOT NULL,
    active integer DEFAULT 1 NOT NULL,
    slug text,
    is_police integer DEFAULT 0 NOT NULL,
    theme text,
    port integer,
    pension_section text
);


--
-- Name: gpf_cases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gpf_cases (
    id text NOT NULL,
    kind text NOT NULL,
    officer_id text,
    officer_name text,
    version integer DEFAULT 1 NOT NULL,
    returns integer DEFAULT 0 NOT NULL,
    issued integer DEFAULT 0 NOT NULL,
    case_disp text,
    from_scans integer DEFAULT 0 NOT NULL,
    state_json text NOT NULL,
    created_at text NOT NULL,
    updated_at text NOT NULL
);


--
-- Name: gpf_documents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gpf_documents (
    id text NOT NULL,
    case_id text NOT NULL,
    name text NOT NULL,
    stored_as text NOT NULL,
    sha256 text NOT NULL,
    bytes integer NOT NULL,
    content_type text NOT NULL,
    saved_at text NOT NULL
);


--
-- Name: idempotency_keys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.idempotency_keys (
    user_id text NOT NULL,
    key text NOT NULL,
    created_at text NOT NULL,
    status_code integer NOT NULL,
    response_json text NOT NULL
);


--
-- Name: login_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.login_attempts (
    username text NOT NULL,
    failures integer DEFAULT 0 NOT NULL,
    locked_until text,
    updated_at text NOT NULL
);


--
-- Name: revoked_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.revoked_tokens (
    jti text NOT NULL,
    user_id text NOT NULL,
    expires_at text NOT NULL,
    revoked_at text NOT NULL
);


--
-- Name: run_timings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.run_timings (
    id bigint NOT NULL,
    run_id text NOT NULL,
    kind text NOT NULL,
    stage text NOT NULL,
    name text,
    page integer,
    started_at text NOT NULL,
    ended_at text NOT NULL,
    duration_s double precision NOT NULL,
    queue_s double precision,
    pages integer,
    status text DEFAULT 'ok'::text NOT NULL,
    detail_json text
);


--
-- Name: run_timings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.run_timings ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.run_timings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    applied_at text NOT NULL
);


--
-- Name: signatory_specimens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signatory_specimens (
    id text NOT NULL,
    authority_id text NOT NULL,
    stored_path text NOT NULL,
    sha256 text,
    bytes integer,
    uploaded_by text,
    uploaded_at text NOT NULL,
    note text
);


--
-- Name: signing_authorities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signing_authorities (
    id text NOT NULL,
    product_scope text DEFAULT 'BOTH'::text NOT NULL,
    department_code text,
    department_name text NOT NULL,
    department_aliases_json text DEFAULT '[]'::text NOT NULL,
    post text NOT NULL,
    post_aliases_json text DEFAULT '[]'::text NOT NULL,
    officer_name text,
    scope text,
    effective_from text NOT NULL,
    effective_to text,
    letter_no text,
    letter_date text,
    letter_path text,
    provisional integer DEFAULT 0 NOT NULL,
    source text NOT NULL,
    gpf_authority_id text,
    gpf_signatory_id text,
    may_sign_for integer DEFAULT 0 NOT NULL,
    stamp_text text,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    closed_at text,
    closed_by text
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id text NOT NULL,
    username text NOT NULL,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role text NOT NULL,
    department_code text,
    active integer DEFAULT 1 NOT NULL,
    token_version integer DEFAULT 1 NOT NULL,
    created_at text NOT NULL,
    updated_at text NOT NULL,
    must_change_password integer DEFAULT 0 NOT NULL,
    pension_wing text,
    CONSTRAINT users_role_check CHECK ((role = ANY (ARRAY['DEPT_OFFICER'::text, 'AG_UPLOAD'::text, 'AG_REVIEWER'::text, 'AG_DAG'::text, 'ADMIN'::text, 'AG_SENIOR_AUDITOR'::text, 'AG_ASSISTANT_AO'::text, 'AG_AO'::text])))
);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: case_documents case_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_documents
    ADD CONSTRAINT case_documents_pkey PRIMARY KEY (id);


--
-- Name: case_events case_events_case_id_seq_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_events
    ADD CONSTRAINT case_events_case_id_seq_key UNIQUE (case_id, seq);


--
-- Name: case_events case_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_events
    ADD CONSTRAINT case_events_pkey PRIMARY KEY (id);


--
-- Name: case_round_checks case_round_checks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_round_checks
    ADD CONSTRAINT case_round_checks_pkey PRIMARY KEY (id);


--
-- Name: case_round_requests case_round_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_round_requests
    ADD CONSTRAINT case_round_requests_pkey PRIMARY KEY (id);


--
-- Name: case_rounds case_rounds_case_id_submission_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_rounds
    ADD CONSTRAINT case_rounds_case_id_submission_no_key UNIQUE (case_id, submission_no);


--
-- Name: case_rounds case_rounds_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_rounds
    ADD CONSTRAINT case_rounds_pkey PRIMARY KEY (id);


--
-- Name: case_runs case_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_runs
    ADD CONSTRAINT case_runs_pkey PRIMARY KEY (id);


--
-- Name: cases cases_case_no_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_case_no_key UNIQUE (case_no);


--
-- Name: cases cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_pkey PRIMARY KEY (id);


--
-- Name: departments departments_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.departments
    ADD CONSTRAINT departments_pkey PRIMARY KEY (code);


--
-- Name: gpf_cases gpf_cases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpf_cases
    ADD CONSTRAINT gpf_cases_pkey PRIMARY KEY (id);


--
-- Name: gpf_documents gpf_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gpf_documents
    ADD CONSTRAINT gpf_documents_pkey PRIMARY KEY (id);


--
-- Name: idempotency_keys idempotency_keys_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.idempotency_keys
    ADD CONSTRAINT idempotency_keys_pkey PRIMARY KEY (user_id, key);


--
-- Name: login_attempts login_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.login_attempts
    ADD CONSTRAINT login_attempts_pkey PRIMARY KEY (username);


--
-- Name: revoked_tokens revoked_tokens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.revoked_tokens
    ADD CONSTRAINT revoked_tokens_pkey PRIMARY KEY (jti);


--
-- Name: run_timings run_timings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.run_timings
    ADD CONSTRAINT run_timings_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: signatory_specimens signatory_specimens_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signatory_specimens
    ADD CONSTRAINT signatory_specimens_pkey PRIMARY KEY (id);


--
-- Name: signing_authorities signing_authorities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signing_authorities
    ADD CONSTRAINT signing_authorities_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: audit_log_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_log_at ON public.audit_log USING btree (at);


--
-- Name: audit_log_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_log_entity ON public.audit_log USING btree (entity_id, action);


--
-- Name: case_documents_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_documents_case ON public.case_documents USING btree (case_id, submission_no, seq);


--
-- Name: case_documents_seq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX case_documents_seq ON public.case_documents USING btree (case_id, submission_no, seq);


--
-- Name: case_round_checks_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_round_checks_case ON public.case_round_checks USING btree (case_id, submission_no, started_at);


--
-- Name: case_round_checks_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_round_checks_run ON public.case_round_checks USING btree (run_id);


--
-- Name: case_round_requests_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_round_requests_case ON public.case_round_requests USING btree (case_id, for_submission_no);


--
-- Name: case_rounds_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_rounds_case ON public.case_rounds USING btree (case_id, submission_no);


--
-- Name: case_runs_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_runs_case ON public.case_runs USING btree (case_id, started_at);


--
-- Name: case_runs_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_runs_run ON public.case_runs USING btree (run_id);


--
-- Name: case_runs_state; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX case_runs_state ON public.case_runs USING btree (state);


--
-- Name: cases_case_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cases_case_type ON public.cases USING btree (product, case_type);


--
-- Name: cases_created_via; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cases_created_via ON public.cases USING btree (created_via);


--
-- Name: cases_department_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cases_department_status ON public.cases USING btree (department_code, status);


--
-- Name: cases_holder; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cases_holder ON public.cases USING btree (status, holder_tier);


--
-- Name: cases_product; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX cases_product ON public.cases USING btree (product, status);


--
-- Name: gpf_cases_disp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gpf_cases_disp ON public.gpf_cases USING btree (case_disp);


--
-- Name: gpf_cases_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gpf_cases_kind ON public.gpf_cases USING btree (kind, updated_at);


--
-- Name: gpf_documents_case; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX gpf_documents_case ON public.gpf_documents USING btree (case_id, saved_at);


--
-- Name: idempotency_keys_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idempotency_keys_created ON public.idempotency_keys USING btree (created_at);


--
-- Name: revoked_tokens_expiry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX revoked_tokens_expiry ON public.revoked_tokens USING btree (expires_at);


--
-- Name: run_timings_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX run_timings_run ON public.run_timings USING btree (run_id, started_at);


--
-- Name: signatory_specimens_authority; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signatory_specimens_authority ON public.signatory_specimens USING btree (authority_id, uploaded_at);


--
-- Name: signing_authorities_dept; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signing_authorities_dept ON public.signing_authorities USING btree (department_code, post);


--
-- Name: signing_authorities_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signing_authorities_scope ON public.signing_authorities USING btree (product_scope, effective_from);


--
-- Name: audit_log audit_log_no_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON public.audit_log FOR EACH ROW EXECUTE FUNCTION public.refuse_change('audit_log is append-only');

ALTER TABLE public.audit_log ENABLE ALWAYS TRIGGER audit_log_no_delete;


--
-- Name: audit_log audit_log_no_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON public.audit_log FOR EACH ROW EXECUTE FUNCTION public.refuse_change('audit_log is append-only');

ALTER TABLE public.audit_log ENABLE ALWAYS TRIGGER audit_log_no_update;


--
-- Name: case_events case_events_no_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_events_no_delete BEFORE DELETE ON public.case_events FOR EACH ROW EXECUTE FUNCTION public.refuse_change('case_events is append-only');

ALTER TABLE public.case_events ENABLE ALWAYS TRIGGER case_events_no_delete;


--
-- Name: case_events case_events_no_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_events_no_update BEFORE UPDATE ON public.case_events FOR EACH ROW EXECUTE FUNCTION public.refuse_change('case_events is append-only');

ALTER TABLE public.case_events ENABLE ALWAYS TRIGGER case_events_no_update;


--
-- Name: case_round_checks case_round_checks_finished_is_final; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_round_checks_finished_is_final BEFORE UPDATE ON public.case_round_checks FOR EACH ROW WHEN ((old.finished_at IS NOT NULL)) EXECUTE FUNCTION public.refuse_change('a finished verification record is final');

ALTER TABLE public.case_round_checks ENABLE ALWAYS TRIGGER case_round_checks_finished_is_final;


--
-- Name: case_round_checks case_round_checks_no_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_round_checks_no_delete BEFORE DELETE ON public.case_round_checks FOR EACH ROW EXECUTE FUNCTION public.refuse_change('case_round_checks rows are never deleted');

ALTER TABLE public.case_round_checks ENABLE ALWAYS TRIGGER case_round_checks_no_delete;


--
-- Name: case_round_requests case_round_requests_no_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_round_requests_no_delete BEFORE DELETE ON public.case_round_requests FOR EACH ROW EXECUTE FUNCTION public.refuse_change('case_round_requests is append-only');

ALTER TABLE public.case_round_requests ENABLE ALWAYS TRIGGER case_round_requests_no_delete;


--
-- Name: case_round_requests case_round_requests_no_update; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_round_requests_no_update BEFORE UPDATE ON public.case_round_requests FOR EACH ROW EXECUTE FUNCTION public.refuse_change('case_round_requests is append-only');

ALTER TABLE public.case_round_requests ENABLE ALWAYS TRIGGER case_round_requests_no_update;


--
-- Name: case_rounds case_rounds_closed_is_final; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_rounds_closed_is_final BEFORE UPDATE ON public.case_rounds FOR EACH ROW WHEN ((old.closed_at IS NOT NULL)) EXECUTE FUNCTION public.refuse_change('a closed submission round is final');

ALTER TABLE public.case_rounds ENABLE ALWAYS TRIGGER case_rounds_closed_is_final;


--
-- Name: case_rounds case_rounds_no_delete; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER case_rounds_no_delete BEFORE DELETE ON public.case_rounds FOR EACH ROW EXECUTE FUNCTION public.refuse_change('case_rounds rows are never deleted');

ALTER TABLE public.case_rounds ENABLE ALWAYS TRIGGER case_rounds_no_delete;


--
-- Name: case_documents case_documents_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_documents
    ADD CONSTRAINT case_documents_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id);


--
-- Name: case_documents case_documents_uploaded_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_documents
    ADD CONSTRAINT case_documents_uploaded_by_fkey FOREIGN KEY (uploaded_by) REFERENCES public.users(id);


--
-- Name: case_events case_events_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_events
    ADD CONSTRAINT case_events_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id);


--
-- Name: case_round_checks case_round_checks_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_round_checks
    ADD CONSTRAINT case_round_checks_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id);


--
-- Name: case_round_requests case_round_requests_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_round_requests
    ADD CONSTRAINT case_round_requests_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id);


--
-- Name: case_rounds case_rounds_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_rounds
    ADD CONSTRAINT case_rounds_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id);


--
-- Name: case_runs case_runs_case_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_runs
    ADD CONSTRAINT case_runs_case_id_fkey FOREIGN KEY (case_id) REFERENCES public.cases(id);


--
-- Name: case_runs case_runs_started_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.case_runs
    ADD CONSTRAINT case_runs_started_by_fkey FOREIGN KEY (started_by) REFERENCES public.users(id);


--
-- Name: cases cases_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: cases cases_department_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cases
    ADD CONSTRAINT cases_department_code_fkey FOREIGN KEY (department_code) REFERENCES public.departments(code);


--
-- Name: signatory_specimens signatory_specimens_authority_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signatory_specimens
    ADD CONSTRAINT signatory_specimens_authority_id_fkey FOREIGN KEY (authority_id) REFERENCES public.signing_authorities(id);


--
-- Name: users users_department_code_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_department_code_fkey FOREIGN KEY (department_code) REFERENCES public.departments(code);


--
-- PostgreSQL database dump complete
--

