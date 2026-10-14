# H3 — app local de vídeo

Geração por blocos e revisão humana sobre os grafos nativos validados do ComfyUI. `.data` no PC é a autoridade; Python serve o front JS, catálogos, upload e mídia própria, observa paths por inotify/SSE e coordena ferramentas externas, sem carregar modelos ou pixels. Ponte/worker, editor Grok isolado e montagem FFmpeg estão integrados e verificados no navegador real. A revisão continua explícita; a montagem de um fim ainda pronto para revisão é uma prévia. Consulte [arquitetura local](docs/local_architecture.md).

As decisões permanentes de autonomia, arquitetura vertical, benchmark, MCP, dados e frontend estão em [`AGENTS.md`](AGENTS.md). A meta é um aplicativo local leve de vídeos encadeados, não apenas um teste de geração.

O Store grava estados/JSONs/mídia persistente em `.data/runs/<UUID>/`. `runs/` permanece como âncora legada intacta: projetos com esse legado exigem [migração offline verificada](docs/data_storage.md), sem reescrever manifests ou apagar vídeos. O runtime só usa a autoridade canônica após recibo válido. `.dumps/` continua como scratch/evidência; recursos `workflows/`, `prompts/` e `assets/` permanecem na raiz do projeto.

## Abrir o estúdio local

Na raiz do projeto, com FFmpeg/ffprobe e o ComfyUI já disponíveis:

```fish
uv sync
env PYTHONDONTWRITEBYTECODE=1 uv run --no-sync uvicorn h3_backend.api:app --host 127.0.0.1 --port 8010
```

Abra `http://127.0.0.1:8010`. Para usar pelo celular na mesma **rede confiável**, na porta8888:

```fish
./start.sh
```

O script inicia a ponte em `0.0.0.0:8888`, sem instalar dependências automaticamente; execute `uv sync` na preparação inicial. Também funciona quando chamado pelo caminho absoluto fora da raiz do projeto. No PC, abra `http://127.0.0.1:8888`.

No celular, abra `http://IP-DO-PC:8888`; `hostname -I` mostra os IPs do PC. Não publique esse servidor na internet: ele opera os arquivos e autorizações locais do PC. Fechar a ponte não libera os modelos do ComfyUI; são processos distintos.

