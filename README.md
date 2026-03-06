# General V9 — Automação n8n

Workflow n8n "General" (versão 9): Telegram, deduplicação, áudio entrada/saída, aguardando/retomar, OpenClaw, logs.

## Importar no n8n

- Abra o n8n → Workflows → Import from File.
- Selecione `GENERAL V9 — Linear Final (1).json` (ou o JSON do V9 que estiver na pasta).

## Requisitos

- PostgreSQL (tabelas: general_logs, general_pending, general_agentes, general_waiting_input, telegram_updates)
- Telegram Bot Token
- OpenAI API
- Credenciais do agente (OpenClaw, etc.) conforme configurado no workflow
