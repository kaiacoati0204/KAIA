--
-- PostgreSQL database dump
--


-- Dumped from database version 17.6
-- Dumped by pg_dump version 17.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA public;


--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA public IS 'standard public schema';


--
-- Name: criar_perfil_no_signup(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.criar_perfil_no_signup() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
begin
  insert into public.perfis (
    user_id, email, nome, role,
    termos_versao, termos_aceite_ts, updated_at
  )
  values (
    new.id,
    new.email,
    nullif(new.raw_user_meta_data->>'nome', ''),
    'aluno',
    nullif(new.raw_user_meta_data->>'termos_versao', ''),
    case when nullif(new.raw_user_meta_data->>'termos_versao', '') is not null
         then now() else null end,
    now()
  )
  on conflict (user_id) do nothing;
  return new;
end; $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: anotacoes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.anotacoes (
    aluno_id text NOT NULL,
    tema text NOT NULL,
    elementos jsonb DEFAULT '[]'::jsonb NOT NULL,
    atualizado timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: coordenadores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.coordenadores (
    coordenador_id uuid DEFAULT gen_random_uuid() NOT NULL,
    escola_id uuid NOT NULL,
    nome character varying NOT NULL,
    email character varying
);


--
-- Name: desempenho_semanal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.desempenho_semanal (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    aluno_id uuid NOT NULL,
    turma_id uuid NOT NULL,
    escola_id uuid NOT NULL,
    semana integer NOT NULL,
    materia character varying NOT NULL,
    media_atencao double precision NOT NULL,
    taxa_acerto double precision NOT NULL,
    minutos_estudados integer NOT NULL,
    CONSTRAINT desempenho_semanal_media_atencao_check CHECK (((media_atencao >= (0)::double precision) AND (media_atencao <= (1)::double precision))),
    CONSTRAINT desempenho_semanal_minutos_estudados_check CHECK ((minutos_estudados >= 0)),
    CONSTRAINT desempenho_semanal_semana_check CHECK (((semana >= 1) AND (semana <= 8))),
    CONSTRAINT desempenho_semanal_taxa_acerto_check CHECK (((taxa_acerto >= (0)::double precision) AND (taxa_acerto <= (1)::double precision)))
);


--
-- Name: escolas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.escolas (
    escola_id uuid DEFAULT gen_random_uuid() NOT NULL,
    nome character varying NOT NULL,
    cidade character varying NOT NULL
);


--
-- Name: interventions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.interventions (
    intervention_id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    intervention_type character varying NOT NULL,
    triggered_at timestamp with time zone NOT NULL,
    reward double precision,
    tempo_ate_aceitar_s double precision,
    feedback_usuario character varying,
    estado_antes text,
    estado_depois text,
    reward_origem text
);


--
-- Name: pai_aluno; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pai_aluno (
    pai_id uuid NOT NULL,
    aluno_id uuid NOT NULL
);


--
-- Name: perfis; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.perfis (
    user_id uuid NOT NULL,
    email text,
    hobbies jsonb DEFAULT '[]'::jsonb NOT NULL,
    data_prova date,
    ambiente_dispositivo text,
    sequencia_dias_estudo integer DEFAULT 0 NOT NULL,
    sessoes_no_dia integer DEFAULT 0 NOT NULL,
    ultimo_dia_estudo date,
    ultima_sessao_ts timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    nome character varying,
    turma_id uuid,
    escola_id uuid,
    role character varying DEFAULT 'aluno'::character varying,
    termos_aceite_ts timestamp with time zone,
    termos_versao text,
    CONSTRAINT perfis_role_check CHECK (((role)::text = ANY ((ARRAY['aluno'::character varying, 'professor'::character varying, 'coordenador'::character varying, 'pai'::character varying, 'admin'::character varying])::text[])))
);


--
-- Name: probe_labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.probe_labels (
    id bigint NOT NULL,
    session_id uuid NOT NULL,
    user_id uuid,
    estado text NOT NULL,
    features jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT probe_labels_estado_check CHECK ((estado = ANY (ARRAY['engajado'::text, 'distraido'::text, 'muito_distraido'::text])))
);


--
-- Name: probe_labels_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.probe_labels_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: probe_labels_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.probe_labels_id_seq OWNED BY public.probe_labels.id;


--
-- Name: professores; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.professores (
    professor_id uuid DEFAULT gen_random_uuid() NOT NULL,
    escola_id uuid NOT NULL,
    nome character varying NOT NULL,
    materia character varying NOT NULL,
    email character varying,
    CONSTRAINT professores_materia_check CHECK (((materia)::text = ANY ((ARRAY['Matemática'::character varying, 'Português'::character varying, 'História'::character varying, 'Geografia'::character varying, 'Biologia'::character varying, 'Física'::character varying])::text[])))
);


--
-- Name: questoes_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.questoes_cache (
    questao_id uuid DEFAULT gen_random_uuid() NOT NULL,
    materia character varying NOT NULL,
    tema character varying NOT NULL,
    nivel integer NOT NULL,
    hobbie character varying,
    enunciado text NOT NULL,
    alternativas jsonb NOT NULL,
    resposta_correta integer NOT NULL,
    explicacao text NOT NULL,
    porque_erradas jsonb NOT NULL,
    criada_em timestamp with time zone DEFAULT now(),
    CONSTRAINT questoes_cache_nivel_check CHECK (((nivel >= 1) AND (nivel <= 5))),
    CONSTRAINT questoes_cache_resposta_correta_check CHECK (((resposta_correta >= 0) AND (resposta_correta <= 4)))
);


--
-- Name: questoes_vistas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.questoes_vistas (
    aluno_id uuid NOT NULL,
    questao_id uuid NOT NULL,
    visto_em timestamp with time zone DEFAULT now()
);


--
-- Name: resumo_turma_semanal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.resumo_turma_semanal (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    turma_id uuid NOT NULL,
    escola_id uuid NOT NULL,
    semana integer NOT NULL,
    materia character varying NOT NULL,
    media_atencao_turma double precision NOT NULL,
    media_taxa_acerto_turma double precision NOT NULL,
    alunos_abaixo_media integer NOT NULL,
    alunos_em_risco integer NOT NULL,
    CONSTRAINT resumo_turma_semanal_alunos_abaixo_media_check CHECK ((alunos_abaixo_media >= 0)),
    CONSTRAINT resumo_turma_semanal_alunos_em_risco_check CHECK ((alunos_em_risco >= 0)),
    CONSTRAINT resumo_turma_semanal_media_atencao_turma_check CHECK (((media_atencao_turma >= (0)::double precision) AND (media_atencao_turma <= (1)::double precision))),
    CONSTRAINT resumo_turma_semanal_media_taxa_acerto_turma_check CHECK (((media_taxa_acerto_turma >= (0)::double precision) AND (media_taxa_acerto_turma <= (1)::double precision))),
    CONSTRAINT resumo_turma_semanal_semana_check CHECK (((semana >= 1) AND (semana <= 8)))
);


--
-- Name: session_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_events (
    event_id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    event_type character varying NOT NULL,
    payload jsonb NOT NULL,
    ts timestamp with time zone NOT NULL
);


--
-- Name: session_features; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.session_features (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    horario_inicio time without time zone NOT NULL,
    sessoes_no_dia integer NOT NULL,
    tempo_resposta_ms double precision NOT NULL,
    velocidade_scroll_px_s double precision NOT NULL,
    pausas_digitacao_s double precision NOT NULL,
    cliques_fora_area_estudo integer NOT NULL,
    mudancas_aba integer NOT NULL,
    tempo_fora_foco_s double precision NOT NULL,
    acertos_questoes integer NOT NULL,
    nivel_dificuldade_atividade integer NOT NULL,
    window_ts timestamp with time zone NOT NULL,
    CONSTRAINT session_features_nivel_dificuldade_atividade_check CHECK (((nivel_dificuldade_atividade >= 1) AND (nivel_dificuldade_atividade <= 5)))
);


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    session_id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    session_start_ts timestamp with time zone NOT NULL,
    session_end_ts timestamp with time zone,
    platform text NOT NULL,
    app_version text NOT NULL
);


--
-- Name: temas_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.temas_cache (
    materia text NOT NULL,
    temas jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: turmas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.turmas (
    turma_id uuid DEFAULT gen_random_uuid() NOT NULL,
    escola_id uuid NOT NULL,
    ano integer NOT NULL,
    turno character varying NOT NULL,
    CONSTRAINT turmas_ano_check CHECK ((ano = ANY (ARRAY[1, 2, 3]))),
    CONSTRAINT turmas_turno_check CHECK (((turno)::text = ANY ((ARRAY['manhã'::character varying, 'tarde'::character varying, 'noite'::character varying])::text[])))
);


--
-- Name: user_profiles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_profiles (
    user_id uuid NOT NULL,
    media_duracao_sessao_min double precision,
    horario_pico_foco time without time zone,
    tipo_intervencao_preferida character varying,
    indice_consistencia double precision,
    fadiga_acumulada_score double precision,
    nivel_global_engajamento double precision,
    curva_aprendizado_topico jsonb,
    last_updated timestamp with time zone
);


--
-- Name: probe_labels id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.probe_labels ALTER COLUMN id SET DEFAULT nextval('public.probe_labels_id_seq'::regclass);


--
-- Name: anotacoes anotacoes_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.anotacoes
    ADD CONSTRAINT anotacoes_pkey PRIMARY KEY (aluno_id, tema);


--
-- Name: coordenadores coordenadores_escola_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coordenadores
    ADD CONSTRAINT coordenadores_escola_id_key UNIQUE (escola_id);


--
-- Name: coordenadores coordenadores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coordenadores
    ADD CONSTRAINT coordenadores_pkey PRIMARY KEY (coordenador_id);


--
-- Name: desempenho_semanal desempenho_semanal_aluno_id_semana_materia_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.desempenho_semanal
    ADD CONSTRAINT desempenho_semanal_aluno_id_semana_materia_key UNIQUE (aluno_id, semana, materia);


--
-- Name: desempenho_semanal desempenho_semanal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.desempenho_semanal
    ADD CONSTRAINT desempenho_semanal_pkey PRIMARY KEY (id);


--
-- Name: escolas escolas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.escolas
    ADD CONSTRAINT escolas_pkey PRIMARY KEY (escola_id);


--
-- Name: interventions interventions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.interventions
    ADD CONSTRAINT interventions_pkey PRIMARY KEY (intervention_id);


--
-- Name: pai_aluno pai_aluno_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pai_aluno
    ADD CONSTRAINT pai_aluno_pkey PRIMARY KEY (pai_id, aluno_id);


--
-- Name: perfis perfis_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perfis
    ADD CONSTRAINT perfis_pkey PRIMARY KEY (user_id);


--
-- Name: probe_labels probe_labels_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.probe_labels
    ADD CONSTRAINT probe_labels_pkey PRIMARY KEY (id);


--
-- Name: professores professores_escola_id_materia_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.professores
    ADD CONSTRAINT professores_escola_id_materia_key UNIQUE (escola_id, materia);


--
-- Name: professores professores_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.professores
    ADD CONSTRAINT professores_pkey PRIMARY KEY (professor_id);


--
-- Name: questoes_cache questoes_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questoes_cache
    ADD CONSTRAINT questoes_cache_pkey PRIMARY KEY (questao_id);


--
-- Name: questoes_vistas questoes_vistas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questoes_vistas
    ADD CONSTRAINT questoes_vistas_pkey PRIMARY KEY (aluno_id, questao_id);


--
-- Name: resumo_turma_semanal resumo_turma_semanal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resumo_turma_semanal
    ADD CONSTRAINT resumo_turma_semanal_pkey PRIMARY KEY (id);


--
-- Name: resumo_turma_semanal resumo_turma_semanal_turma_id_semana_materia_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resumo_turma_semanal
    ADD CONSTRAINT resumo_turma_semanal_turma_id_semana_materia_key UNIQUE (turma_id, semana, materia);


--
-- Name: session_events session_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_events
    ADD CONSTRAINT session_events_pkey PRIMARY KEY (event_id);


--
-- Name: session_features session_features_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_features
    ADD CONSTRAINT session_features_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (session_id);


--
-- Name: temas_cache temas_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.temas_cache
    ADD CONSTRAINT temas_cache_pkey PRIMARY KEY (materia);


--
-- Name: turmas turmas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.turmas
    ADD CONSTRAINT turmas_pkey PRIMARY KEY (turma_id);


--
-- Name: user_profiles user_profiles_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_pkey PRIMARY KEY (user_id);


--
-- Name: idx_probe_labels_criado; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_probe_labels_criado ON public.probe_labels USING btree (created_at);


--
-- Name: idx_probe_labels_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_probe_labels_user ON public.probe_labels USING btree (user_id);


--
-- Name: ix_cache_busca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cache_busca ON public.questoes_cache USING btree (materia, tema, nivel, hobbie);


--
-- Name: ix_desemp_aluno; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_desemp_aluno ON public.desempenho_semanal USING btree (aluno_id, semana);


--
-- Name: ix_desemp_turma; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_desemp_turma ON public.desempenho_semanal USING btree (turma_id, semana);


--
-- Name: ix_perfis_turma; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_perfis_turma ON public.perfis USING btree (turma_id);


--
-- Name: ix_resumo_turma; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_resumo_turma ON public.resumo_turma_semanal USING btree (turma_id, semana);


--
-- Name: ix_vistas_aluno; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vistas_aluno ON public.questoes_vistas USING btree (aluno_id);


--
-- Name: coordenadores coordenadores_escola_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.coordenadores
    ADD CONSTRAINT coordenadores_escola_id_fkey FOREIGN KEY (escola_id) REFERENCES public.escolas(escola_id) ON DELETE CASCADE;


--
-- Name: desempenho_semanal desempenho_semanal_aluno_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.desempenho_semanal
    ADD CONSTRAINT desempenho_semanal_aluno_id_fkey FOREIGN KEY (aluno_id) REFERENCES public.perfis(user_id) ON DELETE CASCADE;


--
-- Name: desempenho_semanal desempenho_semanal_escola_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.desempenho_semanal
    ADD CONSTRAINT desempenho_semanal_escola_id_fkey FOREIGN KEY (escola_id) REFERENCES public.escolas(escola_id) ON DELETE CASCADE;


--
-- Name: desempenho_semanal desempenho_semanal_turma_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.desempenho_semanal
    ADD CONSTRAINT desempenho_semanal_turma_id_fkey FOREIGN KEY (turma_id) REFERENCES public.turmas(turma_id) ON DELETE CASCADE;


--
-- Name: interventions interventions_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.interventions
    ADD CONSTRAINT interventions_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(session_id);


--
-- Name: pai_aluno pai_aluno_aluno_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pai_aluno
    ADD CONSTRAINT pai_aluno_aluno_id_fkey FOREIGN KEY (aluno_id) REFERENCES public.perfis(user_id) ON DELETE CASCADE;


--
-- Name: pai_aluno pai_aluno_pai_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pai_aluno
    ADD CONSTRAINT pai_aluno_pai_id_fkey FOREIGN KEY (pai_id) REFERENCES public.perfis(user_id) ON DELETE CASCADE;


--
-- Name: perfis perfis_escola_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perfis
    ADD CONSTRAINT perfis_escola_id_fkey FOREIGN KEY (escola_id) REFERENCES public.escolas(escola_id) ON DELETE SET NULL;


--
-- Name: perfis perfis_turma_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.perfis
    ADD CONSTRAINT perfis_turma_id_fkey FOREIGN KEY (turma_id) REFERENCES public.turmas(turma_id) ON DELETE SET NULL;


--
-- Name: professores professores_escola_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.professores
    ADD CONSTRAINT professores_escola_id_fkey FOREIGN KEY (escola_id) REFERENCES public.escolas(escola_id) ON DELETE CASCADE;


--
-- Name: questoes_vistas questoes_vistas_aluno_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questoes_vistas
    ADD CONSTRAINT questoes_vistas_aluno_id_fkey FOREIGN KEY (aluno_id) REFERENCES public.perfis(user_id) ON DELETE CASCADE;


--
-- Name: questoes_vistas questoes_vistas_questao_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.questoes_vistas
    ADD CONSTRAINT questoes_vistas_questao_id_fkey FOREIGN KEY (questao_id) REFERENCES public.questoes_cache(questao_id) ON DELETE CASCADE;


--
-- Name: resumo_turma_semanal resumo_turma_semanal_escola_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resumo_turma_semanal
    ADD CONSTRAINT resumo_turma_semanal_escola_id_fkey FOREIGN KEY (escola_id) REFERENCES public.escolas(escola_id) ON DELETE CASCADE;


--
-- Name: resumo_turma_semanal resumo_turma_semanal_turma_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.resumo_turma_semanal
    ADD CONSTRAINT resumo_turma_semanal_turma_id_fkey FOREIGN KEY (turma_id) REFERENCES public.turmas(turma_id) ON DELETE CASCADE;


--
-- Name: session_events session_events_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_events
    ADD CONSTRAINT session_events_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(session_id);


--
-- Name: session_features session_features_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.session_features
    ADD CONSTRAINT session_features_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(session_id);


--
-- Name: sessions sessions_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.perfis(user_id);


--
-- Name: turmas turmas_escola_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.turmas
    ADD CONSTRAINT turmas_escola_id_fkey FOREIGN KEY (escola_id) REFERENCES public.escolas(escola_id) ON DELETE CASCADE;


--
-- Name: user_profiles user_profiles_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_profiles
    ADD CONSTRAINT user_profiles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.perfis(user_id);


--
-- Name: anotacoes; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.anotacoes ENABLE ROW LEVEL SECURITY;

--
-- Name: coordenadores; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.coordenadores ENABLE ROW LEVEL SECURITY;

--
-- Name: desempenho_semanal; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.desempenho_semanal ENABLE ROW LEVEL SECURITY;

--
-- Name: escolas; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.escolas ENABLE ROW LEVEL SECURITY;

--
-- Name: interventions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.interventions ENABLE ROW LEVEL SECURITY;

--
-- Name: perfis; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.perfis ENABLE ROW LEVEL SECURITY;

--
-- Name: probe_labels; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.probe_labels ENABLE ROW LEVEL SECURITY;

--
-- Name: professores; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.professores ENABLE ROW LEVEL SECURITY;

--
-- Name: resumo_turma_semanal; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.resumo_turma_semanal ENABLE ROW LEVEL SECURITY;

--
-- Name: session_events; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.session_events ENABLE ROW LEVEL SECURITY;

--
-- Name: session_features; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.session_features ENABLE ROW LEVEL SECURITY;

--
-- Name: sessions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;

--
-- Name: temas_cache; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.temas_cache ENABLE ROW LEVEL SECURITY;

--
-- Name: turmas; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.turmas ENABLE ROW LEVEL SECURITY;

--
-- Name: user_profiles; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;

--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA public TO service_role;


--
-- Name: FUNCTION criar_perfil_no_signup(); Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON FUNCTION public.criar_perfil_no_signup() TO anon;
GRANT ALL ON FUNCTION public.criar_perfil_no_signup() TO authenticated;
GRANT ALL ON FUNCTION public.criar_perfil_no_signup() TO service_role;


--
-- Name: TABLE anotacoes; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.anotacoes TO anon;
GRANT ALL ON TABLE public.anotacoes TO authenticated;
GRANT ALL ON TABLE public.anotacoes TO service_role;


--
-- Name: TABLE coordenadores; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.coordenadores TO anon;
GRANT ALL ON TABLE public.coordenadores TO authenticated;
GRANT ALL ON TABLE public.coordenadores TO service_role;


--
-- Name: TABLE desempenho_semanal; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.desempenho_semanal TO anon;
GRANT ALL ON TABLE public.desempenho_semanal TO authenticated;
GRANT ALL ON TABLE public.desempenho_semanal TO service_role;


--
-- Name: TABLE escolas; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.escolas TO anon;
GRANT ALL ON TABLE public.escolas TO authenticated;
GRANT ALL ON TABLE public.escolas TO service_role;


--
-- Name: TABLE interventions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.interventions TO anon;
GRANT ALL ON TABLE public.interventions TO authenticated;
GRANT ALL ON TABLE public.interventions TO service_role;


--
-- Name: TABLE pai_aluno; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.pai_aluno TO anon;
GRANT ALL ON TABLE public.pai_aluno TO authenticated;
GRANT ALL ON TABLE public.pai_aluno TO service_role;


--
-- Name: TABLE perfis; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.perfis TO anon;
GRANT ALL ON TABLE public.perfis TO authenticated;
GRANT ALL ON TABLE public.perfis TO service_role;


--
-- Name: TABLE probe_labels; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.probe_labels TO anon;
GRANT ALL ON TABLE public.probe_labels TO authenticated;
GRANT ALL ON TABLE public.probe_labels TO service_role;


--
-- Name: SEQUENCE probe_labels_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON SEQUENCE public.probe_labels_id_seq TO anon;
GRANT ALL ON SEQUENCE public.probe_labels_id_seq TO authenticated;
GRANT ALL ON SEQUENCE public.probe_labels_id_seq TO service_role;


--
-- Name: TABLE professores; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.professores TO anon;
GRANT ALL ON TABLE public.professores TO authenticated;
GRANT ALL ON TABLE public.professores TO service_role;


--
-- Name: TABLE questoes_cache; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.questoes_cache TO anon;
GRANT ALL ON TABLE public.questoes_cache TO authenticated;
GRANT ALL ON TABLE public.questoes_cache TO service_role;


--
-- Name: TABLE questoes_vistas; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.questoes_vistas TO anon;
GRANT ALL ON TABLE public.questoes_vistas TO authenticated;
GRANT ALL ON TABLE public.questoes_vistas TO service_role;


--
-- Name: TABLE resumo_turma_semanal; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.resumo_turma_semanal TO anon;
GRANT ALL ON TABLE public.resumo_turma_semanal TO authenticated;
GRANT ALL ON TABLE public.resumo_turma_semanal TO service_role;


--
-- Name: TABLE session_events; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.session_events TO anon;
GRANT ALL ON TABLE public.session_events TO authenticated;
GRANT ALL ON TABLE public.session_events TO service_role;


--
-- Name: TABLE session_features; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.session_features TO anon;
GRANT ALL ON TABLE public.session_features TO authenticated;
GRANT ALL ON TABLE public.session_features TO service_role;


--
-- Name: TABLE sessions; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.sessions TO anon;
GRANT ALL ON TABLE public.sessions TO authenticated;
GRANT ALL ON TABLE public.sessions TO service_role;


--
-- Name: TABLE temas_cache; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.temas_cache TO anon;
GRANT ALL ON TABLE public.temas_cache TO authenticated;
GRANT ALL ON TABLE public.temas_cache TO service_role;


--
-- Name: TABLE turmas; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.turmas TO anon;
GRANT ALL ON TABLE public.turmas TO authenticated;
GRANT ALL ON TABLE public.turmas TO service_role;


--
-- Name: TABLE user_profiles; Type: ACL; Schema: public; Owner: -
--

GRANT ALL ON TABLE public.user_profiles TO anon;
GRANT ALL ON TABLE public.user_profiles TO authenticated;
GRANT ALL ON TABLE public.user_profiles TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON FUNCTIONS TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR FUNCTIONS; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON FUNCTIONS TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public GRANT ALL ON TABLES TO service_role;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO anon;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin IN SCHEMA public GRANT ALL ON TABLES TO service_role;


--
-- PostgreSQL database dump complete
--



--
-- Trigger em auth.users (schema gerenciado pelo Supabase). O dump acima cobre só
-- o schema `public`, então este gatilho é capturado à parte (pg_get_triggerdef).
-- A cada signup, cria a linha em public.perfis com user_id = auth.users.id (o
-- `sub` do JWT) — é a base do "perfis.user_id == sub" que a autorização assume.
--
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.criar_perfil_no_signup();
