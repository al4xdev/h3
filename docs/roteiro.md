# Roteiro — planejar o conjunto e gerar em sequência

**Implementado conforme o plano41.** Especificação aprovada: [telas v2](design/roteiro-telas.md), [fluxo e crítica](design/roteiro-fluxo.md) e [contrato JSON](design/roteiro-contrato.md). Validação fake/CPU e mobile emulado descrita abaixo; não foi feita nova inferência real.

## Usar

1. Biblioteca →**Novo roteiro**, ou abrir diretamente `/roteiro` na ponte local.
2. Selecionar referência própria e contar a ideia. Nome/quantidade/duração inicial ficam nas opções; duração atual padrão8s vem de capabilities.
3. **Propor roteiro com Grok** ou **Escrever os blocos manualmente**. A proposta preenche ação, duração e instrução-base de todos os blocos; ainda não existem vídeos/pais/frames futuros.
4. Conferir/editar no próprio cartão e **Usar este roteiro**. Salva plano no PC, não gera.
5. **Preparar blocoN**: conferir identidade e, na continuação, o último frame REAL da tentativa aceita doN−1. Instrução-base já preenchida. **Detalhar** é opcional; candidato do Grok só entra no texto escolhido ao **Usar esta proposta**.
6. **Gerar** salva o rascunho escolhido e envia exatamente aquela instrução/duração/seed/pai. Status e revisão são os mesmos do modo Freestyle.
7. Aceitar/recusar explicitamente. Aceitar libera o próximo, mas não o prepara/gera sozinho. Recusado/interrompido tem retry com prompt FINAL literal e mesmo pai original; a tentativa antiga fica intacta.
8. Todos aceitos →**Preparar montagem** →**Montar** explicitamente. Montagem usa a cadeia real, não os cartões planejados.

**Novo freestyle** mantém o modo Freestyle, sem roteiro obrigatório. Não há um segundo motor de vídeo, dispatcher/fila ou outra implementação de revisão/montagem. Os mesmos painéis e handlers são compartilhados; apenas contexto e admissão de roteiro são acrescentados.

## Gerar os blocos restantes

**Gerar os blocos restantes** gera todos os blocos nunca enviados, na ordem do
roteiro, inclusive no meio. Cada trecho pendente continua da versão aceita
selecionada do bloco anterior (o primeiro bloco do roteiro é I2V). Quando o bloco
seguinte a um trecho já tem versão aceita, o último bloco do trecho é gerado como
**bridge** até o primeiro frame dele, com o contexto Grok de edição (identidade +
último frame do pai + primeiro frame do destino, configuração de `roteiro-edits`).
Um bloco anterior recusado/sem versão aceita, revisões pendentes ou resultados
incertos bloqueiam o lote com mensagem.

A confirmação autoriza uma chamada ao Grok antes de cada bloco, o uso automático
do texto melhorado e a aceitação técnica dos intermediários para encadear o próximo.
Essa aceitação não certifica qualidade artística. O último fica pronto para revisão;
a montagem continua sendo uma ação explícita separada.

O lote congela as instruções do editor sequencial e os blocos-base. Para cada etapa,
registra a intenção do editor, envia identidade e, nas continuações, o último frame
real do pai aceito; salva a resposta usada, atualiza apenas o prompt do bloco e gera
com seed, duração e parâmetros registrados. Não envia texto cru como fallback.
Intenções e respostas ficam em `.data/roteiro-batches/`, com IDs conhecidos antes
das submissões. Erro, parada, desconexão incerta ou reinício não repetem provider/GPU.

`POST /roteiros/<id>/batches/<UUID>` exige `expected_revision`,
`auto_accept_intermediate: true` e `enhance_with_grok: true`; responde 202.
`GET` no mesmo endereço consulta o lote; `GET /roteiro-batches/current` descobre o
estado global sem executar. SSE comunica mudanças de paths e a interface relê
esses arquivos, sem polling de conclusão. Fechar a página não cancela o lote.

## Continuar roteiro com Tail

