# gen — um serviço, lançadores intactos

Controle pessoal do PC, independente do runtime H3. A função fish chama um controlador Python stdlib; `systemd --user` supervisiona um único serviço transitório `gen.service`. Não há MCP nesta entrega, serviço habilitado no boot ou reinício automático.

## Uso no fish

A função e as completions estão instaladas em `~/.config/fish/`. Abra outro terminal ou recarregue a função na sessão já aberta:

```fish
source ~/.config/fish/functions/gen.fish
```

```fish
gen imagem                 # image também funciona
gen video
gen qw                     # lançador Bonsai isolado original
gen gmmax                  # Gemma: perfil antigo gmmax
gen gmno                   # perfil antigo gmno
gen gmmed                  # perfil antigo gmmed
gen gmrol                  # perfil antigo gmrol
gen gmlow                  # perfil antigo gmlow
gen status
gen status --json
gen logs                   # últimas 50 linhas da execução atual
gen logs 1 100             # linhas 1 até 100, inclusive
gen logs 101 200
gen logs 1                 # página a partir da linha 1
gen logs 1 100 --run ID     # execução anterior identificada explicitamente
gen stop
```

Não existe `--follow`. As linhas são numeradas e cada leitura é limitada a 500 linhas. Logs pertencem à execução, não misturam reinícios. `gen status` consulta lifecycle; ativo **não certifica** modelo pronto para inferência.

O `qw` aceita os argumentos adicionais que o lançador original já aceita, e preserva `BONSAI_CTX` / `BONSAI_PORT`. Os perfis `gmmax`, `gmno`, `gmmed`, `gmrol`, `gmlow` também aceitam argumentos adicionais como as abreviações antigas. Imagem/vídeo não aceitam parâmetros novos. Ambiente e diretório da chamada são preservados; não se importa configuração global para o gerenciador systemd. O lançador qw continua usando seu shebang fish normal (inclusive a configuração não interativa que já carregava). A execução passa a ser em segundo plano, sem terminal/stdin interativo; stdout/stderr vão para o log em vez de ocupar o terminal. A função requer este checkout no caminho `/home/alex/git/my/h3/tools/gen/gen.py`.

## Abreviações migradas

As definições antigas `gmmax`, `gmno`, `gmmed`, `gmrol`, `gmlow`, `qw` saíram do `config.fish`: use `gen` seguido do mesmo nome. O startup e o source da função apagam também essas abreviações já carregadas; não alteram outras abreviações/aliases. O comando curto `qw` sozinho deixa de expandir; `gen qw` continua chamando o **mesmo lançador isolado**, sem misturar seus paths, bibliotecas ou parâmetros com o llama-server normal dos perfis Gemma.

Os cinco novos lançadores estão em `tools/gen/launchers/`. Usam fish **sem recarregar config**, pois a abreviação antiga chamava o binário diretamente com o ambiente já preparado. Isso é diferente do qw, cujo próprio lançador original continua carregando fish normalmente. Foram derivados da expansão real das abreviações no fish, não de copiar cegamente suas declarações: as aspas em `--samplers` precisam atravessar os mesmos passos de parsing para manter argv idêntico. A proveniência registra declarações originais, expansões e argumentos. Não foram alterados checkpoints, contextos, reasoning, draft, cache, sampler, portas ou opções de inferência.

## Preservação e segurança

Os lançadores originais continuam intactos:

- `/home/alex/.config/my_scripts/start.sh`
- `/home/alex/.config/my_scripts/start_video.sh`
- `/home/alex/Applications/bonsai2/run-bonsai2.fish`

Imagem e vídeo atualmente têm comandos idênticos. A diferença histórica é o cgroup: vídeo mantém `MemoryHigh=79%` e `MemoryMax=80%`; imagem e qw não recebem um limite de memória adicional do gen. Limites herdados do user slice continuam aplicáveis. Não alteramos modelos, argumentos de inferência, CUDA, atenção, host, portas ou defaults.

Backup dos seis arquivos originais (incluindo função, completion e config fish) em `.dumps/gen-sacred-backup/20261013T124943.191333Z`, com `manifest.json` contendo SHA256 e permissões. Antes de migrar as abreviações, novo backup de 11 arquivos em `.dumps/gen-sacred-backup/20261013T130429.571472Z`, incluindo a configuração ainda com as seis abreviações e o gen anterior. `.dumps` é local/gitignored, não backup externo: copie essa pasta para outro disco se quiser proteção contra perda do PC.

Um lock serializa start/stop. Outro perfil ativo não é substituído; use `gen stop` explicitamente. Processos ComfyUI/llama-server reconhecidos fora do serviço bloqueiam start e nunca são encerrados pelo gen. Isso é uma proteção contra os caminhos antigos, não um inventário universal de qualquer software usando GPU: iniciar processos diretamente ainda pode burlar exclusividade.

O controlador verifica os marcadores do serviço próprio antes de parar; não envia sinais nem comandos de parada a servidores externos. Reserve o nome `gen.service` para ele: o lock coordena clientes gen, não outro programa do mesmo usuário que manipule ou substitua essa unidade simultaneamente. Falha/incerteza de início não provoca nova tentativa automática. Não configurar `Restart=always`, nem habilitar o serviço no boot. Encerrar via systemd abrange subprocessos do cgroup; por isso os modelos devem permanecer em foreground como hoje.

Estado, ambiente privado e logs ficam em `~/.local/state/gen`, com diretório restrito. O ambiente completo é necessário para preservar comportamento: os arquivos de execução podem conter segredos herdados e **não devem ser compartilhados**, versionados ou oferecidos pelo futuro MCP. Logs também podem conter dados privados emitidos pelos próprios modelos. Execuções antigas ficam disponíveis enquanto seus arquivos forem preservados.

## Validação sem GPU

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run --no-sync python -m unittest discover -s tools/gen -p 'test_gen.py' -v
fish --no-execute tools/gen/gen.fish
fish --no-execute tools/gen/completions.fish
```

Verificação da primeira entrega: 29 testes inertes passaram; Ruff passou; função instalada, help, status JSON e leitura de logs vazios foram verificados sem iniciar serviço. SHA256 confirmou os três lançadores e, naquele momento, `config.fish` inalterados, e as seis cópias de backup íntegras. Uma revisão independente não encontrou bloqueadores no escopo documentado. A segunda entrega modifica somente o bloco de abreviações migradas do `config.fish`, além da fachada/completions e suporte aos novos perfis. Sua suíte final segura passou 35 testes, incluindo comparação byte a byte do argv real de cada perfil e preservação do ambiente pelo shebang sem config. Os três scripts originais e os 11 backups continuam íntegros; o diff de config foi validado como restrito ao bloco migrado.

Os testes finais usam adaptadores falsos e cópias instrumentadas com printf. Instalação da função não liga modelos; não fazemos um teste real deliberado de carga/geração nesta entrega. Durante um teste inicial da migração, um mock inadequado pode ter alcançado o comando real gmmax; o job foi cancelado, e snapshots posteriores não encontraram modelo remanescente. Não houve requisição de inferência nem alteração de parâmetros. Evidência e correção do método em `.dumps/gen-migration-incident.md`; não afirmar que nenhum modelo foi invocado nessa segunda entrega. O start/stop real via systemd e o cgroup sob carga ainda não foram exercitados. Esta entrega não certifica prontidão nem consumo de RAM dos modelos sob carga. Os logs não têm rotação automática; a leitura tail é limitada em memória/saída, mas percorre o arquivo inteiro. Um gerenciador systemd travado também pode deixar uma chamada aguardando: não há retry automático.
