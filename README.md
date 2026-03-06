# General — Automação n8n

Automação central que funciona como **comandante** entre você (Telegram) e um exército de agentes de IA: interpreta pedidos em linguagem natural, delega tarefas (OpenClaw, executar no PC, SQL, criar/editar agentes), pede aprovação quando necessário e gerencia pausas (2FA, senha, captcha) até você responder.

---

## Objetivos

- **Um único ponto de entrada:** você fala por Telegram; o General decide o que fazer e qual agente usar.
- **Sem comandos com `/`:** pedidos em texto livre (ex.: “posta isso no Instagram”, “cria um agente de marketing”, “qual o status das tarefas?”).
- **Segurança:** só o seu `user_id` passa; ações sensíveis exigem aprovação (ou “CONFIRMO ALFA” para pular).
- **Continuidade:** se um agente pedir 2FA, senha ou captcha, o fluxo salva o estado, te pergunta no Telegram, e quando você responde retoma de onde parou.
- **Rastreio:** logs de pedidos e execuções no PostgreSQL; mensagens de erro e sucesso sempre com nome do agente.

---

## O que a automação faz

### Entrada

1. **Telegram** — Mensagem (texto ou áudio) dispara o workflow.
2. **Padronizar** — Extrai `chat_id`, `user_id`, `text`, `has_voice`, `voice_file_id`, `canal`.
3. **Só Felipe** — Se não for seu user_id, responde “Acesso negado” e encerra.
4. **DB Init** — Cria tabelas se não existirem: `general_logs`, `general_pending`, `general_agentes`, `general_waiting_input`, `telegram_updates`.
5. **Reemitir envelope** — Garante que o item atual tenha sempre o “envelope” (chat_id, user_id, text, etc.) para os nós seguintes.
6. **Deduplicar** — Insere `update_id` em `telegram_updates` com ON CONFLICT DO NOTHING. Se já existir (repetido), o fluxo para e não envia nada (evita loop do Telegram).
7. **É novo?** — Só segue se o update era novo (insert retornou linha).

### Áudio de entrada

8. **Tem Voz?** — Se a mensagem for de áudio: baixa o arquivo no Telegram, corrige binário, envia para **Whisper** (OpenAI), **Setar Transcrição** coloca o texto transcrito em `text` e segue. Se não for áudio, vai direto para o próximo passo com o `text` já existente.
9. **Log** — Registra o pedido em `general_logs` (chat_id, user_id, canal, tipo `pedido`, payload com a mensagem). `continueOnFail: true` para não travar.

### Retomar tarefa (2FA / senha / captcha)

10. **Buscar Aguardando** — Apaga registros antigos (> 30 min) em `general_waiting_input` e busca **no máximo 1** linha para o `chat_id` (aguardando resposta do usuário).
11. **Tem Aguardando?** — Monta um único item com `has_waiting` e, se houver, o objeto `waiting` (id_tarefa, agent_name, input_type, prompt_pt, payload). O `text` (transcrição ou mensagem) vem do fluxo anterior para não se perder.
12. **Retomar?** — Se `has_waiting === true`: chama a API do agente (OpenClaw) com `user_input` = sua resposta, **Apagar Aguardando** (DELETE na linha), **Formatar Retorno** e **Resposta Retomar** (Telegram). Se não tiver aguardando, segue para o General.

### General (cérebro)

13. **Catálogo** — SELECT em `general_agentes` (nome, objetivo, pode, nao_pode, ferramentas).
14. **Contexto** — Junta catálogo + `text` (ou `texto`) + chat_id, user_id para o General.
15. **General** — Agente de IA (LangChain) com modelo OpenAI, memória por `chat_id`. Responde em JSON: `reply_text`, `action`, `need_approval`, `approval_preview`, `need_user_input`, `generate_audio`.
16. **Parse** — Lê o JSON da resposta do General e preenche campos padrão.
17. **Decidir** — Define `rota`: 0 = só responder, 1 = aprovar, 2 = executar, 3 = pedir input.
18. **Rota** — Encaminha para uma das quatro saídas conforme `rota`.

### Saídas do General

