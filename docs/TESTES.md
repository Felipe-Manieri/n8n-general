# Resultados dos testes (executados em 2026-09-25)

| # | Teste | Como foi feito | Resultado |
|---|---|---|---|
| 1 | Worker — contrato, idempotência, verificação, segurança | `worker/test_worker.py` contra o Worker real via Tailscale (`100.107.36.118:8787`); o arquivo é conferido por outro processo | 18/18 passaram |
| 2 | **Ponta a ponta no PC** — General (nós reais) → Worker real → arquivo criado e conferido no disco | `tools/e2e_pc.js` (executa o JS dos nós Classificar/Montar Endpoint/Parse Agente/Resultado OK e faz a chamada HTTP real) | 13 passaram, 0 falharam |
| 3 | Lógica dos nós com respostas simuladas: texto, voz, concluída, falha, desconhecida, aguardando resposta, aprovação, criar/editar/pausar/reativar agente, executor | `tools/test_logic.js` | 106 passaram, 0 falharam |
| 4 | Estrutura dos JSONs (conexões, referências entre nós, sintaxe JS, segredos) | `tools/validate_workflows.py` | RESULTADO: OK — nenhum erro estático |
| 5 | Sintaxe SQL de todas as queries dos nós Postgres (renderizadas com dados hostis) | `pglast` | 22/22 queries com sintaxe PostgreSQL válida |

## O que o teste 2 prova (e o que não prova)
Prova: uma ordem `criar_arquivo_pc`/`executar_pc` produz a chamada correta ao Worker real, o Worker cria o arquivo, o arquivo **existe no disco com o conteúdo e o sha256 esperados**, e a mensagem final só diz “✅ Executado e verificado” nesse caso. Comando “ok” sem o efeito → ❌; comando sem `verify` → ⚠️; Worker fora do ar → ❌; rota legada → ❓; mesmo `task_id` reenviado → não executa de novo.
**Não** prova: o fluxo dentro do n8n (importação, credenciais, expressões `{{ }}`), Telegram, Postgres real, ElevenLabs, nem a VPS/Central.

## Não testado / depende de você
| Item | Motivo |
|---|---|
| Importar e executar o `GENERAL_V10_EXERCITO.json` e o `AGENTE_EXECUTOR_v1.json` no n8n | não foi importado (ordem do projeto: mostrar o diff antes de mexer no ativo; o MCP do n8n só cria workflows a partir de código SDK, não de JSON) |
| Mensagem real no Telegram, transcrição de áudio, banco real | dependem do n8n rodando o V10 |
| **Voz (ElevenLabs)** | a “chave” do repositório era um *ID de chave*; a API respondeu `api_key_id_used_as_api_key`. Precisa de uma chave `sk_…` nova |
| **Central `/task` com sucesso** | a VPS não alcança o PC (chave Tailscale da VPS expirada → `PC_CALL_FAILED … connect timeout=120`); o formato de sucesso do Central segue **desconhecido** e o código do Central não está acessível daqui |
| Agente de Instagram publicar | exige conexão/credencial do Instagram e template de integração (não implementado); o modelo v1 só prepara conteúdo |
| Executor de agentes no n8n (LLM + gravação do artefato) | precisa das credenciais OpenAI/Postgres no n8n |

**Conclusão: o sistema NÃO está pronto.** Estão prontos e testados o Worker com contrato e a lógica de estados/verificação; falta a validação dentro do n8n, a rede VPS⇄PC, o Central no contrato e a voz.
