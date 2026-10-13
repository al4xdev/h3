# H3 · Roteiro — fluxo, ações e limites da proposta

**Revisão crítica v2 — aprovada e implementada pelo plano41.** Telas e palavras em [roteiro-telas.md](roteiro-telas.md); [uso e evidência com limites](../roteiro.md). Esta crítica registra as decisões anteriores à implementação, não substitui os testes nem certifica performance por desenho.

## Revisão crítica: o que encontrei e corrigi

| Problema no primeiro desenho | Consequência no uso | Correção na v2 |
| --- | --- | --- |
| Proposta e roteiro repetiam os mesmos cartões em páginas distintas | Adotar parecia trocar de produto sem mudar a tarefa | Uma tela central com estados proposta/adotado. |
| Editar ação/duração exigia abrir outra tela | Navegação demais para corrigir cada trecho | Edição no cartão; organização em disclosure. |
| Preparação, proposta do enhancer e conferência final eram três páginas | Muitas etapas só para gerar um bloco já planejado | Uma bancada com contexto, editor e adoção explícita da proposta. |
| Botão Usar instrução do roteiro copiava texto já adotado | Clique redundante sem decisão nova | Campo já preenchido; Grok opcional. |
| Nome/contagem/duração dominavam a entrada | Usuário precisava montar formulário antes de contar a ideia | Referência + intenção primeiro, divisão/nome em opções. |
| Dois contextos grandes empilhados distanciavam o prompt | Muitas dobras no mobile antes da ação principal | Cards compactos, contain, lado a lado quando legíveis; ampliar no documento. |
| Três editores de ajustes abertos de uma vez | Mistura tarefa atual com sistemas globais | Seção local clara e dois sistemas em disclosures separados. |
| Repetir avisos técnicos em todo cartão | Plano difícil de ler, foco em implementação e não ação | Avisos nos pontos de adoção/Gerar e mensagens só quando pertinentes. |
| Texto de passado podia soar como prova de obediência | Modelo/usuário confundiria intenção com resultado real | Rotular intenção dos blocos aceitos; frame real continua contexto visual autoritativo. |
| Default2,3s ficou desatualizado após correção40 | Proposta começaria com orçamento diferente do app atual | Default8s vindo de capabilities; benchmark2,3 permanece intocado. |

**O que mantive de propósito:** separação plano/tentativas, pai aceito concreto, adoção de proposta distinta de Gerar, revisão artística por bloco e montagem explícita. Esses limites não exigem páginas redundantes.

**Riscos tratados na implementação:** correlação durável antes de202, salvamento do contexto escolhido antes do pedido e conflitos por revisão têm regressões fake/CPU. Cards/CTA foram medidos no browser mobile emulado a393px e320px, sem overflow horizontal. Capturas não certificam aparelho físico, qualidade do modelo ou performance; veja os limites da evidência.

## 1. O que esta evolução muda

Hoje: pensar num bloco →detalhar opcionalmente →gerar →revisar →pensar na continuação.

Proposto: **pensar no vídeo inteiro →preencher todos os blocos →trabalhar em um bloco por vez com o fluxo existente**.

O roteiro é o plano. O Run continua sendo uma tentativa real. Não gerar todos os prompts finais supondo futuros frames; não gerar todos os vídeos só porque o macro foi adotado.

### Fluxo principal por tela

```text
T00 Biblioteca
 ├─ Novo bloco → fluxo avulso existente
 └─ Novo roteiro → T01 referência + intenção
                      ↓ propor explicitamente ou escrever manualmente
T02 Roteiro
 ├─ Estado proposta: lista preenchida/editável → Usar este roteiro
 ├─ Estado adotado: lista + próximo bloco/histórico
 ├─ Editar: expande o cartão, não muda de página
 └─ Preparar bloco N
                      ↓
T03 Bancada do bloco
 ├─ Instrução-base já preenchida; contexto real + duração/seed
 ├─ Detalhar opcional → candidato no mesmo editor
 │    └─ Usar esta proposta OU Manter minha instrução
 └─ Gerar bloco explicitamente
                      ↓
T04 Pedido no PC → T05 revisão após publicação confirmada
                      ├─ Recusar/interrompido → retry → T03
                      └─ Aceitar → Preparar próximo → T03
                                   ou último aceito → T06 montagem

T07 Ajustes retorna à origem. T02 é a casa do roteiro.
Back/abrir/reler/adotar proposta não geram.
```

