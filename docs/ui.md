# H3 · Bancada de filme

## Mobile por telas, contexto visual e novas tentativas — planos 23–26 e 32–34

HTML/CSS/JavaScript same-origin, sem framework, build, CDN ou fontes remotas. A identidade grafite/cobre e a **linha ancestral real** permanecem. Telefone e desktop mostram um painel principal visível/focável, com topo compacto sticky: **Voltar · título · engrenagem**. Nova cena e Atualizar são ações da biblioteca, não abas permanentes. A biblioteca, cartões ancestrais e ações usam uma única rolagem do documento; não há listas internas rolantes, filmstrip horizontal ou rodapé/docks fixos. Campos de texto mantêm seu comportamento nativo.

### Caminho de uso

1. **Biblioteca** abre primeiro. Nova cena inicia um rascunho; selecionar um bloco lê seus metadados e abre a revisão. Falhas/interrupções não se tornam vídeos prontos.
2. **Referência e ideia** escolhe a imagem original ou uma referência publicada no PC, recebe upload explícito e a ideia simples. Upload salva em `.data` no PC e não gera nem chama Grok.
3. **Proposta do Grok** mantém a ideia separada, mostra texto sempre editável e exige **Usar esta proposta**. **Usar minha instrução** permite pular Grok. Nenhuma dessas ações gera vídeo.
4. **Preparar geração / pedido no PC** mostra a instrução escolhida, referência/parent e resumo seed + duração solicitada → frames → tempo alinhado. A engrenagem edita seed/duração do rascunho ainda não enviado. Só **Gerar** envia a intenção. HTTP 202 é admissão, não conclusão. **Abrir bloco** leva ao resultado confirmado.
5. **Revisar bloco** oferece vídeo retrato manual, tempo solicitado/alinhado/verificado, ancestrais e decisões explícitas. Aceitar apenas desbloqueia continuação; não continua nem monta automaticamente.
6. **Preparar continuação** confirma o pai aceito. A composição mostra **identidade original + último frame real do pai**, com papéis distintos: identidade e pose/roupa atual. Grok recebe os dois somente ao clicar Detalhar. O V2V nativo já inicia nesse último frame e permanece inalterado; descrever leva à ideia/proposta/geração.
7. **Montagem** é uma tela e uma ação separadas. A cadeia é a ancestralidade exata do fim selecionado, sem misturar ramificações. Montar não aceita o fim nem gera outros blocos. Recarregar/abrir diretamente um UUID recupera uma tela com origem na biblioteca: Voltar continua disponível, sem limpar UUID, query/hash ou locks. GET404/5xx/prova incompleta mantém a incerteza e oferece Reler o mesmo ID, nunca novo POST ou fallback de catálogo que esconda a falha.

**Ajustes** abre pela engrenagem e retorna à origem com rascunho/parent/status, scroll e foco preservados, sem abrir teclado automaticamente. Seed/duração estão disponíveis somente para o rascunho ainda não enviado; biblioteca/revisão/status/montagem não editam resultados. A seção Grok separa instruções globais, modelo readonly e Salvar no PC explícito. Voltar/Concluir ajustes não salva configuração nem gera.

**Recusado ou interrompido** conserva o **prompt enviado naquela tentativa**, inclusive a versão melhorada pelo Grok se foi usada. Preparar nova tentativa abre diretamente Preparar geração preenchida — prompt literal, referência registrada, seed e duração — em rascunho `retry:<ID>` isolado. Não volta ao começo, não consulta Grok automaticamente e não gera até Gerar. Rascunho de retry já editado é retomado sem sobrescrever os demais. Root cria novo i2v; continuação usa o mesmo pai original ainda aceito, nunca a tentativa terminal como pai. A tentativa antiga permanece imutável e a nova exige revisão própria. Falta de metadados/proveniência ou parâmetros não suportados bloqueia a cópia com motivo, sem defaults; pedidos ainda incertos/busy não autorizam replay. Não há promessa de mesmos bytes/pixels.

Voltar, seleção, resize, history e SSE conservam rascunhos por cena/pai: ideia, proposta editada, instrução escolhida, referência, seed e duração. O preset não sobrescreve rascunhos sujos em cada troca. Resposta Grok atrasada fica no rascunho original, marcada com o contexto antigo; nunca substitui a ideia de outro pai. **Reabrir proposta deste rascunho** permite conferi-la explicitamente. Se você editou a proposta enquanto Grok trabalhava, essa edição vence: a resposta atrasada fica em um disclosure separado no rascunho de origem. **Substituir a proposta pela resposta atrasada** é outra escolha explícita que só copia para o editor; não muda ideia/instrução escolhida/referência/duração/seed nem envia geração. Sem candidato, essa ação não faz nada.

