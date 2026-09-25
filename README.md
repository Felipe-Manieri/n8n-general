# General — Exército de Agentes (n8n)

Você fala com o **General** pelo Telegram (texto ou voz). Ele entende a ordem, escolhe quem executa, cria/administra agentes, acompanha a execução e informa o resultado **verdadeiro**.
A VPS (Docker + n8n) coordena; o PC (Tailscale) executa tarefas locais pelo Worker/OpenClaw.

| Arquivo | O que é |
|---|---|
| `GENERAL_V10_EXERCITO.json` | workflow principal (importar inativo) |
| `AGENTE_EXECUTOR_v1.json` | modelo validado de agente (webhook) |
| `worker/worker.py`, `worker/test_worker.py` | Worker do PC com o contrato `task_id/status/evidence` |
| `sql/schema.sql` | esquema do banco (o nó `DB Init` aplica sozinho) |
| `tools/` | gerador dos workflows (`build_v10.py`) e testes (`test_logic.js`, `e2e_pc.js`, `validate_workflows.py`) |
| `docs/SETUP.md` | credenciais, importação, rede, voz, agentes |
| `docs/CONTRATO.md` | contrato único n8n ⇄ Central ⇄ Worker |
| `docs/TESTES.md` | resultados reais e o que ainda depende de você |

Regra central: **“✅ Executado” só aparece com `status=completed` + evidência verificável.** Sem isso: ⚠️ (sem verificação), ⏳, ❌ ou ❓ (desconhecido), sempre com o `task_id`.

Regenerar os JSONs: `python tools/build_v10.py` (usa o export ativo em `backup/GENERAL_V9_ativo_67nos.json`, local e fora do Git).
Testes: `python tools/validate_workflows.py && node tools/test_logic.js && python worker/test_worker.py && node tools/e2e_pc.js`.

Arquivos antigos (`GENERAL_FINAL_v6_*`, `GENERAL V9 — …`, `build_bloco1.py`, `patch_pc_bloco1.py`) são histórico. **Nunca** grave tokens em JSON/código/Git; veja `docs/SETUP.md`.