Após concluir e aceitar todos os vídeos atuais, abra **Continuar roteiro · Tail**
abaixo dos blocos. Escreva o que deve acontecer a seguir, escolha a quantidade,
duração e seed, e peça a proposta ao Grok. O planejamento recebe a identidade
original e o frame final real do último vídeo aceito, com saída JSON estruturada.
O limite atual é de 1000 blocos no roteiro inteiro, incluindo os existentes.

Edite, reorganize ou remova os novos blocos e confirme a continuação. Essa ação
acrescenta apenas o trecho novo: preserva os blocos, vídeos e tentativas anteriores
e não inicia geração. Depois use **Gerar os blocos restantes**. Cada novo bloco
passa novamente pelo editor com o frame real atualizado do anterior, usando o
lote descrito acima. O último vídeo exige revisão; a montagem permanece explícita.

A proposta e a adoção usam um UUID conhecido antes do envio e ficam registradas
em `.data/roteiros/<id>/tail-<UUID>.json`. Consulte o mesmo pedido após perda de
conexão; não reenvie uma intenção incerta. Mudanças no roteiro ou no vídeo de
origem invalidam a adoção da proposta antiga. Planejamento mantém o limite de
20000 tokens; melhoria de cada bloco mantém 12000. A interpolação entre duas
âncoras continua no backlog.

`POST /roteiros/<id>/tail/<UUID>` planeja; `GET` consulta sem executar;
`PUT` adota os novos blocos com a revisão de origem. Nenhuma dessas consultas
gera vídeo. A validação usa clientes falsos e mídia CPU, sem inferência real.

## Roteiros longos (contrato do app)

- `GET /roteiros/summary` → `{items:[{id, name, idea, adopted, revision, block_count,
  states:{accepted, ready_for_review, active, failed, planned}, strip:[estado por bloco],
  updated_at}], total}`. Estado do bloco = versão selecionada (ou última tentativa):
  `queued/running/uncertain` → `active`; `rejected/interrupted/failed/not_admitted` →
  `failed`; sem tentativa → `planned`. `updated_at` = maior entre o mtime de `plan.json`
  e o `updated_at` dos runs observados.
- `POST /roteiros/<id>/blocks/<block_id>/remove` `{expected_revision}` → roteiro. O bloco
  sai de `blocks`/`selected_runs`; com tentativas vai para `removed_blocks` (vídeos,
  tentativas e decisões preservados). Bloqueado por tentativa ativa/incerta, vídeo do
  próprio bloco aguardando revisão, lote ativo ou edição pendente. Depois, as versões
  aceitas ficam fixadas em `selected_runs` (modo editorial).
- `PUT /roteiros/<id>`: a subsequência de blocos com tentativas deve ficar idêntica e na
  mesma ordem; blocos nunca enviados podem ser inseridos, editados, reordenados ou apagados.
- `POST /roteiros/<id>/segments/<UUID>` `{expected_revision, after_block_id|null, idea,
  count, duration_seconds, seed}` planeja blocos para inserir (sem gravar o roteiro);
  `GET` no mesmo ID recupera. O app adota inserindo os blocos via `PUT`.
- `Generate` aceita `target_run_id` opcional: bridge até a versão aceita selecionada do
  bloco seguinte.

### Planejamento (proposta, Tail e segmento)

Cadeia de chamadas estreitas, com o mesmo modelo fixo. A tarefa e o formato vão na
mensagem e no schema. O narrador não reenvia o system prompt antigo que pedia um
JSON único de todos os blocos:

1. **Script** (`h3_roteiro_script`): uma chave, um fragmento. Eventos com intenção,
   fala opcional, e listas distintas de corpo, expressão e delta. Sem segundos e sem
   prompt de vídeo.
2. **Paleta** (`h3_roteiro_palette`), só se alguma lista for mais curta que os slots
   daquele evento: uma chave por evento curto. Não copia item por módulo.
3. Relógio no código: piso e teto por evento; o que sobra vira approach/hold do mesmo
   evento. Duração de todo bloco = a pedida. Uma fala, um slot, com o placeholder
   hardcoded do sotaque sulista; os outros recebem `Sem fala.`
4. **Cartões** (`h3_roteiro_card`): uma chave por slot, um fragmento string. Até 4 em
   paralelo, uma tentativa. `run_pos_prompt` não entra. A instrução resultante é o
   que o melhorador já expande; o melhorador não muda.