Incerteza bloqueia execução, não a consulta do rascunho: Voltar/retomar o texto na biblioteca não cria pedido, limpa flags ou retira a marca de um rascunho já admitido. Gerar e preparar um retry distinto continuam bloqueados enquanto a intenção anterior não estiver resolvida.

Estado de tela/rascunhos é transitório em memória, não autoridade de negócio ou armazenamento durável. Recarregar não recupera texto não salvo nem repete intenção. A query de tela é só navegação; preserva outros parâmetros/hash e o ponteiro de montagem. `.data` no PC continua a autoridade. Não há localStorage/sessionStorage, banco no navegador ou acesso direto ao filesystem do celular.

### Duração por bloco

O antigo readonly e o payload fixo de 2.3 foram substituídos por entrada em **Ajustes do rascunho**, realmente ligada aos pedidos i2v **e** v2v. Default continua **2.3**; os grafos, fórmula, presets e benchmark permanecem congelados. `GET /app/config` acrescenta:

```json
{"duration_capabilities":{"default_requested_seconds":2.3,"min_requested_seconds":0,"min_exclusive":true,"max_requested_seconds":10,"input_step":0.01,"fps":24,"frame_base":5,"frame_stride":17,"rounding":"half_even","max_frames":243,"max_actual_seconds":10.125}}
```

UI aceita decimal estrito positivo, ponto ou vírgula e até duas casas; não aceita branco, sinal, expoente, NaN/Infinity ou clamp silencioso. A UI replica **Python half-even**, não `Math.round`. Solicitação e vídeo não têm obrigatoriamente a mesma duração:

| Solicitada | Frames alinhados | Tempo efetivo a 24 fps |
| --- | --- | --- |
| 2.3 s (default) | 56 | 2.333333 s |
| 2.8 s / 3 s | 73 | 3.041667 s |
| 5 s | 124 | 5.166667 s |
| 10 s | 243 | 10.125 s |

O limite de 10 s é **orçamento operacional**, não máximo do modelo ou prova de RAM/VRAM, prazo ou qualidade de gerações longas. Mais tempo custa mais recursos; não reduzimos resolução, sampler, passos, VAEs ou referências para compensar. Se capabilities não existem, o frontend legado fica readonly 2.3 com aviso. Capabilities malformadas falham fechadas, sem liberação presumida.

A revisão mostra a duração solicitada, alinhada e verificada separadamente. O benchmark continua request 2.3 × três blocos, 56 × 3 = 168 frames / 7 s, com seeds/referências originais. O contexto de continuação mantém tail **3 s** e áudio **true**, independentemente do tempo do filho. Nenhuma nova imagem é enviada à geração v2v.

### Grok: ideia + identidade (+ último frame na continuação) → proposta

O dono supersede a antiga restrição de entrada somente texto: **Detalhar ideia e imagem** envia explicitamente `system_prompt`, `prompt`, referência própria `{source_root,path}` e o ID persistido. Modelo fixo mostrado readonly: `grok-4.20-0309-non-reasoning`. `GET /grok/editor` lê configuração local; **Salvar instruções no PC** usa PUT separado do formulário nativo. Nenhuma autenticação/catálogo/provider é chamada ao abrir ou navegar.

Na continuação o payload inclui também `continuation_parent_id` canônico. O adaptador deriva o segundo contexto do vídeo publicado próprio do pai aceito, não de path/URL de frame enviado pelo browser. `GET /grok/continuation/{parent_id}/last-frame` é preview CPU por FFprobe/FFmpeg, sem provider/Comfy/geração ou alteração do pai. Funciona mesmo quando não existe um last_frame.png pregravado. Snapshots privados de disco e streaming bounded mantêm pixels/frames fora do Python. Contexto inválido/preview indisponível não vira envio silencioso de uma imagem; a instrução manual continua uma escolha explícita. Antes desta correção o editor enviava somente identidade, não ambos.

A imagem que será enviada é indicada antes do clique e registrada junto à proposta. O backend valida ownership, JPEG/PNG e máximo 20 MiB; upload para geração continua PNG/JPEG/WebP até 32 MiB. WebP/oversize recusado por Grok não vira resize/recompressão escondidos ou fallback para outra imagem. URLs arbitrárias, paths privados e credenciais nunca são contexto. Front envia somente identificador da referência, não base64 ou imagem inteira em JSON. Leia [contratos e limites do editor](grok.md).

