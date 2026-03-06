# GENERAL — Exército de IA v6

Workflow n8n do **General**, agente que você aciona (Telegram, Dashboard, WhatsApp) e que **delega tarefas** aos agentes do exército.

## Tratamento de erro (PC)

Após **Executar no PC**, o nó **Resultado PC** verifica se deu erro. Sempre responde no Telegram:
- Sucesso → "✅ Concluído!"
- Falha/timeout → "⚠️ PC não respondeu. Verifica o worker."

## Fallback sem LangChain

Arquivo **GENERAL_FALLBACK_sem_chaves.json**: mesmo fluxo, mas o General usa **HTTP (OpenAI)** + **Code** em vez de nós LangChain. Use se o principal não importar ou o LangChain quebrar. Variável do fluxo: **OPENAI_API_KEY** (chave da API OpenAI).

## O que foi aplicado (soluções v6)

- **Compatibilidade de import** — Roteador substituído por cadeia de IFs (É /status?, É /aprovar?, etc.), sem nó Switch 3.2 que quebrava em versões antigas do n8n.
- **Session ID** — `session_id: chat_id` em Padronizar Entrada + Memória do General usando esse `sessionId`.
- **Tabela de sessão** — `general_sessions` para estado da entrevista (criar agente). Carregar Sessão + Merge antes do Montar Contexto; após salvar agente, Limpar Sessão.
- **SQL seguro** — Nós **Preparar Pendência** e **Preparar Agente** escapam textos (apóstrofos) antes de INSERT; Criar Pendência e Salvar Agente usam apenas valores já preparados.
- **Resposta por canal** — Quando não precisa aprovar: **Canal é Telegram?** → Resposta Direta; **Canal é Dashboard?** → Responder Dashboard; senão → **Enviar WhatsApp** (HTTP para variável `WHATSAPP_RESPONSE_URL`).
- **Trava de aprovação** — Em Ler Resposta General, `criar_agente` incluído na lista de tipos que forçam `precisa_aprovar = true`.
- **ElevenLabs** — Nó **Preparar Áudio** após TTS garante binário em propriedade `data` antes de Enviar Áudio no Telegram.
- **Prompt do General** — Reescrito para **delegação**: receber ordens, escolher o agente certo do catálogo, orquestrar e consolidar respostas.

## Variáveis do fluxo (Configurações → Variáveis)

| Variável | Descrição |
|----------|-----------|
| `PC_WORKER_URL` | URL do PC Worker (ex.: `http://IP:8787/execute`) |
| `GATEWAY_TOKEN` | Token do gateway/agente no PC |
| `ELEVENLABS_TTS_URL` | URL da API TTS ElevenLabs |
| `ELEVENLABS_API_KEY` | Chave da API ElevenLabs |
| `WHATSAPP_RESPONSE_URL` | (Opcional) URL do seu provedor WhatsApp para enviar resposta (ex.: Evolution API) |

**O que você já tem:** token do PC Worker → colar em **GATEWAY_TOKEN**. Chave ElevenLabs → colar em **ELEVENLABS_API_KEY**. (Não salve tokens no repositório.)

**Postgres:** já instalado no servidor. No n8n: **Credentials** → crie ou edite **Postgres General** e preencha com os dados que você recebeu (Host, Porta 5432, Usuário `postgres`, Banco `postgres`, Senha). A senha fica só no n8n — não coloque em arquivos do projeto.

**Criar tabelas:** você **não precisa** criar nenhuma tabela à mão. Na primeira vez que o workflow rodar, o nó **DB Init** cria as 4 tabelas (`general_logs`, `general_pending`, `general_agentes`, `general_sessions`). Se quiser rodar o SQL antes, use o arquivo **schema_postgres_general.sql** no seu Postgres.

## Credenciais

- **Telegram** — conta do bot.
- **OpenAI** — para o modelo do General (GPT-4o).
- **Postgres** — credencial **Postgres General** com os dados do seu servidor; usada em `general_logs`, `general_pending`, `general_agentes`, `general_sessions`.

## Comandos (Telegram)

- `/status` — tarefas pendentes  
- `/aprovar N` — aprovar tarefa #N (e executar no PC se houver ação)  
- `/cancelar N` — cancelar tarefa #N  
- `/relatorio` — resumo de logs  
- `/agentes` — listar exército  
- `/ajuda` — lista de comandos  
- `/audio texto` — receber o texto em áudio (ElevenLabs)

Qualquer outra mensagem é tratada como ordem para o General; ele delega aos agentes ou executa via ferramenta "Executar no PC via Gateway", com aprovação quando for ação perigosa.

---

## Última atualização: OpenClaw EXECUTE + erro Postgres

**Nós alterados:** DB Aprovar, DB Cancelar, Criar Pendência — `continueOnFail: true` e saída passando por IF de erro antes do sucesso.

**Nós adicionados:** OpenClaw - EXECUTE (após Enviar Aprovado); Restaurar item aprovação; DB Aprovar erro?, DB Cancelar erro?, Criar Pendência erro?; Enviar Banco falhou (Telegram "Banco falhou.").

**Fluxo /aprovar:** DB Aprovar → DB Aprovar erro? → (sim: Enviar Banco falhou | não: Formatar Aprovação → Enviar Aprovado → OpenClaw EXECUTE → Restaurar item aprovação → Tem Ação PC? → …).

---

## Editar agente

Quando você pedir ao General para **alterar** um agente que já existe (ex.: "muda o objetivo do agente Social"), ele usa a ação `editar_agente`. O fluxo: **É Editar Agente?** → **Preparar Editar Agente** → **DB Atualizar Agente** (UPDATE em `general_agentes`) → **Confirmar Agente Editado** (Telegram "Agente X atualizado! ✅").