O resultado guarda `draft_scenes`, `scenes`, `slices` e os `raw_texts` das chamadas
feitas. `vision` fica vazio: o melhorador não recebe ensaio de câmera nesta etapa.
Falha da primeira chamada por rede ou cancelamento deixa o pedido incerto; falha
posterior deixa `invalid`. Sem retry automático.

## Converter Freestyle para roteiro

Em **Operações → Converter para roteiro**, a origem é a sequência completa já aberta,
incluindo seus blocos posteriores quando um ancestral está selecionado. A conversão
usa os prompts efetivamente enviados como instruções/ações, copia seed e duração,
herda a identidade original e registra a procedência dos runs existentes. Não copia
nem reexecuta vídeos, não chama Grok e não altera decisões nativas.

`POST /roteiros/from-freestyle/<fim>` recebe um `roteiro_id` conhecido pelo cliente.
Em resposta perdida, `GET /roteiros/<roteiro_id>` consulta esse mesmo resultado;
não há nova conversão automática. Só fontes com pedido nativo imutável, cadeia e
metadados comprovados podem ser adotadas. Legado sem essa prova, identidade alterada,
mídia substituída, parâmetros incompatíveis ou propriedade de outro roteiro bloqueiam
a conversão com erro. Evidência de mídia inclui hash e identidade do arquivo, sem
decodificar pixels nem alterar a origem.

## Parar uma geração

Os avisos da biblioteca e os cartões Freestyle ativos oferecem **Parar**. A confirmação
acontece no próprio cartão: preenchimento curto da esquerda para a direita, **Cancelar**
em verde e **Confirmar parada** em vermelho. Abrir/cancelar não envia pedidos; o
segundo clique confirma a parada. Movimento reduzido e mudança dinâmica de preferência
cancelam a animação sem alterar a confirmação ou o estado do pedido.

`POST /runs/<UUID>/stop` e `POST /roteiros/<id>/batches/<UUID>/stop` aceitam `{}`.
Somente o worker próprio pode ser interrompido; parar um filho do lote interrompe
o lote inteiro. A operação acompanha o encerramento mesmo se o cliente desconectar.
Sem ID ou resultado confirmado, a interface mantém a incerteza e consulta o mesmo
endereço, sem repetir POST. Não limpa filas, modelos, caches ou processos globais.

## Estado e recuperação

- `.data` fica no PC. Plano em `.data/roteiros/<UUID>/plan.json`, candidatos próprios no mesmo diretório, configuração do roteirista `.data/roteiros/editor.json`.
- `GET` não grava configuração, chama provider ou admite geração. `PUT` de plano/configuração é explícito, com revisão esperada; conflito preserva a edição, não sobrescreve silenciosamente.
- Nome/ação/duração/prompt do plano não são prova de obediência do vídeo. Aceitação/artístico e pose/roupa do frame real permanecem decisões/evidência concretas.
- Chave planejada identifica uma posição, não um Run futuro. No clique Gerar, a intenção ganha UUID conhecido; servidor salva snapshot e reserva marcador `.data/roteiros/.locks/<UUID>.json` antes de admitir.
- O **mesmo UUID** é admitido pelo pipe nativo. Falha/perda da resposta não deixa o app sem endereço de consulta: `GET /roteiros/<id>/blocks/<key>/attempts/<intentUUID>`.
- Leitura reconcilia marcador+pedido nativo imutável+manifest atual+snapshot+provas de identidade/pai/cadeia. Corrupto/ausente após intenção persistida é **incerto**, nunca autorização de novoPOST. POST duplicado409 não reenvia.
- Toda falha de admissão do roteiro, inclusive400/404/409/422, conserva o bloqueio até consultar a intenção própria. HTTP4xx sozinho não prova ausência de execução. **Consultar envio** só lê quando roteiro/bloco/intenção correspondem exatamente ao contexto atual; não consulta um UUID antigo de outro bloco.
- Rejeição confirmada pelo GET e histórico (`admission: rejected`, `state: not_admitted`, `run: null`) oferece **Preparar novo envio**. Copia o snapshot literal para rascunho isolado, incluindo referência/SHA, seed, duração e pai original aceito. Consultar, recarregar e preparar não fazem POST/PUT nem criam UUID; só Gerar cria a nova intenção. O registro recusado permanece intacto.
- Prefixo enviado e decisões antigas ficam congelados. Ajuste de retry é snapshot novo, não edição do passado. Futuro não enviado pode ser editado/organizado sem gerar; não atravessar posições enviadas.
- URL `/roteiro?roteiro=<UUID>` conserva endereço do plano; block/intent e pending_roteiro/pending_block/pending_intent conservam proprietário da intenção em navegação/reload. Não usar browserstorage como outra autoridade. Rascunho local ainda não salvo continua transitório.

