# H3 — app local de vídeo

Geração por blocos e revisão humana sobre os grafos nativos validados do ComfyUI. `.data` no PC é a autoridade; Python faz a ponte local e coordena ferramentas externas, sem carregar modelos ou pixels. A integração do frontend com observação de paths está em andamento; o contrato escolhido está em [arquitetura local](docs/local_architecture.md).

As decisões permanentes de autonomia, arquitetura vertical, benchmark, MCP, dados e frontend estão em [`AGENTS.md`](AGENTS.md). A meta é um aplicativo local leve de vídeos encadeados, não apenas um teste de geração.

O Store grava estados/JSONs/mídia persistente em `.data/runs/<UUID>/`. `runs/` permanece como âncora legada intacta: projetos com esse legado exigem [migração offline verificada](docs/data_storage.md), sem reescrever manifests ou apagar vídeos. O runtime só usa a autoridade canônica após recibo válido. `.dumps/` continua como scratch/evidência; recursos `workflows/`, `prompts/` e `assets/` permanecem na raiz do projeto.

## Organização

```text
src/h3_backend/
├── __init__.py
├── api.py                 # HTTP, consulta e revisão
├── generation/            # fatia vertical de geração
│   ├── __init__.py
│   ├── i2v.py             # I2VPipe: fluxo completo de imagem → chunk
│   ├── v2v.py             # V2VPipe: fluxo completo de continuação → chunk
│   ├── dispatcher.py      # dispatcher único: slot, RAM, worker e lifecycle
│   ├── workflow.py        # builder único + WorkflowConfig imutável
│   └── models.py          # requests, settings e Run da geração
└── infrastructure/        # adaptadores compartilhados existentes
    ├── __init__.py
    ├── comfy.py
    ├── media.py
    ├── store.py
    └── telemetry.py
workflows/                 # grafos nativos, exports golden e manifests necessários
prompts/                   # templates Markdown de geração/continuação
assets/                    # referência de identidade normalizada e sua procedência
tests/                     # suíte pytest versionada (regressões, não dumps)
tools/
├── export_workflow.mjs     # exportador nativo
└── benchmark_h3.py         # benchmark externo: três chunks + montagem
pyproject.toml, uv.lock    # dependências e configuração reproduzíveis
.data/runs/<id>/           # local: manifest, inputs e chunk.mp4 persistentes
runs/<id>/                 # legado preservado, nunca fallback gravável
.dumps/                    # local: scratch e evidências temporárias
├── tests/requests/        # requests experimentais
├── tests/reports/         # relatórios históricos e checks de integridade
└── references/            # cópia privada original apontada pelo manifest de referência
```

Cada operação concentra sua composição fluente, estado, router e etapas sequenciais no próprio arquivo de `generation/`. Os setters não fazem I/O; `generation/dispatcher.py` admite um único job e seu worker executa o pipe. `generation/workflow.py` usa `continuation_api.json` como template canônico e configura i2v/v2v sem modificar os exports validados. `infrastructure/` reúne somente adaptadores existentes, não novos serviços de negócio. O entrypoint continua `h3_backend.api:app`.

`POST /runs/i2v` e `POST /runs/{parent_id}/v2v` retornam **202**. A continuação exige parent aceito e usa seu último frame, a identidade original e a cauda recente. Os aliases `/runs` e `/runs/{parent_id}/continue` continuam válidos. Aceitar um run não gera automaticamente o próximo.

`GET /runs/{id}/sequence` lista somente a cadeia de manifests até esse run; não lê vídeos nem concatena. Importação de mídia externa e concatenação dos chunks completos ficam fora da API; a extração do último frame e da cauda do parent pertence ao `V2VPipe`.

## O que preservar

- **Versionado:** código, suíte `tests/`, prompts, assets normalizados, grafos/manifests de `workflows/`, exporter e configuração de dependências.
- **Persistente local:** `runs/` contém chunks reais e seus inputs/manifests, necessários à continuação. Ser gitignored **não** os torna descartáveis.
- **Temporário local:** requests avulsos, replays, relatórios e snapshots experimentais ficam em `.dumps/`, nunca no Git. Os relatórios antigos são registros do momento de cada teste, não o estado atual dos runs.
- **Procedência privada:** preservar `.dumps/references/` enquanto `assets/reference_manifest.json` apontar para ela. `.dumps` não é backup; não limpar indiscriminadamente.
- **Workspace:** `.plan/` é gerenciado pelo harness e `.agents/config.json` é configuração local; não fazem parte da aplicação.

## Validar sem recriar caches

Requer `uv`, Python ≥3.12 e FFmpeg/ffprobe no PATH. Pillow é dependência **somente de desenvolvimento** para testes/tooling histórico; o runtime usa FFmpeg/ffprobe externos e hashes/streaming com buffers limitados. Não há imagens ou frames decodificados no Python da aplicação.

