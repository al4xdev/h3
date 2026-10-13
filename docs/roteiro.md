# Roteiro — planejar o conjunto, gerar um bloco por vez

**Implementado conforme o plano41.** Especificação aprovada: [telas v2](design/roteiro-telas.md), [fluxo e crítica](design/roteiro-fluxo.md) e [contrato JSON](design/roteiro-contrato.md). Validação fake/CPU e mobile emulado descrita abaixo; não foi feita nova inferência real.

## Usar

1. Biblioteca →**Novo roteiro**, ou abrir diretamente `/roteiro` na ponte local.
2. Selecionar referência própria e contar a ideia. Nome/quantidade/duração inicial ficam nas opções; duração atual padrão8s vem de capabilities.
3. **Propor roteiro com Grok** ou **Escrever os blocos manualmente**. A proposta preenche ação, duração e instrução-base de todos os blocos; ainda não existem vídeos/pais/frames futuros.
4. Conferir/editar no próprio cartão e **Usar este roteiro**. Salva plano no PC, não gera.
5. **Preparar blocoN**: conferir identidade e, na continuação, o último frame REAL da tentativa aceita doN−1. Instrução-base já preenchida. **Detalhar** é opcional; candidato do Grok só entra no texto escolhido ao **Usar esta proposta**.
6. **Gerar** salva o rascunho escolhido e envia exatamente aquela instrução/duração/seed/pai. Status e revisão são os mesmos do modo avulso.
7. Aceitar/recusar explicitamente. Aceitar libera o próximo, mas não o prepara/gera sozinho. Recusado/interrompido tem retry com prompt FINAL literal e mesmo pai original; a tentativa antiga fica intacta.
8. Todos aceitos →**Preparar montagem** →**Montar** explicitamente. Montagem usa a cadeia real, não os cartões planejados.

**Novo bloco** mantém o modo avulso, sem roteiro obrigatório. Não há um segundo motor de vídeo, dispatcher/fila ou outra implementação de revisão/montagem. Os mesmos painéis e handlers são compartilhados; apenas contexto e admissão de roteiro são acrescentados.

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

Configuração/transportador reutilizados não autorizam acessar OAuth, refresh ou inferência em startup/SSE/tests. Modelo permanece `grok-4.20-0309-non-reasoning`. A autorização real37 de uma chamada já foi consumida; esta implementação usa somente fakes.

Antes de materializar, o pipe compara a projeção original source_root/path/SHA do roteiro com a prova nativa recém calculada. Troca de bytes entre preflight e admissão rejeita antes de Store.create/worker. Setters fluentes de UUID/prova são puros, opcionais e não alteram schema público/parâmetros dos blocos avulsos.

## Limites operacionais, não qualidade/performance

- Até50blocos por documento; listagem até1000roteiros; metadata porarquivo≤1MiB inclusive histórico. Rejeitar excesso, não descartar história.
- Proposta macro raw≤512KiB e candidato completo≤1MiB. JSON estrito, número de blocos exato; sem interpretar Markdown/HTML, clamp ou seed/ID arbitrário do provider.
- Ação/instrução até12000caracteres; contexto do enhancer inteiro respeita o mesmo limite. Erro preserva texto, sem truncamento silencioso.
- Original de roteiro usa o contexto compatível com editor: JPEG/PNG próprio até20MiB/16MP. WebP nativo avulso permanece conforme contrato anterior.
- Duração porbloco requested(0,10], até2casas,24fps/5+17k/Pythonhalf-even. Default8s→192frames/8s; benchmark2.3→56frames/2.333s permanece congelado. Tail3/audioTrue independentes. Não certifica qualidade, VRAM/RAM ou geração longa real.
- RAM continua apenas telemetria. Nenhuma admissão/cancelamento por RAM livre, nenhum controle de cache/processo/lifecycle do ComfyUI/script do dono.

## Validação e evidência

Validação concluída sem iniciar APIreal H3, provider ou GPU:

- **859 testes pytest** fake/CPU, cache-free; Ruff aprovado. Inclui persistência, ownership, prefixo congelado, admissão com UUID/prova de identidade e contratos da ponte. Uma advertência de depreciação existente do Starlette permanece.
- **171 testes Node puros**:43 do front nativo,84 de retry e44 de roteiro. Incluem todos os4xx de roteiro bloqueados até GET próprio e preservação do comportamento avulso.
- **Browser nativo**, Chromium headless,393×852/DPR2/mobile/touch, pt-BR, tema escuro. Navegação normal e reduced-motion, rolagem touch e viewport320px; bancada sem overflow horizontal, CTA de geração48px. Isso é emulação, não teste de aparelho físico ou de teclado/picker do sistema.
- Fixture HTTP loopback independente, com buffers web congelados porSHA e mídia existente em allowlist; nenhuma importação/inicialização do produto. A rodada final usou `app.js` SHA`b688d3bc2f5efb24ce40cfc9375aa6b4d196d0d1a6d1e116577b882d90f94da2`.
- Rodada final: macro preenchido/adotado → raiz aceita →409 de continuação bloqueado →GET/reload/preparação sem reenviar →novoUUID com snapshot idêntico e mesmo pai, semPUT do prefixo →aceitação →terceiro bloco com8.1s/seed0 →montagem explícita da cadeia aceita. Foram4 intenções/3 esperas próprias; uma intenção foi recusada semRun. Salvar sistema do roteirista enviou somente`system_prompt`, semPUT do enhancer.
- Uma rodada anterior também verificou detalhamento opcional com dois contextos, adoção explícita e retry de tentativa rejeitada: preservou espaços/newline do prompt final, novoUUID e mesmo pai original, sem nova chamada ao Grok ao preparar/copiar. Essa rodada antecede os dois guards finais de consulta/4xx; não é apresentada como navegador da versão final desses guards.

Capturas finais inspecionadas: [bancada de continuação](design/roteiro-workbench-mobile.png) e [ajustes do rascunho](design/roteiro-settings-mobile.png), ambas em reduced-motion. A foto preta é a identidade original; o frame vermelho é um frame real existente usado pela fixture, não a saída de uma nova geração nem prova de que o bloco planejado terminou de costas.

**Limites da evidência:** a fixture entrega um clip histórico de56frames e um filme histórico de168frames/7s. Seus metadados simulados não são probes desses arquivos; montagem usa um valor fixo576 mesmo na rodada com8.1s. Não certificam8s reais,593frames montados, obediência artística, identidade facial, memória, qualidade ou performance. O recorder nativo devolveu vídeo parcial com`BACKEND_UNAVAILABLE`; não foi promovido a demonstração/GIF concluído nem contornado por outro harness. Erros de página no documento final: nenhum. Logs/JSONs de requests ficaram localmente em `.dumps/tests/ui-roteiro/`.

O catálogo atual não oferece `advanced.routes` de interceptação. O harness Playwright preparado em `tests/frontend_roteiro_browser_mock.mjs` **não foi executado** após essa mudança de protocolo; sintaxe/preparação de fixtures não valem PASS de navegador. Capturas/interações devem usar somente tool nativa e fixture dedicada readonly dos assets/media selecionados. Logs da fixture e diagnostics suportados registram requests; não alegar interceptação externa da sessão ou device físico.
