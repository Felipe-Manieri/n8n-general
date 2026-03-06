# Resolver Captcha no GENERAL V9 (2Captcha)

## Serviços que funcionam com n8n

- **2Captcha** — https://2captcha.com — pago por resolução (~US$ 0,002 por captcha).  
- **Anti-Captcha** — https://anti-captcha.com — similar.  
- **CaptchaAI** — preço fixo mensal, citado na comunidade n8n.

Todos são chamados por **HTTP Request** no n8n (ou Code).

---

## 2Captcha — fluxo em 2 passos

### 1. Enviar a imagem do captcha

- **URL:** `https://api.2captcha.com/in` (método POST, form-data ou JSON).  
- **Parâmetros:**  
  - `key` = sua API key (conta 2Captcha)  
  - `method` = `post` (captcha de imagem)  
  - `file` = imagem em base64 **ou** `url` = URL pública da imagem do captcha  

Documentação: https://2captcha.com/api-docs/normal-captcha

Resposta exemplo: `OK|request_id` (você guarda o `request_id`).

### 2. Buscar o resultado

- **URL:** `https://api.2captcha.com/res`  
- **Parâmetros:** `key`, `id` = `request_id`  
- Polling a cada 5–10 s até receber `OK|texto_do_captcha` (ou erro).

O “texto do captcha” é o que o usuário digitaria; você usa esse texto como resposta no fluxo (ex.: enviar de volta ao agente / General).

---

## Onde encaixar no V9

Quando o General pedir input do tipo **captcha** (`need_user_input` com `input_type: "captcha"` e opcionalmente `has_image: true`):

1. Se tiver **URL da imagem** do captcha no payload (ex.: `payload.image_url` ou campo que você definir no prompt do General), use essa URL no passo 1 do 2Captcha.  
2. Adicione no workflow:
   - um **HTTP Request** (ou Code) que chama `https://api.2captcha.com/in` com `key` e `url` (ou `file` em base64);
   - depois um **Wait** (alguns segundos) + outro **HTTP Request** em `https://api.2captcha.com/res` com `key` e `id`;
   - ou um **Code** que faz o polling em loop até `OK|...`.
3. O resultado (`OK|texto`) vira a “resposta do usuário” no fluxo: use como se o Felipe tivesse digitado esse texto (ex.: enviar para o nó que trata “resposta ao pedido de input” / retomar tarefa).

Assim o V9 pode **resolver o captcha automaticamente** quando o General indicar que precisa de um captcha e você tiver a imagem (URL ou base64).

---

## Variável de ambiente (recomendado)

Não coloque a API key no JSON do workflow. No n8n:

- Crie uma variável de ambiente, por exemplo: `CAPTCHA_2CAPTCHA_KEY`.
- Nos nós HTTP Request (ou Code), use: `{{ $env.CAPTCHA_2CAPTCHA_KEY }}`.

---

## Resumo

- **Sim**, dá para usar um “bot”/API para resolver captcha: 2Captcha, Anti-Captcha, etc.  
- No V9: quando o fluxo estiver em “pedir input” do tipo captcha e tiver a **imagem** (URL ou base64), adicione 1–2 nós (HTTP ou Code) que chamem a API e usem o texto retornado como resposta no fluxo.  
- Correções já feitas no V9: dedup (Deduplicar sem `alwaysOutputData`) e query do Deduplicar com `Number()` e escape de `chat_id`.
