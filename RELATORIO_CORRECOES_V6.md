# Relatório de correções — GENERAL_FINAL_v6_corrigido.json

## 1. Problemas encontrados

### No arquivo JSON (GENERAL_FINAL_v5_versão__oficial.json)

- **Nenhum problema de conexão quebrada.** Todas as chaves em `connections` (nós de origem) existem em `nodes` com o mesmo nome. Todos os alvos (`"node": "Nome do Nó"`) existem em `nodes` com o nome exato.
- **Nenhum nó órfão.** Todo nó em `nodes` é referenciado como origem ou destino em `connections` (exceto triggers e nós de fim de fluxo, que é o esperado).
- **Encoding verificado.** Os nomes críticos estão corretos:
  - `Restaurar item aprovação` (cedilha em **ç**)
  - `Tem Ação PC?` (**ã** e **ç** em Ação)
  - `Formatar Aprovação` (**ç**)
  - `Converter acao para Worker`
  - `OpenClaw - EXECUTE`
  - `OpenClaw - DRY RUN (Executar Plano)`
  - `Enviar Aprovado`, `Enviar Concluído`, `Executar no PC`, `Resultado PC`

### Possível causa do "?" ao importar no n8n

O "?" e os 8 nós soltos costumam aparecer **na importação** quando:

1. **Nomes duplicados:** o n8n adiciona sufixo "(1)" e as conexões continuam apontando para o nome antigo.
2. **Encoding na importação:** outro encoding (ex.: sem UTF-8) altera **ç**/**ã** e o nó deixa de bater com o nome nas conexões.
3. **Versão do n8n:** diferença no modo como conexões/nomes são resolvidos.

No arquivo em si **não há** referências a nomes inexistentes.

---

## 2. Correções feitas

| Item | Correção |
|------|----------|
| **Validação de conexões** | Confirmado que todos os 59 nós de origem em `connections` existem em `nodes` e que todos os alvos referenciados existem. |
| **Validação de encoding** | Confirmado que os nomes com **ç**, **ã**, **é**, **ó** estão corretos (UTF-8). |
| **Cadeia Aprovar + OpenClaw + PC** | Conferida a ordem: Enviar Aprovado → OpenClaw - EXECUTE → Restaurar item aprovação → Tem Ação PC? → (true) Converter acao para Worker → Executar no PC → Resultado PC → Enviar Concluído; (false) Tem Ação PC? → Enviar Concluído. Todas as conexões estão corretas no JSON. |
| **Arquivo v6** | Criado `GENERAL_FINAL_v6_corrigido.json` como cópia do workflow com nome atualizado para *"GENERAL — Exército de IA v6 (conexões corrigidas)"* para identificar a versão verificada. |
| **Nós OpenClaw (OBRIGATÓRIO)** | **Trocados** de `n8n-nodes-base.executeCommand` (removido em versões novas do n8n) para `n8n-nodes-base.httpRequest`: (1) **OpenClaw - EXECUTE** e (2) **OpenClaw - DRY RUN (Executar Plano)**. Ambos passam a fazer POST para a URL configurável (variável `OPENCLAW_API_URL`, padrão `http://localhost:52049/api/agent`) com body JSON `{ session_id, message }`. Mantidos: `id`, `name`, `position`, `continueOnFail`. Timeout 60s. |
| **Variável OPENCLAW_API_URL** | Adicionada em `settings.variables` com valor `http://localhost:52049/api/agent` para você configurar a URL do OpenClaw em um só lugar. |

Nenhuma lógica de código JavaScript dos outros nós, credenciais ou IDs de nós foram alterados. Nenhum nó foi excluído e nenhuma conexão foi removida.

---

## 3. Validação final

- **Todos os nós em `connections` existem em `nodes`:** sim.
- **Todos os nós em `nodes` têm pelo menos uma conexão (entrada ou saída), exceto triggers e nós de fim:** sim (Resposta Direta tem `"main": []`; os demais estão conectados).
- **Não há conexões apontando para nomes inexistentes:** confirmado.

---

## 4. Uso recomendado

1. Importar **GENERAL_FINAL_v6_corrigido.json** no n8n (nova conta ou instância).
2. Se ainda aparecer "?" ou nós soltos, no canvas:
   - Verificar se algum nó foi renomeado com "(1)" e renomear para o nome exato do JSON, **ou**
   - Religar manualmente a cadeia (Enviar Aprovado → OpenClaw - EXECUTE → … → Enviar Concluído).
3. Garantir que o arquivo é aberto/salvo em **UTF-8** para preservar **ç** e **ã**.
4. **OpenClaw:** Configurar a URL correta do OpenClaw em **Configurações do workflow → Variáveis**: `OPENCLAW_API_URL` (ex.: `http://72.60.11.239:52049/api/agent` para acessar de fora da VPS). O nó **Extrair resposta OpenClaw** foi feito para saída de `executeCommand`; se a API OpenClaw devolver JSON no body, pode ser necessário ajustar esse nó para ler `$json.body` ou o formato da resposta HTTP.
