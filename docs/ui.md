# H3 · Bancada de filme

## Entrega independente — plano 15, revisão 2

HTML/CSS/JavaScript same-origin, sem framework, build, CDN, fontes remotas, dependências novas ou estado persistido no navegador. A bancada grafite/cobre preserva o vídeo retrato no centro e a régua ancestral real (origem → seleção). No celular, vídeo e decisões precedem formulário e biblioteca. Upload e catálogo usam o mesmo formulário simples.

A entrega original de assets/mocks não concluía a integração. A ponte agora foi implementada separadamente no commit `6eae6f9`; o principal já validou leitura real de biblioteca/SSE/Range e reprodução sem POST. A biblioteca com 12 cards revelou compressão flex: `flex-shrink:0` mantém todos os filhos dentro de cada card e a lista rolável limitada. **As revisões acrescentam o editor Grok isolado, a correção visual e controles explícitos de montagem; fechamento e revalidação real da UI final permanecem com o principal.** Não altera geração nativa, recursos ou dados existentes.

## Contratos da ponte

| Caminho | Contrato |
| --- | --- |
| `GET /` | `src/h3_backend/web/index.html` |
| `GET /ui/app.css`, `/ui/app.js` | Assets fixos, MIME CSS/JavaScript ES module |
| `GET /app/config` | `default_prompt`, `continuation_prompt`, `reference_image:"dance_reference.png"`, `duration_seconds:2.3`, `workflow_output_profile`; flags opcionais `filesystem_events`, `reference_library`, `assembly_enabled` (false até os gates da montagem) |
| `GET /runs?limit=50&offset=0` | `{items,total,limit,offset}`; itens `id,state,prompt,seed,duration_seconds,created_at,updated_at,parent_id,video_url` |
| `GET /inputs?limit=50&offset=0` | `{items,total,limit,offset}`; itens `id,source_root,path,name,image_url,width?,height?` |
| `POST /inputs?name=<encodeURIComponent(file.name)>` | Body **File** bruto, Content-Type do arquivo ou `application/octet-stream`; resposta item do catálogo |
| `GET /events` | EventSource same-origin; evento `change` (ou default `message`), JSON `{path,invalidation:true}` |

`source_root` só admite `assets`, `inputs`, `runs`. Paths e nomes são texto, não HTML, CSS selectors ou comandos. Thumbnails só aceitam URLs relativas próprias: `/assets/image?path=…`, `/inputs/image?path=…`, `/runs/{id}/image?name=initial_frame.png|last_frame.png`. O navegador não valida ownership do disco: contenção, formatos reais, symlinks e publicação atômica são responsabilidade da ponte. Paths relativos inseguros e URLs externas são rejeitados na UI também.

A referência original permanece default pelo alias legado. Escolher explicitamente um item envia `references:[{source_root,path}]` no **novo i2v**, sem campos extras do catálogo. Arquivos já no PC e frames publicados entram pelo catálogo, nunca por acesso livre ao filesystem do celular. Upload PNG/JPEG/WebP tem guard de 32 MiB, não vazio, duplo clique e resultado incerto. Nenhum base64, multipart, leitura gigante do File ou blob persistido. A prévia usa a URL própria retornada após publicação. Upload escolhe a imagem, mas **não gera nem revisa**. A validação efetiva do conteúdo pertence ao FFmpeg no PC; os bytes são salvos em `.data` no PC mesmo quando enviados pelo celular.

Rotas existentes preservadas:

