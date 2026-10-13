# H3 local: a pasta é a verdade

## Decisão do dono

A aplicação roda no PC. `.data` materializa pedidos, estados, referências, chunks e montagens. O celular é apenas outro navegador acessando a página do PC: seus uploads terminam nessa mesma pasta. Não há sincronização de pastas, banco, broker, filas externas ou backend clássico com camadas de services.

```text
Navegador JS (PC ou celular)
       ↕ HTTP local: arquivos, upload, metadados
       ↕ SSE: aviso de path alterado, não estado de negócio
Ponte pequena no PC
       ↕ paths próprios em .data
Worker observa a pasta no PC
       ↕ subprocessos / execução nativa
FFmpeg / ffprobe / ComfyUI
```

O navegador não observa livremente o disco do PC. A ponte oferece acesso restrito a arquivos da aplicação. Escolher um arquivo existente em `.data` e fazer upload são duas entradas para os mesmos paths; não criam um segundo catálogo autoritativo no JS.

## Trabalho materializado

- Um JSON publicado atomicamente descreve uma intenção explícita. Um `.lock` controla quem a executa; não substitui o pedido.
- A alteração de um vídeo, o início do observador ou a abertura/reconexão da página nunca autoriza geração.
- Estado e resultado publicados nos paths são lidos por ambos os lados. Eventos de filesystem avisam o worker; SSE invalida a visualização do front, que relê o path relevante.
- Registrar o observador antes de obter o snapshot inicial evita uma janela de mudanças perdidas. Evento perdido/overflow exige releitura de metadados, não replay de inferência.
- Locks abandonados e trabalhos interrompidos preservam a evidência. Não inferir que um POST ao ComfyUI não aconteceu apenas porque um resultado ainda não apareceu.
- Um dispatcher e um builder continuam únicos; i2v/v2v mantêm sua composição fluente e operação vertical. A ponte não duplica essas operações.

## Mídia fora do heap do Python

Python passa caminhos e gerencia arquivos/processos; não carrega pixels, imagens ou vídeos inteiros. FFmpeg/ffprobe validam, extraem, preparam e montam mídia no processo próprio. Python pode copiar, servir e calcular hashes de bytes codificados com buffers limitados. O navegador usa `<video>`, `<img>` e, se necessário, Canvas para comparações.

Pillow não deve integrar o runtime. Scripts históricos CPU de comparação são tooling separado até sua substituição. Não alterar modelos, sampler, condicionamento, guias, VAEs, parâmetros ou decode final para justificar a troca de transporte/validação.

Cache de arquivos do Linux e modelos/tensores do ComfyUI são separados do heap do orquestrador. Medir RSS por processo; não prometer redução de memória por usar locks ou por não usar banco.

## Implementação e âncoras verificadas

- Geração nativa estável `502c13f`, benchmark inicial `990e27a`, MCP `6e20e61`.
- Perfil opt-in `final_only`, `b83c6ca`: somente preview18/176/177 removido, sem religar decodes. Comparação de 7s concluída; cache/processo externo mudou, portanto tempo não prova ganho causal.
- Migração `e6c2b45`: `.data/runs` autoritativa com recibo `4854b208-743e-42d8-a7de-c40a9f1f7ff0`; 12 runs/80 arquivos copiados, originais `runs/` preservados. Verificar o recibo real antes de novas operações; contagens podem crescer.
- Mídia externa `750dfe2`: sem Pillow no runtime, validação FFmpeg/ffprobe e hashes com buffers limitados. Extração mantém RGB nativo verificado; PNG codificado pode ter metadados diferentes.
- Worker `051c5ba`: `.data/runs/<mesmo UUID>/request.json` é o snapshot imutável admitido, publicado por último. `manifest.json` contém lifecycle/output. Worker recebe somente UUID e reidrata dos arquivos; startup interrompe antigos queued/running, nunca os reproduz. Os leases existentes `.data/state/storage.lock` SH e `runtime.lock` EX coordenam a propriedade.
- Ponte `6eae6f9`: UI estática, catálogos, upload bruto limitado a32MiB, referências `assets|inputs|runs`, mídia própria/Range e SSE no mesmo observador inotify. Publicação de upload preserva bytes originais; `metadata.json` é o commit final. Validação/frame/thumbnail não passam pixels pelo Python.
- Front `4a68a02`: selecionar referência, enviar imagem ao PC, assistir/revisar/continuar explicitamente; SSE precede snapshot e nunca reenvia POST. 521 testes Python e32 Node passaram, incluindo71 novos da ponte e4 eventos de subpastas profundas. Dados antigos e cópia permaneceram byte-exact.
- Auditoria real somente leitura: desktop1440 e celular emulado393/touch, reprodução manual480×864/24fps e Range206, failed oculto, SSE inicial `.data`; zero POST/provider/GPU. Evidência local `.dumps/tests/reports/frontend_real.json` e `runtime_sse.json`. A inspeção inicial encontrou compressão dos12 cards. Correção flex-shrink:0 em21c1d54; revalidação real final70460f6/eaf4ba8 em `.dumps/tests/reports/frontend_final.json` passou: todos os12 cards têm137px e filhos contidos, desktop1440/mobile393touch2x sem overflow, Grok GET/configuração inerte, reprodução manual do bloco2.333s e montagem7s sem autoplay, failed oculto e zero erros/POSTs/cloud. Screenshots `.dumps/tests/ui-final/` inspecionados, inclusive painel móvel real.

