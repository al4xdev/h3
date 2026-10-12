# H3 — instruções permanentes para agentes

## Objetivo do projeto

Construir um aplicativo local leve que transforme referências e instruções de cena em vídeos encadeados: imagem → primeiro chunk → continuações → revisão → montagem. Preservar continuidade visual e permitir mudanças intencionais de ação/roupa. Os arquivos materializados em `.data` são a autoridade; HTTP é apenas a ponte local para o navegador. Benchmark e MCP são instrumentos de desenvolvimento e operação, não o produto final.

O dono autorizou trabalho autônomo: investigar, propor planos, implementar fases, testar, gerar benchmarks próprios e criar commits locais. Não esperar aprovação rotineira a cada passo dentro deste escopo. Seguir as revisões de tarefas aprovadas pelo sistema de planos; esta instrução não substitui essa autorização nem as regras do harness. Não editar arquivos gerenciados de planos diretamente.

Autonomia não autoriza: alterar parâmetros de geração para tentar melhorar o modelo, sacrificar qualidade por desempenho, controlar globalmente o ComfyUI, apagar dados, divulgar segredos, fazer push, ou repetir uma submissão de resultado incerto. Em risco fora do escopo ou ambiguidade real, parar a operação afetada e registrar a evidência.

## Arquitetura: Python fluente e verticalidade forte

- Cada operação concentra sua composição, estado, validações de negócio, router e sequência de execução no próprio arquivo vertical. Exemplos atuais: `generation/i2v.py` e `generation/v2v.py`.
- Composição fluente deve ser clara e completa; setters apenas compõem estado, sem I/O ou execução escondida. Preferir estado/dataclasses imutáveis e argumentos explícitos.
- Um dispatcher coordena admissão, slot global, RAM, worker e lifecycle. Um `workflow.py`/builder configura ambos os modos nativos.
- Não dividir uma operação em uma coleção horizontal de pequenos services, handlers, commands ou registries. Não criar DSL, plugin framework ou hierarquia de classes para um fluxo simples.
- `infrastructure/` contém adaptadores técnicos compartilhados, não uma segunda camada de negócio.
- Backend Python não importa PyTorch nem carrega modelos; ele coordena o ComfyUI. Importação/composição de ferramentas não inicia jobs.
- Preservar o entrypoint e contratos HTTP existentes, ou migrá-los explicitamente com testes de compatibilidade.

## Decisão mais recente: app local e paths como verdade

- A pasta `.data` fica **no PC**, não no celular. Upload do celular pela página é salvo nessa pasta; também deve ser possível selecionar mídia já materializada ali. Sem sincronização entre dispositivos ou segunda fonte de estado.
- Servidor Python local é uma ponte pequena: serve JS, lê metadados, recebe upload com escrita atômica e entrega arquivos próprios por streaming/Range. Não construir backend clássico, banco, broker, fila externa, camadas horizontais ou protocolo complexo de mensagens.
- Pedido explícito fica em arquivo JSON próprio; `.locks` coordenam escritores/executores locais. Um lock sozinho, uma alteração de mídia ou a abertura da página nunca autoriza gerar. Não repetir intenção incerta ou job interrompido automaticamente.
- Worker observa os paths no PC por eventos de filesystem (Linux/inotify), não por polling front↔back. Notificação SSE apenas informa que um path mudou; o JS relê os arquivos/metadados correspondentes. Registro inicial e recuperação de eventos devem evitar perder mudanças; reconexão não pode reenviar geração.
- Python não decodifica/manipula pixels nem mantém imagens, frames ou vídeos inteiros na memória. FFmpeg/ffprobe fazem validação, extração, preparação e montagem fora do processo Python. Hash/cópia/streaming de bytes codificados usam buffers limitados. Nenhum Pillow no runtime; JS/Canvas pode montar comparações visuais. Ferramentas CPU históricas de auditoria são separadas do aplicativo.
- O navegador precisa da ponte para acessar a pasta do PC, especialmente pelo celular; não prometer filesystem direto sem permissão/suporte real. A ponte não expõe a árvore inteira do PC nem permite caminhos arbitrários.
- Locks/filesystem não eliminam cache de modelos/tensores do ComfyUI nem cache recuperável de arquivos do Linux. Medir RSS de processos separadamente; não prometer ganho só por trocar arquitetura.