- `GET /runs/{id}`: Run completo com `output.path`, erro e timestamps.
- `GET /runs/{id}/sequence`: mantém `blocks` na ordem recebida, sem ordenar IDs, escolher irmãos ou montar frames.
- `GET /runs/{id}/video`: player único, controls/playsinline/preload metadata/contain, sem autoplay. Exige estado `ready_for_review|accepted|rejected`, `output.path` no detalhe e URL própria explícita na coleção/cadeia. Falha, interrupção ou arquivo ausente não viram vídeo pronto.
- `POST /runs/{id}/accept|reject`: apenas `ready_for_review`, ação explícita, sem body. Evidência rejeitada permanece.
- `POST /runs/i2v`: `{seed,prompt,duration_seconds:2.3,image:"dance_reference.png"}` por default; seleção explícita troca apenas `image` por `references`.
- `POST /runs/{accepted_parent_id}/v2v`: `{seed,prompt,duration_seconds:2.3,reference_tail_seconds:3,include_audio:true}`. **Sem nova referência**: identidade original do pai é herdada imutavelmente. Catálogo/upload ficam desabilitados nesse modo, com explicação visível.

Seed aceita somente dígitos e inteiro seguro `0..9007199254740991` (não sinais, expoente, hexadecimal, decimal, espaços ou newline/CRLF). Prompt não vazio, até 12000 caracteres, preservado exatamente. Duração e parâmetros de geração continuam fixos. Montagem aparece somente com `assembly_enabled:true`, conforme o plano 22r2; false/flag ausente não faz requests de montagem.

## Eventos, admissão e recuperação

1. Config sem flags mantém comportamento legado, sem abrir EventSource ou pedir catálogo.
2. Com SSE, registra listeners e espera o primeiro `open` **antes do snapshot** de catálogo/runs. Um erro inicial permite snapshot offline; o próximo open relê metadados. Não há timer, polling ou retry de POST.
3. Hints aceitam paths `runs/…`, `inputs/…` e prefixo real `.data/…`; `.data`/invalidation sem path relê o snapshot inteiro. Telemetria, tmp e `.part` são ignorados. Bursts se agrupam em microtask, uma leitura ativa e um dirty flag; mudanças durante a leitura provocam uma releitura limitada após ela.
4. Durante geração/revisão/upload, hints ficam dirty até o resultado. Epochs protegem seleção e coleção contra respostas antigas. Refresh de progresso não reassocia `video.src` quando a URL é a mesma. Pagehide fecha EventSource e aborta somente a espera local, **não cancela geração**.
5. Geração explícita exige um POST **202** com ID real, seguido de exatamente um `GET /runs/{own_id}?wait=true`. Resultado vazio/de outro ID, wait perdido, admissão ambígua ou 5xx bloqueiam nova geração nesta sessão. Refresh/SSE nunca limpam esse bloqueio por suposição e nunca reenviam intenção.
6. 400/404/409 explícitos não são repetidos. Upload desconhecido também permanece bloqueado para evitar duplicação silenciosa; consulte o catálogo. Uma falha de leitura após publicação confirmada não é tratada como falha de admissão.

Somente estado transitório em memória. textContent/createElement, labels, teclado, foco visível, aria-live, skip link e reduced-motion. CSP recomendado: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`. Sem scripts/styles inline no HTML.

## Validação CPU e browser totalmente interceptado

Comandos fish (Playwright/Chromium já instalados; **não instalar npm/dependências**):

```fish
node --check src/h3_backend/web/app.js
node --test tests/frontend_ui.test.mjs
env H3_UI_TEST_CLIP=runs/02cf408f-c985-47a2-887d-731569d7827a/chunk.mp4 H3_UI_TEST_ASSEMBLY=.dumps/benchmarks/baseline-three-chunks/benchmark.mp4 node tests/frontend_browser_mock.mjs
```

25 testes Node, incluindo os oito contratos originais, cinco de Grok, sete de montagem e os de roots/references, URLs inseguras, File bruto/duplo upload, normalização SSE e espera vazia/ID incorreto. Browser intercepta **todas** as requests de `http://h3.mock.invalid`, bloqueia origem externa e nunca abre processo API/Comfy. EventSource fake controlável reproduz abertura, reconexão, hints e close. POSTs de inferência, review, upload, Grok e montagem são separados e rotulados no relatório; upload/montagem fake não escrevem disco.