O processo próprio da ponte observado após essa auditoria tinha RSS58928KiB e swap0. É uma amostra de um processo Python, não pico de todo o sistema, redução medida ou afirmação sobre memória/cache do ComfyUI.

## Duração por bloco, sem retunar geração

Pedido explícito do dono supersede o antigo cap3s. Backend `e52747c` aceita requested finite(0,10] em root e continuação, usando o mesmo helper na admissão, builder, hidratação e saída. Default2.3→56 permanece; fórmula nativa Pythonhalf-even24fps/5+17k intacta:2.8/3→73,5→124,10→243frames/10.125s. `GET /app/config` expõe `duration_capabilities` aditivo; frontend não adivinha limites. Probe exige exactF(request),480×864/24fps e duração coerente com frames/24, não cap3s nem requested10s sobre o tempo alinhado.

10s é orçamento operacional explícito. Schema estático instalado `MiniMaxH3ReferenceToVideo.length` min5/max3600/step17 e tooltiptrained~124..362 permitem243 no contrato; não certificam checkpointqualidade/RAM/VRAM/latência. Tail3/audioTrue são referência do parent e permanecem independentes da duração do filho. Deadline1200s/RAM1536MiB/cancel somenteUUID/no replay intactos; não escalar knobs em falha.69 testes novos incluem snapshot/hidratação, parent-child3/5/10 e FFmpeg CPU sintético5/10s com124/243frames; focused368 passou. Não houve geraçãoGPUlonga, mudança de benchmark2.3×3/seeds/golden ou promessa de ganho causal.

## Grok apartado

A rota independente do dono (`041b014`) devolve texto ao front, sem Store/worker/revisão/geração. Editor `21c1d54` introduziu GET/PUT `.data/grok/editor.json`, separado de OAuth, com publicação atômica/fsync e GET ausente inerte. Essa entrega teve22 testes do editor+34provider/OAuth offline.

Correção pedida pelo dono, backend `c6d0045`: modelo persistido é autoridade relida no POST; override diferente409, PUT altera system prompt sem trocar o pin. Ação administrativa explícita `seed_editor` publicou `.data/grok/editor.json` no-clobber com `grok-4.20-0309-non-reasoning`; não ocorreu em startup/GET e não leu OAuth. Card público oficial confirma non-reasoning/text+image→text, mas elegibilidade na conta não foi consultada. A referência opcional estrita `{source_root,path}` tem prova técnica própria, snapshot privado em disco e validação externa JPEG/PNG≤20MiB/16MP. Somente SHA de manifesto/recibo comprovado admite frames de runs; ausência de prova rejeita, não inventa ownership. Não há importação de Store/worker. Responses recebe base64/JSON em streaming48KiB+carry≤2, nunca mídia inteira no heap Python; cancelar reap subprocessos próprios/snapshot.

68 testes novos exercitam autoridade, no-clobber/races/pathlinks/ownership/mutação/cancelamento/stream sem materialização. FullPython739 passou após correção de escopo de erros e reap na criação de subprocesso; zero provider/API/GPU real. Imagem é contexto para uma proposta de TEXTO, não edição de imagem ou vídeo. Usar proposta e gerar continuam cliques separados; navegação/SSE não chama provider nem autoriza inferência.

## Montagem explícita, no mesmo orçamento local

Backend `eaf4ba8`: composição pura `AssemblyPipe(service).have(UUID).from_end(runUUID).save_video().arun()`. Uma reserva CPU estreita usa o mesmo dispatcher/leases/RAM mínima1536MiB da geração; não cria fila, framework de comandos ou conexão ao Grok. POST com UUID conhecido aguarda CPU e devolve200; disconnect não cancela o task dono. Reconexão/resultado incerto usa GET do mesmo ID, nunca rePOST.

`.data/assemblies/<UUID>/request.json` é o pedido imutável, publicado por último e relido para executar. Metadados de lifecycle são mutáveis; `video.mp4`/`output.json` são evidência própria imutável, e metadata.completed é o último commit. Guards de path/UUID/regular/uid/nlink1/tamanho e SHA rejeitam provas trocadas; startup interrompe inacabados sem replay. Fim ready ou accepted e todos os ancestrais accepted são obrigatórios. Não altera decisões dos runs.