- **Novo roteiro** planeja o conjunto em `/roteiro`: ideia + referência →proposta de blocos preenchidos →edição/adoção explícita →preparar um bloco por vez. **Novo freestyle** mantém o modo Freestyle; geração, status, revisão, retry e montagem são compartilhados, não outro motor. Plano/intenções vivem no PC; adotar não gera e aceitar não gera o próximo. Veja [roteiro e recuperação](docs/roteiro.md).
- **Gerar os blocos restantes** executa o roteiro salvo em ordem após confirmação: detalha cada bloco com Grok, usa a proposta e aceita tecnicamente os intermediários para continuar. O último exige revisão. Erro, resultado incerto ou **Parar** interrompem o lote sem replay.
- **Continuar roteiro · Tail** acrescenta blocos após o último vídeo aceito: uma frase vira proposta estruturada editável, a adoção preserva o trecho existente e o lote melhora cada novo bloco com o frame real atualizado. Todos os blocos atuais precisam estar concluídos e aceitos; o limite total permanece 50. Consulte o mesmo UUID após resultado incerto, sem reenviar.
- Ações bloqueadas explicam o motivo ao toque/clique, preservando o bloqueio. Na tela do roteiro, Tail fica após os blocos e ações principais; apagar e consultar a ideia/referência ficam em **Outras opções**.
- Enquanto o Grok responde, um indicador discreto alterna 20 mensagens de espera. Não representa progresso; pausa em telas ocultas e respeita redução de movimento, sem reenviar pedidos.
- Microanimações acompanham estrelas de favorito após confirmação, ícones de navegação, seções recolhíveis e mudanças de estado do roteiro. Mídia e controles nativos permanecem estáveis; redução de movimento desativa os efeitos.
- No Freestyle, **Operações → Converter para roteiro** adota a sequência completa aberta, preservando mídia, prompts, parâmetros e decisões. Não gera nem chama Grok.
- Os avisos de geração na biblioteca oferecem **Parar**: o cartão abre confirmação verde/vermelha, e somente **Confirmar parada** cancela o pedido próprio.
- A biblioteca organiza **Favoritos**, **Roteiros** e **Freestyle** em seções recolhíveis. Estrela e lixeira ficam no próprio cartão; os textos das listas mostram até três linhas, preservando o prompt completo ao abrir. Freestyle carrega12 itens por página e lê as seguintes só em **Carregar mais**. Favoritos ficam em `.data/library/favorites.json`, compartilhados pelos navegadores conectados ao mesmo PC.
- Ao reconectar, o app consulta o ID original e troca o aviso incerto pelo estado confirmado. **Dispensar aviso** aparece somente para pedidos resolvidos; não apaga arquivos, libera um pedido ativo nem repete geração. Os ponteiros de recuperação permanecem na URL. Uma decisão de revisão sem resultado confirmado continua bloqueada.
- O PWA inclui ícone H3 próprio, manifesto e opção **Instalar H3** nos Ajustes quando o navegador permitir. No celular, instalação exige **HTTPS confiável**; HTTP pelo IP da rede continua como site. Tela cheia depende do suporte da plataforma. A tela offline preserva a URL para reconectar; API, mídia, operações e rascunhos não são cacheados nem repetidos. JavaScript do estúdio é sempre lido da rede para evitar versões antigas. Veja o [requisito de instalação](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable).
- Animações de navegação/feedback têm o dobro da duração anterior; os dropdowns abrem e fecham suavemente nos navegadores com suporte. **Reduzir movimento** remove as transições, sem atrasar as ações.
- Um carregamento genérico bloqueia a vista atual congelada ao iniciar o estúdio e abrir roteiros, blocos ou montagens, com entrada/saída por opacidade. O gesto de voltar fica bloqueado durante a leitura; **Voltar** na camada de loading abandona a consulta da tela. Uma resposta atrasada não força navegação nem cancela geração no PC. Atualizações de metadados em segundo plano continuam discretas.
- O visual usa roxo/lavanda, cartões arredondados e movimentos inspirados em **Coisas de Casa**. O gesto de voltar acompanha o dedo sobre vistas congeladas: soltar cedo devolve a tela ao lugar; completar restaura rolagem, rascunho, seleção, seções abertas e posição do vídeo, sem autoplay ou nova geração. Vídeos e controles reais não são transformados durante o arrasto.
- Selecione uma referência da biblioteca ou **Envie imagem ao PC**; upload não gera vídeo. Imagens próprias ficam em `.data/inputs/`, com bytes originais preservados.
- Descreva a cena e clique **Gerar** explicitamente. Assista ao bloco antes de aceitar/rejeitar; apenas um pai aceito permite continuar.
- **Detalhar ideia e imagem** envia explicitamente sua ideia e a referência selecionada ao Grok. Na continuação, você vê e envia **identidade original + último frame do pai aceito**, para distinguir identidade de pose/roupa atual. O preview do frame é CPU, não geração. **Usar esta proposta** e **Gerar** são ações separadas. System prompt é editável nos Ajustes, mas o modelo continua fixo: `grok-4.20-0309-non-reasoning`. Credenciais ficam separadas; uma chamada real autorizada com duas imagens respondeu200, mas limites/cota e obediência integral da proposta não estão certificados. Veja [Grok](docs/grok.md); abrir/reconectar não chama o provider.
- A engrenagem abre **Ajustes**: seed/duração pertencem ao rascunho do bloco ainda não enviado, não alteram resultados nem viram preset global. Duração solicitada até10s, default8s para novos blocos; alinhamento nativo24fps/5+17k:8s→192frames/8s,3s→73frames/3.042s,5s→124frames/5.167s,10s→243frames/10.125s. Benchmark2.3s e durações históricas de retry permanecem explícitos.10s é orçamento operacional, não garantia de memória/desempenho/qualidade; não foi feita geraçãoGPUlonga.
- Blocos **recusados/interrompidos** conservam seu **prompt final enviado**, inclusive o melhorado pelo Grok se usado. **Preparar nova tentativa** abre geração já preenchida, sem voltar ao começo ou chamar Grok de novo. Só Gerar cria outro pedido; a tentativa antiga não é reaberta e a nova exige revisão. Continuação usa o mesmo pai original aceito. Sem metadados seguros, a cópia é bloqueada com motivo, não substituída por defaults.
- Atualização de arquivos chega por SSE; reconectar ou atualizar a biblioteca só relê metadados, nunca repete geração. Resultado incerto exige consulta do ID conhecido, não novo POST cego.