## Geração: simplificar trabalho, não reajustar o resultado

O dono já configurou os parâmetros. Preservar modelos, sampler, scheduler, passos, resolução/MP, duração/fórmula de frames, atenção, condicionamento, referências, guias, VAEs e caminho de decode/export final. Não experimentar parâmetros para obter uma geração "melhor" durante a simplificação.

Investigar dependências e execução real antes de remover nós. Menos nós no JSON não significa menos RAM: os nós fora da ancestralidade dos outputs podem não executar. Ramos já bypassados não justificam promessas de ganho.

A auditoria inicial comprovou que apenas `18`, `176`, `177` pertencem exclusivamente à prévia ativa duplicada. Preview usa latent output0; final usa denoised output1. Remover a prévia não autoriza religar ou reutilizar seus decodes no final. Os ancestrais do output final `34` devem permanecer estruturalmente iguais.

Manter grafos/manifests golden, prompts e referências originais intactos. Implementar podas como transformações de allowlist exata e perfil explícito, com guards/proveniência por perfil; não permitir remoção arbitrária. A versão baseline deve continuar reproduzível.

## Benchmark é a âncora de regressão

- Geração estável original: commit `502c13f`. Tooling inicial congelado: `990e27a`.
- CLI reutilizável: `tools/benchmark_h3.py`. Não duplicar cenário, geração ou validadores em MCP/frontend.
- Cenário: chunk1 dança/vestido PRETO original; chunk2 pequeno salto, muda o vestido para VERMELHO durante o chunk e termina DE COSTAS; chunk3 começa desse frame DE COSTAS, vira DE FRENTE/revela aparência facial usando a referência original e mantém VERMELHO.
- Foto original preta permanece inalterada. Seeds: `2026101205`, `2026101206`, `2026101207`. Request2.3s → 56frames a24fps,480×864 por chunk; três chunks →168frames/7s.
- Montagem externa usa todos os frames, sem trim de overlap, crossfade, filtro de cor ou correção escondida. Áudio é preenchido até cada boundary. Junções nos frames56/112.
- Opt-in `--technical-acceptance` autoriza apenas aceitar tecnicamente os dois novos parents do benchmark para avançar. Não muda a política de revisão da API nem certifica aprovação artística; terceiro permanece pronto para revisão.
- Salvar intenção antes de cada POST, depois IDs/status/payload/probes/hashes/tempos/telemetria. Sem loops de nova inferência, polling de conclusão, resume automático ou replay cego. Um diretório existente não pode ser reciclado para esconder falhas.
- Comparar o mesmo cenário/seeds/parâmetros antes/depois, com diretórios novos apenas para comparações intencionais autorizadas. Registrar cache/warm/cold e limites de medição. Seeds iguais não garantem pixels iguais; porcentagem de memória ou IO isolado não prova offload para SSD.
- Inspecionar o vídeo montado e evidência visual dos primeiros/últimos frames; observar também ação/transições no interior. O contact sheet do benchmark permite perceber pose, cor e deriva de aparência. Frame count, RGB/MAE e hashes não certificam identidade facial ou equivalência perceptual. Não instalar modelo de FaceID/embedding para esse teste.
- Baseline inicial aprovada: `.dumps/benchmarks/baseline-three-chunks/benchmark.mp4` e `contact_frames.png`; relatório completo adjacente. Ela levou410.259s end-to-end, incluindo2.057s de montagem, com modelos/cache não reiniciados. Tratar como observação, não SLA ou pico exato.

