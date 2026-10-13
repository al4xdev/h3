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
O card, isoladamente, **não comprova elegibilidade, visão, cota ou cobrança do grant**.
A implementação foi inicialmente validada somente offline; uma validação real
posterior, deliberada e autorizada no plano37, está registrada abaixo. Seu sucesso
pontual não garante elegibilidade geral, cota futura ou condições de cobrança.

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

## Continuação: identidade original + último frame real

`POST /grok` aceita `continuation_parent_id` opcional, **string UUID canônica**, junto
com a `reference` original obrigatória. Sem o campo, text-only e uma imagem mantêm
seu contrato. Pai inválido não provoca fallback para uma imagem nem autenticação.

```json
{
  "system_prompt": "Meu sistema customizado, sem alteração.",
  "prompt": "ela vira de frente e mantém o vestido vermelho",
  "reference": {"source_root": "assets", "path": "dance_reference.png"},
  "continuation_parent_id": "00000000-0000-0000-0000-000000000001"
}
```

O adaptador técnico lê somente o manifesto próprio limitado a 1 MiB. Exige `id`
igual ao diretório, `state: accepted`, `decision.accepted: true`, `error: null`,
`publication_mode: atomic_copy_from_comfy_output` e
`output.path: .data/runs/<UUID>/chunk.mp4`. Ignora completamente `output.source`
(privado do Comfy). Alias legado exato `runs/<UUID>/chunk.mp4` é permitido somente
com o par receipt/verified da migração existente e SHA do vídeo no inventário
concordantes; o arquivo lido continua sendo o canonical próprio em `.data/runs`.
Estado/decisão ausentes ou ambíguos continuam bloqueados, mesmo em legado.

Exige exatamente uma referência `type: image, role: identity`, com
`source_root/source/sha256` correspondentes à seleção. Não suporta múltiplas
identidades. Só reconhece os demais papéis nativos `image/initial_frame` e
`video/motion_video`; não usa esses arquivos como identidade. Até assets sem prova
normal de publicação precisam concordar com o SHA registrado pelo pai neste modo.
Manifesto, fonte e identidade são revalidados depois das cópias e antes de submit;
troca de inode ou conteúdo do manifesto/vídeo durante preparação rejeita o pedido.

`GET /grok/continuation/<UUID>/last-frame` é prévia **CPU apenas**. Não chama OAuth,
catálogo, provider, Store, worker, Comfy, jobs ou decisões e não cria UUID de geração.
Não exige `last_frame.png` preexistente: congela o `chunk.mp4` próprio em snapshot
anônimo de disco sob `.dumps/grok-editor`, conta frames decodificados por FFprobe e
extrai `select=eq(n,count-1),format=rgb24,setsar=0` via FFmpeg. Mantém geometria,
PNG RGB e `map_metadata -1`, como o helper nativo intacto; nunca decodifica pixels
em Python. Valida a imagem **antes dos headers** e transmite bytes codificados em
blocos até 48 KiB; desconexão/cancelamento fecha snapshots e reap dos filhos próprios.
Não escreve frame, manifesto ou decisão no run e não lê um output privado.

Orçamentos operacionais do editor: vídeo até **256 MiB**, **3600 frames** decodificados,
geometria até **16 megapixels**, cada JPEG/PNG até **20 MiB** (40 MiB codificados
no máximo para o par), subprocesso até **120 s**, stdout/stderr limitados. Não são
máximos do modelo, garantia de desempenho ou ajustes dos parâmetros de geração.
Diretório scratch pertence ao dono e é privado; fontes/metadados são regulares,
link único, dono local e abertos por descriptors no-follow. Snapshots anônimos têm
zero links e são fechados em sucesso/erro/cancelamento; não há cache persistente.

A ação explícita congela e valida **ambas** as imagens antes de qualquer auth/provider.
Responses recebe um rótulo separado mandando analisar AMBAS, seguido de dois
`input_image` flat: primeiro identidade original, segundo último frame (pose/roupa
atual), e a instrução literal do usuário em `input_text` separado, sem transformação.
System customizado é enviado exato e não é regravado/reseedado. `Content-Length`
é calculado com a expansão base64 dos dois snapshots e todo o envelope. Leitura/hash
usa 48 KiB; expansão base64 gera blocos até 64 KiB, carry de no máximo dois bytes,
sem imagem/base64 inteira no heap. O helper antigo de uma imagem permanece compatível.

A UI deve mostrar identidade e frame com rótulos distintos, vincular respostas
atrasadas também ao ID do pai e apresentar falha de prévia honestamente. **Usar minha
instrução** pode seguir disponível: V2V nativo extrai seu próprio frame na geração,
que permanece uma ação separada e não foi alterada. Os testes automatizados usam
somente vídeos CPU sintéticos e fábricas provider falsas. A chamada real posterior
do plano37 confirmou aceitação do payload de duas imagens naquele grant, não uma
certificação científica de visão ou aderência completa da proposta.

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
diretos. A validação automatizada deste backend é fake/CPU em raízes temporárias: precedência do pin,
seed no-clobber, shape Responses/base64/limites, ownership/hash/races/links/cancelamento,
sem replay ou imports de geração. Essa implementação/testes não iniciaram servidor
de produção, provider ou GPU. A validação real deliberada abaixo é uma etapa separada;
integração UI, aderência da proposta e elegibilidade geral continuam gates distintos.

## Validação real posterior: plano37, autorização consumida

Após o opt-in explícito do dono, foi concluída **uma única** validação real do modelo
fixo `grok-4.20-0309-non-reasoning`: **um GET models/200** e **um POST Responses/200**,
com a identidade original e o último frame derivado do pai aceito `29699…`.
O transporte enviou `Content-Length: 2183776` exato, em **40 chunks**, maior bloco
**65536 bytes**; a execução completa levou **8.7403 s**. Evidência local preservada:
`.dumps/tests/grok-real-two-images-20261013-plan37-8d42e6/`.

A verificação final confirmou código congelado, pin, system customizado, grant,
identidade, referências, provas/SHA e vídeo inalterados, com o pai ainda aceito.
Não houve refresh, reautenticação, retry, GPU ou geração de vídeo. A autorização
desse teste foi consumida: o resultado não autoriza novas chamadas nem replay.

A resposta mencionou vestido vermelho e continuidade da pose de costas, mas também
acrescentou detalhes não solicitados e veio em inglês, estruturada como `Video 1`
com duração de 8 s. O system customizado atual foi mantido exato; esses elementos
eram apenas texto da proposta, não alterações dos parâmetros nativos ou geração.
O sucesso comprova aceitação real desse payload de duas imagens naquele instante,
**não aderência completa**, certificação científica de visão, qualidade artística
ou garantia geral de elegibilidade, cota e cobrança.
