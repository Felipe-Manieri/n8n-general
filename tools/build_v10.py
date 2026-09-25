#!/usr/bin/env python3
"""
Gera GENERAL_V10_EXERCITO.json a partir do JSON ativo (GENERAL V9 — Linear Final 1, 67 nós, arquivo V9-Fenix)
e AGENTE_EXECUTOR_v1.json (modelo validado de agente).

Uso: python tools/build_v10.py
Não contém nenhum segredo: tokens ficam em credenciais do n8n (httpHeaderAuth).
"""
import copy
import json
import pathlib
import re
import uuid

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "backup" / "GENERAL_V9_ativo_67nos.json"
OUT = ROOT / "GENERAL_V10_EXERCITO.json"
OUT_EXEC = ROOT / "AGENTE_EXECUTOR_v1.json"

PG = {"postgres": {"id": "0ORmAig8ppcK65yV", "name": "Postgres account"}}
TG = {"telegramApi": {"id": "5tU8eIaFS3fDn3Qi", "name": "Telegram account"}}
OAI = {"openAiApi": {"id": "26eON1fwGMrSnkGF", "name": "OpenAi account 3"}}


def hdr(name):
    return {"httpHeaderAuth": {"id": "CONFIGURAR", "name": name}}


CRED_WORKER = hdr("Worker PC (X-AGENT-TOKEN)")
CRED_CENTRAL = hdr("OpenClaw Central (X-CENTRAL-TOKEN)")
CRED_EXECUTOR = hdr("Agente Executor (webhook)")
CRED_ELEVEN = hdr("ElevenLabs (xi-api-key)")

# --------------------------------------------------------------------------- helpers
wf = json.loads(SRC.read_text(encoding="utf-8"))
NODES = {n["name"]: n for n in wf["nodes"]}
CONN = wf["connections"]
_new_i = [0]
REPLACE_OK = {"Parse Agente"}   # nós existentes que são reescritos por completo


def nid(name):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, "general-v10/" + name))