O clip histórico é lido sem alteração e servido só pelo mock: dimensões 480×864, playback explícito/pausa, sem inferência. Testes cobrem 1440/390/320 sem overflow, XSS textual, estados sem arquivo, cadeia, duplo submit, payloads exatos, upload selecionado sem geração, snapshot SSE-first, burst bounded, dirty durante wait, seleção atrasada, reconexão sem POST e sem limpar incerteza, pagehide e config legado sem flags.

Evidências locais novas (não sobrescrevem entrega R1):

- `.dumps/tests/ui-paths/`: desktop/mobile, empty, API error, admission uncertain, failed evidence, reference gallery, upload selected e SSE refreshed.
- `.dumps/tests/reports/frontend_paths.json`: requests, exceções, violações, contagens de fake inference e fake disk upload.
- `.dumps/tests/reports/frontend_paths_before.json`: hashes de manifests/mídia existentes de `runs`, `.data/runs` e `assets`; verificação posterior separada.

## Editor de cena Grok — plano 20, revisão 2

Um botão **Detalhar com Grok** envia somente ideia atual + system prompt + modelo
opcional a `POST /grok`. Texto estável volta ao campo editável; resposta velha vira
proposta explícita. Não é chat, não recebe fotos/paths e nunca envia geração,
aceitação, continuação ou montagem. Confira e use **Gerar** separadamente.

Details **Configurar Grok** oferece system prompt e ID de modelo opcionais, mais
**Salvar configuração no PC**. Fica fora do formulário nativo para Enter no modelo
não enviar vídeo. `GET /grok/editor` é leitura local inerte no startup;
`PUT /grok/editor` publica `.data/grok/editor.json`, nunca OAuth. Modelo vazio no
pedido defere ao ambiente; nenhum modelo é escolhido automaticamente. Leia
[contratos, autenticação e limites](grok.md). Sem calls remotas na abertura/SSE,
sem catálogo/auth automático ou repetição de pedido incerto.

Novos mocks cobrem conteúdo literal/XSS, ideia simples, system/model, PUT explícito,
Grok duplo clique sem POST nativo, draft mais novo/proposta/Usar, geração somente
pelo botão nativo, erro/oversize/unknown sem truncar/retry ou limpar incerteza nativa,
config indisponível sem bloquear geração e Enter no modelo. A regressão de 12 cards
longos verifica bounding boxes de todos os filhos em 1440/393/320. Phone real-emulado
393×852, touch e escala 2, verifica detalhe sem envio nativo e sem overflow.

Evidências desta revisão, separadas das anteriores:

- `.dumps/tests/ui-grok/`: desktop/mobile e estados anteriores; `grok-detailed-desktop`,
  `grok-stale-proposal`, `grok-oversized-error`, `grok-uncertain`,
  `grok-phone-393-touch-2x` e `library-many-{1440,393,320}` PNGs.
- `.dumps/tests/reports/grok_editor.json`: requests e contagens distintas de Grok
  fake, PUT config, inferência/review/upload fake, erros e bloqueios externos.
- `.dumps/tests/reports/library_bounds_after.json`: children/card, altura e shrink.
- `.dumps/tests/reports/grok_editor_hashcheck.json`: 162 arquivos protegidos
  originais/canônicos/assets comparados, sem credenciais.

**Pendente do principal:** browser real read-only final com configuração Grok e
correção dos cards, empacotamento/validação de assets e fechamento das tarefas.
Testes Grok são offline; não provam elegibilidade/cobrança/provider real. Nenhum
GPU, ajuste de geração, alteração de recursos ou certificação perceptual foi
executado nesta entrega.

## Montagem explícita — plano 22, revisão 2

**Montar sequência** fica fora do formulário de geração. Só aparece com flag true
e habilita quando o último bloco é pronto/aceito, todos os pais são aceitos e a
cadeia origem → seleção tem IDs e URLs próprios publicados (até 100 blocos).
Montar não aceita o último bloco, não altera revisão, não usa Grok nem gera novos
chunks. O vídeo do bloco continua no player original.

