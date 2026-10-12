# Grok: somente backend Python

`src/h3_backend/grok.py` monta a operação independente na API H3. Não há UI,
conversa persistente nem ligação com geração de vídeo. O adaptador técnico OAuth
foi portado de `alex-tavern-plugins/plugins/grok_supergrok/oauth.py`; não importa
Tavern nem reutiliza suas credenciais.

## Autenticar uma vez

Com a API ativa em `http://127.0.0.1:8010` (substitua a porta se necessário):

```fish
curl -sS -X POST http://127.0.0.1:8010/grok/auth/start
```

Abra `verification_uri` no navegador, entre **diretamente na xAI** e informe
`user_code`. Não envie senha, cookies ou tokens ao H3. O backend acompanha o
Device Flow nos intervalos exigidos pela xAI; o frontend H3 não participa.
Consulte a conclusão usando o `flow_id` retornado:

```fish
curl -sS -X POST http://127.0.0.1:8010/grok/auth/flow \
  -H 'Content-Type: application/json' -d '{"flow_id":"COLE_O_FLOW_ID"}'
curl -sS -X POST http://127.0.0.1:8010/grok/auth/status
curl -sS -X POST http://127.0.0.1:8010/grok/auth/models
```

As credenciais ficam em `.data/grok/oauth.json` no projeto (ou sob
`H3_PROJECT_ROOT`): arquivo 0600, diretório 0700, escrita atômica e gitignored.
São plaintext local: proteja o computador e seus backups. A pedido do dono,
o grant existente do Alex Tavern foi importado sem alterar a fonte ou acessar a
xAI. Não use os dois projetos simultaneamente para renovar esse mesmo grant:
refresh rotativo em um pode exigir reautenticação no outro. Reiniciar preserva a
conexão; a renovação ocorre quando necessário. Falha ambígua na renovação de um
grant rotativo exige autenticar novamente, sem reutilizar o grant anterior.
Para cancelar um login pendente, POST `/grok/auth/cancel` com o mesmo `flow_id`.

## Enviar somente system_prompt e prompt

Escolha um ID real do catálogo e configure o modelo ao iniciar a API:

```fish
env H3_GROK_MODEL=ID_DO_CATALOGO uv run uvicorn h3_backend.api:app --host 127.0.0.1 --port 8010
```

```fish
curl -sS -X POST http://127.0.0.1:8010/grok \
  -H 'Content-Type: application/json' \
  -d '{"system_prompt":"Responda em português, de forma objetiva.","prompt":"Olá!"}'
```

Resposta: `{"text":"...","model":"ID_DO_CATALOGO"}`. `system_prompt` é opcional.
Se preferir não configurar ambiente, inclua `"model":"ID_DO_CATALOGO"` no JSON.
Não selecionamos automaticamente o primeiro modelo ou um alias possivelmente
incompatível. Campos extras são rejeitados.

A chamada usa somente `https://api.x.ai/v1/responses`, com `store=false`,
`stream=false` e limite de saída de 8192 tokens. Não há retry de inferência,
fallback de endpoint/API key, histórico ou parâmetros de raciocínio adicionados.
Timeout/erro retorna falha sanitizada; um resultado incerto não deve ser repetido
cegamente. As rotas retornam `Cache-Control: no-store`.

## Limites

OAuth SuperGrok é experimental, usa o client público observado no plugin e não
comprova direito a integração de terceiros. O consentimento pode exibir Grok
Build. Verifique elegibilidade, cota e cobrança da conta: login não garante que
inferência esteja incluída na assinatura ou livre de cobrança adicional.
Mantenha a API local/rede confiável: ela não possui autenticação de acesso remoto.
O bloqueio same-origin existente impede mutações de outras origens no navegador,
mas não substitui autenticação para clientes HTTP diretos.

Validação nesta implementação: testes offline com HTTP falso; nenhuma chamada
real à xAI, autenticação da conta ou geração GPU realizada.