Grok devolve texto literal até 12000 caracteres, via `.value`/`textContent`, sem truncar/XSS. Não edita nem gera imagem/vídeo. Contexto/ideia/parent/duração/system alterados durante uma chamada tornam sua proposta antiga explícita. Elegibilidade/cota OAuth da conta e visão ao vivo não foram verificadas por mocks.

### Contratos e segurança preservados

- `/runs?limit=50&offset=0`, `/inputs?limit=50&offset=0`, `/runs/{id}`, `/runs/{id}/sequence`: leituras próprias, URLs same-origin, paths contidos. Publicação real exige estado jogável + path de output + URL explícita própria; estado terminal sozinho não prova arquivo.
- `POST /runs/i2v`: seed, texto exato, duração escolhida; referência original legada ou `references:[{source_root,path}]`.
- `POST /runs/{accepted_parent_id}/v2v`: seed, texto exato, duração escolhida, `reference_tail_seconds:3`, `include_audio:true`, sem novas fontes de identidade.
- Seed é inteiro seguro de dígitos `0..9007199254740991`; texto não vazio até 12000. Enter nos inputs/editor/settings ou submissão de formulário invisível não gera vídeo.
- Um POST 202, seguido de **um** `GET /runs/{own_id}?wait=true`. Espera perdida/ID errado/admissão incerta/5xx nunca causa replay. Navegação/SSE não limpa bloqueios independentes de native/Grok/upload/montagem.
- EventSource se registra e abre antes do snapshot; hints invalidam paths normalizados, ignoram temporários/telemetria e se agrupam em microtask. Durante operação ficam dirty; reconexão só relê. Sem polling/timers de conclusão.
- Pagehide fecha SSE e aborta espera **local**, não o job no PC. Não existe promessa de cancelar por fechar a página. Native mantém slot global e cancelamento próprio explícito/cleanup; por correção38 do dono, RAM é só telemetria, sem bloqueio ou cancelamento por memória livre. Ciclo de vida do ComfyUI pertence ao script externo, não ao app.
- Players usam controls/playsinline/preload metadata/contain, sem autoplay. Vídeo não recebe src inicial enquanto sua tela está invisível; esconder pausa playback local. Releitura/SSE com mesma URL não recarrega o player.

Montagem mantém UUID criptográfico registrado na query **antes** do POST `/assemblies/{UUID}` com `{end_run_id}`; aguarda 200/arquivo publicado. Em resultado incerto, **Reler montagem**/reload/SSE consultam o mesmo ID; 404 não autoriza outro UUID/POST. Preview tem fim pronto ainda pendente; accepted sequence tem fim aceito. Aceitar fim não monta; uma nova revisão aceita exige novo clique explícito Montar. URL/download somente próprios, com completed + hashes + output verificados. Ordem/count não certificam equivalência perceptual ou bytes/pixels lossless.

### Movimento intencional — plano26

Movimento é só apresentação, não parte da execução: nenhuma operação espera `animationend`/`finished`, cria UUID/POST, altera payload/rascunho/revisão, reenvia intenção ou dá autoplay. Graphite/copper e a filmstrip ancestral real continuam sendo a identidade. Um painel fica ativo imediatamente; o antigo já está hidden/inert quando o novo começa a aparecer. Foco e clique não esperam efeitos.

| Interação | Feedback de uso |
| --- | --- |
| Trocar tela / Voltar / abrir bloco | Heading e folhas estáticas entram 12 px em 180 ms; direção inversa ao Voltar, sem painel fantasma. |
| Biblioteca / página nova | Até seis cards reais, stagger de 16 ms (máximo80 ms); snapshot idêntico/SSE não reaplica entrada em cards recriados. |
| Press / teclado | Tinta cobre em90 ms por pseudo-elemento sem capturar ponteiro ou encolher o botão. Hit target continua >=44 px. |
| Referência / upload publicado | Fade160 ms somente após load da URL atual; nem fallback de imagem, nem upload/geração automáticos. |
| Grok / salvar editor / upload / gerar / montar / reler | Ponto discreto corresponde à flag real; dois pulsos de160 ms, depois estático. Sem percentual, progresso inventado ou loop interminável. |
| Decisão em revisão | Só a ação clicada/ID atual mostra ocupado; geração pendente não faz Aceitar/Rejeitar pulsarem. Badge/frame recebe confirmação240 ms só após estado confirmado. |
| Ideia / prompt / seed / duração | Caret e inputs permanecem estáticos; readout/provas alterados têm cue160 ms, sem debounce de negócio. |
| Proposta / resposta tardia | Provas/caption recebem cue160 ms no contexto ativo. Candidato de outro pai permanece no rascunho de origem, fechado; não rouba foco, abre tela ou escolhe proposta. |
| Disclosure / erro / incerto / preview→aceito | Summary/caption têm cue160 ms localizado; mensagem permanece legível. Sem shake/confetti, retry ou arquivo prévio apresentado como aceito. |
| Vídeo / fullscreen / download / picker / filmstrip scroll | Controles e gestos nativos, sem animação sobre o vídeo nem swipeBack/pullrefresh global. |

