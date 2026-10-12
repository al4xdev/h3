# Estado durável em `.data`

O Store usa **somente `.data/runs/<UUID>/`** para manifests, inputs, prompts, workflow executado, telemetria e vídeos. `project_root` continua sendo a raiz de `workflows/`, `prompts/` e `assets/`; não configure `H3_PROJECT_ROOT=.data`. Os URLs continuam `/runs/<UUID>` e `/runs/<UUID>/video`.

`runs/` é a âncora legada preservada, não um segundo Store gravável. A migração copia todos os arquivos e diretórios (incluindo ocultos e diagnósticos aninhados), sem editar JSON, estados, decisões ou procedência. Um failed sem vídeo é válido. Caminhos históricos de Comfy/probes e telemetria de importação continuam sendo histórico, não entradas para execução.

## Migração offline explícita (fish)

Pare primeiro **só a API própria deste projeto** e confirme ausência de outros escritores. Não pare/reinicie o ComfyUI. A ferramenta não faz rede nem inferência, e não acredita apenas no flag `--offline`: toma um lock exclusivo do produto. Um runtime ativo mantém lock compartilhado até shutdown; um lease separado permite somente um backend por projeto. Stores de leitura do mesmo processo continuam compatíveis.

```fish
# Preflight: não copia nem publica mídia.
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/migrate_state.py

# Uma intenção, cópia verificada, publicação sem overwrite e recibo final.
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/migrate_state.py --execute --offline
```

O preflight lê todo `runs/`, verifica UUIDs/manifests, rejeita queued/running, symlinks, arquivos especiais, colisão de destino e falta de espaço. A execução cria uma intenção imutável em `.data/migrations/<UUID>/intent.json`, copia para `staging/runs`, compara inventário/SHA256 da fonte e cópia e publica **só** o subtree `.data/runs` com Linux `renameat2(RENAME_NOREPLACE)`. Não substitui nem um destino vazio criado concorrentemente. Cada arquivo e a publicação de diretórios são fsynced.

Após a publicação, `.data/migrations/<UUID>/verified.json` e `.data/state/migration.json` registram UUID de intenção, raiz, destino, inventário, IDs e checksum. O startup falha fechado se existir legado/intenção sem recibo válido, ou se prova/recibo divergirem. Importação dos módulos não migra nem reenvia jobs. Projetos novos sem legado podem criar `.data/runs` diretamente.

`.data/benchmark-mcp/` pertence ao adapter MCP e é intocado. `.dumps/benchmarks/` continua como scratch/evidência da CLI, não estado durável do aplicativo.

## Crash e reconciliação

Não apague staging/recibos nem tente outra intenção para esconder um erro. Os originais ficam intactos e podem ser inspecionados como âncora; o runtime novo não usa fallback gravável para eles. Uma staging parcial/fonte divergente exige investigação, não cópia/replay automático.

Com o UUID **já registrado** em uma intenção própria, uma cópia completa e ainda idêntica à fonte pode ser finalizada explicitamente:

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/migrate_state.py --execute --offline --reconcile UUID-DA-INTENCAO
```

A reconciliação não recopia nada: verifica todos os bytes/IDs/raiz antes de publicar uma staging completa ou finalizar um publish já feito. Fonte divergente, stage parcial, outro destino ou symlink são recusados. Depois do recibo, reexecutar a ferramenta é idempotente: reconhece a migração e **não** compara/restaura manifests mutáveis canônicos a partir do legado. Decisões novas e novos chunks permanecem em `.data`.

Não volte cegamente para o código antigo após novas decisões. Preserve/snapshot `.data` e use código compatível com esta autoridade. Nenhuma pasta é apagada pela migração.

## Contrato técnico para consumidores

- `Store.root`: raiz de recursos do projeto, inalterada.
- `Store.runs` / `Store.directory(UUID)`: raiz/diretório físico canônico em `.data`.
- `Store.relative_artifact(UUID, filename)`: string persistível `.data/runs/<UUID>/<filename>`.
- `Store.own_artifact(UUID, persisted_path, filename)`: valida propriedade e retorna o caminho físico canônico. Permite `runs/<MESMO_UUID>/<filename>` **somente** para IDs da prova/recibo da cópia; não cria symlinks nem reescreve manifests.
- Allowlist: `chunk.mp4`, `initial_frame.png`, `last_frame.png`, `reference_tail.mp4`, `workflow_api.json`, `prompt.md`, `telemetry.jsonl`, `telemetry_error.json`. Não é um resolvedor arbitrário de arquivos. Rejeita outro UUID, prefixos não canônicos, caminho absoluto/traversal e ancestrais symlink.
- `source_root: runs` continua categoria lógica para referências próprias; as strings de novas referências/slot_map usam `.data/runs/...`. `source_root: assets` e a identidade original são preservados.
- `Store.sequence` continua metadata-only e só lê a cadeia de ancestrais escolhida. `restore` observa só a autoridade canônica, interrompe queued/running sem replay e preserva terminais.

A CLI de benchmark reutiliza o resolvedor de ownership; cenário/STAGES/Markdown/seeds/modelos/parâmetros são os mesmos. Nenhuma geração adicional é necessária para testar a migração: CPU/fakes e GET de vídeos existentes bastam.