Exemplo fish, com API já ativa e diretório realmente novo:

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run python tools/benchmark_h3.py --api-url http://127.0.0.1:8010 --output-dir .dumps/benchmarks/comparison-new --technical-acceptance
```

## Dados e procedência

- `.data/` é o destino de estado persistente da aplicação: JSONs, manifests, inputs, vídeos e montagens duráveis, em subpastas próprias. É local/gitignored, não descartável.
- `runs/` contém dados legados reais, inclusive falhas e importações auditadas. Não assumir que já foram migrados. Uma migração para `.data` exige plano específico, leitura/snapshot/hash, compatibilidade de paths/IDs, publicação sem overwrite e cutover verificável. Nunca mover/apagar só por estarem gitignored.
- `.dumps/` é scratch/evidência local: relatórios, requests avulsos e mídia de teste. Não é backup. Preservar `.dumps/references/` enquanto a procedência dos assets apontar para lá.
- Grafos, manifests de referência, prompts e assets versionados são recursos reais do runtime, não exemplos descartáveis. Relocação só com plano próprio e ajuste/teste de todos os consumidores.
- Preservar estados terminais e decisões. Não transformar failed em ready por JSON manual ou API privada; recuperações específicas exigem prova, procedência e transições públicas legítimas.

## MCP local e ferramentas compartilhadas

Expor ferramentas do projeto pelo mecanismo MCP nativo comprovado do host: `.agents/mcp.json`, diretório de shims controlado `.agents/tools/` e adapter fino. Não inventar campos de configuração; consultar schema/código/documentação real. Não apontar descoberta genérica para `tools/` se ela importar scripts executáveis como `export_workflow.mjs`.

Manter `dshCustoms.managedPlans.autoApprove` e configurações globais intactos. Não modificar plugins globais, credenciais ou dependências da aplicação para viabilizar um adapter sem necessidade comprovada.

MCP deve reutilizar a CLI existente, com opt-in, paths contidos, ledger anti-replay, logs fora do stdout de protocolo e operação própria identificável. Initialize/list/help/read não submetem GPU. Smoke tests usam worker falso inerte. Documentar namespaced tool names e se descoberta exige nova sessão; não afirmar que está disponível antes da verificação.

## Git, testes e segurança operacional

1. Ler estado real de Git/plans/arquivos; não assumir que narração anterior permanece atual.
2. Snapshot de recursos e dados existentes; escopo de arquivos explícito, sem dois agentes editando o mesmo arquivo. Capturar mudanças de outros agentes sem incluí-las no próprio commit.
3. Testes fake/CPU cache-free, Ruff, whitespace/diff e commit separado antes de benchmark real. Sem push. Usar commits para rollback não destrutivo; não resetar histórico ou sobrescrever edits alheios.
4. Um job global por vez, RAM mínima disponível1536MiB preservada. HTTP202/admissão não é conclusão. WebSocket do próprio prompt e evento pós-commit do histórico; long wait, sem polling/replay. Cancelamento somente próprio UUID.
5. Track todos os jobs/processos próprios. Após concluir, coletar resultados e encerrar apenas a API criada pelo agente se não houver motivo para mantê-la. Não reiniciar/liberar caches/modelos/filas globais do ComfyUI nem parar servidores alheios.
6. Falhas/timeout/resultado ambíguo: preservar ledger/IDs/evidência, não criar outro diretório para repetir a mesma geração às cegas.

```fish
env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run ruff check --no-cache src tests tools/benchmark_h3.py
```

Usar tools nativas para leitura/busca/edição e `bash` para Git, build/test e processos. Python via `uv`; comandos para o usuário em fish. Comentários explicam decisões/constraints não óbvias, não repetem o código.

## Frontend final: simples, leve, vídeo primeiro

HTML/CSS/JS simples, preferencialmente same-origin servido pelo backend; sem framework/build/service extra sem motivo concreto. A página deve permitir ver vídeos, estados e sequência, revisar e continuar explicitamente, com erros e loading honestos. Não apresentar failed/incompleto como vídeo pronto.

Design intencional ligado à montagem por blocos, não dashboard genérico; responsivo, foco de teclado visível, labels claros, reduced-motion e sem autoplay pesado. Usar mídias reais existentes, não placeholders. Seguir `frontend-design` antes de criar UI e `playwright` antes de automatizar validação/browser. Testes de UI não disparam GPU por clique incidental; geração real fica restrita a benchmarks deliberados.

## Ordem autônoma de execução

1. Instruções/roadmap versionados.
2. Concluir adapter MCP isolado.
3. Podar apenas o preview ativo exclusivo e repetir benchmark congelado; promover somente com provas técnicas e inspeção visual. Em regressão, manter/reativar baseline e registrar, sem alterar presets para compensar.
4. Adotar `.data` por migração/compatibilidade segura e atualizar consumidores/testes.
5. Implementar frontend JS leve para operar/assistir os vídeos.
6. Validar integração dados/API/MCP/UI, documentar comandos fish e entregar aplicativo utilizável com evidências. Concluir goal somente quando esse resultado inteiro estiver verificado, não por terminar uma subfase.