WAAPI usa apenas opacity/transform, sem blur/layout por frame, framework, dependência ou `will-change` permanente. Nunca transforma `.task-panel`, `.stage`, `.studio`, `body`, forms/fieldsets, ancestrais das CTAs `position:fixed`, vídeos ou inputs. Assinaturas são limitadas a canais conhecidos de apresentação, não um Map crescente por UUID; substituir DOM não basta para dedupe. Sem WAAPI, o aplicativo continua estático e funcional. Preferência reduzida tem zero WAAPI/CSS animation/transition; alteração dinâmica cancela efeitos. Resize e nova navegação cancelam WAAPI; preferência reduzida, página oculta e pagehide também interrompem CSS motion sem disparar negócio; promises canceladas são consumidas e só limpam a apresentação.

### Validação sem API/provider/GPU

Comandos fish, Playwright/Chromium existentes (sem instalar dependências):

```fish
node --check src/h3_backend/web/app.js
node --test tests/frontend_ui.test.mjs tests/frontend_retry.test.mjs tests/test_benchmark_mcp.mjs
env H3_UI_TEST_CLIP=runs/02cf408f-c985-47a2-887d-731569d7827a/chunk.mp4 H3_UI_TEST_ASSEMBLY=.dumps/benchmarks/baseline-three-chunks/benchmark.mp4 H3_UI_TEST_LAST_FRAME=.dumps/tests/ui-app-navigation/fixture-last-frame.png node tests/frontend_browser_mock.mjs
```

Browser intercepta **toda** request em `http://h3.mock.invalid`, bloqueia origem externa e simula SSE/POSTs separados; não abre servidor ou chama inferência/provider real. A auditoria atual exige rolagem do documento, topo sticky com controles >=44 px, painéis hidden/inert e CTAs no fluxo alcançáveis por scroll/hit-test, não todas permanentemente fixas no viewport. Inclui settings/Back, identidade+frame, retries root/child e preservação do prompt final. Default protege recursos versionados e somente os arquivos prerecorded explicitamente selecionados; não percorre árvores de dados de produção. `.data/grok`/OAuth nunca são lidos ou hashed. Nada de picker/IME físico, elegibilidade de provider, 60fps ou RAM/qualidade GPU longa é certificado por emulação.

#### Entrega dos planos32–34 e correção38

O dono testou o front e o aprovou diretamente: “eu testei o front pra voce, ta de boas já”. Dispositivo/IME físico não foram informados. Última regressão:800 testes Python passaram após retirar a política de RAM (`80c704c`);145 Node passaram (42 UI,84 retry,19 MCP fake). Ruff e whitespace passaram. Nenhuma nova chamada real foi feita depois do opt-in37.

Evidências locais: `.dumps/tests/ui-app-navigation/report.json`,11 PNGs `owner-*.png` e2 PNGs em `.dumps/tests/ui-app-motion/`. Capturas inspecionadas mostram Biblioteca, Ajustes de bloco, geração5s, retry direto com UUID de origem e identidade preta/frame final vermelho com rótulos distintos. São estados mockados com mídia real existente, não geração nova nem aceitação do run real usado como fixture. Auditoria normal/reduced-motion cobre393×852DPR2,320/640,landscape e desktop; toque CDP real moveu somente o documento nas três larguras, sem selecionar cartão ou fazer POST. Hashes dos três assets servidos são iguais antes/depois.

**Browser completo não passou:** a execução final parou no cenário antigo de motion que tenta retornar à revisão durante admissão nativa pendente. O port primeiro volta à Biblioteca raiz, removendo aquela revisão da trilha; depois nem Back encontra a entrada nem a seleção nova por GET é permitida pela guarda busy existente. As regressões de negócio anteriores, montagem404/503/prova ausente, view de rascunho incerto, fence de Gerar/retry, prompt literal e retries root/child passaram. A cauda normal de pending-review/wait/busy-decision/assembly, pagehidden/pagehide e fallback não foi concluída nessa execução. O harness mantém a assertiva e exit1, sem esconder/skipping ou alegar fullPASS; não foi alterado o app aprovado para satisfazer esse roteiro.

