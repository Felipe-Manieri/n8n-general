# Configuração — General V10 (Exército de Agentes)

Arquitetura: **Telegram/voz → n8n (VPS) → General decide e acompanha → Worker do PC (Tailscale) / Central `/task` / Executor de agentes → resultado verificado → Telegram.**

## 1. Credenciais no n8n (nenhum segredo fica no JSON)
| Credencial | Tipo | Nome esperado | Valor |
|---|---|---|---|
| Telegram, Postgres, OpenAI | já existentes | `Telegram account`, `Postgres account`, `OpenAi account 3` | (as atuais) |
| Worker do PC | Header Auth | `Worker PC (X-AGENT-TOKEN)` | Name `X-AGENT-TOKEN`, Value = conteúdo de `C:\general_worker\worker_token.txt` |
| Central | Header Auth | `OpenClaw Central (X-CENTRAL-TOKEN)` | Name `X-CENTRAL-TOKEN`, Value = token do Central |
| Executor | Header Auth | `Agente Executor (webhook)` | Name `Authorization` (ou qualquer), Value = um segredo novo (gere você mesmo) |
| ElevenLabs | Header Auth | `ElevenLabs (xi-api-key)` | Name `xi-api-key`, Value = chave **`sk_...`** nova (ver §5) |

Depois de importar, abra cada nó marcado com aviso e escolha a credencial (os ids `CONFIGURAR` são placeholders).

## 2. Importar (não sobrescreve o workflow ativo)
1. Importe `AGENTE_EXECUTOR_v1.json` → escolha as credenciais → ative → confira que o webhook responde em `/webhook/agente-executor`.
2. Importe `GENERAL_V10_EXERCITO.json` (vem **inativo** e sem id → cria um workflow novo). Revise as URLs no nó **Config**.
3. Teste o V10 com o V9 ainda ativo? **Não** — os dois usam o mesmo Telegram Trigger. Desative o V9, ative o V10; se algo falhar, desative o V10 e reative o V9 (backup em `backup/`).
4. Na primeira mensagem o nó `DB Init` cria/atualiza as tabelas (`sql/schema.sql`). Agentes antigos viram `legado_nao_testado` (não recebem tarefas até passarem em teste).

## 3. PC (Worker)
Já existe a tarefa agendada **GeneralWorker** (`C:\general_worker\start_worker.cmd` → `worker.py`, porta 8787, ao fazer logon). Não instale outro.
- Substituir o `worker.py` pela versão de `worker/worker.py` (contrato novo). O token vem de `worker_token.txt` (ao lado do script) ou da variável `WORKER_TOKEN`.
- Há uma segunda tarefa antiga, **PC-Worker-8787** (`Documents\PC-Worker\worker.py`, só comandos da lista `SAFE_CMDS`), que também usa a porta 8787 e falha ao iniciar (`0x80070002`). Sugestão: desativá-la (`Disable-ScheduledTask -TaskName PC-Worker-8787`).
- Teste: `python worker/test_worker.py` (18 verificações, cria/remove arquivos em `%USERPROFILE%\general_worker_test`).

## 4. Rede (VPS ⇄ PC)
Na VPS o `tailscale status` mostrava o PC, mas do PC: **“peer's node key has expired”** para `srv955406` → a VPS **não alcança** `100.107.36.118:8787` (o Central respondeu `PC_CALL_FAILED … connect timeout`).
Correção: no painel https://login.tailscale.com/admin/machines → `srv955406` → **Disable key expiry** e reautentique na VPS: `sudo tailscale up --force-reauth`. Se o n8n roda em Docker, confirme que o contêiner alcança `100.107.36.118` (`docker exec <n8n> wget -qO- http://100.107.36.118:8787/health`).

## 5. ElevenLabs (voz)
- O texto em `PROMPT_CORRECOES_WORKFLOW.md` era um **ID de chave**, não uma chave (a API respondeu `api_key_id_used_as_api_key`). Ele foi removido do arquivo, mas **continua no histórico do Git** — considere-o vazado.
- Rotacionar/criar: ElevenLabs → *Developers → API Keys* → criar nova chave (`sk_…`), revogar a antiga, colocar na credencial `ElevenLabs (xi-api-key)`.
- Comportamento: “responda em voz / manda áudio / estou dirigindo” → áudio (inclusive após tarefas e aprovações). “sem áudio” volta ao texto. Preferência fixa: “sempre responda em voz” (tabela `general_prefs`). Áudio **recebido** só é transcrito; não liga voz sozinho. Se a ElevenLabs falhar → texto + registro em `general_logs` (`tipo='erro_voz'`).

## 6. Token fraco
O token padrão antigo (um valor fraco) aparece em versões antigas do repositório (histórico). Gere tokens novos (`python -c "import secrets;print(secrets.token_urlsafe(32))"`), atualize `worker_token.txt`, a credencial do n8n e o Central, e reinicie a tarefa `GeneralWorker`.

## 7. Agentes (fluxo)
1. “Crie um agente para cuidar do meu Instagram” → o General pergunta nome, objetivo, o que pode/não pode, ferramentas/conexões (ex.: `instagram_graph`) e tarefa de teste, e grava como **rascunho** (não é funcional).
2. “Testar agente Instagram” → o **Executor** roda a tarefa de teste; só passa com **artefato salvo e lido de volta do banco**. Passou → `ativo` (ou `aguardando_conexao` se há conexões pendentes).
3. Conexão externa: configure a credencial **no n8n** (nunca no chat) → diga “conexão instagram_graph pronta no agente Instagram” → o General marca e pede novo teste.
4. Operar: `status dos agentes`, `erros do agente X`, `pausar/reativar agente X`, `editar agente X` (volta a rascunho até novo teste), `status da tarefa <id>`.
5. Limite conhecido: o modelo validado v1 só **prepara conteúdo e responde texto**. **Publicar** no Instagram (ou qualquer integração) retorna `NOT_IMPLEMENTED`/`CONNECTION_MISSING` até existir um template de integração próprio + credencial + sua aprovação.