- **Rota 0 (Responder)** — **Áudio?** Se `generate_audio`: **ElevenLabs** (TTS, resposta em binário) → **Enviar Áudio**. Senão: **Enviar Texto** (reply_text no Telegram).
- **Rota 1 (Aprovar)** — **Prep Pendência** → **Criar Pendência** (INSERT em `general_pending`) → **Formatar Prévia** → **Enviar Prévia** (Telegram com “aprovar X” / “cancelar X”). Quando você disser “aprovar 5”, outro caminho (consulta SQL + reexecução) trata a aprovação.
- **Rota 2 (Executar)** — **Classificar** (tipo da ação, task_id, agent_name) → **Externo?** Se for agente externo: **Montar Endpoint** → **Chamar Agente** (OpenClaw ou Executar PC) → **Parse Agente** (normaliza resposta, detecta timeout/erro). Depois **Precisa Input?**: se o agente pediu 2FA/senha/captcha → **Salvar Aguardando** (INSERT em `general_waiting_input`) → **Msg Input** → **Enviar Pedido Input** (Telegram com texto tipo “[OpenClaw • tarefa 123] Me manda o código…”). Se não precisar de input → **Resultado OK** → **Log Exec** → **Resposta Exec** (Telegram com reply + “✅ Executado” e prefixo do agente). Se for interno (SQL): **Montar SQL** → **Executar SQL** → **Resultado SQL** → **Resposta SQL** ou reexecução de ação aprovada.
- **Rota 3 (Pedir input do General)** — **Prep Input General** → **Salvar Input General** → **Msg Input General** → **Enviar Input General** (pedido no Telegram; quando você responder, o próximo disparo cai em “Buscar Aguardando” e retoma).

### Logs

- **Log** — Registra cada pedido (texto ou transcrição).
- **Log Exec** — Registra execução ao final do caminho “Resultado OK” (opcional; `continueOnFail: true`).

---

## Requisitos

- **n8n** (self-hosted ou cloud).
- **PostgreSQL** — Tabelas criadas pelo próprio workflow (DB Init). Coluna de tempo em `general_waiting_input`: `created_at` (ajuste a query de “Buscar Aguardando” se a sua tabela usar outro nome).
- **Telegram Bot** — Token nas credenciais do nó do gatilho e dos nós que enviam mensagem.
- **OpenAI** — API key para o modelo do General e para o Whisper (áudio).
- **ElevenLabs** — API key em variável de ambiente `ELEVENLABS_API_KEY` (usada nos nós de TTS).
- **Agente OpenClaw / Executar PC** — URLs e tokens configurados nos nós HTTP (Montar Endpoint, Chamar Retomar, etc.).

---

## Importar no n8n

1. Workflows → **Import from File** (ou colar JSON).
2. Escolher o arquivo do General (ex.: `GENERAL V9 — Linear Final (1).json` ou `GENERAL_V10_COMPLETO.json`).
3. Configurar credenciais: Telegram, Postgres, OpenAI, e variável **ELEVENLABS_API_KEY** (Settings → Variables ou ambiente).

---

## Variáveis de ambiente

| Nome | Uso |
|------|-----|
| `ELEVENLABS_API_KEY` | Chave da API ElevenLabs para geração de áudio (TTS). |

Defina no n8n (Settings → Variables) ou no ambiente onde o n8n roda.

---

## Resumo do fluxo (visão geral)

```
Telegram → Padronizar → Só Felipe → DB Init → Reemitir envelope → Deduplicar → Envelope se novo
    → Tem Voz? [sim] → Baixar Voz → Fix Binário → Whisper → Setar Transcrição → Log
    → Tem Voz? [não] → Log
→ Buscar Aguardando → Tem Aguardando? [sim] → Retomar (API agente + Apagar + Resposta Retomar)
→ Tem Aguardando? [não] → Catálogo → Contexto → General → Parse → Decidir → Rota
    → [responder] → Áudio? → ElevenLabs / Enviar Texto
    → [aprovar] → Prep Pendência → Criar Pendência → Enviar Prévia
    → [executar] → Classificar → Externo? → Chamar Agente → Parse Agente → Precisa Input? → Salvar Aguardando / Resultado OK → …
    → [pedir input] → Prep Input General → Salvar Input General → Enviar Input General
```

Este README descreve o comportamento da automação General (V9/V10) e seus objetivos; ajustes de nomes de nós ou IDs podem existir entre versões do JSON.
