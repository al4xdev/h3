# Grok: contexto visual, saída somente texto

`src/h3_backend/grok.py` é uma operação independente da geração de vídeo.
Recebe a ideia, o system prompt e uma referência opcional própria; devolve texto
editável. Não gera/edita imagens, cria runs, aceita revisões, continua ou monta vídeos.
Usar a proposta e **Gerar** continuam ações explícitas separadas. O frontend deve
capturar a referência com o rascunho e separar respostas atrasadas, nunca sobrescrever
uma ideia nova. Texto é não confiável: `.value`/`textContent`, não HTML.

## Modelo fixo e configuração no PC

Pin aprovado: **`grok-4.20-0309-non-reasoning`**, sem alias `latest`.
O [card oficial](https://docs.x.ai/developers/models/grok-4.20-non-reasoning.md)
publica text+image → text, sem reasoning, contexto de 1 milhão de tokens.
Isso **não comprova elegibilidade, visão, cota ou cobrança do grant da conta**;
nesta implementação não houve inferência/autenticação/catálogo real.

- `.data/grok/editor.json`, sob `H3_PROJECT_ROOT`, guarda `{system_prompt,model}`.
  É separado de `oauth.json`; não coloque segredos nesses campos.
- `seed_editor(root)` é uma ação administrativa explícita, nunca import/startup/GET.
  Cria somente se ausente, com system prompt padrão e o pin acima: temp exclusivo
  0600 → fsync → link no-clobber → remover seu temp → fsync do diretório.
  Configuração existente válida é retornada intacta, inclusive se seu modelo divergir;
  o administrador deve conferir a divergência, não substituí-la silenciosamente.
- `GET /grok/editor` é inerte. Sem arquivo, retorna o system padrão e
  `H3_GROK_MODEL`, sem criar diretórios. Corrupção/links/inacessibilidade retornam 409.
- `POST /grok` relê a configuração. Modelo persistido **não vazio** é autoridade;
  request com outro modelo retorna `model_fixed`/409 antes de qualquer rede.
  Sem pin persistido, mantém compatibilidade: request.model → ambiente capturado
  no startup. Sem nenhum modelo retorna 400, nunca escolhe o primeiro catálogo.
- `PUT /grok/editor` mantém o pin existente não vazio. Permite system prompt novo
  com modelo omitido ou idêntico; modelo diferente ou vazio retorna 409 sem alteração.
  Trocar um pin exige decisão administrativa explícita no JSON local, não o editor
  público. Config legacy ausente/vazia ainda permite seu contrato antigo de gravação.
- System prompt: 1..100000 caracteres, não vazio; modelo: até 256 caracteres.
  JSON tem limite de 1 MiB e não aceita campos extras. Config inválida existente
  nunca é apagada/substituída para esconder evidência. Diretórios/arquivo são no-follow,
  arquivo regular, dono local e link único. Gravação normal é atômica/fsync.

## HTTP: ideia e referência selecionada

Exemplo de body de `POST /grok` (somente no clique explícito de detalhar):

```json
{
  "system_prompt": "Detalhe a ideia sem inventar ações ou parâmetros.",
  "prompt": "ela dá um salto e o vestido fica vermelho",
  "reference": {"source_root": "assets", "path": "dance_reference.png"}
}
```

`reference` é opcional para compatibilidade text-only. `model` é opcional e não
pode divergir do pin persistido. Resposta: `{"text":"...","model":"..."}`.
O endpoint recebe prompt até 100000 caracteres; o campo de cena/UI limita 12000 e
rejeita saída maior sem truncar. O system prompt padrão pede somente a instrução da
cena no idioma do usuário, sem inventar identidade ou alterar parâmetros nativos.

O helper `infrastructure/grok_image.py` resolve somente bytes públicos próprios:

- `assets`: path relativo público contido em `assets/`, sem segmentos privados.
- `inputs`: `<UUID>/original.png|jpg|jpeg`, sob `.data/inputs`, com publicação
  `metadata.json` própria e id/source_root/path/SHA concordantes; `.part` rejeitado.
  Inputs colocados manualmente sem prova publicada não são enviados ao Grok.
- `runs`: `.data/runs/<UUID>/initial_frame.png|last_frame.png`. Exige manifest com
  id correto e referência explícita de imagem para esse path/SHA, ou inventário de
  migração completo. Alias `runs/<UUID>/...` só com recibo e verified.json idênticos,
  root/destination/run_ids/inventory_sha256 e SHA do frame comprovados. Não importa
  Store/models/dispatcher/worker nem lê decisões para autorizar geração.
  Frame sem prova explícita é rejeitado, mesmo se listado na biblioteca antiga.

Todos os componentes de path são abertos por descriptors no-follow; não aceita
URLs/absolutos/traversal/links/FIFO/arquivo estrangeiro/temporário. O arquivo final
é regular, dono local, link único e até **20 MiB**. Cópia e SHA usam buffers de
48 KiB; identidade/tamanho/mtime/ctime da fonte e prova são conferidos novamente.
Um snapshot privado temporário no filesystem de `.dumps/grok-editor/` congela os
bytes antes da validação/submissão e é fechado/removido em erro/cancelamento.
Os bytes originais e metadados publicados não são escritos ou alterados.

FFprobe/FFmpeg externos confirmam JPEG/PNG real e uma única imagem completa.
Mantém guard operacional local de 16 megapixels; não é um máximo documentado do
modelo. WebP, imagem maior que 20 MiB, corrupção/animação ou prova ausente retornam
`invalid_reference`/400 **antes de auth/catálogo/inferência**. Não converte, redimensiona
ou recomprime silenciosamente; o limite de 32 MiB da geração permanece intacto.
Python não decodifica pixels nem guarda toda imagem/base64 no heap.

A [documentação oficial de imagem](https://docs.x.ai/developers/model-capabilities/images/understanding.md)
especifica JPEG/PNG, até 20 MiB e o contrato Responses:

```json
{"role":"user","content":[
  {"type":"input_image","image_url":"data:image/png;base64,..."},
  {"type":"input_text","text":"ideia"}
]}
```

`image_url` é uma **string flat**, não o objeto `{url:...}` do Chat Completions.
Não publica mídia na Internet nem pede que xAI acesse URL localhost.
O body sai por `httpx content=`/async JSON stream, com prefixo/sufixo limitados e
base64 incremental de blocos divisíveis por três. `Content-Length` inclui a expansão
`4*ceil(bytes/3)`; uma imagem de 20 MiB ocupa 27.962.028 bytes base64 mais o envelope.
Não usa `read_bytes`, base64 completa ou `json=` com mídia inteira.

## Provider e autenticação permanecem separados

Somente a ação explícita de editar usa `https://api.x.ai/v1/responses`, após validar
modelo no catálogo do grant pelo adaptador OAuth existente (cache curto pode evitar
GET remoto; renovação pode acontecer nesse clique). Não há atividade remota em
import/startup/GET/config save/upload/SSE/reload. Mantém `store=false`, `stream=false`,
8192 tokens de saída, timeout de 120 s e resposta limitada a 2 MiB. Sem retry de
inferência, fallback de endpoint/API key, histórico ou parâmetros de reasoning.
Erro é sanitizado e mantém rascunho; não repetir resultado incerto às cegas.
As rotas retornam `Cache-Control: no-store`.

O OAuth foi portado do Alex Tavern, independente do editor. Credenciais ficam em
`.data/grok/oauth.json`, 0600/diretório 0700 e plaintext local: proteja computador e
backups. Não use os dois projetos simultaneamente para renovar o mesmo grant rotativo.
Não leia/exiba/copie credenciais para configurar o editor. Login não comprova direito
à integração de terceiros nem que inferência esteja incluída na assinatura.

Se o dono decidir autenticar, com a API **já ativa**, ação explícita em fish:

```fish
curl -sS -X POST http://127.0.0.1:8010/grok/auth/start
```

Abra `verification_uri` diretamente na xAI e informe `user_code`. Nunca envie senha,
cookies ou tokens ao H3. POST `/grok/auth/flow` com `{"flow_id":"..."}` consulta o fluxo;
`/grok/auth/cancel` cancela esse mesmo fluxo. `/grok/auth/status` e `/grok/auth/models`
são operações explícitas, não descoberta automática de página.

API local/rede confiável: same-origin não substitui autenticação para clientes HTTP
diretos. Validação deste backend é fake/CPU em raízes temporárias: precedência do pin,
seed no-clobber, shape Responses/base64/limites, ownership/hash/races/links/cancelamento,
sem replay ou imports de geração. Integração UI e elegibilidade real são gates separados;
não foram iniciados servidor de produção, provider ou GPU para validar este código.
