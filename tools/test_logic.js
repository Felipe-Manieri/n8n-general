// Testes da lógica dos nós Code do GENERAL V10 e do AGENTE EXECUTOR v1, com respostas simuladas.
// Uso: node tools/test_logic.js   (não toca no n8n, no banco nem na rede)
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const V10 = JSON.parse(fs.readFileSync(path.join(root, 'GENERAL_V10_EXERCITO.json'), 'utf8'));
const EXE = JSON.parse(fs.readFileSync(path.join(root, 'AGENTE_EXECUTOR_v1.json'), 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;

let pass = 0, fail = 0;
function check(name, cond, detail) {
  if (cond) { pass++; console.log('PASS ' + name); }
  else { fail++; console.log('FAIL ' + name + (detail !== undefined ? '  -> ' + JSON.stringify(detail).slice(0, 400) : '')); }
}

// executa o jsCode de um nó com um contexto simulado
async function run(wf, nodeName, input, refs = {}) {
  const node = wf.nodes.find(n => n.name === nodeName);
  if (!node) throw new Error('nó não existe: ' + nodeName);
  const items = Array.isArray(input) ? input : [input];
  const $input = { first: () => ({ json: items[0] }), all: () => items.map(j => ({ json: j })) };
  const $ = (name) => {
    if (!(name in refs)) throw new Error("Node '" + name + "' hasn't been executed");
    const r = Array.isArray(refs[name]) ? refs[name] : [refs[name]];
    return { first: () => ({ json: r[0] }), all: () => r.map(j => ({ json: j })) };
  };
  const fn = new AsyncFunction('$input', '$', '$json', node.parameters.jsCode);
  const out = await fn($input, $, items[0]);
  return out.map(o => o.json);
}

const CFG = { CENTRAL_URL: 'http://central/task', WORKER_URL: 'http://worker:8787', EXECUTOR_URL: 'http://n8n/webhook/agente-executor' };
const ctxWorker = { destino: 'worker', task_id: 't1', body: { task_id: 't1' }, chat_id: '1', user_id: 1, agent_name: 'PC', tipo: 'executar_pc', origem: 'direto' };
const okEvidence = { verified: true, checks: [{ type: 'file_exists', path: 'C:\\x.txt', ok: true }] };

(async () => {
  // ---------------------------------------------------------------- Parse Agente + Resultado OK (estados)
  const parse = async (res, ctx = ctxWorker) => (await run(V10, 'Parse Agente', res, { 'Preparar Tarefa': ctx }))[0];
  const msg = async (s) => (await run(V10, 'Resultado OK', s))[0].reply_text;

  let s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', result_pt: 'feito', evidence: okEvidence } });
  check('completed + evidência verificável -> verified', s.state === 'completed' && s.verified === true, s);
  check('"✅ Executado" aparece só com evidência', (await msg(s)).includes('✅ Executado e verificado'));
  check('mensagem traz o ID da tarefa', (await msg(s)).includes('Tarefa: t1'));

  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', result_pt: 'ok', evidence: { verified: false, checks: [] } } });
  check('completed SEM evidência -> não verificado', s.state === 'completed' && s.verified === false, s);
  let m = await msg(s);
  check('sem evidência: NÃO diz "✅ Executado"', !m.includes('✅') && m.includes('SEM verificação'), m);

  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', evidence: { verified: true, checks: [] } } });
  check('verified:true declarado sem checks não vale', s.verified === false, s);
  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', evidence: { verified: true, checks: [{ ok: true }, { ok: false }] } } });
  check('uma checagem com ok:false invalida a evidência', s.verified === false, s);

  s = await parse({ statusCode: 200, body: { ok: true, stdout: 'qualquer coisa', stderr: '' } });
  check('HTTP 200 + formato legado {ok:true} -> desconhecido', s.state === 'unknown' && s.is_error === true, s);
  m = await msg(s);
  check('desconhecido: mensagem diz que NÃO confirmou', m.includes('❓') && !m.includes('✅') && m.includes('não confirmei'), m);

  s = await parse({ statusCode: 200, body: '' });
  check('resposta vazia -> desconhecido', s.state === 'unknown', s);
  s = await parse({ statusCode: 200, body: { status: 'sucesso!!' } });
  check('status fora do contrato -> desconhecido', s.state === 'unknown', s);
  s = await parse({ statusCode: 200, body: { task_id: 'outra', status: 'completed', evidence: okEvidence } });
  check('task_id divergente -> desconhecido (não confia)', s.state === 'unknown' && /difere/.test(s.reason), s);

  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'failed', result_pt: 'não achei', error_code: 'X' } });
  check('failed do agente -> failed', s.state === 'failed' && s.is_error, s);
  check('failed: mensagem começa com ❌', (await msg(s)).includes('❌ Falhou'));

  s = await parse({ statusCode: 500, body: { ok: false, error: 'PC_CALL_FAILED', detail: 'ConnectTimeoutError 100.107.36.118:8787' } }, { ...ctxWorker, destino: 'central' });
  check('HTTP 500 do Central (PC_CALL_FAILED) -> failed com detalhe', s.state === 'failed' && /PC_CALL_FAILED|ConnectTimeout/.test(s.reason), s);
  s = await parse({ error: { message: 'The connection timed out' } });
  check('timeout de rede -> failed', s.state === 'failed' && /timed out/.test(s.reason), s);
  s = await parse({ statusCode: 401, body: { status: 'failed', error_code: 'UNAUTHORIZED' } });
  check('HTTP 401 -> failed', s.state === 'failed', s);

  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'running', result_pt: 'rodando' } });
  m = await msg(s);
  check('running -> "Em andamento" (sem ✅)', s.state === 'running' && m.includes('⏳') && !m.includes('✅'), m);

  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'waiting_input', input_type: 'otp', prompt_pt: 'Envie o código', has_image: false, payload: { a: 1 } } });
  check('waiting_input -> need_input true', s.need_input === true && s.input_type === 'otp' && s.payload_in.a === 1, s);

  // teste de agente: status derivado do resultado
  const ctxTeste = { ...ctxWorker, destino: 'executor', tipo: 'testar_agente', agent_name: 'Instagram' };
  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', evidence: { verified: true, checks: [{ type: 'artifact_saved', id: 3, ok: true }] }, meta: { conexoes_pendentes: ['instagram_graph'] } } }, ctxTeste);
  check('teste ok + conexão pendente -> aguardando_conexao (teste_ok)', s.agente_status.status === 'aguardando_conexao' && s.agente_status.teste_ok === true, s.agente_status);
  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', evidence: { verified: true, checks: [{ type: 'artifact_saved', id: 3, ok: true }] }, meta: { conexoes_pendentes: [] } } }, ctxTeste);
  check('teste ok sem pendências -> ativo', s.agente_status.status === 'ativo', s.agente_status);
  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', result_pt: 'texto sem evidência' } }, ctxTeste);
  check('teste SEM evidência -> erro (não ativa agente)', s.agente_status.status === 'erro' && s.agente_status.teste_ok === false, s.agente_status);
  s = await parse({ statusCode: 200, body: { task_id: 't1', status: 'failed', error_code: 'CONNECTION_MISSING', meta: { conexoes_pendentes: ['x'] } } }, ctxTeste);
  check('CONNECTION_MISSING -> aguardando_conexao', s.agente_status.status === 'aguardando_conexao', s.agente_status);
  m = await msg({ ...s, agente_status: { status: 'ativo', pendentes: [] } });
  check('mensagem de teste mostra o status do agente', m.includes('Status do agente: ativo'), m);

  // ação aprovada usa a mesma mensagem e cita a pendência
  m = await msg({ ...(await parse({ statusCode: 200, body: { task_id: 't1', status: 'completed', evidence: okEvidence } })), origem: 'aprovacao', pendencia_id: 7 });
  check('ação aprovada: cita pendência e exige a mesma evidência', m.includes('pendência #7') && m.includes('✅ Executado'), m);

  // ---------------------------------------------------------------- Forçar Aprovação
  const fa = async (tipo, payload, text = 'faça', need = false) => (await run(V10, 'Forçar Aprovação', { action: { type: tipo, payload }, text, need_approval: need }))[0].need_approval;
  check('executar_pc exige aprovação', (await fa('executar_pc', {})) === true);
  check('criar_arquivo_pc exige aprovação', (await fa('criar_arquivo_pc', {})) === true);
  check('openclaw exige aprovação', (await fa('openclaw', {})) === true);
  check('executar_agente publicar_* exige aprovação', (await fa('executar_agente', { acao: 'publicar_post' })) === true);
  check('executar_agente preparar_conteudo não exige', (await fa('executar_agente', { acao: 'preparar_conteudo' })) === false);
  check('CONFIRMO ALFA dispensa aprovação só naquela mensagem', (await fa('executar_pc', {}, 'CONFIRMO ALFA rode isso')) === false);
  check('ações internas nunca viram pendência externa', (await fa('criar_agente', {}, 'x', true)) === false);

  // ---------------------------------------------------------------- Voz (Parse)
  const parseGeneral = async (text, extra = {}, out = {}) => (await run(V10, 'Parse', { output: JSON.stringify({ reply_text: 'ok', action: null, ...out }) }, { Contexto: { text, chat_id: '1', user_id: 1, ...extra } }))[0].generate_audio;
  for (const t of ['responda em voz', 'me manda áudio', 'manda um audio pra mim', 'estou dirigindo', 'fale comigo em áudio', 'responde por voz']) {
    check('pede voz: "' + t + '"', (await parseGeneral(t)) === true);
  }
  check('texto comum NÃO liga voz', (await parseGeneral('qual o status dos agentes?')) === false);
  check('mensagem que veio de áudio NÃO liga voz sozinha', (await parseGeneral('transcrição de um áudio qualquer sobre reunião')) === false);
  check('preferência salva liga voz', (await parseGeneral('oi', { voz_auto: true })) === true);
  check('"sem áudio" desliga mesmo com preferência', (await parseGeneral('pode ser sem áudio agora', { voz_auto: true })) === false);
  check('modelo pediu áudio -> respeita', (await parseGeneral('oi', {}, { generate_audio: true })) === true);
  const pr = (await run(V10, 'Parse', { output: 'texto solto sem json' }, { Contexto: { text: 'oi', chat_id: '1', user_id: 1 } }))[0];
  check('saída do modelo sem JSON não quebra', pr.reply_text === 'texto solto sem json' && pr.action === null, pr);

  // ---------------------------------------------------------------- Montar Endpoint / Prep Reexecução (sem tokens)
  let e = { tipo: 'executar_pc', payload: { command: 'Get-Date', verify: [{ type: 'file_exists', path: 'C:\\a' }] }, task_id: 't9', chat_id: '1', user_id: 1, agent_name: 'PC', text: 'x', generate_audio: true };
  let me = (await run(V10, 'Montar Endpoint', e, { Config: CFG }))[0];
  check('executar_pc -> Worker /task com contrato', me.destino === 'worker' && me.url === 'http://worker:8787/task' && me.body.action === 'powershell' && me.body.task_id === 't9' && me.body.verify.length === 1, me);
  check('voz pedida é preservada até a resposta', me.generate_audio === true);
  me = (await run(V10, 'Montar Endpoint', { ...e, tipo: 'criar_arquivo_pc', payload: { path: 'C:\\Users\\x\\a.txt', content: 'oi' } }, { Config: CFG }))[0];
  check('criar_arquivo_pc -> action create_file', me.body.action === 'create_file' && me.body.path.endsWith('a.txt'), me);
  me = (await run(V10, 'Montar Endpoint', { ...e, tipo: 'openclaw', payload: { url: 'https://x.com', instructions: 'clique' } }, { Config: CFG }))[0];
  check('openclaw -> Central /task {task,task_id}', me.destino === 'central' && me.url === 'http://central/task' && /^Abra https:\/\/x.com/.test(me.body.task) && me.body.task_id === 't9', me);
  me = (await run(V10, 'Montar Endpoint', { ...e, tipo: 'executar_agente', payload: { nome: 'Insta', acao: 'preparar_conteudo', tarefa: 'post' } }, { Config: CFG }))[0];
  check('executar_agente -> Executor', me.destino === 'executor' && me.body.agent === 'Insta' && me.body.acao === 'preparar_conteudo', me);
  me = (await run(V10, 'Montar Endpoint', { ...e, tipo: 'testar_agente', payload: { nome: 'Insta' } }, { Config: CFG }))[0];
  check('testar_agente -> acao "teste"', me.body.acao === 'teste', me);
  me = (await run(V10, 'Montar Endpoint', { ...e, tipo: 'coisa_estranha' }, { Config: CFG }))[0];
  check('tipo desconhecido -> destino inválido (não vai para lugar nenhum)', me.destino === 'invalido', me);
  const jsonText = JSON.stringify(V10);
  check('nenhum token/segredo em texto no workflow', !/MEU_TOKEN|X-AGENT-TOKEN\"\s*,\s*\"value|e4cb4023/.test(jsonText));

  const rx = (await run(V10, 'Prep Reexecução', { acao: { type: 'executar_pc', payload: { command: 'x' }, meta: { task_id: 't-orig', generate_audio: true } }, chat_id: '1', user_id: 1, pendencia_id: 5, generate_audio: false }, { Config: CFG }))[0];
  check('aprovada: mantém o task_id do pedido original', rx.task_id === 't-orig' && rx.body.task_id === 't-orig', rx);
  check('aprovada: executa a ação GRAVADA e mantém preferência de voz', rx.body.command === 'x' && rx.generate_audio === true && rx.origem === 'aprovacao' && rx.pendencia_id === 5, rx);

  // ---------------------------------------------------------------- Pendência
  const pp = (await run(V10, 'Prep Pendência', { action: { type: 'executar_pc', payload: { command: "echo 'oi'" } }, reply_text: "vou rodar 'x'", approval_preview: "Rodar 'x'", chat_id: '1', user_id: 1, generate_audio: true }))[0];
  const acaoGravada = JSON.parse(pp.acao_json.replace(/''/g, "'"));
  check('pendência guarda task_id + voz na ação', /^t\d+-/.test(pp.task_id) && acaoGravada.meta.task_id === pp.task_id && acaoGravada.meta.generate_audio === true, acaoGravada);
  check('aspas escapadas para SQL', pp.previa_esc.includes("''x''"), pp.previa_esc);
  const fp = (await run(V10, 'Formatar Prévia', { id: 12 }, { 'Prep Pendência': { ...pp, approval_preview: "Rodar 'x' no PC" } }))[0];
  check('prévia legível (sem aspas duplicadas, com ID e escopo)', fp.txt.includes("Rodar 'x' no PC") && !fp.txt.includes("''") && fp.txt.includes('aprovar 12') && fp.txt.includes('só para esta ação'), fp.txt);

  // ---------------------------------------------------------------- Ctx Tarefa (duplicidade)
  check('task_id duplicado NÃO executa de novo', (await run(V10, 'Ctx Tarefa', [{}], { 'Preparar Tarefa': ctxWorker })).length === 0);
  check('task_id novo executa', (await run(V10, 'Ctx Tarefa', [{ task_id: 't1' }], { 'Preparar Tarefa': ctxWorker })).length === 1);

  // ---------------------------------------------------------------- Montar SQL / Resultado SQL (agentes)
  const ms = async (tipo, payload, extra = {}) => (await run(V10, 'Montar SQL', { tipo, payload, chat_id: '1', user_id: 1, reply_text: 'x', ...extra }))[0];
  let q = await ms('criar_agente', { nome: 'Instagram', objetivo: "cuidar do Insta d'a marca", pode: 'rascunhos', nao_pode: 'publicar sem aprovar', ferramentas: 'llm', prompt_sistema: 'p', conexoes_necessarias: ['instagram_graph'], tarefa_teste: 'gere um post' });
  check('criar_agente grava como RASCUNHO (não funcional)', /'rascunho',FALSE/.test(q.sql) && q.extra.includes('RASCUNHO') && q.extra.includes('NÃO é um agente funcional') && q.extra.includes('instagram_graph'), q);
  check('criar_agente escapa aspas', q.sql.includes("d''a marca"));
  q = await ms('criar_agente', { nome: 'x', objetivo: '' });
  check('criar_agente sem dados não grava', q.sql === 'SELECT 1;' && q.extra.includes('Preciso'), q);
  q = await ms('criar_agente', { nome: "a'; DROP TABLE general_agentes;--", objetivo: 'o' });
  check('nome malicioso é recusado (não vai para o SQL)', q.sql === 'SELECT 1;' && !q.sql.includes('DROP'), q.sql);
  q = await ms('editar_agente', { nome: 'Instagram', objetivo: 'novo' });
  check('editar_agente volta a RASCUNHO e exige novo teste', /status='rascunho',teste_ok=FALSE/.test(q.sql) && q.extra.includes('novo teste'), q);
  q = await ms('pausar_agente', { nome: 'Instagram' });
  check('pausar_agente grava status pausado e o estado anterior', /status='pausado'/.test(q.sql) && /status_pre_pausa/.test(q.sql), q.sql);
  q = await ms('reativar_agente', { nome: 'Instagram' });
  check('reativar só reativa teste_ok, senão rascunho', /CASE WHEN teste_ok THEN/.test(q.sql) && /ELSE 'rascunho'/.test(q.sql), q.sql);
  q = await ms('marcar_conexao_pronta', { nome: 'Instagram', conexao: 'instagram_graph' });
  check('marcar conexão NÃO ativa o agente (exige novo teste)', /status='rascunho',teste_ok=FALSE/.test(q.sql) && q.extra.includes('NÃO está verificada'), q);
  q = await ms('status_agentes', {});
  check('status_agentes é só SELECT', /^SELECT/.test(q.sql) && q.lista === true);
  q = await ms('ver_erros_agente', { nome: 'Instagram' });
  check('ver_erros lê general_tasks com falhas', /general_tasks/.test(q.sql) && /'failed','unknown'/.test(q.sql));
  q = await ms('definir_preferencia_voz', { ativo: true });
  check('preferência de voz grava por chat', /general_prefs/.test(q.sql) && /TRUE/.test(q.sql));
  q = await ms('aprovar_pendencia', { id: 5 });
  check('aprovar_pendencia só da própria conversa e ainda pendente', /chat_id='1'/.test(q.sql) && /status='PENDENTE'/.test(q.sql) && q.reexecutar === true, q.sql);
  q = await ms('consultar_sql', { query: 'SELECT * FROM general_tasks' });
  check('consultar_sql SELECT simples passa (com LIMIT)', /^SELECT \* FROM \(SELECT \* FROM general_tasks\) AS _q LIMIT 50;$/.test(q.sql), q.sql);
  for (const bad of ['DROP TABLE general_logs', 'DELETE FROM general_logs', 'SELECT 1; DELETE FROM general_logs', 'SELECT pg_sleep(30)', 'UPDATE general_logs SET tipo=1', "SELECT * FROM x; --"]) {
    q = await ms('consultar_sql', { query: bad });
    check('consultar_sql recusa: ' + bad, q.sql === 'SELECT 1;' && q.extra.includes('SELECT'), q.sql);
  }
  q = await ms('acao_inventada', {});
  check('ação desconhecida não faz nada', q.sql === 'SELECT 1;' && q.extra.includes('Nada foi executado'));

  const rs = async (prev, rows) => (await run(V10, 'Resultado SQL', rows.length ? rows : [{}], { 'Montar SQL': prev }))[0];
  let r = await rs({ tipo: 'aprovar_pendencia', extra: '✅ Pendência #5 aprovada.', reexecutar: true, mutates: true, notfound: 'pendência #5 não está pendente.', payload: { id: 5 } }, []);
  check('aprovar pendência inexistente/repetida: NÃO reexecuta e avisa', r.reexecutar === false && r.reply_text.includes('Nada foi alterado'), r);
  r = await rs({ tipo: 'aprovar_pendencia', extra: '✅ Pendência #5 aprovada.', reexecutar: true, mutates: true, payload: { id: 5 } }, [{ id: 5, acao: { type: 'executar_pc', payload: { command: 'x' }, meta: { task_id: 'tX' } } }]);
  check('aprovar pendência válida: reexecuta a ação gravada', r.reexecutar === true && r.acao.type === 'executar_pc' && r.pendencia_id === 5, r);
  r = await rs({ tipo: 'criar_agente', extra: 'criado', mutates: true, notfound: 'falhou' }, []);
  check('criar agente sem linha retornada: não confirma', r.reply_text.includes('Nada foi alterado'), r);
  r = await rs({ tipo: 'status_agentes', extra: '🪖 Agentes:', lista: true }, [{ nome: 'A', status: 'ativo', teste_ok: true }]);
  check('lista formata linhas', r.reply_text.includes('nome=A | status=ativo'), r);

  // ---------------------------------------------------------------- Aguardando / Contexto
  const ta = (await run(V10, 'Tem Aguardando?', [{ id_tarefa: 'w1', agent_name: 'OpenClaw', payload: { destino: 'central' } }], { Padronizar: { chat_id: '1', user_id: 1, text: '123456' }, Log: { text: '123456' } }))[0];
  check('espera de agente externo -> retomar', ta.has_waiting === true && ta.waiting.id_tarefa === 'w1');
  const tg = (await run(V10, 'Tem Aguardando?', [{ id_tarefa: 'g1', agent_name: 'General', input_type: 'otp', prompt_pt: 'Envie o código' }], { Padronizar: { chat_id: '1', user_id: 1, text: '123456' }, Log: {} }))[0];
  check('espera criada pelo General vira contexto (não vai para agente externo)', tg.has_waiting === false && tg.text.includes('123456') && tg.text.includes('Envie o código'), tg);
  const rt = (await run(V10, 'Montar Retomar', { has_waiting: true, chat_id: '1', user_id: 1, text: '999', waiting: { id_tarefa: 'w1', agent_name: 'OpenClaw', payload: { destino: 'central', original: { task: 'x' } } } }, { Config: CFG }))[0];
  check('retomada preserva task_id original no corpo e cria novo id de rastreio', rt.body.task_id === 'w1' && rt.task_id !== 'w1' && rt.body.user_input === '999' && rt.origem === 'retomada', rt);
  const cx = (await run(V10, 'Contexto', [{}], { 'Tem Aguardando?': { text: 'oi', chat_id: '1', user_id: 1 }, 'Catálogo': [{ nome: 'Insta', objetivo: 'o', pode: 'p', nao_pode: 'n', ferramentas: 'f', status: 'rascunho' }, { nome: 'Leg', objetivo: 'o', pode: 'p', nao_pode: 'n', ferramentas: 'f', status: 'legado_nao_testado' }, { nome: 'Ok', objetivo: 'o', pode: 'p', nao_pode: 'n', ferramentas: 'f', status: 'ativo' }], 'Preferências': { voz_auto: true } }))[0];
  check('catálogo marca rascunho/legado como NÃO delegar e ativo como testado', /Insta \[RASCUNHO[^\]]*NÃO delegue/.test(cx.catalogo) && /Leg \[LEGADO[^\]]*NÃO delegue/.test(cx.catalogo) && /Ok \[ATIVO e testado\]/.test(cx.catalogo), cx.catalogo);
  check('preferência de voz chega ao General', cx.voz_auto === true);

  // ---------------------------------------------------------------- Voz: falha da ElevenLabs -> texto + erro registrado
  const vf = (await run(V10, 'Voz Falhou', { error: { message: 'API key ID used as API key' } }, { 'Áudio?': { chat_id: '1', user_id: 1, reply_text: 'resposta que iria em áudio', generate_audio: true } }))[0];
  check('voz falhou: mantém a resposta para enviar em TEXTO e guarda o erro', vf.reply_text === 'resposta que iria em áudio' && vf.chat_id === '1' && /API key/.test(vf.voz_erro), vf);
  const vf2 = (await run(V10, 'Voz Falhou', { error: 'timeout' }, { 'Áudio?': { chat_id: '1', reply_text: 'x' } }))[0];
  check('voz falhou (erro em string) também tratado', vf2.voz_erro === 'timeout', vf2);
  const tgA = V10.nodes.find(n => n.name === 'Enviar Áudio');
  check('envio de áudio usa o chat_id do nó Áudio? (a resposta HTTP não tem chat_id)', tgA.parameters.chatId.includes("$('Áudio?')"), tgA.parameters);
  const el = V10.nodes.find(n => n.name === 'ElevenLabs');
  check('ElevenLabs: credencial (sem chave no JSON), saída em arquivo, erro não derruba o fluxo', el.credentials.httpHeaderAuth && el.onError === 'continueRegularOutput' && el.parameters.options.response.response.responseFormat === 'file' && !JSON.stringify(el.parameters).includes('xi-api-key'), el.parameters);

  // ---------------------------------------------------------------- Poller
  const pc = await run(V10, 'Parse Consulta', [{ statusCode: 200, body: { task_id: 'a', status: 'running' } }, { statusCode: 200, body: { task_id: 'b', status: 'completed', evidence: okEvidence } }, { error: { message: 'timeout' } }],
    { 'Montar Consulta': [{ task_id: 'a', chat_id: '1', destino: 'worker', body: { task_id: 'a' } }, { task_id: 'b', chat_id: '1', destino: 'worker', body: { task_id: 'b' } }, { task_id: 'c', chat_id: '1', destino: 'worker', body: { task_id: 'c' } }] });
  check('acompanhamento: ignora running, notifica concluída verificada e falha de rede', pc.length === 2 && pc[0].task_id === 'b' && pc[0].reply_text.includes('✅') && pc[1].task_id === 'c' && pc[1].state === 'failed', pc);

  // ---------------------------------------------------------------- AGENTE EXECUTOR
  const prep = async (body, ag) => (await run(EXE, 'Preparar', ag, { 'Executor Webhook': { body: { task_id: 'e1', ...body } } }))[0];
  const agBase = { nome: 'Insta', objetivo: 'o', pode: 'p', nao_pode: 'n', ferramentas: 'llm', prompt_sistema: 'sys', status: 'ativo', teste_ok: true, config: { conexoes_necessarias: ['instagram_graph'], conexoes_ok: [] } };
  let x = await prep({ agent: 'Nada', acao: 'teste' }, {});
  check('executor: agente inexistente -> failed AGENT_NOT_FOUND', x.run === false && x.contract.error_code === 'AGENT_NOT_FOUND', x);
  x = await prep({ agent: 'Insta', acao: 'preparar_conteudo', tarefa: 't' }, { ...agBase, status: 'pausado' });
  check('executor: pausado não executa', x.contract.error_code === 'AGENT_PAUSED', x);
  x = await prep({ agent: 'Insta', acao: 'preparar_conteudo', tarefa: 't' }, { ...agBase, status: 'rascunho', teste_ok: false });
  check('executor: agente não testado só aceita "teste"', x.contract.error_code === 'AGENT_NOT_TESTED', x);
  x = await prep({ agent: 'Insta', acao: 'teste' }, { ...agBase, status: 'rascunho', teste_ok: false });
  check('executor: teste permitido em rascunho', x.run === true, x);
  x = await prep({ agent: 'Insta', acao: 'publicar_post', tarefa: 't' }, agBase);
  check('executor: publicar sem conexão -> "aguardando conexão" (CONNECTION_MISSING)', x.contract.error_code === 'CONNECTION_MISSING' && x.contract.meta.conexoes_pendentes[0] === 'instagram_graph' && /Aguardando conexão/.test(x.contract.result_pt), x);
  x = await prep({ agent: 'Insta', acao: 'publicar_post', tarefa: 't' }, { ...agBase, config: { conexoes_necessarias: ['instagram_graph'], conexoes_ok: ['instagram_graph'] } });
  check('executor: mesmo com conexão declarada, publicar NÃO é implementado (não finge)', x.contract.error_code === 'NOT_IMPLEMENTED', x);
  x = await prep({ agent: 'Insta', acao: 'preparar_conteudo', tarefa: 'post sobre café' }, agBase);
  check('executor: preparar conteúdo roda mesmo com publicação pendente e avisa pendências', x.run === true && x.pendentes[0] === 'instagram_graph' && /NÃO publica/.test(x.system) || /não publica/i.test(x.system), x);
  x = await prep({ agent: 'Insta', acao: 'preparar_conteudo', tarefa: '   ' }, agBase);
  check('executor: tarefa vazia é recusada', x.contract.error_code === 'EMPTY_TASK', x);

  const base = { task_id: 'e1', acao: 'preparar_conteudo', agent: 'Insta', tam: 5, conteudo: 'olá!!', pendentes: [] };
  let mr = (await run(EXE, 'Montar Resposta', { id: 9, len: 5 }, { 'Preparar Artefato': { ...base, falha: false } }))[0].contract;
  check('executor: evidência = artefato lido de volta do banco', mr.status === 'completed' && mr.evidence.verified === true && mr.evidence.checks[0].type === 'artifact_saved' && mr.evidence.checks[0].id === 9 && /Nada foi publicado/.test(mr.result_pt), mr);
  mr = (await run(EXE, 'Montar Resposta', { id: 9, len: 3 }, { 'Preparar Artefato': { ...base, falha: false } }))[0].contract;
  check('executor: leitura divergente -> failed (não finge sucesso)', mr.status === 'failed' && mr.error_code === 'ARTIFACT_NOT_CONFIRMED' && mr.evidence.verified === false, mr);
  mr = (await run(EXE, 'Montar Resposta', {}, { 'Preparar Artefato': { ...base, falha: false } }))[0].contract;
  check('executor: nada gravado no banco -> failed', mr.status === 'failed', mr);
  mr = (await run(EXE, 'Montar Resposta', {}, { 'Preparar Artefato': { ...base, falha: true, motivo: 'sem crédito' } }))[0].contract;
  check('executor: falha do LLM -> failed LLM_FAILED', mr.error_code === 'LLM_FAILED' && mr.result_pt.includes('sem crédito'), mr);
  mr = (await run(EXE, 'Montar Resposta', { id: 9, len: 5 }, { 'Preparar Artefato': { ...base, acao: 'teste', falha: false } }))[0].contract;
  check('executor: teste avisa que NÃO valida integrações externas', /NÃO testa integrações externas/.test(mr.result_pt), mr.result_pt);

  console.log(`\n${pass} passaram, ${fail} falharam`);
  process.exit(fail ? 1 : 0);
})().catch(err => { console.error('ERRO NO HARNESS:', err); process.exit(2); });
