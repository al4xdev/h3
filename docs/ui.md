# H3 · Bancada de filme

## Mobile por telas — planos 23, 24 e 25

HTML/CSS/JavaScript same-origin, sem framework, build, CDN ou fontes remotas. A identidade grafite/cobre e a **linha ancestral real** permanecem; a bancada de três colunas foi substituída por uma decisão de cada vez. No telefone, exatamente um painel principal está visível e focável. Desktop tem uma navegação lateral compacta, não sete formulários simultâneos.

### Caminho de uso

1. **Biblioteca** abre primeiro. Nova cena inicia um rascunho; selecionar um bloco lê seus metadados e abre a revisão. Falhas/interrupções não se tornam vídeos prontos.
2. **Referência e ideia** escolhe a imagem original ou uma referência publicada no PC, recebe upload explícito e a ideia simples. Upload salva em `.data` no PC e não gera nem chama Grok.
3. **Proposta do Grok** mantém a ideia separada, mostra texto sempre editável e exige **Usar esta proposta**. **Usar minha instrução** permite pular Grok. Nenhuma dessas ações gera vídeo.
4. **Preparar geração / pedido no PC** mostra a instrução escolhida, referência/parent, seed e duração solicitada → frames → tempo alinhado. Só **Gerar** envia a intenção. HTTP 202 é admissão, não conclusão. **Abrir bloco** leva ao resultado confirmado.
5. **Revisar bloco** oferece vídeo retrato manual, tempo solicitado/alinhado/verificado, ancestrais e decisões explícitas. Aceitar apenas desbloqueia continuação; não continua nem monta automaticamente.
6. **Preparar continuação** confirma o pai aceito. Sua identidade original é herdada; o último frame inicia o vídeo, mas o contexto enviado a Grok é a imagem de identidade original. Descrever leva novamente à ideia/proposta/geração.
7. **Montagem** é uma tela e uma ação separadas. A cadeia é a ancestralidade exata do fim selecionado, sem misturar ramificações. Montar não aceita o fim nem gera outros blocos.

Voltar, seleção, resize, history e SSE conservam rascunhos por cena/pai: ideia, proposta editada, instrução escolhida, referência, seed e duração. O preset não sobrescreve rascunhos sujos em cada troca. Resposta Grok atrasada fica no rascunho original, marcada com o contexto antigo; nunca substitui a ideia de outro pai. **Reabrir proposta deste rascunho** permite conferi-la explicitamente. Se você editou a proposta enquanto Grok trabalhava, essa edição vence: a resposta atrasada fica em um disclosure separado no rascunho de origem. **Substituir a proposta pela resposta atrasada** é outra escolha explícita que só copia para o editor; não muda ideia/instrução escolhida/referência/duração/seed nem envia geração. Sem candidato, essa ação não faz nada.

Estado de tela/rascunhos é transitório em memória, não autoridade de negócio ou armazenamento durável. Recarregar não recupera texto não salvo nem repete intenção. A query de tela é só navegação; preserva outros parâmetros/hash e o ponteiro de montagem. `.data` no PC continua a autoridade. Não há localStorage/sessionStorage, banco no navegador ou acesso direto ao filesystem do celular.

### Duração por bloco

O antigo readonly e o payload fixo de 2.3 foram substituídos por entrada realmente ligada aos pedidos i2v **e** v2v. Default continua **2.3**; os grafos, fórmula, presets e benchmark permanecem congelados. `GET /app/config` acrescenta:

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

### Grok: ideia + imagem → proposta de texto

O dono supersede a antiga restrição de entrada somente texto: **Detalhar ideia e imagem** envia explicitamente `system_prompt`, `prompt`, referência própria `{source_root,path}` e o ID persistido. Modelo fixo mostrado readonly: `grok-4.20-0309-non-reasoning`. `GET /grok/editor` lê configuração local; **Salvar instruções no PC** usa PUT separado do formulário nativo. Nenhuma autenticação/catálogo/provider é chamada ao abrir ou navegar.

A imagem que será enviada é indicada antes do clique e registrada junto à proposta. O backend valida ownership, JPEG/PNG e máximo 20 MiB; upload para geração continua PNG/JPEG/WebP até 32 MiB. WebP/oversize recusado por Grok não vira resize/recompressão escondidos ou fallback para outra imagem. URLs arbitrárias, paths privados e credenciais nunca são contexto. Front envia somente identificador da referência, não base64 ou imagem inteira em JSON. Leia [contratos e limites do editor](grok.md).

Grok devolve texto literal até 12000 caracteres, via `.value`/`textContent`, sem truncar/XSS. Não edita nem gera imagem/vídeo. Contexto/ideia/parent/duração/system alterados durante uma chamada tornam sua proposta antiga explícita. Elegibilidade/cota OAuth da conta e visão ao vivo não foram verificadas por mocks.

### Contratos e segurança preservados