Para validar o projeto, na raiz:

```fish
uv sync
env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run ruff check --no-cache src tests
```

A suíte usa transporte Comfy simulado e fixtures sintéticas de mídia: não submete jobs GPU nem precisa gerar novos chunks reais.

## Perfil de saída (opt-in)

O default continua `baseline`: 75 nós i2v/78 v2v, com a prévia nativa. `H3_WORKFLOW_OUTPUT_PROFILE=final_only` remove **apenas** `18`, `176`, `177` (prévia/decode vídeo/decode áudio exclusivos), deixando 72/75 nós. Todos os nós e links restantes são iguais; o output final `34` continua usando os decodes originais do denoised output1. Modelos, sampler, guias, condicionamento e parâmetros não são reajustados. Perfis desconhecidos falham antes de admitir jobs.

Para selecionar o perfil na API (comando fish; **inicia a API**, não inferência por si):

```fish
env PYTHONDONTWRITEBYTECODE=1 H3_WORKFLOW_OUTPUT_PROFILE=final_only uv run uvicorn h3_backend.api:app --host 127.0.0.1 --port 8010
```

Para restaurar o default, omita a variável ou use `H3_WORKFLOW_OUTPUT_PROFILE=baseline`. A proveniência registra `output_profile`, `removed_preview_nodes` e `effective_baseline_hash`; `workflow_hash` continua identificando o export golden original, enquanto o SHA do payload persistido identifica o JSON realmente submetido. `.data`/armazenamento e o cenário da CLI não mudam nesta fase. Remover a prévia não implica ganho proporcional de RAM/VRAM: modelos e cache continuam residentes. A comparação real já foi concluída: baseline410.259s e final_only451.258s, com 168 frames/7s, cenário/presets preservados e inspeção visual amostrada. O processo/cache externo mudou entre execuções; esses tempos não permitem atribuir desempenho à poda. Evidência local: `.dumps/benchmarks/final-only-three-chunks/report.json` e `.dumps/tests/reports/output_profile_comparison.json`.

## Benchmark real congelado (opt-in)

Com a API atual já rodando e a fila ComfyUI livre, execute uma vez, na raiz:

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/benchmark_h3.py --api-url http://127.0.0.1:8010 --output-dir .dumps/benchmarks/baseline --technical-acceptance
```

O comando **gera três vídeos reais/GPU** em sequência, com seeds `2026101205/6/7`, duração solicitada `2.3`, 56 frames a 24 fps e 480×864 por chunk:

1. Dança suave com o vestido **preto original**.
2. Continua da pose anterior, pequeno salto; o vestido muda **de preto para vermelho durante o chunk**, terminando **de costas/vermelho**.
3. Começa **de costas/vermelho**, vira **de frente** e revela o rosto da fotografia original, mantendo o vestido **vermelho**.

A fotografia original nunca é recolorida. O relatório congela Markdown completo, seeds, parâmetros e SHA da referência/cenário. Os dois primeiros parents são aceitos **tecnicamente apenas neste benchmark**, depois dos checks, por autorização explícita da flag; isso não equivale à aprovação visual do dono. O terceiro permanece `ready_for_review`. Sem a flag, nenhuma submissão ocorre. O benchmark não muda a política de revisão da API.

`benchmark.mp4` e `report.json` ficam no diretório local/ignorado informado. A montagem externa preserva os 168 frames (~7 s), sem trim, crossfade ou compensação escondida; áudio é preenchido até cada boundary. As junções são nos frames 56/112 (2,333333/4,666667 s). A cor, pose e recuperação facial precisam de **revisão visual humana**; checks técnicos não provam identidade ou continuidade perceptual.

O diretório precisa ser novo e ficar sob `.dumps/benchmarks/`; arquivos existentes não são sobrescritos. Antes de cada POST o ledger grava a intenção. Se falhar/timeout, **não repetir o comando nesse diretório nem submeter às cegas**: consultar `report.json` e os IDs conhecidos para recuperação explícita. Não há resume automático ou cancelamento global.

O relatório registra tempos wall-clock por chunk/total/montagem, timings do backend, probes/hashes, proveniência e contagem real dos grafos, estado dos parents e métricas disponíveis da telemetria. RAM/VRAM/swap são amostras de 5 s, não picos exatos; IO indisponível é registrado como tal. Modelos/cache não são liberados/reiniciados pelo teste, warm/cold é desconhecido, e uso de memória não é prova de offload para SSD. Mesmas seeds não garantem pixels idênticos. Para comparar uma poda futura, repita **o mesmo cenário** em outro diretório novo e revise o vídeo montado antes de declarar ausência de perda.
