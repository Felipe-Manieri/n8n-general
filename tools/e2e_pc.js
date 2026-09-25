// Teste ponta a ponta (parcial): lógica REAL dos nós do GENERAL V10 + Worker REAL do PC via Tailscale.
// NÃO passa por n8n, Telegram nem Postgres: o "HTTP Request" é feito aqui, com o mesmo corpo/URL/token da credencial.
// Verifica o EFEITO no disco por fora do Worker. Uso: node tools/e2e_pc.js
const fs = require('fs'), path = require('path'), os = require('os'), crypto = require('crypto');
const root = path.resolve(__dirname, '..');
const V10 = JSON.parse(fs.readFileSync(path.join(root, 'GENERAL_V10_EXERCITO.json'), 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const TOKEN = process.env.WORKER_TOKEN || fs.readFileSync('C:/general_worker/worker_token.txt', 'utf8').trim();
const CFG = { CENTRAL_URL: 'http://72.60.11.239:8080/task', WORKER_URL: process.env.WORKER_URL || 'http://100.107.36.118:8787', EXECUTOR_URL: 'x' };
let pass = 0, fail = 0;
const check = (n, c, d) => { c ? pass++ : fail++; console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : '  -> ' + JSON.stringify(d).slice(0, 500))); };

async function run(name, input, refs = {}) {
  const node = V10.nodes.find(n => n.name === name);
  const $ = (n) => ({ first: () => ({ json: refs[n] }), all: () => [{ json: refs[n] }] });
  const $input = { first: () => ({ json: input }), all: () => [{ json: input }] };
  return (await new AsyncFunction('$input', '$', '$json', node.parameters.jsCode)($input, $, input)).map(o => o.json);
}
// imita o nó "HTTP Request" (fullResponse + neverError; falha de rede vira {error})
async function http(call) {
  try {
    const r = await fetch(call.url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-AGENT-TOKEN': TOKEN }, body: JSON.stringify(call.body), signal: AbortSignal.timeout(60000) });
    const txt = await r.text(); let body; try { body = JSON.parse(txt); } catch { body = txt; }
    return { statusCode: r.status, body };
  } catch (e) { return { error: { message: e.message + (e.cause ? ' / ' + e.cause.code : '') } }; }
}
// passa uma ordem do General pelos nós reais até a mensagem final
async function pipeline(action, extra = {}, cfg = CFG) {
  const gen = { action, chat_id: '1', user_id: 1, text: 'ordem de teste', generate_audio: false, ...extra };
  const cl = (await run('Classificar', gen))[0];
  const call = (await run('Montar Endpoint', cl, { Config: cfg }))[0];
  const prep = (await run('Preparar Tarefa', call))[0];
  const res = await http(prep);
  const st = (await run('Parse Agente', res, { 'Preparar Tarefa': prep }))[0];
  const msg = (await run('Resultado OK', st))[0];
  return { prep, res, st, msg: msg.reply_text };
}

(async () => {
  const dir = path.join(os.homedir(), 'general_e2e_' + crypto.randomBytes(3).toString('hex'));
  const f = path.join(dir, 'ordem.txt');
  const content = 'criado pelo General em ' + new Date().toISOString();

  let r = await pipeline({ type: 'criar_arquivo_pc', payload: { path: f, content } });
  check('criar_arquivo_pc -> estado completed verificado', r.st.state === 'completed' && r.st.verified === true, r.st);
  check('mensagem final: "✅ Executado e verificado" + task_id', r.msg.includes('✅ Executado e verificado') && r.msg.includes(r.prep.task_id), r.msg);
  check('EFEITO REAL: arquivo existe no disco do PC', fs.existsSync(f));
  check('EFEITO REAL: conteúdo idêntico', fs.existsSync(f) && fs.readFileSync(f, 'utf8') === content);
  check('evidência traz o sha256 do arquivo real', r.st.evidence.checks.some(c => c.sha256 === crypto.createHash('sha256').update(content).digest('hex')), r.st.evidence);

  const f2 = path.join(dir, 'via_powershell.txt');
  r = await pipeline({ type: 'executar_pc', payload: { command: `Set-Content -LiteralPath '${f2}' -Value 'ok'`, verify: [{ type: 'file_exists', path: f2 }] } });
  check('executar_pc + verify -> ✅ e arquivo existe', r.msg.includes('✅ Executado e verificado') && fs.existsSync(f2), r.msg);

  const f3 = path.join(dir, 'nunca_criado.txt');
  r = await pipeline({ type: 'executar_pc', payload: { command: 'Write-Output "fiz tudo"', verify: [{ type: 'file_exists', path: f3 }] } });
  check('comando "ok" mas efeito ausente -> ❌ (nunca ✅)', r.st.state === 'failed' && !r.msg.includes('✅') && r.msg.includes('NÃO foi confirmado'), r.msg);
  check('EFEITO REAL ausente confere', !fs.existsSync(f3));

  r = await pipeline({ type: 'executar_pc', payload: { command: 'Write-Output oi' } });
  check('comando sem verify -> ⚠️ sem verificação (nunca ✅)', r.st.state === 'completed' && r.st.verified === false && !r.msg.includes('✅') && r.msg.includes('SEM verificação'), r.msg);

  r = await pipeline({ type: 'executar_pc', payload: { command: 'exit 7' } });
  check('comando que falha -> ❌ Falhou', r.msg.includes('❌ Falhou'), r.msg);

  // mesma tarefa reenviada (mensagem duplicada): Worker não executa de novo
  const gen = { action: { type: 'criar_arquivo_pc', payload: { path: path.join(dir, 'dup.txt'), content: 'v1' } }, chat_id: '1', user_id: 1, text: 't' };
  const cl = (await run('Classificar', gen))[0];
  const c1 = (await run('Montar Endpoint', cl, { Config: CFG }))[0];
  await http(c1);
  const again = await http({ ...c1, body: { ...c1.body, content: 'v2-NAO-DEVE-GRAVAR' } });
  check('mesmo task_id reenviado -> duplicado, sem nova execução', again.body.duplicate === true && fs.readFileSync(path.join(dir, 'dup.txt'), 'utf8') === 'v1', again.body);

  // Worker inacessível
  const off = await pipeline({ type: 'executar_pc', payload: { command: 'whoami' } }, {}, { ...CFG, WORKER_URL: 'http://127.0.0.1:9' });
  check('Worker fora do ar -> ❌ Falhou (não inventa sucesso)', off.st.state === 'failed' && off.msg.includes('❌') && !off.msg.includes('✅'), off.msg);

  // formato legado (rota "/" do Worker antigo) nunca vira ✅
  const leg = await http({ url: CFG.WORKER_URL + '/', body: { command: 'whoami' } });
  const legSt = (await run('Parse Agente', leg, { 'Preparar Tarefa': { destino: 'worker', task_id: 'L', body: { task_id: 'L' }, tipo: 'executar_pc', agent_name: 'PC', chat_id: '1' } }))[0];
  check('resposta da rota legada {ok,stdout} -> desconhecido, nunca ✅', legSt.state === 'unknown', legSt);

  fs.rmSync(dir, { recursive: true, force: true });
  console.log(`\n${pass} passaram, ${fail} falharam`);
  process.exit(fail ? 1 : 0);
})();