## 2. Exemplo completo: o roteiro já preenche os blocos

Referência: mulher de vestido preto na imagem original. Ideia: dançar, pequeno salto com mudança para vermelho, terminar de costas e depois virar de frente.

| Posição | Ação preenchida | Duração preenchida | O que ainda NÃO existe |
| --- | --- | --- | --- |
| 1 | Dança mantendo o vestido preto. | 8s | Vídeo, Run ID, frame final, decisão. |
| 2 | Pequeno salto; vestido fica vermelho; termina de costas. | 8s | Pai Run confirmado, vídeo, pose real de partida. |
| 3 | Vira de frente; mantém vermelho. | 8s | Pai Run confirmado e frame real de costas. |

Adotar esse roteiro prepara três itens e seus rascunhos. A primeira instrução-base pode ser usada diretamente ou detalhada. Depois de o bloco1 ser aceito, o2 pode ser detalhado com **identidade original + final REAL do1**. O plano do3 ajuda a contextualizar o2, mas não é uma imagem conhecida nem deve ser executado antecipadamente.

Se o2 não termina de costas, a revisão precisa mostrar o vídeo real. Aceitar esse resultado não prova que seguiu o roteiro. O usuário pode recusá-lo ou ajustar a ação futura; não reescrever o passado para aparentar continuidade.

## 3. Estado e autoridade: três coisas distintas

### A. Plano do roteiro — editável

- ID próprio do roteiro, nome, ideia geral e referência original OWNED.
- Revisão do documento, ordem dos itens e chave estável de cada bloco.
- Por bloco: ação planejada, duração solicitada, seed de rascunho, instrução-base, proposta opcional e instrução escolhida.
- Contexto/versão usados no detalhamento, para detectar resposta antiga ou prompt desatualizado.
- Salvo explicitamente no PC sob `.data/roteiros/`; não em localStorage, banco ou memória do telefone como autoridade.
- Chave estável do bloco não vira um Run UUID nem muda só porque a ordem mudou.

### B. Tentativa real — histórico separado

- Intenção de envio própria, vínculo com roteiro/bloco/revisão e o UUID real do Run quando admitido.
- Snapshot enviado: prompt literal, seed, duração, identidade e pai concreto, sem substituir por ideia antiga.
- Estado real, mídia publicada e decisão pelo fluxo nativo existente.
- Rejeição/interrupção preservam a tentativa. Retry é outro pedido e outra revisão.
- Uma tentativa não é considerada aceita porque o roteiro diz “bloco concluído”. A decisão nativa é autoridade.

### C. Prefixo aceito — base da continuação

- Para gerar posiçãoN, a tentativa escolhida da posiçãoN−1 deve estar realmente aceita e publicada.
- Cada filho deve apontar para essa tentativa exata; não basta ela aparecer imediatamente acima num cartão.
- Mudança de ordem entre futuros itens não modifica parent de um filho já enviado.
- Aceitos e snapshots admitidos ficam congelados. Revisar o sufixo planejado não muda a cadeia já materializada.
- Montagem usa a ancestralidade concreta do fim escolhido, nunca concatena quaisquer runs com o mesmo número de bloco.

## 4. Matriz de ações — nenhum efeito escondido

| Ação na UI | Salva plano/config? | Chama Grok? | Gera vídeo? | Muda decisão? |
| --- | --- | --- | --- | --- |
| Novo roteiro / abrir / Voltar | Não | Não | Não | Não |
| Enviar referência | Salva input próprio | Não | Não | Não |
| Propor roteiro com Grok | Registra intenção/proposta própria | Sim, uma ação explícita | Não | Não |
| Editar proposta | Rascunho até salvar/adotar | Não | Não | Não |
| Usar este roteiro | Sim, plano validado | Não | Não | Não |
| Salvar alterações do bloco | Sim, bloco/revisão | Não | Não | Não |
| Preparar bloco | Prepara rascunho/contexto próprio | Não | Não | Não |
| Detalhar este bloco | Registra proposta/contexto | Sim, somente aquele trecho | Não | Não |
| Usar esta proposta | Copia candidato para instrução escolhida, na mesma bancada | Não | Não | Não |
| Gerar bloco | Registra intenção e snapshot/vínculo | Não | Sim, uma tentativa | Não |
| Consultar pedido / montagem | Somente leitura/reconciliação legítima | Não | Não | Não |
| Aceitar / recusar tentativa | Mantém decisão nativa | Não | Não | Sim, explicitamente |
| Preparar outra tentativa | Novo rascunho baseado no snapshot | Não | Não | Não |
| Montar vídeo | Intenção/montagem própria | Não | Não | Não |
| Salvar instruções do roteirista | Só configuração separada | Não | Não | Não |
| Salvar instruções do detalhamento | Só configuração atual do enhancer | Não | Não | Não |