Vídeo diagnóstico `.dumps/tests/ui-app-motion/card-drag-3s.webm` e frames reais `gesture-inspection-01/02/03.png` foram inspecionados: incluem boot/loading, troca de viewport e um frame em transição. Não é demonstração promocional limpa nem prova de60fps; screenshots estáveis são a evidência visual principal. Proteção final `.dumps/tests/ui-app-navigation/final-protected-after-plan38.json`:23 âncoras H3 intactas e dispatcher alterado exclusivamente pela correçãoRAM38 autorizada.14 caminhos históricos `tools/gen/` foram excluídos por commits separados de relocação, nunca incluídos no commit H3. RAM permanece observacional, sem guardas de admissão/cancelamento; o script externo do dono controla o ciclo de vida do ComfyUI.

#### Teste real deliberado do editor — plano37

Após opt-in explícito do dono, uma única inferência real recebeu a identidade original e o último frame do pai aceito `29699f9c-fcab-4225-89fd-6650a1ad7819`. Houve um GET de catálogo e um POST Responses, ambos200; 2.183.776 bytes em40 chunks,8,74s para a chamada completa, modelo fixo0309. Ledger/proposta/verificação estão em `.dumps/tests/grok-real-two-images-20261013-plan37-8d42e6/`. Sem replay, refresh/reauth, mudanças de grant/pin/system, GPU, vídeo ou revisão. Proposta manteve vermelho/pose de costas, mas saiu em inglês, com template8s/Video1 e detalhes não pedidos: o system custom permaneceu intocado. Isso prova aceitação real do payload de duas imagens, não obediência integral/visão científica ou aprovação do texto para geração. A autorização foi consumida; nenhuma nova chamada é implícita nos testes de UI.

#### Evidências históricas dos planos25/26

A validação anterior passou 56 Node (37 frontend +19 MCP): 289 requests interceptadas, 25 POSTs fake e50 auditorias, zero exceções JS/requests inesperadas. Seu contrato antigo de footer/CTAs fixos foi supersedido; métricas/capturas abaixo descrevem aquela execução, não a navegação atual.

Capturas somente após estado/console/rede/bounds auditados, em `.dumps/tests/ui-progressive/`, com `report.json`. Fixtures de falhas HTTP/rede têm erros esperados registrados, sem exceções JavaScript. Os cinco PNGs benignos `owner-library/context/proposal/generation-5s/review` são evidência visual separada dos fixtures XSS. Capturas nativas DPR2 (786 × 1704) usam clip explícito na origem do documento, foco/blur/frames renderizados e rede/media estabilizados para evitar scroll pendente do compositor mobile. Hashes de 205 recursos, prompts, assets, runs/inputs/assemblies reais antes/depois protegem originais; `.data/grok`/OAuth nunca são lidos ou hashed pelo harness. Nada de picker físico, elegibilidade de provider ou qualidade/RAM GPU longa é certificado pela emulação.

O segundo contexto touch usa motion normal, não só screenshots com animações desativadas. `motionEvidence` no report registra keyframes/targets, heading pausado no meio da entrada (90 ms), confirmação240 ms, preferência alterada em runtime, ocultação, Voltar rápido/rascunho preservado e fallback sem WAAPI. Durante admissão nativa pendente, voltar a outra revisão não sinaliza decisões ocupadas; durante Aceitar, só Aceitar fica busy. Toque em **Usar proposta** durante entrada continua imediatamente; double clicks não duplicam provider/native, eventos `animationend` e SSE não geram operações. Os artefatos `.dumps/tests/ui-motion/context-mid.png` e `assembly-settled.png` foram inspecionados em resolução nativa, com header/CTAs/footer inteiros; `motion-filmstrip.png` contém frames reais extraídos pelo FFmpeg. O WebM final, apontado no report, tem3.28 s,299846 bytes,392×852/VP9 e25 fps de **gravação**: não é promessa60fps da UI nem vídeo novo gerado. A mídia exibida dentro da página é fixture prerecorded, não certificação GPU/qualidade.

Evidências históricas anteriores permanecem em `.dumps/tests/ui-paths/`, `ui-grok/`, `ui-assembly/` e seus relatórios. Suas descrições de painéis empilhados, texto-only e duração fixa são históricas, não o contrato atual.