1. Antes do POST, o navegador gera um UUID criptográfico e grava somente o ponteiro
   `?assembly=<UUID>` via history.replaceState, preservando outras queries e o
   skiplink/hash `#viewer`. Preferência: crypto.randomUUID; em HTTP LAN sem essa
   função, WebCrypto.getRandomValues com 16 bytes, version4/variant RFC4122. Nunca
   Math.random. Sem WebCrypto, falha antes do POST.
2. `POST /assemblies/{UUID}` recebe somente `{end_run_id:<UUID>}` e aguarda **200**
   com montagem completa. Não há 202, fila ou GET wait nesse fluxo. Guard no botão
   e cliente impede envio duplicado. Busy/409/collision são honestos e não repetidos.
3. Erro incerto mantém o mesmo UUID/query e bloqueia outra intenção às cegas.
   **Reler montagem**, reload e SSE fazem só GETs. 404 não autoriza novo UUID/replay.
   Confirmar metadados terminais reconcilia apenas essa montagem; o mesmo intento
   conhecido não é submetido novamente. Após prévia completed e aceite explícito do
   último bloco, Montar pode criar uma nova revisão accepted com outro UUID; aceitar,
   reload e SSE nunca criam esse ID/POST. A prévia anterior continua imutável e com
   seu label original. Incerteza nativa/Grok continua independente.
4. `GET /assemblies?end_run_id=<UUID>&limit=50&offset=0` redescobre registros do fim
   escolhido; `GET /assemblies/{UUID}` recupera o ponteiro conhecido. A query não
   guarda estado de negócio: JSON/commit em `.data` permanece a autoridade.
5. Painel separado e recolhível, controls/playsinline/preload metadata/contain, sem
   autoplay. URL/download só `/assemblies/{UUID}/video`, completed + hashes válidos
   e output próprio. Lazy src ao abrir o painel. Seleção antiga/resposta tardia nunca
   troca o player do bloco atual. SSE metadata usa o mesmo subscriber/coalescing,
   sem timers e sem POST; tmp/request/video não iniciam montagem.
6. Label: **Montagem de prévia — revisão pendente** para fim ready; **Montagem da
   sequência aceita** para fim accepted. Metadados mostram ID, frames, fps e erro.
   Ordem/count preservados não significam pixels/MP4 lossless ou qualidade artística.

Mocks usam o filme histórico já existente de 7 s exclusivamente como bytes
interceptados: 480×864, 168 frames/24 fps, playback explícito/pausa. Hash da fixture
é verificado sem alteração; não houve FFmpeg/POST/API real pelo agente de UI.
Casos: flag false sem requests, duplo clique, query/hash/UUID fallback, preview com
terceiro ainda ready, accepted, stale selection, busy/collision, lost response +
GET/reload mesmo ID, missing ID bloqueado, pais rejeitados/fim failed, URL externa
rejeitada, SSE/reconnect sem POST nem reset dos players e 393×852 touch/2x + 320 sem
overflow. Não é teste em celular físico.

Evidências novas (preservam os relatórios e screenshots anteriores):

- `.dumps/tests/ui-assembly/`: desktop/mobile, preview, accepted, stale, busy,
  uncertain, missing ID e painel phone; também regressões anteriores.
- `.dumps/tests/reports/assembly_ui.json`: requests, contagens fake por endpoint,
  UUID fallback, hash da fixture e zero cloud/GPU/exceções externas.
- `.dumps/tests/reports/assembly_ui_hashcheck.json`: 162 arquivos originais/data/
  assets inalterados, sem leitura de credenciais.

**Pendente do principal:** gate backend completo, integração real e UMA montagem
CPU deliberada em revisão própria, preservando os vídeos/Runs/revisões originais.
Frontend/mocks não concluem o plano 22 ou o objetivo inteiro do aplicativo.