## Editor e identidade

Roteirista tem configuração própria. O enhancer de bloco continua usando seu sistema custom atual, modelo fixo e endpoint `/grok`, com intenção geral/past-intents/current/next e duração. Texto de passado é **intenção**, não alegação de fato visual. Continuação envia identidade original + frame do pai aceito pelo adaptador existente, sem PNG inventado, override de path ou fallback silencioso para uma imagem.

Nos ajustes, **Vídeos sequenciais** e **Roteiro completo** são seções recolhíveis,
com campos e ações de salvar independentes. Vídeos sequenciais usa
`.data/grok/editor.json` e devolve a instrução textual de um bloco. Roteiro completo
usa `.data/roteiros/editor.json` e recebe a ideia, nome, quantidade e duração inicial,
além da referência original. Os prompts padrão e contextos acrescentados pelo
aplicativo são escritos em inglês; ideias, instruções já enviadas e falas literais
do usuário são preservadas. O transporte Responses pede `text.format` com
`type: json_schema`, `strict: true` e o schema do roteiro, incluindo o número exato
de blocos. A validação local continua obrigatória; erro ou resposta incompleta não
provoca nova chamada ou fallback para texto livre.

A migração explícita `tools/migrate_grok_prompts.py` preserva exatamente a
configuração de vídeos sequenciais, exige os hashes esperados dos dois arquivos e
salva cópias privadas antes de trocar apenas o prompt de roteiro completo. Não
acessa OAuth, altera modelo ou chama o provider. Nova edição do usuário impede
substituição pela migração; uma configuração já migrada não é regravada.

Configuração/transportador reutilizados não autorizam acessar OAuth, refresh ou inferência em startup/SSE/tests. Modelo permanece `grok-4.20-0309-non-reasoning`. A autorização real37 de uma chamada já foi consumida; esta implementação usa somente fakes.

Antes de materializar, o pipe compara a projeção original source_root/path/SHA do roteiro com a prova nativa recém calculada. Troca de bytes entre preflight e admissão rejeita antes de Store.create/worker. Setters fluentes de UUID/prova são puros, opcionais e não alteram schema público/parâmetros dos blocos Freestyle.

## Apagar itens da biblioteca

Os cartões de **Roteiros** e **Freestyle**, e suas telas de detalhe, oferecem
**Apagar**. A confirmação solicita uma remoção real de mídia própria: arquivos são
transferidos para um diretório privado novo `/tmp/h3-trash-*`, com registro da
operação. Referências compartilhadas, assets versionados, dados legados e arquivos
do ComfyUI permanecem intactos. Pequenos manifests, pedidos, decisões e marcadores
de remoção ficam em `.data` para preservar procedência e impedir replay de UUID.

`DELETE /runs/<UUID>` não aceita body; `DELETE /roteiros/<UUID>` exige
`{"expected_revision": <revisão atual>}`. Apagar roteiro inclui mídias das suas
tentativas confirmadas e montagens próprias. Uso por outro roteiro, continuação
externa ou montagem compartilhada bloqueia a remoção. Geração/montagem ativa ou
admissão incerta também bloqueiam. A operação usa o slot local existente, sem
controlar o ComfyUI, e guarda evidência de falha/rollback sem repetição automática.
Itens removidos deixam os catálogos e leituras públicas; uma abertura antiga não
recria vídeos nem libera IDs já utilizados.

## Navegação e sequência aberta

