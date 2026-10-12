# H3 backend

API de geração por blocos, com revisão humana, sobre os grafos nativos validados do ComfyUI. Sem frontend ou inferência PyTorch dentro do backend.

## Organização

```text
src/h3_backend/
├── api.py                 # HTTP, consulta e revisão
├── routes/
│   ├── i2v.py             # I2VPipe: fluxo completo de imagem → chunk
│   └── v2v.py             # V2VPipe: fluxo completo de continuação → chunk
├── service.py             # dispatcher único: slot, RAM, worker e lifecycle
├── workflow.py            # builder único + WorkflowConfig imutável
└── comfy.py, media.py, models.py, store.py, telemetry.py
workflows/                 # grafos nativos, exports golden e manifests necessários
prompts/                   # templates Markdown de geração/continuação
assets/                    # referência de identidade normalizada e sua procedência
tests/                     # suíte pytest versionada (regressões, não dumps)
tools/export_workflow.mjs  # exportador nativo; não é um teste avulso
pyproject.toml, uv.lock    # dependências e configuração reproduzíveis
runs/<id>/                 # local: manifest, inputs e chunk.mp4 persistentes
.dumps/                    # local: scratch e evidências temporárias
├── tests/requests/        # requests experimentais
├── tests/reports/         # relatórios históricos e checks de integridade
└── references/            # cópia privada original apontada pelo manifest de referência
```

Cada operação concentra sua composição fluente, estado e etapas sequenciais no próprio arquivo. Os setters não fazem I/O; o dispatcher admite um único job e seu worker executa o pipe. `workflow.py` usa `continuation_api.json` como template canônico e configura i2v/v2v sem modificar os exports validados.

`POST /runs/i2v` e `POST /runs/{parent_id}/v2v` retornam **202**. A continuação exige parent aceito e usa seu último frame, a identidade original e a cauda recente. Os aliases `/runs` e `/runs/{parent_id}/continue` continuam válidos. Aceitar um run não gera automaticamente o próximo.

`GET /runs/{id}/sequence` lista somente a cadeia de manifests até esse run; não lê vídeos nem concatena. Importação de mídia externa e concatenação dos chunks completos ficam fora da API; a extração do último frame e da cauda do parent pertence ao `V2VPipe`.

## O que preservar

- **Versionado:** código, suíte `tests/`, prompts, assets normalizados, grafos/manifests de `workflows/`, exporter e configuração de dependências.
- **Persistente local:** `runs/` contém chunks reais e seus inputs/manifests, necessários à continuação. Ser gitignored **não** os torna descartáveis.
- **Temporário local:** requests avulsos, replays, relatórios e snapshots experimentais ficam em `.dumps/`, nunca no Git. Os relatórios antigos são registros do momento de cada teste, não o estado atual dos runs.
- **Procedência privada:** preservar `.dumps/references/` enquanto `assets/reference_manifest.json` apontar para ela. `.dumps` não é backup; não limpar indiscriminadamente.
- **Workspace:** `.plan/` é gerenciado pelo harness e `.agents/config.json` é configuração local; não fazem parte da aplicação.

## Validar sem recriar caches

Requer `uv`, Python ≥3.12 e FFmpeg/ffprobe no PATH. Na raiz do projeto:

```fish
uv sync
env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run ruff check --no-cache src tests
```

A suíte usa transporte Comfy simulado e fixtures sintéticas de mídia: não submete jobs GPU nem precisa gerar novos chunks reais.