def add(name, typ, ver, params, cred=None, pos=None, **extra):
    if name in NODES:
        if name not in REPLACE_OK:
            raise SystemExit(f"nó duplicado: {name}")
        pos = pos or NODES[name]["position"]
        NODES.pop(name)
    _new_i[0] += 1
    i = _new_i[0]
    n = {"parameters": params, "id": nid(name), "name": name, "type": typ, "typeVersion": ver,
         "position": pos or [-1500 + (i % 8) * 260, 2600 + (i // 8) * 220]}
    if cred:
        n["credentials"] = cred
    n.update(extra)
    NODES[name] = n
    return n


def code(name, js, **kw):
    return add(name, "n8n-nodes-base.code", 2, {"jsCode": js}, **kw)


def pg(name, query, always=False, **kw):
    extra = {"alwaysOutputData": True} if always else {}
    return add(name, "n8n-nodes-base.postgres", 2.5, {"operation": "executeQuery", "query": query, "options": {}},
               cred=PG, **extra, **kw)


def tg(name, chat, text, **kw):
    return add(name, "n8n-nodes-base.telegram", 1.2,
               {"chatId": chat, "text": text, "additionalFields": {"appendAttribution": False}}, cred=TG, **kw)


def bool_if(name, expr, **kw):
    return add(name, "n8n-nodes-base.if", 2.2, {
        "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 1},
                       "conditions": [{"id": nid(name + "/c"), "leftValue": expr, "rightValue": "={{true}}",
                                       "operator": {"type": "boolean", "operation": "true"}}],
                       "combinator": "and"}, "options": {}}, **kw)


def http(name, cred, timeout, method="POST", **kw):
    p = {"method": method, "url": "={{ $json.url }}", "authentication": "genericCredentialType",
         "genericAuthType": "httpHeaderAuth", "sendHeaders": True,
         "headerParameters": {"parameters": [{"name": "Content-Type", "value": "application/json"}]},
         "options": {"timeout": timeout, "response": {"response": {"fullResponse": True, "neverError": True}}}}
    if method == "POST":
        p.update({"sendBody": True, "contentType": "raw", "rawContentType": "application/json",
                  "body": "={{ JSON.stringify($json.body) }}"})
    return add(name, "n8n-nodes-base.httpRequest", 4.2, p, cred=cred, onError="continueRegularOutput", **kw)


def remove(*names):
    for n in names:
        NODES.pop(n)
        CONN.pop(n, None)
    for src in list(CONN):
        for t in list(CONN[src]):
            CONN[src][t] = [[c for c in (o or []) if c["node"] not in names] for o in CONN[src][t]]


def clear_out(src):
    CONN.pop(src, None)


def link(src, dst, out=0, typ="main"):
    c = CONN.setdefault(src, {}).setdefault(typ, [])
    while len(c) <= out:
        c.append([])
    c[out].append({"node": dst, "type": "main" if typ == "main" else typ, "index": 0})


def set_params(name, **kv):
    NODES[name]["parameters"].update(kv)


def js(name, text):
    NODES[name]["parameters"]["jsCode"] = text


# ------------------------------------------------------------------ blocos JS compartilhados
NORMALIZE_JS = r"""
// Normaliza a resposta de QUALQUER destino (Worker, Central, Executor) para o contrato único:
// {task_id, status: completed|running|waiting_input|failed, result_pt, evidence:{verified, checks[]}}
// Sucesso NUNCA é inferido de HTTP 200 nem de texto: só de status + evidência.
function normalize(res, ctx) {
  let body = res.body !== undefined ? res.body : res;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch (e) { body = { _raw: body.slice(0, 300) }; } }
  if (body === null || typeof body !== 'object') body = { _raw: String(body).slice(0, 300) };
  const http = Number(res.statusCode || 0);
  const VALID = ['completed', 'running', 'waiting_input', 'failed'];
  const netErr = (res.error && !res.statusCode)
    ? (typeof res.error === 'string' ? res.error : (res.error.message || res.error.code || JSON.stringify(res.error))) : '';
  let state = 'unknown', reason = '';
  if (netErr) { state = 'failed'; reason = 'Sem resposta de ' + ctx.destino + ': ' + String(netErr).slice(0, 200); }
  else if (http >= 400) {
    state = 'failed';
    reason = 'HTTP ' + http + ' de ' + ctx.destino + ': ' + String(body.detail || body.error || body.error_code || body.result_pt || JSON.stringify(body)).slice(0, 300);
  } else {
    const st = String(body.status || '').toLowerCase();
    if (VALID.includes(st)) state = st;
    else reason = 'A resposta de ' + ctx.destino + ' não traz o campo status do contrato (recebido: ' + JSON.stringify(body).slice(0, 200) + ')';
    const expected = (ctx.body && ctx.body.task_id) || ctx.task_id;
    if (body.task_id && body.task_id !== expected) { state = 'unknown'; reason = 'task_id da resposta (' + body.task_id + ') difere do enviado (' + expected + ')'; }
  }
  const evidence = (body.evidence && typeof body.evidence === 'object') ? body.evidence : null;
  const checks = Array.isArray(evidence && evidence.checks) ? evidence.checks : [];
  const verified = state === 'completed' && evidence !== null && evidence.verified === true && checks.length > 0 && checks.every(c => c && c.ok === true);
  if (state === 'failed' && !reason) reason = String(body.result_pt || body.error_code || 'falha sem detalhe').slice(0, 300);
  return { state, verified, reason, evidence, body,
    result_pt: String(body.result_pt || body.reply_text || '').slice(0, 1500),
    error_code: body.error_code || null, http_status: http || null, meta: body.meta || null };
}
"""

MSG_JS = r"""
function buildMsg(s) {
  const nome = s.agent_name ? '[' + s.agent_name + '] ' : '';
  const ev = s.evidence || {};
  const lines = (Array.isArray(ev.checks) ? ev.checks : []).slice(0, 4)
    .map(c => (c.ok ? '✔ ' : '✘ ') + (c.type || '') + (c.path ? ': ' + c.path : '') + (c.id ? ' #' + c.id : ''));
  let head;
  if (s.state === 'completed' && s.verified) head = '✅ Executado e verificado.';
  else if (s.state === 'completed') head = '⚠️ Concluído, mas SEM verificação independente do efeito. Não posso afirmar que a ação aconteceu.';
  else if (s.state === 'running') head = '⏳ Em andamento. Vou acompanhar e aviso quando terminar (peça: "status da tarefa ' + s.task_id + '").';
  else if (s.state === 'failed') head = '❌ Falhou: ' + (s.reason || 'sem detalhe');
  else head = '❓ Resultado desconhecido: não confirmei que a tarefa foi executada. Motivo: ' + (s.reason || 'sem detalhe');
  let txt = nome + head;
  if (s.result_pt) txt += '\n' + s.result_pt;
  if (lines.length) txt += '\n' + lines.join('\n');
  if (s.agente_status) txt += '\nStatus do agente: ' + s.agente_status.status + (s.agente_status.pendentes && s.agente_status.pendentes.length ? ' (conexões pendentes: ' + s.agente_status.pendentes.join(', ') + ')' : '');
  txt += '\nTarefa: ' + s.task_id + (s.origem === 'aprovacao' ? ' (ação da pendência #' + (s.pendencia_id || '?') + ')' : '');
  return txt;
}
"""

BUILD_CALL_JS = r"""
// Monta a chamada conforme o destino. Tokens NÃO ficam aqui: a autenticação é feita pela credencial do nó HTTP.
function buildCall(tipo, p, task_id, CFG) {
  p = p || {};
  if (tipo === 'executar_pc') return { destino: 'worker', url: CFG.WORKER_URL + '/task',
    body: { task_id, action: 'powershell', command: String(p.command || ''), verify: Array.isArray(p.verify) ? p.verify : [], timeout_s: 60, wait_s: 25 } };
  if (tipo === 'criar_arquivo_pc') return { destino: 'worker', url: CFG.WORKER_URL + '/task',
    body: { task_id, action: 'create_file', path: String(p.path || ''), content: String(p.content || '') } };
  if (tipo === 'openclaw') return { destino: 'central', url: CFG.CENTRAL_URL,
    body: { task: ['Abra ' + (p.url || '') + '.', p.instructions || ''].filter(Boolean).join(' '), task_id } };
  if (tipo === 'executar_agente' || tipo === 'testar_agente') return { destino: 'executor', url: CFG.EXECUTOR_URL,
    body: { task_id, agent: String(p.nome || ''), acao: tipo === 'testar_agente' ? 'teste' : String(p.acao || 'preparar_conteudo'), tarefa: String(p.tarefa || '') } };
  return { destino: 'invalido', url: '', body: {} };
}
"""

# ============================================================================= GENERAL V10
# ---- Config (URLs não secretas) entre "Só Felipe" e "DB Init"
code("Config", r"""// URLs NÃO secretas. Ajuste aqui se o endereço mudar. Tokens ficam nas credenciais do n8n.
return [{ json: { ...$input.first().json,
  CENTRAL_URL: 'http://72.60.11.239:8080/task',
  WORKER_URL: 'http://100.107.36.118:8787',
  EXECUTOR_URL: 'http://localhost:5678/webhook/agente-executor'
} }];""", pos=[-1340, 300])
CONN["Só Felipe"]["main"][0] = [{"node": "Config", "type": "main", "index": 0}]
link("Config", "DB Init")

# ---- DB Init: esquema completo (idempotente)
set_params("DB Init", query="""CREATE TABLE IF NOT EXISTS general_logs (id SERIAL PRIMARY KEY, ts TIMESTAMPTZ DEFAULT NOW(), chat_id TEXT, user_id BIGINT, canal TEXT, tipo TEXT, payload JSONB);
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
CREATE TABLE IF NOT EXISTS general_prefs (chat_id TEXT PRIMARY KEY, voz_auto BOOLEAN DEFAULT FALSE, updated_at TIMESTAMPTZ DEFAULT NOW());""")

# ---- Log / Buscar Aguardando / Tem Aguardando?
NODES["Log"]["alwaysOutputData"] = True
set_params("Buscar Aguardando", query="""WITH g AS (DELETE FROM general_waiting_input WHERE chat_id='{{ $('Padronizar').first().json.chat_id }}' AND agent_name='General' RETURNING *)
SELECT * FROM g
UNION ALL
(SELECT * FROM general_waiting_input WHERE chat_id='{{ $('Padronizar').first().json.chat_id }}' AND agent_name<>'General' ORDER BY id LIMIT 1);""")
js("Tem Aguardando?", r"""const pad = $('Padronizar').first().json;
const logItem = $('Log').first().json || {};
let textFromSetar = '';
try { const s = $('Setar Transcrição').first(); if (s?.json?.text != null) textFromSetar = String(s.json.text).trim(); } catch (e) {}
const text = textFromSetar !== '' ? textFromSetar : (logItem.text || pad.text || '');
const rows = $input.all().map(i => i.json).filter(r => r.id_tarefa);
const ext = rows.find(r => r.agent_name !== 'General');
const gen = rows.find(r => r.agent_name === 'General');
if (ext) return [{ json: { chat_id: pad.chat_id, user_id: pad.user_id, text, has_waiting: true, waiting: ext } }];
// Espera criada pelo próprio General: a resposta vira contexto da próxima conversa (a linha já foi consumida na query)
const t2 = gen ? ('Contexto: pedi ao Felipe (' + gen.input_type + '): "' + gen.prompt_pt + '". Resposta dele: ' + text) : text;
return [{ json: { chat_id: pad.chat_id, user_id: pad.user_id, text: t2, has_waiting: false } }];""")

# ---- Catálogo / Preferências / Contexto
set_params("Catálogo", query="SELECT nome,objetivo,pode,nao_pode,ferramentas,status,teste_ok FROM general_agentes WHERE status <> 'pausado' ORDER BY id;")
pg("Preferências", "SELECT voz_auto FROM general_prefs WHERE chat_id='{{ $('Padronizar').first().json.chat_id }}' LIMIT 1;",
   always=True, pos=[NODES["Catálogo"]["position"][0] + 160, NODES["Catálogo"]["position"][1] + 140])
clear_out("Catálogo")
link("Catálogo", "Preferências")
link("Preferências", "Contexto")
js("Contexto", r"""const pad = $('Tem Aguardando?').first().json;
const agentes = $('Catálogo').all().map(i => i.json).filter(j => j.nome);
const pref = ($('Preferências').first() || {}).json || {};
const rot = { ativo: 'ATIVO e testado', aguardando_conexao: 'ATIVO e testado, mas a publicação/integração externa aguarda conexão', rascunho: 'RASCUNHO nunca testado (NÃO delegue)', em_teste: 'EM TESTE (NÃO delegue)', erro: 'COM ERRO no último teste (NÃO delegue)', legado_nao_testado: 'LEGADO: só cadastro, nunca testado (NÃO delegue; proponha testar)' };
const catalogo = agentes.length
  ? agentes.map(a => '- ' + a.nome + ' [' + (rot[a.status] || a.status) + ']: ' + a.objetivo + ' | PODE: ' + a.pode + ' | NÃO PODE: ' + a.nao_pode + ' | FERRAMENTAS: ' + a.ferramentas).join('\n')
  : 'Nenhum agente criado. Pergunte se quer criar.';
return [{ json: { catalogo, text: pad.text, chat_id: pad.chat_id, user_id: pad.user_id, voz_auto: pref.voz_auto === true } }];""")

# ---- General (prompt)
NODES["General"]["parameters"]["options"]["systemMessage"] = """=Você é o GENERAL — comandante e supervisor dos agentes de IA do Felipe. Você recebe ordens, escolhe quem executa, acompanha o estado e reporta o resultado VERDADEIRO. O sistema (não você) confirma a execução e anexa o resultado real; portanto NUNCA escreva que algo "foi feito/executado/publicado" — escreva no futuro ou como plano ("vou pedir ao agente X...").

CATÁLOGO DE AGENTES (status entre colchetes; só delegue a agentes ATIVOS e testados):
{{ $json.catalogo }}

Você SEMPRE responde em JSON válido e NADA fora dele:
{
  "reply_text": "texto pro Felipe (plano/pergunta, nunca afirmação de conclusão)",
  "action": { "type": "nome_da_acao", "payload": {} } ou null,
  "need_approval": false,
  "approval_preview": "descrição clara do que será feito, se need_approval",
  "need_user_input": { "input_type": "otp"|"password"|"captcha"|"confirm", "prompt_pt": "texto pedindo", "input_where_pt": "SMS"|"email"|"app"|"WhatsApp", "has_image": false, "payload": {} } ou null,
  "generate_audio": false
}

ACTIONS (type) — UMA ação por resposta:
Execução (passam pelo contrato task_id/status/evidência):
- executar_pc → {command, verify?} — PowerShell no PC. SEMPRE que possível inclua verify: lista de checagens do efeito, ex. [{"type":"file_exists","path":"C:\\\\..."}], tipos: file_exists, dir_exists, path_absent, file_contains{text}, file_sha256{sha256}
- criar_arquivo_pc → {path, content} — cria arquivo dentro do perfil do usuário (o Worker confere de volta)
- openclaw → {url, instructions} — RPA no navegador via Central
- executar_agente → {nome, acao, tarefa} — delega a um agente ATIVO. acao: "preparar_conteudo" (padrão) ou ações sensíveis como "publicar_..." (exigem aprovação e conexão)
- testar_agente → {nome} — roda a tarefa de teste do agente
Administração de agentes (SQL interno):
- criar_agente → {nome, objetivo, pode, nao_pode, ferramentas, prompt_sistema, conexoes_necessarias:[...], acoes_requerem_conexao:[...], tarefa_teste}
- editar_agente → mesmos campos (volta a RASCUNHO até novo teste)
- pausar_agente → {nome} | reativar_agente → {nome}
- marcar_conexao_pronta → {nome, conexao} — só depois que o Felipe disser que configurou a credencial no n8n; em seguida proponha testar_agente
- status_agentes → {} | ver_erros_agente → {nome} | consultar_tarefa → {task_id?}
- consultar_sql → {query} — SOMENTE SELECT (tabelas general_*)
- aprovar_pendencia → {id} | cancelar_pendencia → {id}
- definir_preferencia_voz → {ativo: true|false}

REGRAS:
1) Felipe fala linguagem natural. Sem comandos com /.
2) Ações perigosas (postar/publicar, pagar, apagar, enviar em massa, executar_pc, criar_arquivo_pc, openclaw): need_approval=true + approval_preview. Cada aprovação vale só para a ação mostrada.
3) Se a mensagem contém CONFIRMO ALFA: execute direto, need_approval=false (vale só para esta mensagem).
4) CRIAR AGENTE — pergunte 1 por vez: nome → objetivo → tarefas permitidas → limites (não pode) → ferramentas/conexões externas necessárias (ex.: Instagram exige conexão) → tarefa de teste. Só use criar_agente com TUDO definido. Depois de criar, diga que é RASCUNHO e proponha testar_agente. Nunca diga que o agente está funcionando antes do teste passar. Se faltar conexão, explique o passo (configurar a credencial no n8n, nunca enviar senha/token pelo chat) e aguarde.
5) Trava (2FA/senha/captcha): use need_user_input. Informe em input_where_pt onde o código chega. NUNCA peça senha completa ou token pelo chat.
6) Áudio: se Felipe pedir ("responda em voz", "manda áudio", "estou dirigindo"), generate_audio=true. Se pedir para lembrar da preferência, use definir_preferencia_voz.
7) Status/relatório/agentes/tarefas: use status_agentes, consultar_tarefa ou consultar_sql.
8) Aprovar/cancelar: "aprovar 5" → aprovar_pendencia {id:5}.
9) Seja direto. Delegue a agentes ATIVOS quando o catálogo tiver um adequado; se não houver, proponha criar um."""

# ---- Parse / Forçar Aprovação / Decidir
js("Parse", r"""const raw = $input.first().json;
let content = '';
if (typeof raw.output === 'string') content = raw.output;
else if (raw.output && typeof raw.output === 'object') content = JSON.stringify(raw.output);
else content = raw.content || raw.text || JSON.stringify(raw);

let p = {};
try { const m = content.match(/\{[\s\S]*\}/); if (m) p = JSON.parse(m[0]); } catch (e) { p = {}; }

if (!p.reply_text) p.reply_text = content;
if (typeof p.action === 'string') p.action = { type: p.action, payload: {} };
if (!p.action || !p.action.type) p.action = null;
p.need_approval = p.need_approval === true;
if (!p.need_user_input) p.need_user_input = null;

const ctx = $('Contexto').first().json;
const t = String(ctx.text || '');
if (t.toUpperCase().includes('CONFIRMO ALFA')) p.need_approval = false;

// Voz: só quando o Felipe pedir (ou tiver definido a preferência). Áudio recebido NÃO liga a voz sozinho.
const pediuVoz = /(respond[ae]|mand[ae]|envi[ae]|fal[ae]|quero|prefiro)\b[^.!?\n]{0,40}(?:\s|^)(?:em\s+)?(?:voz|[áa]udio)|\b(por|em)\s+(voz|[áa]udio)\b|estou\s+dirigindo/i.test(t);
const pediuTexto = /\b(sem|pare de|parar de|volte? (a|para) )[^.!?\n]{0,25}(voz|[áa]udio|texto)/i.test(t);
p.generate_audio = pediuTexto ? false : (p.generate_audio === true || pediuVoz || ctx.voz_auto === true);

return [{ json: { ...ctx, ...p, chat_id: ctx.chat_id, user_id: ctx.user_id, acao: p.action } }];""")

js("Forçar Aprovação", r"""const prev = $input.first().json;
const perigosas = ['executar_pc', 'criar_arquivo_pc', 'openclaw'];
const internas = ['criar_agente', 'editar_agente', 'aprovar_pendencia', 'cancelar_pendencia', 'consultar_sql', 'pausar_agente', 'reativar_agente', 'status_agentes', 'ver_erros_agente', 'marcar_conexao_pronta', 'consultar_tarefa', 'definir_preferencia_voz', 'testar_agente'];
const acao = prev.action || prev.acao;
const tipo = (acao?.type || acao?.tipo || '').toString().toLowerCase();
const pl = acao?.payload || {};
const sensivel = tipo === 'executar_agente' && (/^(publicar|postar|apagar|deletar|excluir|pagar|enviar_massa)/i.test(String(pl.acao || '')) || pl.sensivel === true);
const confirmoAlfa = String(prev.text || '').toUpperCase().includes('CONFIRMO ALFA');
let need_approval = prev.need_approval;
if (tipo && (perigosas.includes(tipo) || sensivel)) need_approval = true;
if (tipo && internas.includes(tipo)) need_approval = false;   // administração interna nunca vira pendência de execução externa
if (confirmoAlfa) need_approval = false;                      // vale só para esta mensagem
return [{ json: { ...prev, need_approval } }];""")

# ---- Rota: cosmético (nome das saídas)
for rule, key in zip(NODES["Rota"]["parameters"]["rules"]["values"], ["Responder", "Aprovar", "Executar", "PedirInput"]):
    rule["renameOutput"] = True
    rule["outputKey"] = key

# ---- Áudio / voz com fallback
NODES["Áudio?"]["parameters"]["conditions"]["conditions"][0]["leftValue"] = "={{ $json.generate_audio === true }}"
set_params("Enviar Texto", text="={{ String($json.reply_text || '').slice(0, 4000) }}", additionalFields={"appendAttribution": False})
NODES["ElevenLabs"]["parameters"] = {
    "method": "POST", "url": "https://api.elevenlabs.io/v1/text-to-speech/Zk0wRqIFBWGMu2lIk7hw",
    "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
    "sendHeaders": True, "headerParameters": {"parameters": [{"name": "Content-Type", "value": "application/json"}]},
    "sendBody": True, "contentType": "raw", "rawContentType": "application/json",
    "body": "={{ JSON.stringify({ text: String($json.reply_text || ' ').slice(0, 2500), model_id: 'eleven_multilingual_v2', voice_settings: { stability: 0.5, similarity_boost: 0.75 } }) }}",
    "options": {"timeout": 60000, "response": {"response": {"responseFormat": "file", "outputPropertyName": "data"}}}}
NODES["ElevenLabs"]["credentials"] = CRED_ELEVEN
NODES["ElevenLabs"]["onError"] = "continueRegularOutput"
set_params("Enviar Áudio", chatId="={{ $('Áudio?').first().json.chat_id }}")
bool_if("Áudio OK?", "={{ ($binary && $binary.data) ? true : false }}", pos=[NODES["ElevenLabs"]["position"][0] + 240, NODES["ElevenLabs"]["position"][1]])
code("Voz Falhou", r"""// A voz falhou: responde em TEXTO e registra o erro.
const o = $('Áudio?').first().json;
const err = $input.first().json.error;
const msg = typeof err === 'string' ? err : (err && (err.message || err.description)) || 'ElevenLabs não devolveu áudio';
return [{ json: { ...o, voz_erro: String(msg).slice(0, 300) } }];""", pos=[NODES["ElevenLabs"]["position"][0] + 480, NODES["ElevenLabs"]["position"][1] + 160])
pg("Log Erro Voz", """INSERT INTO general_logs (chat_id, user_id, canal, tipo, payload) VALUES ('{{ $json.chat_id }}', {{ $json.user_id || 0 }}, 'telegram', 'erro_voz', ('{{ JSON.stringify({ erro: $json.voz_erro || '' }).replace(/'/g, "''") }}')::jsonb);""",
   pos=[NODES["ElevenLabs"]["position"][0] + 720, NODES["ElevenLabs"]["position"][1] + 300])
clear_out("ElevenLabs")
link("ElevenLabs", "Áudio OK?")
link("Áudio OK?", "Enviar Áudio", 0)
link("Áudio OK?", "Voz Falhou", 1)
link("Voz Falhou", "Enviar Texto")
link("Voz Falhou", "Log Erro Voz")

# ---- Pendência (aprovação vinculada à ação e ao task_id)
js("Prep Pendência", r"""const prev = $input.first().json;
const esc = s => String(s ?? '').replace(/'/g, "''");
const acao = prev.action || prev.acao || {};
const task_id = 't' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
const acaoFull = { ...acao, meta: { task_id, generate_audio: prev.generate_audio === true } };
return [{ json: { ...prev, task_id, pedido_esc: esc(prev.text || prev.reply_text), previa_esc: esc(prev.approval_preview || prev.reply_text), acao_json: JSON.stringify(acaoFull).replace(/'/g, "''") } }];""")
js("Formatar Prévia", r"""const row = $input.first().json;
const id = row.id;
const prev = $('Prep Pendência').first().json;
const previa = String(prev.approval_preview || prev.reply_text || '(sem descrição)');
const txt = '👀 PRÉVIA #' + id + '\n\n' + previa + '\n\n✅ Para aprovar: "aprovar ' + id + '"\n❌ Para cancelar: "cancelar ' + id + '"\n🔎 A aprovação vale só para esta ação.';
return [{ json: { ...prev, txt, reply_text: txt, chat_id: prev.chat_id } }];""")
set_params("Enviar Prévia", additionalFields={"appendAttribution": False})

# ---- Classificar
js("Classificar", r"""const e = $input.first().json;
const action = e.action || e.acao || {};
const tipo = (action.type || '').toLowerCase();
const payload = action.payload || {};
const externas = ['executar_pc', 'criar_arquivo_pc', 'openclaw', 'executar_agente', 'testar_agente'];
const task_id = 't' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
let agent_name = tipo;
if (tipo === 'openclaw') agent_name = 'OpenClaw';
else if (tipo === 'executar_pc' || tipo === 'criar_arquivo_pc') agent_name = 'PC';
else if (tipo === 'executar_agente' || tipo === 'testar_agente') agent_name = String(payload.nome || 'agente');
return [{ json: { ...e, tipo, payload, task_id, agent_name, exec_type: externas.includes(tipo) ? 'external' : 'internal' } }];""")

# ---- Rastreamento de tarefas: Montar Endpoint / Prep Reexecução / Preparar Tarefa / Registrar / Destino
js("Montar Endpoint", BUILD_CALL_JS + r"""
const CFG = $('Config').first().json;
const e = $input.first().json;
const call = buildCall(e.tipo, e.payload, e.task_id, CFG);
return [{ json: { ...call, chat_id: e.chat_id, user_id: e.user_id, task_id: e.task_id, agent_name: e.agent_name, tipo: e.tipo,
  pedido: e.text || '', generate_audio: e.generate_audio === true, origem: 'direto', pendencia_id: null } }];""")
js("Prep Reexecução", BUILD_CALL_JS + r"""
// Executa EXATAMENTE a ação gravada na pendência aprovada (não a que o modelo diria agora).
const CFG = $('Config').first().json;
const e = $input.first().json;
const acao = e.acao || {};
const tipo = String(acao.type || acao.tipo || '').toLowerCase();
const meta = acao.meta || {};
const task_id = meta.task_id || ('t' + Date.now() + '-' + Math.random().toString(36).slice(2, 8));
let agent_name = tipo;
if (tipo === 'openclaw') agent_name = 'OpenClaw';
else if (tipo === 'executar_pc' || tipo === 'criar_arquivo_pc') agent_name = 'PC';
else if (tipo === 'executar_agente' || tipo === 'testar_agente') agent_name = String((acao.payload || {}).nome || 'agente');
const call = buildCall(tipo, acao.payload || {}, task_id, CFG);
return [{ json: { ...call, chat_id: e.chat_id, user_id: e.user_id, task_id, agent_name, tipo,
  pedido: 'pendência aprovada #' + (e.pendencia_id || '?'), generate_audio: e.generate_audio === true || meta.generate_audio === true,
  origem: 'aprovacao', pendencia_id: e.pendencia_id || null } }];""")
js("Montar Retomar", r"""const CFG = $('Config').first().json;
const d = $json;
const w = d.waiting || {};
const pl = w.payload || {};
const destino = pl.destino || 'central';
const task_id = 't' + Date.now() + '-r' + Math.random().toString(36).slice(2, 6);
const url = destino === 'worker' ? CFG.WORKER_URL + '/task' : (destino === 'executor' ? CFG.EXECUTOR_URL : CFG.CENTRAL_URL);
return [{ json: { destino, url, body: { task_id: w.id_tarefa, resume_id: task_id, resume: true, user_input: d.text, payload: pl.original || {} },
  chat_id: d.chat_id, user_id: d.user_id, task_id, agent_name: w.agent_name || 'Agente', tipo: 'retomar',
  pedido: 'retomada de ' + w.id_tarefa, generate_audio: d.voz_auto === true, origem: 'retomada', pendencia_id: null } }];""")
NODES["Montar Retomar"]["position"] = NODES["Montar Retomar"]["position"]

code("Preparar Tarefa", r"""// Ponto único de entrada da execução externa (direto, aprovado ou retomada).
return [$input.first()];""", pos=[-300, 2000])
pg("Registrar Tarefa", """INSERT INTO general_tasks (task_id,chat_id,agent_name,tipo,destino,pedido,pendencia_id,state) VALUES ('{{ $json.task_id }}','{{ $json.chat_id }}','{{ String($json.agent_name || '').replace(/'/g, "''") }}','{{ String($json.tipo || '').replace(/'/g, "''") }}','{{ $json.destino }}','{{ String($json.pedido || '').replace(/'/g, "''").slice(0, 500) }}',{{ $json.pendencia_id || 'NULL' }},'running') ON CONFLICT (task_id) DO NOTHING RETURNING task_id;""",
   always=True, pos=[-60, 2000])
code("Ctx Tarefa", r"""// Se o task_id já existia, a execução é DUPLICADA: não executa de novo.
const rows = $input.all().map(i => i.json).filter(r => r.task_id);
if (!rows.length) return [];
return [{ json: $('Preparar Tarefa').first().json }];""", pos=[180, 2000])
add("Destino?", "n8n-nodes-base.switch", 3.2, {"rules": {"values": [
    {"conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 1},
                    "conditions": [{"id": nid("dest/" + d), "leftValue": "={{ $json.destino }}", "rightValue": d,
                                    "operator": {"type": "string", "operation": "equals"}}], "combinator": "and"},
     "renameOutput": True, "outputKey": d} for d in ("worker", "central", "executor")]},
    "options": {"fallbackOutput": "extra"}}, pos=[420, 2000])
http("Chamar Worker PC", CRED_WORKER, 90000, pos=[700, 1880])
http("Chamar Central", CRED_CENTRAL, 240000, pos=[700, 2020])
http("Chamar Agente Executor", CRED_EXECUTOR, 120000, pos=[700, 2160])
code("Falha Roteamento", r"""const c = $('Preparar Tarefa').first().json;
return [{ json: { ...c, state: 'failed', verified: false, reason: 'Tipo de ação sem destino de execução (' + (c.tipo || '?') + ').', evidence: null, result_pt: '', need_input: false, is_error: true, agente_status: null } }];""",
     pos=[700, 2300])
code("Parse Agente", NORMALIZE_JS + r"""
const res = $input.first().json;
const ctx = $('Preparar Tarefa').first().json;
const n = normalize(res, ctx);
let agente_status = null;
if (ctx.tipo === 'testar_agente') {
  const pend = (n.meta && n.meta.conexoes_pendentes) || [];
  if (n.state === 'completed' && n.verified) agente_status = { status: pend.length ? 'aguardando_conexao' : 'ativo', teste_ok: true, pendentes: pend };
  else if (n.error_code === 'CONNECTION_MISSING') agente_status = { status: 'aguardando_conexao', teste_ok: false, pendentes: pend };
  else agente_status = { status: 'erro', teste_ok: false, pendentes: [] };
}
return [{ json: { ...ctx, state: n.state, verified: n.verified, reason: n.reason, result_pt: n.result_pt, evidence: n.evidence,
  error_code: n.error_code, http_status: n.http_status, meta: n.meta, agente_status,
  need_input: n.state === 'waiting_input', input_type: ['otp', 'password', 'captcha', 'confirm'].includes(n.body.input_type) ? n.body.input_type : 'otp', prompt_pt: n.body.prompt_pt, has_image: n.body.has_image === true,
  payload_in: n.body.payload || {}, is_error: n.state === 'failed' || n.state === 'unknown' } }];""", pos=[960, 2020])
code("Estado", r"""return [$input.first()];""", pos=[1200, 2020])
pg("Atualizar Tarefa", """UPDATE general_tasks SET state='{{ $json.state }}', result_pt='{{ String($json.result_pt || '').replace(/'/g, "''").slice(0, 1500) }}', evidence=('{{ JSON.stringify({ evidence: $json.evidence || {}, verified: $json.verified === true, reason: $json.reason || '' }).replace(/'/g, "''") }}')::jsonb, erro=NULLIF('{{ String($json.reason || '').replace(/'/g, "''").slice(0, 500) }}',''), updated_at=NOW() WHERE task_id='{{ $json.task_id }}' RETURNING task_id;""",
   always=True, pos=[1420, 2020])
code("Estado Final", r"""return [{ json: $('Estado').first().json }];""", pos=[1640, 2020])

# fluxo de chamada
clear_out("Montar Endpoint")
link("Montar Endpoint", "Preparar Tarefa")
link("Prep Reexecução", "Preparar Tarefa")
clear_out("Montar Retomar")
link("Montar Retomar", "Preparar Tarefa")
link("Preparar Tarefa", "Registrar Tarefa")
link("Registrar Tarefa", "Ctx Tarefa")
link("Ctx Tarefa", "Destino?")
link("Destino?", "Chamar Worker PC", 0)
link("Destino?", "Chamar Central", 1)
link("Destino?", "Chamar Agente Executor", 2)
link("Destino?", "Falha Roteamento", 3)
for n in ("Chamar Worker PC", "Chamar Central", "Chamar Agente Executor"):
    link(n, "Parse Agente")
link("Parse Agente", "Estado")
link("Falha Roteamento", "Estado")
link("Estado", "Atualizar Tarefa")
link("Atualizar Tarefa", "Estado Final")

# ramificações depois do estado final
clear_out("Parse Agente")
link("Parse Agente", "Estado")
link("Estado Final", "Precisa Input?")
link("Estado Final", "Só Erros?")
bool_if("Agente Teste?", "={{ $json.tipo === 'testar_agente' && !!$json.agente_status }}", pos=[1880, 2320])
pg("Atualizar Agente", """UPDATE general_agentes SET status='{{ $json.agente_status.status }}', teste_ok={{ $json.agente_status.teste_ok ? 'TRUE' : 'FALSE' }}, ultimo_teste=NOW(), ultimo_erro={{ $json.agente_status.status === 'erro' ? ("'" + String($json.reason || $json.result_pt || 'teste sem verificação').replace(/'/g, "''").slice(0, 500) + "'") : 'NULL' }}, config=jsonb_set(COALESCE(config,'{}'::jsonb),'{conexoes_pendentes}',('{{ JSON.stringify($json.agente_status.pendentes || []) }}')::jsonb), ativo=TRUE WHERE nome='{{ String($json.agent_name || '').replace(/'/g, "''") }}' RETURNING nome,status;""",
   always=True, pos=[2100, 2320])
link("Estado Final", "Agente Teste?")
link("Agente Teste?", "Atualizar Agente", 0)
bool_if("Retomada?", "={{ $json.origem === 'retomada' }}", pos=[1880, 2460])
link("Estado Final", "Retomada?")
link("Retomada?", "Apagar Aguardando", 0)
NODES["Apagar Aguardando"]["parameters"]["query"] = "DELETE FROM general_waiting_input WHERE chat_id='{{ $json.chat_id }}' AND id_tarefa='{{ ($json.body && $json.body.task_id) || '' }}';"
NODES["Apagar Aguardando"]["position"] = [2100, 2460]
NODES["Apagar Aguardando"]["alwaysOutputData"] = True

# aguardando input do agente
set_params("Salvar Aguardando", query="""INSERT INTO general_waiting_input (chat_id,id_tarefa,agent_name,input_type,prompt_pt,payload,has_image) VALUES ('{{ $json.chat_id }}','{{ $json.task_id }}','{{ String($json.agent_name || 'Agente').replace(/'/g, "''") }}','{{ $json.input_type || 'otp' }}','{{ String($json.prompt_pt || $json.result_pt || 'Preciso de uma resposta sua.').replace(/'/g, "''") }}',('{{ JSON.stringify({ destino: $json.destino, original: $json.body, agente: $json.payload_in || {} }).replace(/'/g, "''") }}')::jsonb,{{ $json.has_image === true ? 'TRUE' : 'FALSE' }}) ON CONFLICT (chat_id,id_tarefa) DO NOTHING;""")
NODES["Salvar Aguardando"]["alwaysOutputData"] = True
js("Msg Input", r"""const prev = $('Estado Final').first().json;
const nome = prev.agent_name || 'Agente';
const prompt = prev.prompt_pt || prev.result_pt || 'Me envie o código aqui.';
const tipo = (prev.input_type || 'otp').toLowerCase();
const extra = tipo === 'captcha' ? ' Resolva e responda OK.' : '';
const txt = '[' + nome + ' • tarefa ' + prev.task_id + '] ' + prompt + extra;
return [{ json: { ...prev, txt, chat_id: prev.chat_id } }];""")
set_params("Enviar Pedido Input", additionalFields={"appendAttribution": False})

# resultado
js("Resultado OK", MSG_JS + r"""
const s = $input.first().json;
return [{ json: { ...s, reply_text: buildMsg(s) } }];""")
set_params("Log Exec", query="""INSERT INTO general_logs (chat_id,user_id,canal,tipo,payload) VALUES ('{{ $json.chat_id }}',{{ $json.user_id ?? 0 }},'telegram','execucao',('{{ JSON.stringify({ task_id: $json.task_id, agente: $json.agent_name, destino: $json.destino, state: $json.state, verified: $json.verified === true, origem: $json.origem }).replace(/'/g, "''") }}')::jsonb);""")
NODES["Log Exec"]["alwaysOutputData"] = True
code("Restaurar Resposta", r"""return [{ json: $('Resultado OK').first().json }];""", pos=[NODES["Log Exec"]["position"][0] + 220, NODES["Log Exec"]["position"][1]])
clear_out("Log Exec")
link("Log Exec", "Restaurar Resposta")
link("Restaurar Resposta", "Áudio?")

# log de erro
set_params("Log Erro", query="""INSERT INTO general_logs (chat_id, user_id, canal, tipo, payload) VALUES ('{{ $json.chat_id }}', {{ $json.user_id || 0 }}, 'telegram', 'erro', ('{{ JSON.stringify({ task_id: $json.task_id, state: $json.state, destino: $json.destino, reason: $json.reason || '' }).replace(/'/g, "''") }}')::jsonb);""")

# ---- Montar SQL / Resultado SQL / Prep Input
js("Montar SQL", r"""const e = $input.first().json;
const tipo = e.tipo;
const p = e.payload || {};
const esc = s => String(s ?? '').replace(/'/g, "''");
const nomeOk = /^[\wÀ-ÿ\- ]{2,40}$/.test(String(p.nome || ''));
const nome = esc(p.nome);
let sql = 'SELECT 1;', extra = '', reexecutar = false, mutates = false, lista = false, notfound = '';
const arr = v => Array.isArray(v) ? v.map(String) : [];
switch (tipo) {
  case 'criar_agente': {
    if (!nomeOk || !p.objetivo) { extra = '⚠️ Preciso de nome (2–40 letras) e objetivo para cadastrar o agente.'; break; }
    const cfg = { conexoes_necessarias: arr(p.conexoes_necessarias), conexoes_ok: [], conexoes_pendentes: arr(p.conexoes_necessarias),
      acoes_requerem_conexao: arr(p.acoes_requerem_conexao), tarefa_teste: String(p.tarefa_teste || '') };
    sql = "INSERT INTO general_agentes (nome,objetivo,pode,nao_pode,ferramentas,prompt_sistema,ativo,status,teste_ok,config) VALUES ('" + nome + "','" + esc(p.objetivo) + "','" + esc(p.pode) + "','" + esc(p.nao_pode) + "','" + esc(p.ferramentas) + "','" + esc(p.prompt_sistema) + "',TRUE,'rascunho',FALSE,'" + esc(JSON.stringify(cfg)) + "'::jsonb) ON CONFLICT (nome) DO UPDATE SET objetivo=EXCLUDED.objetivo,pode=EXCLUDED.pode,nao_pode=EXCLUDED.nao_pode,ferramentas=EXCLUDED.ferramentas,prompt_sistema=EXCLUDED.prompt_sistema,config=EXCLUDED.config,ativo=TRUE,status='rascunho',teste_ok=FALSE,versao=general_agentes.versao+1 RETURNING id,nome,status;";
    extra = '📝 Agente "' + p.nome + '" cadastrado como RASCUNHO. Isso ainda NÃO é um agente funcional: falta o teste.' + (cfg.conexoes_necessarias.length ? ' Conexões necessárias: ' + cfg.conexoes_necessarias.join(', ') + '.' : '') + ' Diga "testar agente ' + p.nome + '" para validar.';
    mutates = true; notfound = 'não consegui gravar o agente.'; break; }
  case 'editar_agente':
    if (!nomeOk) { extra = '⚠️ Informe o nome do agente a editar.'; break; }
    sql = "UPDATE general_agentes SET objetivo=COALESCE(NULLIF('" + esc(p.objetivo) + "',''),objetivo),pode=COALESCE(NULLIF('" + esc(p.pode) + "',''),pode),nao_pode=COALESCE(NULLIF('" + esc(p.nao_pode) + "',''),nao_pode),ferramentas=COALESCE(NULLIF('" + esc(p.ferramentas) + "',''),ferramentas),prompt_sistema=COALESCE(NULLIF('" + esc(p.prompt_sistema) + "',''),prompt_sistema),status='rascunho',teste_ok=FALSE,versao=versao+1 WHERE nome='" + nome + "' RETURNING id,nome,status;";
    extra = '✏️ Agente "' + p.nome + '" editado. Volta a RASCUNHO até um novo teste ("testar agente ' + p.nome + '").';
    mutates = true; notfound = 'agente "' + p.nome + '" não encontrado.'; break;
  case 'pausar_agente':
    sql = "UPDATE general_agentes SET config=jsonb_set(COALESCE(config,'{}'::jsonb),'{status_pre_pausa}',to_jsonb(status)),status='pausado',ativo=FALSE WHERE nome='" + nome + "' AND status<>'pausado' RETURNING nome,status;";
    extra = '⏸️ Agente "' + p.nome + '" pausado.'; mutates = true; notfound = 'agente "' + p.nome + '" não encontrado ou já pausado.'; break;
  case 'reativar_agente':
    sql = "UPDATE general_agentes SET status=CASE WHEN teste_ok THEN COALESCE(NULLIF(config->>'status_pre_pausa','pausado'),'ativo') ELSE 'rascunho' END,ativo=TRUE WHERE nome='" + nome + "' AND status='pausado' RETURNING nome,status;";
    extra = '▶️ Agente "' + p.nome + '" reativado (se nunca passou em teste, volta como RASCUNHO).'; mutates = true; notfound = 'agente "' + p.nome + '" não encontrado ou não estava pausado.'; break;
  case 'marcar_conexao_pronta':
    sql = "UPDATE general_agentes SET config=jsonb_set(COALESCE(config,'{}'::jsonb),'{conexoes_ok}',COALESCE(config->'conexoes_ok','[]'::jsonb) || to_jsonb('" + esc(p.conexao) + "'::text)),status='rascunho',teste_ok=FALSE WHERE nome='" + nome + "' RETURNING nome,status;";
    extra = '🔌 Registrei a conexão "' + p.conexao + '" como pronta, mas ainda NÃO está verificada. Rode "testar agente ' + p.nome + '" para confirmar.';
    mutates = true; notfound = 'agente "' + p.nome + '" não encontrado.'; break;
  case 'status_agentes':
    sql = "SELECT nome,status,teste_ok,to_char(ultimo_teste,'DD/MM HH24:MI') AS ultimo_teste,ultimo_erro,versao FROM general_agentes ORDER BY id;"; lista = true; extra = '🪖 Agentes:'; break;
  case 'ver_erros_agente':
    sql = "SELECT task_id,state,erro,to_char(updated_at,'DD/MM HH24:MI') AS quando FROM general_tasks WHERE agent_name='" + nome + "' AND state IN ('failed','unknown') ORDER BY updated_at DESC LIMIT 5;"; lista = true; extra = '🚨 Últimos erros de ' + (p.nome || '?') + ':'; break;
  case 'consultar_tarefa':
    sql = "SELECT task_id,agent_name,state,result_pt,erro,to_char(updated_at,'DD/MM HH24:MI') AS quando FROM general_tasks WHERE chat_id='" + esc(e.chat_id) + "' AND ('" + esc(p.task_id) + "'='' OR task_id='" + esc(p.task_id) + "') ORDER BY created_at DESC LIMIT 5;"; lista = true; extra = '📋 Tarefas:'; break;
  case 'definir_preferencia_voz': {
    const on = p.ativo === true;
    sql = "INSERT INTO general_prefs (chat_id,voz_auto) VALUES ('" + esc(e.chat_id) + "'," + (on ? 'TRUE' : 'FALSE') + ") ON CONFLICT (chat_id) DO UPDATE SET voz_auto=EXCLUDED.voz_auto,updated_at=NOW() RETURNING voz_auto;";
    extra = on ? '🔊 Passo a responder sempre em voz (diga "sem áudio" para voltar ao texto).' : '💬 Voltei a responder em texto, exceto quando você pedir voz.';
    mutates = true; notfound = 'não consegui salvar a preferência.'; break; }
  case 'aprovar_pendencia':
    sql = "UPDATE general_pending SET status='APROVADO' WHERE id=" + Number(p.id || 0) + " AND chat_id='" + esc(e.chat_id) + "' AND status='PENDENTE' RETURNING id,acao;";
    extra = '✅ Pendência #' + p.id + ' aprovada.'; reexecutar = true; mutates = true;
    notfound = 'pendência #' + p.id + ' não está pendente (já processada, cancelada ou inexistente). Nada foi executado.'; break;
  case 'cancelar_pendencia':
    sql = "UPDATE general_pending SET status='CANCELADO' WHERE id=" + Number(p.id || 0) + " AND chat_id='" + esc(e.chat_id) + "' AND status='PENDENTE' RETURNING id;";
    extra = '❌ Pendência #' + p.id + ' cancelada.'; mutates = true; notfound = 'pendência #' + p.id + ' não está pendente.'; break;
  case 'consultar_sql': {
    const q = String(p.query || '').trim().replace(/;+\s*$/, '');
    if (!/^select\b/i.test(q) || q.includes(';') || /\b(pg_sleep|pg_read_file|pg_ls_dir|lo_import|dblink|copy)\b/i.test(q)) { extra = '⚠️ Só consultas SELECT simples são permitidas.'; break; }
    sql = 'SELECT * FROM (' + q + ') AS _q LIMIT 50;'; lista = true; extra = '📊 Resultado:'; break; }
  default:
    extra = '⚠️ Ação não reconhecida: ' + tipo + '. Nada foi executado.';
}
return [{ json: { ...e, sql, extra, reply_text: e.reply_text, chat_id: e.chat_id, user_id: e.user_id, tipo, reexecutar, mutates, lista, notfound } }];""")
js("Resultado SQL", r"""const rows = $input.all().map(i => i.json).filter(r => r && Object.keys(r).length > 0 && !(Object.keys(r).length === 1 && 'success' in r));
const prev = $('Montar SQL').first().json;
let reply = prev.extra || prev.reply_text || '';
let reexecutar = false, acao = null, tipo = prev.tipo, pendencia_id = null;

if (prev.mutates && rows.length === 0) {
  reply = '⚠️ Nada foi alterado: ' + (prev.notfound || 'registro não encontrado') + ' Não confirmo a operação.';
} else if (prev.reexecutar && rows[0] && rows[0].acao) {
  try {
    acao = typeof rows[0].acao === 'string' ? JSON.parse(rows[0].acao) : rows[0].acao;
    tipo = acao.type || acao.tipo || null;
    pendencia_id = rows[0].id;
    reexecutar = !!tipo;
    reply += '\n⏳ Executando a ação aprovada (acompanhe o resultado abaixo).';
  } catch (e) { reply = '⚠️ A pendência aprovada tem uma ação ilegível; nada foi executado.'; }
}
if (prev.lista) {
  reply += rows.length ? '\n' + rows.map(r => Object.entries(r).map(([k, v]) => k + '=' + (v === null ? '-' : (typeof v === 'object' ? JSON.stringify(v) : v))).join(' | ')).join('\n').slice(0, 3000) : '\n(sem resultados)';
}
return [{ json: { ...prev, reply_text: reply, reexecutar, acao, tipo, pendencia_id } }];""")
NODES["Executar SQL"]["parameters"]["query"] = "={{ $json.sql }}"
clear_out("Resultado SQL")
link("Resultado SQL", "Reexecutar?")
CONN["Reexecutar?"]["main"][1] = [{"node": "Áudio?", "type": "main", "index": 0}]
set_params("Enviar Input General", additionalFields={"appendAttribution": False})


js("Prep Input General", r"""const g = $input.first().json;
const inp = g.need_user_input || {};
const task_id = 't' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
const agent_name = 'General';
const input_type = ['otp', 'password', 'captcha', 'confirm'].includes(inp.input_type) ? inp.input_type : 'otp';
const prompt_pt = inp.prompt_pt || g.reply_text || 'Me envie o código aqui.';
const has_image = inp.has_image === true;
return [{ json: { chat_id: g.chat_id, task_id, agent_name, input_type, prompt_pt, has_image, payload: inp.payload || {}, reply_text: g.reply_text } }];""")
set_params("Salvar Input General", query="""INSERT INTO general_waiting_input (chat_id,id_tarefa,agent_name,input_type,prompt_pt,payload,has_image) VALUES ('{{ $json.chat_id }}','{{ $json.task_id }}','General','{{ $json.input_type }}','{{ String($json.prompt_pt || '').replace(/'/g, "''") }}',('{{ JSON.stringify($json.payload || {}).replace(/'/g, "''") }}')::jsonb,{{ $json.has_image ? 'TRUE' : 'FALSE' }}) ON CONFLICT (chat_id,id_tarefa) DO NOTHING;""")
NODES["Salvar Input General"]["alwaysOutputData"] = True

# ---- Acompanhamento de tarefas longas (Worker: running -> estado final)
add("Acompanhar Tarefas", "n8n-nodes-base.scheduleTrigger", 1.2,
    {"rule": {"interval": [{"field": "minutes", "minutesInterval": 1}]}}, pos=[-300, 2700])
pg("Tarefas Running", """SELECT task_id,chat_id,agent_name FROM general_tasks WHERE state='running' AND destino='worker' AND created_at > NOW() - INTERVAL '2 hours' AND updated_at < NOW() - INTERVAL '20 seconds' ORDER BY created_at LIMIT 5;""", pos=[-60, 2700])
code("Montar Consulta", r"""const WORKER_URL = 'http://100.107.36.118:8787';
return $input.all().filter(i => i.json.task_id).map(i => ({ json: { ...i.json, destino: 'worker', url: WORKER_URL + '/task/' + i.json.task_id, body: { task_id: i.json.task_id } } }));""", pos=[180, 2700])
http("Consultar Worker", CRED_WORKER, 30000, method="GET", pos=[420, 2700])
code("Parse Consulta", NORMALIZE_JS + MSG_JS + r"""
const ctxs = $('Montar Consulta').all();
const out = [];
$input.all().forEach((it, i) => {
  const ctx = ctxs[i].json;
  const n = normalize(it.json, ctx);
  if (n.state === 'running') return;                // ainda em andamento: tenta de novo no próximo ciclo
  const s = { ...ctx, state: n.state, verified: n.verified, reason: n.reason, result_pt: n.result_pt, evidence: n.evidence, origem: 'acompanhamento' };
  out.push({ json: { ...s, reply_text: buildMsg(s) } });
});
return out;""", pos=[660, 2700])
pg("Atualizar Tarefa Poll", """UPDATE general_tasks SET state='{{ $json.state }}', result_pt='{{ String($json.result_pt || '').replace(/'/g, "''").slice(0, 1500) }}', evidence=('{{ JSON.stringify({ evidence: $json.evidence || {}, verified: $json.verified === true, reason: $json.reason || '' }).replace(/'/g, "''") }}')::jsonb, erro=NULLIF('{{ String($json.reason || '').replace(/'/g, "''").slice(0, 500) }}',''), updated_at=NOW() WHERE task_id='{{ $json.task_id }}' RETURNING task_id;""",
   always=True, pos=[900, 2700])
code("Msg Poll", r"""return $('Parse Consulta').all().map(i => ({ json: { chat_id: i.json.chat_id, reply_text: '🔔 Atualização de tarefa\n' + i.json.reply_text } }));""", pos=[1140, 2700])
tg("Avisar Tarefa", "={{ $json.chat_id }}", "={{ String($json.reply_text).slice(0, 4000) }}", pos=[1380, 2700])
link("Acompanhar Tarefas", "Tarefas Running")
link("Tarefas Running", "Montar Consulta")
link("Montar Consulta", "Consultar Worker")
link("Consultar Worker", "Parse Consulta")
link("Parse Consulta", "Atualizar Tarefa Poll")
link("Atualizar Tarefa Poll", "Msg Poll")
link("Msg Poll", "Avisar Tarefa")

# ---- remoção de nós substituídos
remove("Chamar Agente", "Chamar Retomar", "Formatar Retorno", "Resposta Retomar", "Resposta Exec", "Resposta SQL",
       "Executar Aprovado", "Resultado Aprovado", "Enviar Aprovado", "Só Erro Aprovado?")
# Precisa Input? true -> Salvar Aguardando; false -> Resultado OK (já ligados no original)

wf["nodes"] = list(NODES.values())
wf["connections"] = CONN
wf["name"] = "GENERAL V10"
wf["active"] = False
wf.pop("id", None)   # sem id: a importação cria um workflow NOVO e não sobrescreve o ativo


def fix_expr(v, key=""):
    """Parâmetro com {{ }} só é expressão no n8n se começar com '='. (No V9 as 10 queries não tinham.)"""
    if isinstance(v, str):
        return "=" + v if ("{{" in v and not v.startswith("=") and key != "jsCode") else v
    if isinstance(v, list):
        return [fix_expr(x, key) for x in v]
    if isinstance(v, dict):
        return {k: fix_expr(x, k) for k, x in v.items()}
    return v


for _n in wf["nodes"]:
    _n["parameters"] = fix_expr(_n["parameters"])
wf["versionId"] = str(uuid.uuid5(uuid.NAMESPACE_DNS, "general-v10-version"))
wf.setdefault("meta", {})
OUT.write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")
print("GENERAL V10:", len(wf["nodes"]), "nós")

# ============================================================================= AGENTE EXECUTOR v1
EN, EC = {}, {}


def e_add(name, typ, ver, params, cred=None, pos=None, **extra):
    n = {"parameters": params, "id": nid("exec/" + name), "name": name, "type": typ, "typeVersion": ver, "position": pos}
    if cred:
        n["credentials"] = cred
    n.update(extra)
    EN[name] = n


def e_link(a, b, out=0):
    c = EC.setdefault(a, {}).setdefault("main", [])
    while len(c) <= out:
        c.append([])
    c[out].append({"node": b, "type": "main", "index": 0})


e_add("Executor Webhook", "n8n-nodes-base.webhook", 2,
      {"httpMethod": "POST", "path": "agente-executor", "authentication": "headerAuth", "responseMode": "responseNode", "options": {}},
      cred=hdr("Agente Executor (webhook)"), pos=[0, 300], webhookId=nid("exec/webhook"))
e_add("Carregar Agente", "n8n-nodes-base.postgres", 2.5,
      {"operation": "executeQuery", "query": "SELECT nome,objetivo,pode,nao_pode,ferramentas,prompt_sistema,status,teste_ok,config FROM general_agentes WHERE nome='{{ String($json.body.agent || '').replace(/'/g, \"''\") }}' LIMIT 1;", "options": {}},
      cred=PG, pos=[240, 300], alwaysOutputData=True)
e_add("Preparar", "n8n-nodes-base.code", 2, {"jsCode": r"""const body = $('Executor Webhook').first().json.body || {};
const ag = $input.first().json;
const task_id = String(body.task_id || '');
const acao = String(body.acao || 'preparar_conteudo');
const respond = (status, result_pt, error_code, meta) => [{ json: { run: false, contract: { task_id, status, result_pt, ...(error_code ? { error_code } : {}), evidence: { verified: false, checks: [] }, ...(meta ? { meta } : {}) } } }];
if (!task_id) return respond('failed', 'task_id ausente.', 'BAD_TASK_ID');
if (!ag.nome) return respond('failed', 'Agente "' + (body.agent || '?') + '" não existe no catálogo.', 'AGENT_NOT_FOUND');
const cfg = ag.config || {};
const necess = Array.isArray(cfg.conexoes_necessarias) ? cfg.conexoes_necessarias : [];
const ok = Array.isArray(cfg.conexoes_ok) ? cfg.conexoes_ok : [];
const pendentes = necess.filter(c => !ok.includes(c));
if (ag.status === 'pausado') return respond('failed', 'O agente está pausado.', 'AGENT_PAUSED');
const isTeste = acao === 'teste';
if (!isTeste && !(['ativo', 'aguardando_conexao'].includes(ag.status) && ag.teste_ok === true)) return respond('failed', 'O agente ainda não passou no teste (status: ' + ag.status + '). Rode o teste antes.', 'AGENT_NOT_TESTED');
const requerConexao = /^(publicar|postar|enviar)/i.test(acao) || (Array.isArray(cfg.acoes_requerem_conexao) && cfg.acoes_requerem_conexao.includes(acao));
if (requerConexao && pendentes.length) return respond('failed', 'Aguardando conexão: ' + pendentes.join(', ') + '. Configure a credencial no n8n e diga que está pronta.', 'CONNECTION_MISSING', { conexoes_pendentes: pendentes });
if (!['teste', 'preparar_conteudo', 'responder'].includes(acao)) return respond('failed', 'A ação "' + acao + '" não é implementada neste modelo (v1 só cobre preparar_conteudo/responder/teste). Publicar/integrar exige um template de integração próprio.', 'NOT_IMPLEMENTED', { conexoes_pendentes: pendentes });
const tarefa = isTeste ? (cfg.tarefa_teste || 'Apresente-se em duas frases: quem você é e o que consegue fazer.') : String(body.tarefa || '');
if (!tarefa.trim()) return respond('failed', 'Tarefa vazia.', 'EMPTY_TASK');
const system = (ag.prompt_sistema || 'Você é um agente especialista.') +
  '\n\nOBJETIVO: ' + ag.objetivo + '\nPODE: ' + ag.pode + '\nNÃO PODE: ' + ag.nao_pode + '\nFERRAMENTAS DECLARADAS: ' + ag.ferramentas +
  '\n\nREGRAS: você só PREPARA conteúdo e respostas (texto). Você não publica, não envia e não acessa contas externas. Se a tarefa exigir algo fora do que PODE, diga claramente que não pode. Responda em português.';
return [{ json: { run: true, task_id, agent: ag.nome, acao, tarefa, system, pendentes } }];"""}, pos=[480, 300])
e_add("Pode Executar?", "n8n-nodes-base.if", 2.2, {
    "conditions": {"options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 1},
                   "conditions": [{"id": "pe1", "leftValue": "={{ $json.run }}", "rightValue": "={{true}}", "operator": {"type": "boolean", "operation": "true"}}],
                   "combinator": "and"}, "options": {}}, pos=[720, 300])
e_add("Agente LLM", "@n8n/n8n-nodes-langchain.agent", 1.7,
      {"promptType": "define", "text": "={{ $json.tarefa }}", "options": {"systemMessage": "={{ $json.system }}"}},
      pos=[960, 220], onError="continueRegularOutput")
e_add("Modelo", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2,
      {"model": {"__rl": True, "value": "gpt-4.1", "mode": "list", "cachedResultName": "gpt-4.1"}, "options": {"temperature": 0.4}},
      cred=OAI, pos=[960, 460])
e_add("Preparar Artefato", "n8n-nodes-base.code", 2, {"jsCode": r"""const p = $('Preparar').first().json;
const r = $input.first().json;
const out = typeof r.output === 'string' ? r.output.trim() : '';
if (r.error || !out) return [{ json: { ...p, falha: true, motivo: String((r.error && (r.error.message || r.error)) || 'o modelo não devolveu conteúdo').slice(0, 300) } }];
return [{ json: { ...p, falha: false, conteudo: out, conteudo_esc: out.replace(/'/g, "''"), tam: out.length } }];"""}, pos=[1240, 220])
e_add("Salvar Artefato", "n8n-nodes-base.postgres", 2.5,
      {"operation": "executeQuery", "query": "{{ $json.falha ? 'SELECT 0 AS id WHERE FALSE;' : \"INSERT INTO general_artifacts (task_id,agent_name,tipo,conteudo) VALUES ('\" + $json.task_id + \"','\" + String($json.agent).replace(/'/g, \"''\") + \"','\" + $json.acao + \"','\" + $json.conteudo_esc + \"') RETURNING id;\" }}", "options": {}},
      cred=PG, pos=[1480, 220], alwaysOutputData=True)
e_add("Verificar Artefato", "n8n-nodes-base.postgres", 2.5,
      {"operation": "executeQuery", "query": "SELECT id, length(conteudo) AS len FROM general_artifacts WHERE id = {{ Number($json.id || 0) }} AND task_id = '{{ $('Preparar Artefato').first().json.task_id }}';", "options": {}},
      cred=PG, pos=[1720, 220], alwaysOutputData=True)
e_add("Montar Resposta", "n8n-nodes-base.code", 2, {"jsCode": r"""// Evidência = leitura de volta do banco (não o texto do modelo).
const p = $('Preparar Artefato').first().json;
const row = $input.first().json;
const c = { task_id: p.task_id };
if (p.falha) { c.status = 'failed'; c.result_pt = 'A geração falhou: ' + p.motivo; c.error_code = 'LLM_FAILED'; c.evidence = { verified: false, checks: [] }; }
else if (row.id && Number(row.len) === p.tam) {
  c.status = 'completed';
  c.result_pt = (p.acao === 'teste' ? 'Teste do agente concluído (geração + registro; NÃO testa integrações externas). ' : 'Rascunho gerado e salvo. Nada foi publicado/enviado. ') + 'Artefato #' + row.id + ':\n' + p.conteudo.slice(0, 700);
  c.evidence = { verified: true, kind: 'artifact', checks: [{ type: 'artifact_saved', id: row.id, ok: true, length: p.tam }] };
} else { c.status = 'failed'; c.result_pt = 'O conteúdo foi gerado, mas não consegui confirmar o registro no banco.'; c.error_code = 'ARTIFACT_NOT_CONFIRMED'; c.evidence = { verified: false, checks: [{ type: 'artifact_saved', ok: false }] }; }
c.meta = { conexoes_pendentes: p.pendentes || [] };
return [{ json: { contract: c } }];"""}, pos=[1960, 220])
e_add("Responder", "n8n-nodes-base.respondToWebhook", 1.1,
      {"respondWith": "json", "responseBody": "={{ $json.contract }}", "options": {}}, pos=[2200, 300])
e_link("Executor Webhook", "Carregar Agente")
e_link("Carregar Agente", "Preparar")
e_link("Preparar", "Pode Executar?")
e_link("Pode Executar?", "Agente LLM", 0)
e_link("Pode Executar?", "Responder", 1)
e_link("Agente LLM", "Preparar Artefato")
e_link("Preparar Artefato", "Salvar Artefato")
e_link("Salvar Artefato", "Verificar Artefato")
e_link("Verificar Artefato", "Montar Resposta")
e_link("Montar Resposta", "Responder")
EC.setdefault("Modelo", {})["ai_languageModel"] = [[{"node": "Agente LLM", "type": "ai_languageModel", "index": 0}]]
for _n in EN.values():
    _n["parameters"] = fix_expr(_n["parameters"])
execwf = {"name": "AGENTE EXECUTOR v1", "nodes": list(EN.values()), "connections": EC, "active": False, "pinData": {},
          "settings": {"executionOrder": "v1"}, "meta": {"templateCredsSetupCompleted": False}, "tags": []}
OUT_EXEC.write_text(json.dumps(execwf, ensure_ascii=False, indent=2), encoding="utf-8")
print("AGENTE EXECUTOR v1:", len(execwf["nodes"]), "nós")