**Montar sequência** concatena a cadeia selecionada, sem gerar novos blocos: todos os pais devem estar aceitos e o fim pode estar aceito ou pronto para revisão. Assista/baixe o resultado no painel próprio. Montar não aceita o fim: a prévia mantém a revisão pendente. Após aceitar o fim, um novo clique explícito pode publicar uma montagem da sequência aceita. Se a resposta for perdida, use **Reler montagem** no ID conhecido; não reenvie às cegas.

No celular, uma tela principal por vez e um topo compacto **Voltar · título · engrenagem**. Biblioteca/Nova cena não ficam como abas permanentes; listas, ancestrais e ações acompanham a única rolagem da página, sem rodapé/docks fixos. Grok é opcional no fluxo manual e obrigatório antes de cada bloco no lote. Voltar/Ajustes preservam o rascunho, referência, seed e duração durante a sessão. Recarregar relê os arquivos do PC sem repetir operações; rascunhos ainda não enviados não são persistidos no navegador.

O fluxo tem microanimações curtas de entrada, toque, seleção e confirmação, principalmente no mobile. Elas não atrasam cliques nem movem os vídeos/controles fixos; respeitam a preferência **reduzir movimento** do aparelho. Loading é feedback do estado real, sem progresso inventado ou operações disparadas pela animação.

## Organização

```text
src/h3_backend/
├── __init__.py
├── api.py                 # HTTP, consulta e revisão
├── roteiro.py             # planos, propostas, configuração e correlação de intenções
├── generation/            # fatia vertical de geração
│   ├── __init__.py
│   ├── i2v.py             # I2VPipe: fluxo completo de imagem → chunk
│   ├── v2v.py             # V2VPipe: fluxo completo de continuação → chunk
│   ├── dispatcher.py      # slot único, worker e lifecycle dos pedidos; RAM só telemetria
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
.data/roteiros/<id>/       # local: plano, candidatos e histórico de intenções
runs/<id>/                 # legado preservado, nunca fallback gravável
.dumps/                    # local: scratch e evidências temporárias
├── tests/requests/        # requests experimentais
├── tests/reports/         # relatórios históricos e checks de integridade
└── references/            # cópia privada original apontada pelo manifest de referência
```

Cada operação concentra sua composição, estado, router e etapas no próprio arquivo vertical: os pipes em `generation/` e os planos em `roteiro.py`. Setters fluentes não fazem I/O; `generation/dispatcher.py` admite um único job e seu worker executa o pipe nativo. `generation/workflow.py` usa `continuation_api.json` como template canônico e configura i2v/v2v sem modificar os exports validados. `infrastructure/` reúne somente adaptadores existentes, não novos serviços de negócio. O entrypoint continua `h3_backend.api:app`.

`POST /runs/i2v` e `POST /runs/{parent_id}/v2v` retornam **202**. A continuação exige parent aceito e usa seu último frame, a identidade original e a cauda recente. Os aliases `/runs` e `/runs/{parent_id}/continue` continuam válidos. Aceitar um run não gera automaticamente o próximo.

`GET /runs/{id}/sequence` lista somente a cadeia de manifests até esse run; não lê vídeos nem concatena. `POST /assemblies/{UUID}` com `{end_run_id}` aguarda a montagem CPU e devolve200; ela vive em `.data/assemblies/<UUID>/` separada dos runs. GET do mesmo ID e vídeo próprio/Range permitem redescobrir o resultado sem executar novamente. A reserva CPU compartilha slot/leases com geração; não altera decisões dos runs. RAM é só telemetria: o app não rejeita/cancela por memória livre nem gerencia o ComfyUI, cujo ciclo de vida pertence ao script externo do dono. O helper FFmpeg mantém ordem/contagem e áudio preenchido, sem trim/crossfade; CRF18 não promete pixels RGB ou MP4 byte-exact. A extração do último frame e da cauda do parent pertence ao `V2VPipe`; geração continua restrita ao pedido explícito.

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
node --test tests/frontend_ui.test.mjs tests/frontend_retry.test.mjs tests/frontend_roteiro.test.mjs
```

A suíte usa transporte Comfy simulado e fixtures sintéticas de mídia: não submete jobs GPU nem precisa gerar novos chunks reais. A integração de roteiro passou859 testes Python e171 Node; [evidência mobile e limites](docs/roteiro.md#validação-e-evidência) distinguem dados mockados de geração real.

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