Não confundir upload/salvar plano/criar UUID local com autorização de inferência.

## 5. Detalhamento por bloco: reaproveitar o enhancer existente

A nova proposta é dar contexto ao enhancer, não substituir seu sistema custom:

```text
Roteiro: Dança: do preto ao vermelho
Ideia geral: [intenção original do usuário]

Intenção dos blocos aceitos:
[ações planejadas e prompts realmente enviados dos trechos anteriores]
Esses textos descrevem a intenção; o resultado visual pode diferir.

Este bloco:
[ação planejada da posiçãoN]
Duração solicitada: [valor do rascunho]
Frames alinhados / tempo: [capabilities atuais]

Próximo bloco planejado:
[ação da posiçãoN+1, ou “Este é o último bloco.”]
Não repetir o anterior nem antecipar a ação do próximo.

Contexto visual:
1. Identidade original.
2. Último frame REAL do pai aceito, quando houver.
```

Somente o usuário clicando **Detalhar este bloco** dispara a consulta. Reutilizar cliente/provider/auth/modelo fixo e o preview CPU existente. Não ler/exibir OAuth, reautenticar, renovar grant ou alterar o pin para implementar roteiro.

O **roteirista do macro** tem um sistema separado, voltado a dividir a ideia em blocos. Não salvar esse sistema sobre `.data/grok/editor.json`. Resposta estruturada inválida não vira execução; mostrar erro e preservar texto/ideia. Não prometer que o provider obedece perfeitamente duração, idioma ou aparência.

Não propor nova chamada real durante desenho/implementação/testes: a autorização única37 já foi consumida. Testes futuros serão fake/CPU; uso real só por ação explícita do dono.

## 6. Rota isolada, reaproveitamento e superfície proposta

**Proposta técnica a validar depois da revisão das telas:** uma operação vertical `roteiro.py` para plano, propostas e correlação de tentativas; mesma ponte local, sem novo servidor/framework/banco/fila.

- Página/contexto próprio `/roteiros` e `/roteiros/{id}` para a experiência de roteiro. Pode usar a mesma shell/estilos e telas atuais de preparação/revisão; não duplicar todo o frontend só para ter URL separada.
- API local de planos: listar/criar/ler/salvar roteiro e sua revisão, com locks/escrita atômica bounded e conflito explícito. Paths são owned; navegador não escolhe paths arbitrários.
- Ação explícita de proposta do roteiro separada da ação de detalhar bloco. Ambas retornam propostas editáveis, nunca callbacks de geração.
- Salvar sistemas de roteirista e enhancer tem contratos/escopos separados. Um não muda o outro.
- Geração/revisão/continuação/montagem reutilizam os pipes, Store, dispatcher, media e contratos nativos existentes. Não copiar validador de vídeo, frames, revisão ou código de geração para o roteirista.
- Registro/recuperação da intenção de um bloco precisa ser durável antes do envio. Um vínculo só no JS após202 não é suficiente: se a resposta se perde, “sem Run ID no plano” não significa “não gerou”.
- A composição que delega ao pipe nativo deve registrar o vínculo concreto no mesmo caminho de admissão, com prova/reconciliação de sua intenção. **Não** criar um segundo dispatcher, novo worker ou endpoint de gerar todos os blocos. O detalhe do contrato de correlação será definido na implementação aprovada, não fingido como já existente.
- GET/SSE/reload reconstituem o estado e consultam o mesmo ID. Não geram nem repetem pedido automaticamente.