FFmpeg concatena todos os frames em ordem e preenche áudio até os boundaries, pelo helper existente CRF18/yuv420p; isso NÃO é identidade RGB/MP4 byte-exact nem certificação facial/perceptual. 602 testes Python (521baseline+22editor+59montagem) e44 Node passaram antes do último polimento UI.

Auditoria real: uma única montagem CPU `808836a6-434d-47d8-8d2a-98d97e038385` dos três chunks final_only existentes produziu168frames/7s/480×864/24fps, AAC32000Hz estéreo, boundaries56/112 e Range206. Terceiro run continua ready; dois pais accepted. Decode completo externo de vídeo/áudio passou, sem pixels Python. Evidência `.dumps/tests/reports/runtime_assembly.json`; 162 arquivos protegidos permaneceram intactos. Montagem está habilitada, mas o fim ready é rotulado **prévia — revisão pendente**, não aceitação artística.

## Entrega verificada e limites

UI final70460f6 permite nova montagem explícita aceita após aceitar o fim de uma prévia; aceitar sozinho não monta. 44Node e browsermock442/407requests/26fakePOST+1PUT/zeroerro/cloud/GPU passaram. Wheel offline final contémHTML/CSS/JS byte-exact e somente5dependências runtime, sem Pillow/torch; é prova de empacotamento, não app standalone sem recursos externos. RSS do processo próprio609946 após montagem foi62021632bytes e swap0: amostra, não pico/ganho causal. Comandos fish/PC/LAN confiável estão noREADME.

Benchmark nativo final deliberado MCP concluído com exit0, job `7906b6fc-6955-470f-88bc-b3e5ca7c8262`, fonte70460f6, diretório `.dumps/benchmarks/mcp-local-app-final-three-chunks`:385.850s observados,168frames/7s/boundaries56/112, cenário SHA bf9a79ac… idêntico, native_anchor_exact em cada bloco. Dois novos parents tecnicamente accepted; terceiro84310291-3fe2-4066-aadf-4232d979180d permanece ready. Contact sheet FFmpeg dos frames0/28/55/56/84/111/112/140/167 mostra preto→vermelho/de costas→frente; não certifica identidade facial/perceptual ou aprovação artística. Cache/warm-cold desconhecido, sem controles de modelos/filas e sem ganho causal declarado. Amostra5s do benchmark chegou a87924736bytes RSS da ponte, não pico exato.

Após benchmark,162arquivos antigos protegidos continuaram SHA-exact; somente3novos runs canônicos foram adicionados legitimamente. Queue Comfy GET contou0running/0pending, sem mutações. API própria609946/job437 encerrada e coletada graciosamente; Comfy externo292174 preservado. Essa integração original ficou tecnicamente concluída; revisão artística do vídeo continua com o dono.

## Correções posteriores: mobile por telas

Front `15c6e99`, planos23/24/25: biblioteca → referência/ideia → proposta editável → preparar geração/status → revisar → preparar continuação → montagem. Uma tela principal hidden/inert, navegação/foco separados do negócio; desktop mantém rail e painel focado. Rascunhos transitórios por new/parent guardam ideia, proposta, instrução escolhida, imagem, seed e duração; não usam browserstorage como autoridade. Modelo fixo/read-only, envio explícito da imagem original, Usar proposta separado de Gerar. A proposta manual não é apagada por retorno atrasado: candidato separado no draft de origem, adoção explícita altera somente editor, não gera. Statuswait/IDs/incertezas/montagemquerypointer e recuperação GET-only permanecem.

50Node(31front+19MCP), browser fullyinterceptado248requests/21FAKEPOST/43audits,0exceções/API/provider/GPU. Viewports320/393touchDPR2/640/1440, tela única/foco/CTA≥44px/rect+hittest/footerdisjoint/campos focados acima dos botões fixos. 205arquivos próprios protegidos intactos; verificação independente174âncoras incluindo160arquivos dos runs antigos/grafos/prompts/assets/CLI/MCP SHA-exact, sem ler/hashar OAuth. Capturas benignas `.dumps/tests/ui-progressive/owner-*.png` em786×1704 inspecionadas, relatório adjacente. Vídeo de fixture é pré-gravado: não é prova de GPUlonga ou Grok real. FullPython739/28.89s passou contra o novo front antes do ajuste final pequeno da corrida de proposta, que teve regressão browser/Node própria; Ruff global limpo.

Servidor produção não foi reiniciado para estas correções. JSON novo `.data/grok/editor.json` é adição autorizada, não migração/reescrita de mídia. Elegibilidade xAI, qualidade/recursos de10sGPU e picker/IME físico não são certificados por mocks/emulação. Pedido adicional do dono para microanimações mobile é a fase seguinte, não parte dessas métricas estáticas.
