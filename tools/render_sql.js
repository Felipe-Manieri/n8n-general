// Renderiza as queries dos nós Postgres com dados de exemplo (inclui aspas e caracteres perigosos) para checar a sintaxe SQL.
const fs = require('fs'), path = require('path');
const root = path.resolve(__dirname, '..');
const out = [];
const tricky = "O'Brien \"x\" ; -- {{ }}";
const J = { chat_id: '123', user_id: 6044282195, task_id: 't1-abc', agent_name: tricky, tipo: 'executar_pc', destino: 'worker', pedido: tricky, pendencia_id: 5, state: 'completed', verified: true,
  reason: tricky, result_pt: tricky, evidence: { checks: [{ ok: true, path: "C:\o'k" }] }, origem: 'direto', text: tricky, update_id: 99, message_id: 7,
  agente_status: { status: 'ativo', teste_ok: true, pendentes: ['a'] }, voz_erro: tricky, body: { task_id: 'w1' }, sql: 'SELECT 1;', input_type: 'otp', prompt_pt: tricky,
  payload_in: { k: tricky }, has_image: false, id: 3, acao: 'preparar_conteudo', agent: tricky, conteudo_esc: "x''y", falha: false, waiting: {} };
const refs = { Padronizar: { chat_id: '123', update_id: 99, message_id: 7, user_id: 1 }, 'Preparar Artefato': { task_id: 't1' }, 'Prep Pendência': J };
const $ = (n) => ({ first: () => ({ json: refs[n] || J }) });
for (const f of ['GENERAL_V10_EXERCITO.json', 'AGENTE_EXECUTOR_v1.json']) {
  const wf = JSON.parse(fs.readFileSync(path.join(root, f), 'utf8'));
  for (const n of wf.nodes) {
    if (n.type !== 'n8n-nodes-base.postgres') continue;
    let q = n.parameters.query;
    if (q.startsWith('=')) {
      q = q.slice(1).replace(/\{\{([\s\S]*?)\}\}/g, (_, expr) => { try { return String(new Function('$json', '$', 'return (' + expr + ')')(J, $)); } catch (e) { return '/*ERRO_EXPR ' + e.message + '*/'; } });
    }
    out.push({ wf: f, node: n.name, sql: q });
  }
}
fs.writeFileSync(process.argv[2], JSON.stringify(out));
console.log(out.length + ' queries renderizadas');