“Rota isolada” significa separar a operação de roteiro. Não significa criar outro motor de vídeo, autenticação, fonte de estado ou ciclo de vida do ComfyUI.

## 7. Bordas de UX que precisam estar visíveis

| Problema | O que o usuário vê | O que não pode acontecer |
| --- | --- | --- |
| Plano não salvo | Alterações não salvas; salvar/descartar/continuar | Perder texto por Back sem escolha. |
| Outro navegador salvou versão nova | O roteiro mudou no PC; conferir versão/guardar rascunho | Sobrescrever revisão automaticamente. |
| Macro voltou inválido | Resposta não convertível; ver texto/manual | Inventar duração, clamp ou gerar. |
| Resposta antiga | Contexto anterior; adoção explícita | Trocar pai ou edição atual. |
| Pai sem aceitação/prova | Abrir predecessor; preparar bloqueado | Continuar de rejeitado ou frame errado. |
| Preview ausente | Reler frame/manual existente | Enviar silenciosamente só identidade ao Grok. |
| Envio incerto sem Run ID | Consultar intenção de envio | Repetir POST porque não há link. |
| Tentativa recusada/interrompida | Prompt final + preparar outra | Mutar terminal ou consultar Grok sozinho. |
| Frame real diverge da ação | Vídeo/revisão e contexto real | Fingir que a intenção foi obedecida. |
| Montagem incompleta/404/5xx | Reler o mesmo ID | Novo UUID ou sucesso presumido. |
| Script externo encerra ComfyUI | Erro/incerteza honesta da tentativa | Controlar script, RAM ou caches; replay. |

## 8. Parâmetros e limites não negociados por este desenho

Preservar os valores configurados: modelo nativo, sampler, scheduler, passos, resolução, referência, VAE/decode/export. Duração por bloco continua requested(0,10], máximo duas casas, default8s conforme correção40,24fps e arredondamento Python half-even5+17k.8s→192frames/8s; três desses blocos somam576frames/24s, sem certificar desempenho ou obediência visual.2,3s permanece explícito no benchmark congelado e registros históricos. Tail3/audioTrue independentes da duração. Totais alinhados são soma dos frames, não promessa de duração solicitada exata para outros valores.

Nenhuma política de RAM: não rejeitar/cancelar porque memória livre caiu. Telemetria continua observacional; lifecycle do ComfyUI pertence ao script do dono. Slot único e incerteza/no-replay continuam.

## 9. Propostas para decidir juntos, não dúvidas bloqueantes

| Decisão | Minha recomendação | Alternativa |
| --- | --- | --- |
| Entrada inicial | Referência + ideia, nome/quantidade/duração inicial em opções | Duração total desejada + divisão proposta, deixando alinhamento explícito. |
| Adotar o macro | Preenche/salva todos os blocos, sem gerar | Nenhuma alternativa automática presumida. |
| Avançar | Aceitar →Preparar próximo explicitamente | Automação depois, com escopo/autorização próprios. |
| Planejamento futuro | Editável mesmo antes de o predecessor existir | Bloquear tudo até gerar, menos útil. |
| Seed | Copiar preset atual ao rascunho e conservar | Política explícita por bloco; não escolher pelo Grok nem incrementar escondido. |
| Edição do meio | Fora desta primeira evolução | Rota separada com âncoras anterior/following, ainda precisa design/workflow próprios. |
| Frontend | Shell familiar + tela central de roteiro + reutilização das demais | Página completamente separada; exige cuidado extra com rascunhos e incertezas ao navegar. |
| Resultado failed | Exibir evidência; política atual de retry preservada | Incluir retry de failed num escopo explícito posterior. |

## 10. Critério para começar a implementar

1. Eu reviso criticamente os desenhos e corrijo o percurso — esta v2 já registra essa primeira revisão crítica.
2. Dono revisa as telas T00–T07 e as palavras/botões desta v2.
3. Incorporar comentários em nova revisão dos Markdown.
4. Depois da aprovação humana, fechar plano técnico com arquivos exclusivos, contrato durável de intenção/vínculo, testes fake/CPU e integração do frontend.
5. Só então implementar. Não interpretar autoApprove do gerenciador como sua revisão destas telas.

**Te chamar para revisar estes Markdown é a próxima ação; não implementar em seguida sem sua resposta.**
