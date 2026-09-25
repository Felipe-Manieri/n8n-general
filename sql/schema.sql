-- Esquema completo do General V10 (idempotente). O nó "DB Init" já executa isto a cada mensagem;
-- o arquivo existe para documentação e para criar o esquema manualmente se preferir.
CREATE TABLE IF NOT EXISTS general_logs (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(), chat_id TEXT, user_id BIGINT, canal TEXT, tipo TEXT, payload JSONB);
CREATE TABLE IF NOT EXISTS general_pending (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(), chat_id TEXT, user_id BIGINT, status TEXT DEFAULT 'PENDENTE', pedido TEXT, previa TEXT, acao JSONB);
CREATE TABLE IF NOT EXISTS general_agentes (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(), nome TEXT UNIQUE, objetivo TEXT, pode TEXT, nao_pode TEXT, ferramentas TEXT, prompt_sistema TEXT, ativo BOOLEAN DEFAULT TRUE);
CREATE TABLE IF NOT EXISTS general_waiting_input (id SERIAL PRIMARY KEY, chat_id TEXT NOT NULL, id_tarefa TEXT NOT NULL, agent_name TEXT NOT NULL, input_type TEXT NOT NULL, prompt_pt TEXT NOT NULL, input_where_pt TEXT, payload JSONB, has_image BOOLEAN DEFAULT FALSE, created_at TIMESTAMPTZ DEFAULT NOW(), UNIQUE(chat_id, id_tarefa));
CREATE TABLE IF NOT EXISTS telegram_updates (update_id BIGINT PRIMARY KEY, chat_id TEXT, message_id BIGINT, created_at TIMESTAMPTZ DEFAULT NOW());
ALTER TABLE general_waiting_input ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE general_agentes ADD COLUMN IF NOT EXISTS status TEXT;
ALTER TABLE general_agentes ADD COLUMN IF NOT EXISTS config JSONB DEFAULT '{}'::jsonb;
ALTER TABLE general_agentes ADD COLUMN IF NOT EXISTS teste_ok BOOLEAN DEFAULT FALSE;
ALTER TABLE general_agentes ADD COLUMN IF NOT EXISTS ultimo_teste TIMESTAMPTZ;
ALTER TABLE general_agentes ADD COLUMN IF NOT EXISTS ultimo_erro TEXT;
ALTER TABLE general_agentes ADD COLUMN IF NOT EXISTS versao INT DEFAULT 1;
UPDATE general_agentes SET status = CASE WHEN ativo THEN 'legado_nao_testado' ELSE 'pausado' END WHERE status IS NULL;
ALTER TABLE general_agentes ALTER COLUMN status SET DEFAULT 'rascunho';
CREATE TABLE IF NOT EXISTS general_tasks (task_id TEXT PRIMARY KEY, chat_id TEXT, agent_name TEXT, tipo TEXT, destino TEXT, pedido TEXT, pendencia_id INT, state TEXT NOT NULL DEFAULT 'running', result_pt TEXT, evidence JSONB, erro TEXT, created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS general_artifacts (id SERIAL PRIMARY KEY, task_id TEXT, agent_name TEXT, tipo TEXT, conteudo TEXT, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS general_prefs (chat_id TEXT PRIMARY KEY, voz_auto BOOLEAN DEFAULT FALSE, updated_at TIMESTAMPTZ DEFAULT NOW());
