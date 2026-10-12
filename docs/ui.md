# H3 · Bancada de filme

## Entrega independente — plano 15, revisão 2

HTML/CSS/JavaScript same-origin, sem framework, build, CDN, fontes remotas, dependências novas ou estado persistido no navegador. A bancada grafite/cobre preserva o vídeo retrato no centro e a régua ancestral real (origem → seleção). No celular, vídeo e decisões precedem formulário e biblioteca. Upload e catálogo usam o mesmo formulário simples.

**Assets e mocks apenas; integração real pendente do agente principal.** Esta entrega não altera backend, recursos, dados, geração nativa ou benchmark, nem conclui plano/goal. SSE verdadeiro, publicação de upload e segurança dos paths precisam dos gates da ponte Python.

## Contratos da ponte

| Caminho | Contrato |
| --- | --- |
| `GET /` | `src/h3_backend/web/index.html` |
| `GET /ui/app.css`, `/ui/app.js` | Assets fixos, MIME CSS/JavaScript ES module |
| `GET /app/config` | `default_prompt`, `continuation_prompt`, `reference_image:"dance_reference.png"`, `duration_seconds:2.3`, `workflow_output_profile`; flags opcionais `filesystem_events`, `reference_library`, `assembly_enabled:false` |
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

Seed aceita somente dígitos e inteiro seguro `0..9007199254740991` (não sinais, expoente, hexadecimal, decimal ou espaços). Prompt não vazio, até 12000 caracteres, preservado exatamente. Duração e parâmetros de geração continuam fixos. Não há botão nem POST de montagem: `assembly_enabled:false` não promete implementação da fase 18.

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
env H3_UI_TEST_CLIP=runs/02cf408f-c985-47a2-887d-731569d7827a/chunk.mp4 node tests/frontend_browser_mock.mjs
```

13 testes Node, incluindo os oito contratos originais, roots/references, URLs inseguras, File bruto/duplo upload, normalização SSE e espera vazia/ID incorreto. Browser intercepta **todas** as requests de `http://h3.mock.invalid`, bloqueia origem externa e nunca abre processo API/Comfy. EventSource fake controlável reproduz abertura, reconexão, hints e close. POSTs de inferência, review e upload são separados e rotulados no relatório; upload fake não escreve disco.

O clip histórico é lido sem alteração e servido só pelo mock: dimensões 480×864, playback explícito/pausa, sem inferência. Testes cobrem 1440/390/320 sem overflow, XSS textual, estados sem arquivo, cadeia, duplo submit, payloads exatos, upload selecionado sem geração, snapshot SSE-first, burst bounded, dirty durante wait, seleção atrasada, reconexão sem POST e sem limpar incerteza, pagehide e config legado sem flags.

Evidências locais novas (não sobrescrevem entrega R1):

- `.dumps/tests/ui-paths/`: desktop/mobile, empty, API error, admission uncertain, failed evidence, reference gallery, upload selected e SSE refreshed.
- `.dumps/tests/reports/frontend_paths.json`: requests, exceções, violações, contagens de fake inference e fake disk upload.
- `.dumps/tests/reports/frontend_paths_before.json`: hashes de manifests/mídia existentes de `runs`, `.data/runs` e `assets`; verificação posterior separada.

**Pendente do principal:** endpoints verdadeiros/config, stream SSE/inotify e lifecycle real, upload atômico validado, contenção/MIME/CSP/Range, wheel assets e browser read-only em API própria após gates CPU. Nenhum GPU, ajuste de geração, mudança de dados ou certificação perceptual foi executado nesta entrega.