**Estúdio local**, no topo, abre a biblioteca. A revisão de uma tentativa de roteiro
retorna à tela de todos os blocos pelo **Voltar**. Rascunhos e pedidos em andamento
ou incertos mantêm seus registros e bloqueios ao navegar.

O gesto de voltar começa na borda esquerda e segue para a direita, usando a mesma
navegação do botão. Rolagem vertical, múltiplos toques, gesto cancelado e interação
com campos, vídeos, controles ou a linha de continuidade não acionam essa navegação.

Ao selecionar um ancestral na linha de continuidade, a sequência já aberta mantém
seu último bloco explícito: abrir o bloco 12 e selecionar o 7 mantém os doze cartões
visíveis. Esse contexto visual não substitui a cadeia real da seleção: continuar e
montar seguem usando o bloco selecionado e seus próprios ancestrais. Outra
ramificação precisa ser aberta explicitamente; não há escolha automática de filho
ou resultado mais recente.

## Limites operacionais, não qualidade/performance

- Até1000blocos por documento (lote, Tail, segmento, edição e montagem editorial); cadeia da montagem freestyle continua100; listagem até1000roteiros; metadata porarquivo≤16MiB inclusive histórico. Rejeitar excesso, não descartar história.
- Cada texto bruto do planejamento≤512KiB. JSON estrito, número de blocos exato; sem interpretar Markdown/HTML, clamp ou seed/ID arbitrário do provider.
- Ação/instrução até12000caracteres; contexto manual até12000 e contexto integral do lote até100000. Erro preserva texto, sem truncamento silencioso.
- Original de roteiro usa o contexto compatível com editor: JPEG/PNG próprio até20MiB/16MP. WebP nativo Freestyle permanece conforme contrato anterior.
- Duração porbloco requested(0,10], até2casas,24fps/5+17k/Pythonhalf-even. Default8s→192frames/8s; benchmark2.3→56frames/2.333s permanece congelado. Tail3/audioTrue independentes. Não certifica qualidade, VRAM/RAM ou geração longa real.
- RAM continua apenas telemetria. Nenhuma admissão/cancelamento por RAM livre, nenhum controle de cache/processo/lifecycle do ComfyUI/script do dono.

## Validação e evidência

Atualização de avisos, favoritos e PWA em 2026-10-13: **933 testes Python**
fake/CPU e **236 testes Node** passaram; Ruff e whitespace check aprovados.
Inclui reconciliação do mesmo pedido após desconexão, decisão ainda incerta
preservada, dispensa sem apagar/repetir, favoritos atômicos compartilhados,
resumos limitados, paginação lazy de12 sem perder atualização SSE, PWA sem cache
de API/mídia/operações e reconexão preservando os IDs da URL. Os textos das listas
ficam em três linhas e os ícones de favorito/apagar têm área de toque44px.
O ícone próprio foi gerado pela ferramenta nativa image_gen; original e exportações
estão em `src/h3_backend/web/`, com prompt em `icon-provenance.json`.
Logs em `.dumps/tasks/notices-pwa-library-pytest.txt` e
`notices-pwa-library-node-tests.txt`. Sem nova chamada ao Grok/GPU, reinício de
servidor de produção ou nova captura visual automatizada. Instalação PWA no
celular requer HTTPS confiável; fullscreen e fechamento animado do dropdown
dependem do suporte do navegador.

Atualização de lote, Freestyle e parada em 2026-10-13: **924 testes Python**
fake/CPU e **209 testes Node** passaram; Ruff e whitespace check aprovados.
Inclui melhoria Grok obrigatória por bloco, ausência de fallback/replay, descoberta
passiva do lote, conversão com provas de mídia, navegação e gesto de retorno,
confirmação inline e cancelamento com publicação em disco concluída antes de liberar
o slot. Logs locais em `.dumps/tasks/freestyle-batch-pytest.txt` e
`freestyle-batch-node-tests.txt`. Não houve chamada real ao provider/GPU,
início/reinício do servidor de produção ou nova captura visual no navegador.

