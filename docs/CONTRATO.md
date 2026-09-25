# Contrato único n8n ⇄ Central ⇄ Worker ⇄ Executor

Toda execução externa usa o mesmo formato. O n8n **não infere sucesso** de HTTP 200 nem de texto.

## Requisição (n8n → destino)
```json
{ "task_id": "t1790338595562-qm8h4u", "action": "create_file", "path": "C:\Users\...\a.txt", "content": "..." }
```
- `task_id` nasce no General (ou na pendência) e acompanha pedido → execução → resposta → tabela `general_tasks`.
- Aprovação: o `task_id` é gravado junto com a ação em `general_pending.acao.meta`; ao aprovar, executa-se **a ação gravada**, com o mesmo `task_id`.

## Resposta (destino → n8n)
```json
{
  "task_id": "t1790338595562-qm8h4u",
  "status": "completed | running | waiting_input | failed",
  "result_pt": "texto curto",
  "evidence": { "verified": true, "checks": [ { "type": "file_exists", "path": "...", "ok": true } ] },
  "error_code": "só em falha", "meta": { }
}
```
| status | significado | o que o n8n faz |
|---|---|---|
| `completed` + `evidence.verified=true` + `checks[]` todas `ok` | **efeito confirmado** | `✅ Executado e verificado` |
| `completed` sem evidência | terminou, efeito não provado | `⚠️ Concluído, mas SEM verificação` |
| `running` | em andamento | `⏳` + acompanhamento a cada 1 min (Worker) |
| `waiting_input` | precisa de você (`input_type`, `prompt_pt`) | grava em `general_waiting_input` e pergunta no Telegram |
| `failed` | falhou (`error_code`, `result_pt`) | `❌ Falhou: motivo` + log |
| qualquer outra coisa / sem `status` / `task_id` diferente | **desconhecido** | `❓ Resultado desconhecido` + motivo no log |

Falhas de rede/timeout/HTTP ≥ 400 viram `failed` com o motivo. Nunca há “✅” sem evidência.

## Destinos
| destino | URL (nó `Config`) | autenticação (credencial n8n) | estado |
|---|---|---|---|
| Worker do PC | `http://100.107.36.118:8787/task` | `X-AGENT-TOKEN` | **implementado e testado** (`worker/worker.py`) |
| Central/OpenClaw | `http://72.60.11.239:8080/task` (corpo `{"task": "...", "task_id": "..."}`) | `X-CENTRAL-TOKEN` | **falta adaptar o código do Central ao contrato** (ver abaixo) |
| Executor de agentes | `http://localhost:5678/webhook/agente-executor` | header auth do webhook | implementado (`AGENTE_EXECUTOR_v1.json`), não testado no n8n |

### O que o Central precisa devolver
Hoje o Central devolve `{"ok":false,"error":"UNAUTHORIZED"}` (401) e `{"ok":false,"error":"PC_CALL_FAILED","detail":"..."}` (500). O formato de sucesso **não foi observado** (a chamada autenticada deu timeout porque a VPS não alcança o PC: chave Tailscale da VPS expirada). Até o Central devolver `status`+`evidence`, toda resposta dele aparece como **❓ desconhecido** ou **⚠️ sem verificação** — nunca como ✅. Para o Central falar com o Worker no contrato novo, ele deve chamar `POST {WORKER}/task` com `task_id`, `action` (`powershell`/`create_file`) e `verify`, e repassar o JSON recebido do Worker sem alterar `status`/`evidence`.

## Worker (rotas)
`GET /health` · `POST /task` · `GET /task/<id>` · `POST /` (legada, sem status/evidência → o n8n a trata como desconhecida).
Ações: `ping`, `create_file{path,content}` (só dentro do perfil do usuário; confere sha256 lendo de volta), `powershell{command, verify?}`.
Checagens `verify`: `file_exists`, `dir_exists`, `path_absent`, `file_contains{text}`, `file_sha256{sha256}`.
Idempotência: mesmo `task_id` não executa duas vezes. Tarefas ficam em `C:\general_worker\tasks\<id>.json`.
