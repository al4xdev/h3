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

## Grok apartado

A rota independente do dono (`041b014`) recebe system prompt/ideia e devolve texto ao front. Não conhece Store/worker/runs/revisão nem dispara vídeo. Configuração editável própria em `.data/grok/` é separada de credenciais OAuth; nenhuma chamada ao provider em importação, startup, abertura da página ou reconexão. Editor `21c1d54`: `GET/PUT /grok/editor` lê/salva somente `.data/grok/editor.json`, com limites, guard de symlink e publicação atômica/fsync. GET ausente é inerte. O texto resultante volta ao rascunho; resposta atrasada vira proposta explícita, sem truncar. Configuração fica fora do formulário de geração, inclusive Enter em modelo não gera vídeo. 22 testes novos do editor e 34 provider/OAuth offline passaram; nenhuma chamada real ao xAI foi feita. Gerar vídeo continua outro clique explícito.

## Montagem explícita, no mesmo orçamento local

Backend `eaf4ba8`: composição pura `AssemblyPipe(service).have(UUID).from_end(runUUID).save_video().arun()`. Uma reserva CPU estreita usa o mesmo dispatcher/leases/RAM mínima1536MiB da geração; não cria fila, framework de comandos ou conexão ao Grok. POST com UUID conhecido aguarda CPU e devolve200; disconnect não cancela o task dono. Reconexão/resultado incerto usa GET do mesmo ID, nunca rePOST.

`.data/assemblies/<UUID>/request.json` é o pedido imutável, publicado por último e relido para executar. Metadados de lifecycle são mutáveis; `video.mp4`/`output.json` são evidência própria imutável, e metadata.completed é o último commit. Guards de path/UUID/regular/uid/nlink1/tamanho e SHA rejeitam provas trocadas; startup interrompe inacabados sem replay. Fim ready ou accepted e todos os ancestrais accepted são obrigatórios. Não altera decisões dos runs.

FFmpeg concatena todos os frames em ordem e preenche áudio até os boundaries, pelo helper existente CRF18/yuv420p; isso NÃO é identidade RGB/MP4 byte-exact nem certificação facial/perceptual. 602 testes Python (521baseline+22editor+59montagem) e44 Node passaram antes do último polimento UI.

Auditoria real: uma única montagem CPU `808836a6-434d-47d8-8d2a-98d97e038385` dos três chunks final_only existentes produziu168frames/7s/480×864/24fps, AAC32000Hz estéreo, boundaries56/112 e Range206. Terceiro run continua ready; dois pais accepted. Decode completo externo de vídeo/áudio passou, sem pixels Python. Evidência `.dumps/tests/reports/runtime_assembly.json`; 162 arquivos protegidos permaneceram intactos. Montagem está habilitada, mas o fim ready é rotulado **prévia — revisão pendente**, não aceitação artística.

## Entrega verificada e limites

UI final70460f6 permite nova montagem explícita aceita após aceitar o fim de uma prévia; aceitar sozinho não monta. 44Node e browsermock442/407requests/26fakePOST+1PUT/zeroerro/cloud/GPU passaram. Wheel offline final contémHTML/CSS/JS byte-exact e somente5dependências runtime, sem Pillow/torch; é prova de empacotamento, não app standalone sem recursos externos. RSS do processo próprio609946 após montagem foi62021632bytes e swap0: amostra, não pico/ganho causal. Comandos fish/PC/LAN confiável estão noREADME.

Benchmark nativo final deliberado MCP concluído com exit0, job `7906b6fc-6955-470f-88bc-b3e5ca7c8262`, fonte70460f6, diretório `.dumps/benchmarks/mcp-local-app-final-three-chunks`:385.850s observados,168frames/7s/boundaries56/112, cenário SHA bf9a79ac… idêntico, native_anchor_exact em cada bloco. Dois novos parents tecnicamente accepted; terceiro84310291-3fe2-4066-aadf-4232d979180d permanece ready. Contact sheet FFmpeg dos frames0/28/55/56/84/111/112/140/167 mostra preto→vermelho/de costas→frente; não certifica identidade facial/perceptual ou aprovação artística. Cache/warm-cold desconhecido, sem controles de modelos/filas e sem ganho causal declarado. Amostra5s do benchmark chegou a87924736bytes RSS da ponte, não pico exato.

Após benchmark,162arquivos antigos protegidos continuaram SHA-exact; somente3novos runs canônicos foram adicionados legitimamente. Queue Comfy GET contou0running/0pending, sem mutações. API própria609946/job437 encerrada e coletada graciosamente; Comfy externo292174 preservado. Nenhuma pendência técnica desta integração; revisão artística do vídeo continua com o dono.