Atualização de biblioteca, prompts e navegação em 2026-10-13: **889 testes Python**
fake/CPU e **185 testes Node** passaram; Ruff e whitespace check aprovados. Inclui
exclusão de roteiro com tentativa nativa e montagem falsas, preservação dos arquivos
de origem, restart sem replay, dependências compartilhadas, rollback, migração
privada/atômica, payload de JSON Schema, navegação 12→7 sem truncamento, falha de
leitura do fim da sequência, respostas atrasadas e histórico de itens apagados.
A configuração local do roteiro completo foi migrada para inglês com snapshot;
o hash da configuração sequencial permaneceu exatamente igual. Logs locais em
`.dumps/tasks/library-grok-pytest.txt` e `library-grok-node-tests.txt`. Não houve
provider/GPU ou início/reinício de servidor de produção. Esta atualização não
inclui nova captura visual em navegador; a evidência mobile abaixo é histórica.

Validação concluída sem iniciar APIreal H3, provider ou GPU:

- **859 testes pytest** fake/CPU, cache-free; Ruff aprovado. Inclui persistência, ownership, prefixo congelado, admissão com UUID/prova de identidade e contratos da ponte. Uma advertência de depreciação existente do Starlette permanece.
- **171 testes Node puros**:43 do front nativo,84 de retry e44 de roteiro. Incluem todos os4xx de roteiro bloqueados até GET próprio e preservação do comportamento Freestyle.
- **Browser nativo**, Chromium headless,393×852/DPR2/mobile/touch, pt-BR, tema escuro. Navegação normal e reduced-motion, rolagem touch e viewport320px; bancada sem overflow horizontal, CTA de geração48px. Isso é emulação, não teste de aparelho físico ou de teclado/picker do sistema.
- Fixture HTTP loopback independente, com buffers web congelados porSHA e mídia existente em allowlist; nenhuma importação/inicialização do produto. A rodada final usou `app.js` SHA`b688d3bc2f5efb24ce40cfc9375aa6b4d196d0d1a6d1e116577b882d90f94da2`.
- Rodada final: macro preenchido/adotado → raiz aceita →409 de continuação bloqueado →GET/reload/preparação sem reenviar →novoUUID com snapshot idêntico e mesmo pai, semPUT do prefixo →aceitação →terceiro bloco com8.1s/seed0 →montagem explícita da cadeia aceita. Foram4 intenções/3 esperas próprias; uma intenção foi recusada semRun. Salvar sistema do roteirista enviou somente`system_prompt`, semPUT do enhancer.
- Uma rodada anterior também verificou detalhamento opcional com dois contextos, adoção explícita e retry de tentativa rejeitada: preservou espaços/newline do prompt final, novoUUID e mesmo pai original, sem nova chamada ao Grok ao preparar/copiar. Essa rodada antecede os dois guards finais de consulta/4xx; não é apresentada como navegador da versão final desses guards.

Capturas finais inspecionadas: [bancada de continuação](design/roteiro-workbench-mobile.png) e [ajustes do rascunho](design/roteiro-settings-mobile.png), ambas em reduced-motion. A foto preta é a identidade original; o frame vermelho é um frame real existente usado pela fixture, não a saída de uma nova geração nem prova de que o bloco planejado terminou de costas.

**Limites da evidência:** a fixture entrega um clip histórico de56frames e um filme histórico de168frames/7s. Seus metadados simulados não são probes desses arquivos; montagem usa um valor fixo576 mesmo na rodada com8.1s. Não certificam8s reais,593frames montados, obediência artística, identidade facial, memória, qualidade ou performance. O recorder nativo devolveu vídeo parcial com`BACKEND_UNAVAILABLE`; não foi promovido a demonstração/GIF concluído nem contornado por outro harness. Erros de página no documento final: nenhum. Logs/JSONs de requests ficaram localmente em `.dumps/tests/ui-roteiro/`.

O catálogo atual não oferece `advanced.routes` de interceptação. O harness Playwright preparado em `tests/frontend_roteiro_browser_mock.mjs` **não foi executado** após essa mudança de protocolo; sintaxe/preparação de fixtures não valem PASS de navegador. Capturas/interações devem usar somente tool nativa e fixture dedicada readonly dos assets/media selecionados. Logs da fixture e diagnostics suportados registram requests; não alegar interceptação externa da sessão ou device físico.
