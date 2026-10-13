# Grok: editor de texto independente

`src/h3_backend/grok.py` monta a operação independente na API H3. A UI permite
descrever uma ideia simples e receber uma instrução editável. Não há conversa
persistente nem ligação com geração de vídeo. O adaptador técnico OAuth
foi portado de `alex-tavern-plugins/plugins/grok_supergrok/oauth.py`; não importa
Tavern nem reutiliza suas credenciais.

## Usar no front

Escreva na instrução da cena, por exemplo: **“ela dá um salto e o vestido fica
vermelho”**, e clique **Detalhar com Grok**. O texto retornado permanece editável.
Confira e só então clique **Gerar**: detalhar ou usar uma proposta nunca envia
vídeo, revisão ou continuação. Grok não recebe imagens, paths de runs ou parâmetros
nativos. Não edita imagens.

Em **Configurar Grok**, altere o system prompt que explica a tarefa e, se necessário,
informe um **ID real do modelo**. Vazio no pedido usa `H3_GROK_MODEL`; o app nunca
seleciona automaticamente o primeiro catálogo. A autenticação continua separada,
pelos comandos abaixo. Não cole tokens ou senhas nos campos do editor.

- `GET /grok/editor` retorna `{system_prompt,model}`. Sem arquivo, usa o system
  padrão de cena e o modelo do ambiente, **sem rede, auth ou criação de arquivos**.
- **Salvar configuração no PC** envia `PUT /grok/editor` com os mesmos dois campos.
  Salva somente `.data/grok/editor.json`, sob `H3_PROJECT_ROOT`, independentemente
  da configuração de vídeo. Não toca em `oauth.json`.
- System prompt não vazio: até 100000 caracteres. Modelo: string até 256, vazio
  permitido. Campos extras, JSON inválido e body acima de 1 MiB são rejeitados.
  Arquivo inválido/inacessível retorna 409 e não é apagado/substituído para esconder
  corrupção. Paths fixos usam diretórios/arquivo sem symlink e arquivo regular;
  publicação é temp exclusivo → fsync → replace → fsync do diretório.
- Padrão preserva ação, roupa, pose, ordem e idioma; pede somente a cena em até
  12000 caracteres, sem inventar identidade nem ajustar seed/duração/resolução/nodes.
  Templates/presets/benchmark nativos não são alterados.
- Se o rascunho, modo, seleção ou system/model mudar enquanto a resposta vem,
  a proposta fica separada para **Usar esta proposta**, sem sobrescrever o rascunho
  novo. Texto recebido usa value/textContent, nunca HTML.
- Resposta vazia/inválida/acima de 12000 não é truncada nem aplicada. Erro mantém
  o rascunho. Duplo clique envia apenas um POST; resultado incerto bloqueia novo
  pedido Grok nesta sessão, sem retry. Nunca contorne o bloqueio para repetir sem
  verificar a chamada. Isso não limpa uma admissão nativa incerta.

Os campos de configuração ficam fora do formulário de geração: Enter no ID do
modelo não dispara vídeo. Abertura da página só lê a configuração local; não
inicia inferência, autenticação, catálogo remoto ou renovação OAuth. SSE/reconexão
não chama Grok.

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

Validação nesta implementação: testes offline com HTTP falso e configuração em
raízes temporárias isoladas; nenhuma chamada real à xAI, autenticação da conta ou
geração GPU realizada. A suíte focada config/provider/OAuth passa 56 testes, com
22 novos casos de editor: default inerte, persistência/restart, limites Unicode,
JSON/unknown keys, corrupção, symlinks e falha atômica preservando o arquivo antigo.
A UI tem 18 contratos Node e browser com todas as requests interceptadas, incluindo
Grok, PUT de configuração e geração fake; mobile touch 393×852/2x e regressão de
12 cards longos em 1440/393/320. Evidências locais novas em `.dumps/tests/ui-grok/`
e `.dumps/tests/reports/grok_editor.json`; integração real read-only é gate separado
do principal, não prova de chamada ao provider ou de qualidade da geração.
