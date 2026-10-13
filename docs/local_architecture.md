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
- Auditoria real somente leitura: desktop1440 e celular emulado393/touch, reprodução manual480×864/24fps e Range206, failed oculto, SSE inicial `.data`; zero POST/provider/GPU. Evidência local `.dumps/tests/reports/frontend_real.json` e `runtime_sse.json`. A inspeção visual encontrou compressão de cards com12 blocos; sua correção e revalidação estão pendentes, portanto isso ainda não certifica UI final.

O processo próprio da ponte observado após essa auditoria tinha RSS58928KiB e swap0. É uma amostra de um processo Python, não pico de todo o sistema, redução medida ou afirmação sobre memória/cache do ComfyUI.

## Grok apartado

A rota independente do dono (`041b014`) recebe system prompt/ideia e devolve texto ao front. Não conhece Store/worker/runs/revisão nem dispara vídeo. Configuração editável própria em `.data/grok/` é separada de credenciais OAuth; nenhuma chamada ao provider em importação, startup, abertura da página ou reconexão. O editor visual é uma tarefa separada; gerar vídeo continua outro clique explícito.

## Ainda falta para a entrega completa

Corrigir/revalidar a biblioteca com muitos blocos, concluir editor Grok isolado e montagem vertical de sequência via FFmpeg, verificar integração final/memória/benchmark e documentar execução local. Montagem permanece desabilitada na configuração até existir uma implementação verificada; fim ready é prévia, não aceitação artística.
