-- Tabelas usadas pelo workflow GENERAL (n8n).
-- Você NÃO precisa rodar isso à mão: o nó "DB Init" do workflow já cria as tabelas na primeira execução (CREATE TABLE IF NOT EXISTS).
-- Use este arquivo só se quiser criar/ver a estrutura no banco antes de rodar o workflow.

CREATE TABLE IF NOT EXISTS general_logs (
  id SERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT NOW(),
  chat_id TEXT,
  user_id BIGINT,
  canal TEXT,
  tipo TEXT,
  payload JSONB
);

CREATE TABLE IF NOT EXISTS general_pending (
  id SERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT NOW(),
  chat_id TEXT,
  user_id BIGINT,
  status TEXT DEFAULT 'PENDENTE',
  pedido TEXT,
  previa TEXT,
  acao JSONB
);

CREATE TABLE IF NOT EXISTS general_agentes (
  id SERIAL PRIMARY KEY,
  ts TIMESTAMPTZ DEFAULT NOW(),
  nome TEXT UNIQUE,
  objetivo TEXT,
  pode TEXT,
  nao_pode TEXT,
  ferramentas TEXT,
  prompt_sistema TEXT,
  ativo BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS general_sessions (
  chat_id TEXT PRIMARY KEY,
  estado TEXT,
  agente_em_criacao JSONB,
  ts TIMESTAMPTZ DEFAULT NOW()
);