- `/runs?limit=50&offset=0`, `/inputs?limit=50&offset=0`, `/runs/{id}`, `/runs/{id}/sequence`: leituras próprias, URLs same-origin, paths contidos. Publicação real exige estado jogável + path de output + URL explícita própria; estado terminal sozinho não prova arquivo.
- `POST /runs/i2v`: seed, texto exato, duração escolhida; referência original legada ou `references:[{source_root,path}]`.
- `POST /runs/{accepted_parent_id}/v2v`: seed, texto exato, duração escolhida, `reference_tail_seconds:3`, `include_audio:true`, sem novas fontes de identidade.
- Seed é inteiro seguro de dígitos `0..9007199254740991`; texto não vazio até 12000. Enter nos inputs/editor/settings ou submissão de formulário invisível não gera vídeo.
- Um POST 202, seguido de **um** `GET /runs/{own_id}?wait=true`. Espera perdida/ID errado/admissão incerta/5xx nunca causa replay. Navegação/SSE não limpa bloqueios independentes de native/Grok/upload/montagem.
- EventSource se registra e abre antes do snapshot; hints invalidam paths normalizados, ignoram temporários/telemetria e se agrupam em microtask. Durante operação ficam dirty; reconexão só relê. Sem polling/timers de conclusão.
- Pagehide fecha SSE e aborta espera **local**, não o job no PC. Não existe promessa de cancelar por fechar a página. Native mantém slot global, RAM floor e cancelamento próprio no backend.
- Players usam controls/playsinline/preload metadata/contain, sem autoplay. Vídeo não recebe src inicial enquanto sua tela está invisível; esconder pausa playback local. Releitura/SSE com mesma URL não recarrega o player.

Montagem mantém UUID criptográfico registrado na query **antes** do POST `/assemblies/{UUID}` com `{end_run_id}`; aguarda 200/arquivo publicado. Em resultado incerto, **Reler montagem**/reload/SSE consultam o mesmo ID; 404 não autoriza outro UUID/POST. Preview tem fim pronto ainda pendente; accepted sequence tem fim aceito. Aceitar fim não monta; uma nova revisão aceita exige novo clique explícito Montar. URL/download somente próprios, com completed + hashes + output verificados. Ordem/count não certificam equivalência perceptual ou bytes/pixels lossless.

### Validação sem API/provider/GPU

Comandos fish, Playwright/Chromium existentes (sem instalar dependências):

```fish
node --check src/h3_backend/web/app.js
node --test tests/frontend_ui.test.mjs
env H3_UI_TEST_CLIP=runs/02cf408f-c985-47a2-887d-731569d7827a/chunk.mp4 H3_UI_TEST_ASSEMBLY=.dumps/benchmarks/baseline-three-chunks/benchmark.mp4 node tests/frontend_browser_mock.mjs
```

50 testes Node passam: 31 puros de frontend e 19 do adapter MCP com worker inerte. Frontend cobre contratos anteriores, duração/capabilities/half-even/locale/payloads root+continue, imagem própria e snapshots atrasados. Browser intercepta **toda** request em `http://h3.mock.invalid`, bloqueia origem externa, simula SSE e POSTs separados; não abre servidor nem faz inferência/provider real. Execução final: 248 requests interceptadas, 21 POSTs fake explícitos, 43 auditorias de bounds/foco, zero exceções JavaScript ou requests inesperadas. Phone 393 × 852 / DPR2 / touch, 320/640/1440 e contexto desktop separado auditam um painel ativo, hidden/inert/foco, >=44 px, overflow e cards sem compressão. CTAs inteiras cabem no visual viewport, não intersectam o footer e passam hit-test no próprio botão. Após tap/scrollIntoView, ideia/proposta/duração focadas ficam acima dos controles fixos. Fixtures já existentes são só bytes prerecorded; um vídeo antigo usado pelo mock não é prova de geração de 5/10 s.

Capturas somente após estado/console/rede/bounds auditados, em `.dumps/tests/ui-progressive/`, com `report.json`. Fixtures de falhas HTTP/rede têm erros esperados registrados, sem exceções JavaScript. Os cinco PNGs benignos `owner-library/context/proposal/generation-5s/review` são evidência visual separada dos fixtures XSS. Capturas nativas DPR2 (786 × 1704) usam clip explícito na origem do documento, foco/blur/frames renderizados e rede/media estabilizados para evitar scroll pendente do compositor mobile. Hashes de 205 recursos, prompts, assets, runs/inputs/assemblies reais antes/depois protegem originais; `.data/grok`/OAuth nunca são lidos ou hashed pelo harness. Nada de picker físico, elegibilidade de provider ou qualidade/RAM GPU longa é certificado pela emulação.

Evidências históricas anteriores permanecem em `.dumps/tests/ui-paths/`, `ui-grok/`, `ui-assembly/` e seus relatórios. Suas descrições de painéis empilhados, texto-only e duração fixa são históricas, não o contrato atual.
