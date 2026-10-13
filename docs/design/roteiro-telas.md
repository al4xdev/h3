# H3 · Roteiro — telas revisadas, v2

**Desenho aprovado e implementado pelo plano41.** Esta revisão substitui o primeiro desenho de12 telas. Os diagramas abaixo são especificação, não screenshots ou prova de geração. [Fluxo e motivos das mudanças](roteiro-fluxo.md); [uso, capturas e limites de validação](../roteiro.md).

## O que mudou depois de desenhar

1. **Conferir proposta e acompanhar roteiro são a mesma tela**, em estados diferentes. Não repetir a lista inteira ao clicar Usar.
2. **Editar um item acontece no seu próprio cartão**, sem uma tela adicional para pequenas alterações.
3. **Contexto, instrução, proposta Grok e Gerar ficam na tela do bloco.** Preservar adoção explícita sem obrigar três páginas consecutivas.
4. **Status, revisão e montagem reutilizam o fluxo atual**, com origem no roteiro; não construir outra versão de cada operação.
5. **Salvar plano não é gerar.** Tornar essa distinção clara em dois pontos importantes, não repetir avisos técnicos em todo cartão.
6. Default atual do app: **8s por bloco**, conforme correção40. Benchmark2,3s e registros anteriores permanecem históricos, não defaults do roteiro.

### Caminho curto

```text
Biblioteca → Novo roteiro → Roteiro preenchido
                              ↓ escolher próximo
                         Preparar bloco
                              ↓ gerar explicitamente
                         Pedido → Revisão
                              ↓ aceitar
                         Preparar próximo
                              ↓ último aceito
                           Montagem
```

São **oito telas**, contando Biblioteca e Ajustes. Proposta/edição são estados dentro delas, não novas páginas. Não empilhar todas as telas numa página.

## Padrão visual e de interação

- Mobile393×852, uma rolagem do documento. Topo sticky **Voltar · título · engrenagem**, hit targets44px; campos/botões principais48px. Sem abas globais ou dock fixo.
- Grafite `#242725`, superfícies `#151816`, papel `#eeeae2`, cobre `#c38b62`, secundário `#a7ada7`, bordas `#454b46`.
- Display atual: Arial Narrow/Liberation Sans Narrow/Impact; corpo system-ui; dados ui-monospace. Sem novas fontes/deps.
- Título26px, seção22px, corpo/campos16px, legenda14px, dados12px. Margens16px; espaçamento8/16/24px; cards padding16px/borda1px/raio3px.
- Ação principal: cobre preenchido, texto escuro, largura total. Secundárias neutras. Desabilitado tem motivo textual. Foco visível.
- Sequência vertical é ordem real do plano. Aceito tem decisão real; Planejado não tem thumbnail de vídeo inexistente.
- Dois contextos visuais em cards lado a lado quando couberem sem overflow, inclusive no telefone; imagens com contain, sem crop. A320px, empilhar se os rótulos ficarem ilegíveis. Cada `Ampliar imagem` expande sua figura no documento, sem novo fluxo/modal obrigatório.
- Desktop: leitura central até960px. Não transformar o plano numa timeline horizontal rolante.
- Voltar conserva rascunho/origem/scroll/foco. Não salva configuração, chama Grok, gera, aceita ou monta. Nenhum Enter implícito gera.
- Movimento atual/reduced-motion, sem autoplay, progresso inventado ou gestos globais.

---

## T00 · Biblioteca

**Uma escolha real:** roteiro inteiro ou bloco avulso.

```text
┌─────────────────────────────────────┐
│ ←      Biblioteca                ⚙ │
├─────────────────────────────────────┤
│ Seus vídeos                         │
│                                     │
│ [ Novo roteiro ]                    │
│ [ Novo freestyle ]                      │
│                                     │
│ Roteiros                            │
│ ┌─────────────────────────────────┐ │
│ │ Dança: do preto ao vermelho     │ │
│ │ 3 blocos · 1 aceito             │ │
│ │ Próximo: bloco 2                │ │
│ │ [ Abrir roteiro ]              │ │
│ └─────────────────────────────────┘ │
│                                     │
│ Freestyle                      │
│ ┌─────────────────────────────────┐ │
│ │ Ela gira e olha para a câmera.  │ │
│ │ Pronto para revisão            │ │
│ │ [ Abrir bloco ]                │ │
│ └─────────────────────────────────┘ │
└─────────────────────────────────────┘
```

- Novo roteiro →T01. Novo freestyle →fluxo atual, sem roteiro obrigatório.
- Abrir roteiro →T02. Abrir bloco →revisão atual.
- Vazio: **“Seu primeiro roteiro começa com uma ideia.”** / **“Nenhum bloco avulso ainda.”**
- Loading: **“Lendo seus vídeos no PC…”** Erro: **“Não foi possível ler a biblioteca.”** +`Reler biblioteca`.
- Um run do roteiro continua no histórico, mas não duplicar cada tentativa como um novo projeto principal. O cartão resume posições aceitas, não quantidade de runs.

## T01 · Novo roteiro

**Primeiro a intenção.** Nome e divisão são controles secundários, não um formulário técnico obrigatório antes de contar a cena.

```text
┌─────────────────────────────────────┐
│ ←      Novo roteiro              ⚙ │
├─────────────────────────────────────┤
│ Referência original                 │
│ [ Escolher imagem no PC       ▾ ]   │
│ [ Enviar imagem do celular ]        │
│ ┌─────────────────────────────────┐ │
│ │       imagem selecionada        │ │
│ └─────────────────────────────────┘ │
│                                     │
│ O que acontece no vídeo?            │
│ ┌─────────────────────────────────┐ │
│ │ Começa dançando de preto.        │ │
│ │ Dá um salto e muda para         │ │
│ │ vermelho, termina de costas     │ │
│ │ e depois vira de frente.        │ │
│ └─────────────────────────────────┘ │
│                                     │
│ [ Ajustar divisão e nome ▾ ]        │
│                                     │
│ [ Propor roteiro com Grok ]         │
│ [ Escrever os blocos manualmente ]  │
│ Cria uma proposta. Não gera vídeo.  │
└─────────────────────────────────────┘
```

O disclosure **Ajustar divisão e nome** contém exatamente:

```text
Nome [ Dança: do preto ao vermelho ]
Quantidade inicial [ 3 ] blocos
Duração inicial [ 8 ] segundos por bloco
3 × 8 s = 24 s planejados
Você pode alterar cada trecho depois.
```

- Quantidade3 é exemplo de planejamento, não parâmetro nativo. Não usar número escolhido pelo Grok como seed/frames.
- Nome é opcional na entrada; proposta pode sugerir título editável. Quantidade/duração ficam disponíveis sem poluir a primeira tarefa.
- Default da duração vem de capabilities atuais:8s. Campos não ficam hardcoded em8 para sempre. Requested(0,10], duas casas; validar, não clamp.
- Upload usa o fluxo existente, salva input no PC, não chama Grok.
- Propor é uma chamada explícita →T02 em estado proposta. Manual cria itens editáveis →mesma T02. Nada gera em nenhuma dessas ações.

## T02 · Roteiro — proposta, edição e acompanhamento

**Esta é a casa do projeto.** A mesma lista funciona antes e depois de adotar o roteiro.

### Estado A — proposta recebida, não adotada

```text
┌─────────────────────────────────────┐
│ ←      Roteiro                   ⚙ │
├─────────────────────────────────────┤
│ Dança: do preto ao vermelho          │
│ Proposta · nenhum vídeo gerado       │
│ 3 blocos · 24 s planejados           │
│                                     │
│ ┌─ 1 · Planejado ─────────────────┐ │
│ │ Dança mantendo o vestido preto. │ │
│ │ 8 s · [ Editar ]                │ │
│ └─────────────────────────────────┘ │
│ ┌─ 2 · Planejado ─────────────────┐ │
│ │ Salto; muda para vermelho;      │ │
│ │ termina de costas.              │ │
│ │ 8 s · [ Editar ]                │ │
│ └─────────────────────────────────┘ │
│ ┌─ 3 · Planejado ─────────────────┐ │
│ │ Vira de frente; mantém vermelho.│ │
│ │ 8 s · [ Editar ]                │ │
│ └─────────────────────────────────┘ │
│                                     │
│ [ Adicionar bloco ]                 │
│ [ Usar este roteiro ]               │
│ Salva todos os blocos. Não gera.     │
└─────────────────────────────────────┘
```

- **Todos os itens já têm ação, duração e instrução-base.** Vídeos, frames futuros e Run IDs ainda não existem.
- Usar este roteiro valida/salva. Permanece nesta tela, mudando para estadoB. Não reproduzir a lista em outra página.
- Propondo: **“Dividindo sua ideia em blocos…”** Erro: **“Não foi possível obter a proposta. Sua ideia continua aqui.”** +`Voltar à ideia` / `Escrever manualmente`.
- Inválido: **“A resposta não pôde ser convertida em blocos válidos.”** +`Ver resposta` / `Voltar à ideia`. Sem JSON/HTML executável, adivinhação ou preenchimento silencioso.
- Outra proposta só por ação explícita `Propor outra versão` em opções. A nova é candidata separada: não substituir edição ou sequência já adotada.

### Estado B — plano adotado

```text
│ Salvo no PC · 1 de 3 blocos aceito   │
│ [ Preparar bloco 2 ]                │
│                                     │
│ 1 · Aceito                          │
│ Dança mantendo o vestido preto.     │
│ [ Assistir bloco ]                  │
│                                     │
│ 2 · Próximo                         │
│ Salto; vermelho; termina de costas. │
│ 8 s · [ Editar ]                    │
│                                     │
│ 3 · Planejado                       │
│ Vira de frente; mantém vermelho.    │
│ Aguarda o bloco 2 ser aceito.        │
│ 8 s · [ Editar ]                    │
│                                     │
│ [ Ver ideia e referência ▾ ]        │
│ [ Adicionar bloco ]                 │
```

Ação principal do estadoB:

| Estado real | Texto/ação |
| --- | --- |
| Nenhum gerado | Preparar bloco 1 |
| Prefixo aceito | Preparar bloco N |
| Enviado/running | Ver pedido do bloco N |
| Pronto | Revisar bloco N |
| Recusado/interrompido confirmado | Preparar outra tentativa |
| Falha confirmada | Ver tentativa |
| Incerto | Consultar envio do bloco N |
| Todos aceitos | Preparar montagem |

Sem Gerar tudo. Um cartão aceito abre o resultado, não editor retroativo. Para cada posição, `Ver tentativas` fica disponível ao expandir detalhes, separado do plano.

### Estado C — editar no cartão

```text
│ 2 · Editando plano                  │
│ O que acontece                      │
│ [ Texto da ação, editável.        ] │
│ Duração [ 8 ] s                     │
│ 192 frames → 8,000 s alinhados       │
│ [ Salvar alterações ] [ Cancelar ]  │
│ [ Organizar bloco ▾ ]               │
```

- Apenas um cartão em edição por vez; trocar com alterações não salvas oferece `Salvar e continuar` / `Descartar alterações` / `Continuar editando`.
- Organizar: `Mover para cima`, `Mover para baixo`, `Remover bloco`. São ações de planejamento, sem exclusão de runs/mídia. Remover exige confirmar.
- Só o sufixo não enviado pode mudar de ordem; não atravessa uma posição já enviada. Não fazer renumeração visual que mude a identidade das tentativas.
- Modificar ação/duração/vizinho marca instrução detalhada anterior como desatualizada. Não chamar Grok nem sobrescrever o prompt escolhido.
- Unsaved: **“Alterações não salvas.”** Erro de save conserva o cartão editado. Conflito: **“O roteiro mudou no PC. Confira a outra versão antes de salvar.”**
- Adicionar um bloco depois de todos aceitos torna o projeto novamente incompleto; não invalida/exclui montagem anterior.

## T03 · Preparar bloco — uma bancada, não três páginas

**Uma tarefa:** conferir o contexto e a instrução, detalhar se quiser, gerar quando decidir.

```text
┌─────────────────────────────────────┐
│ ←      Preparar bloco 2          ⚙ │
├─────────────────────────────────────┤
│ Bloco 2 de 3 · continuação           │
│ ┌──────────────┐ ┌────────────────┐ │
│ │   imagem     │ │  frame REAL    │ │
│ │   original   │ │  do bloco 1    │ │
│ └──────────────┘ └────────────────┘ │
│ Identidade       Onde terminou      │
│ [ Ampliar ]      [ Ampliar ]         │
│                                     │
│ Salto; vestido vermelho; de costas.  │
│ [ Ver antes e depois ▾ ]            │
│                                     │
│ Instrução que será enviada           │
│ Origem: roteiro                      │
│ ┌─────────────────────────────────┐ │
│ │ Texto já preenchido e editável. │ │
│ └─────────────────────────────────┘ │
│ [ Detalhar este bloco com Grok ]     │
│                                     │
│ 8 s solicitados · 192 frames · 8 s   │
│ Seed: 2026101205                     │
│ [ Ajustar este bloco ]              │
│                                     │
│ [ Gerar bloco ]                     │
│ Envia uma nova tentativa para o PC. │
└─────────────────────────────────────┘
```

- A primeira entrada já preenche a instrução-base: não exigir `Usar instrução do roteiro` para copiar algo que já foi adotado.
- Bloco1 tem só identidade e **“Primeiro bloco · sem vídeo anterior.”** N>1 usa tentativa aceita e publicada doN−1. As duas figuras continuam visíveis no modo proposta também.
- Antes/depois expandido: **Intenção dos blocos aceitos / Este bloco / Próximo bloco planejado**. Não chamar texto de “o que realmente aconteceu”; o frame é a prova visual atual.
- Botão de detalhar consulta só este trecho com referência+frame/contexto/duração; não altera seu sistema custom. Abrir a bancada não chama Grok.
- Gerar usa exatamente o campo indicado como instrução escolhida; manual/Grok/edição são opções, não exigência de outra navegação.

### Estado de proposta Grok dentro da mesma bancada

```text
│ Proposta do Grok · ainda não usada   │
│ [ Texto recebido, editável.       ] │
│ [ Usar esta proposta ]              │
│ [ Manter minha instrução ]          │
│ Confira antes de gerar.              │
```

- Editor mostra o candidato sem sobrescrever o texto escolhido anterior. `Usar esta proposta` copia/adota e retorna ao editor **Instrução que será enviada**, origemGrok. `Manter minha instrução` retorna ao texto anterior.
- Enquanto o candidato está aberto, não mostrar Gerar como se fosse gerar o texto recebido: **primeiro escolher um dos dois caminhos**. Adotar proposta não gera.
- Se o usuário mudou o rascunho durante a chamada, a resposta é marcada anterior; adoção explícita e contexto visível. Submissão posterior não pode ter seu snapshot reescrito pela resposta.
- Pending: **“Detalhando este bloco…”** Erro: **“Não foi possível detalhar. Sua instrução foi mantida.”** Não bloquear o caminho manual por erro isolado do editor.
- Se o plano/vizinho mudou: **“O plano mudou depois deste detalhamento. Confira a instrução.”** +`Usar esta instrução mesmo assim` / `Voltar ao texto do roteiro`. Confirmação explicita intenção, não limpa incerteza de pedido.
- Frame indisponível: **“Não foi possível mostrar o último frame.”** +`Reler frame`; Grok com duas imagens indisponível, manual nativo continua conforme contrato existente, sem fallback silencioso.
- Antecessor inválido: **“Aceite o bloco anterior antes de preparar esta continuação.”** +`Abrir bloco anterior`. Não trocar o pai.
- Retry entra aqui já preenchido com **prompt FINAL enviado**, referência/seed/duração/pai original e aviso **“Nova tentativa; a anterior continua no histórico.”** Não recomputar do macro.

## T04 · Pedido no PC — tela atual contextualizada

```text
┌─────────────────────────────────────┐
│ ←      Bloco 2 no PC              ⚙ │
├─────────────────────────────────────┤
│ Dança: do preto ao vermelho          │
│ Gerando bloco 2                      │
│ Aguardando o resultado do PC.        │
│                                     │
│ [ Ver instrução enviada ▾ ]         │
│ [ Dados desta tentativa ▾ ]         │
│ [ Voltar ao roteiro ]               │
│ Voltar não cancela nem reenvia.      │
└─────────────────────────────────────┘
```

- Enviando: **“Enviando pedido ao PC…”**;202: **“Pedido recebido. Aguardando execução.”**; running: **“Gerando bloco N.”** Sem falso percentual.
- Ready: `Revisar bloco`. Incerto com Run ID: **“Resultado ainda não confirmado.”** +`Consultar pedido`. Sem ID: **“Não foi possível confirmar se o pedido entrou.”** +`Consultar envio`.
- Consultar reconcilia a intenção durável/vínculo, não envia outroPOST. Um link faltando no browser não prova que o job não existiu.
- Nenhuma geração concorrente/retry enquanto sua intenção permanece incerta. Consultar/editar planos futuros não limpa flags.

## T05 · Revisar bloco — operação existente

```text
┌─────────────────────────────────────┐
│ ←      Revisar bloco 2            ⚙ │
├─────────────────────────────────────┤
│ Bloco 2 de 3 · pronto para revisão   │
│ ┌─────────────────────────────────┐ │
│ │ Vídeo real · controles nativos  │ │
│ └─────────────────────────────────┘ │
│ Solicitado 8 s · verificado 8,000 s  │
│ [ Ver instrução enviada ▾ ]         │
│ [ Ver tentativas deste bloco ▾ ]    │
│                                     │
│ [ Aceitar bloco ]                   │
│ [ Recusar tentativa ]               │
│ Aceitar não gera o próximo.         │
└─────────────────────────────────────┘
```

Depois de aceitar: **“Bloco 2 aceito.”** +`Preparar bloco 3` / `Voltar ao roteiro`. Permanecer nesta tela; não trocar automaticamente para outro editor.

Depois de recusar/interrupção confirmada: **“O bloco 2 ainda precisa de uma tentativa aceita.”** +`Preparar outra tentativa` / `Voltar ao roteiro`. Retry →T03 diretamente, sem novo roteiro/Grok.

Sem vídeo: mostrar erro/estado/prompt, não player fictício. Failed conserva política atual, sem inventar retry novo. Resultados aceitos não editam o meio: operação de duas âncoras é outra evolução.

## T06 · Montagem — operação existente

```text
┌─────────────────────────────────────┐
│ ←      Montagem                  ⚙ │
├─────────────────────────────────────┤
│ Dança: do preto ao vermelho          │
│ 3 blocos aceitos · 24 s verificados  │
│ 1 · Dança de preto                  │
│ 2 · Salto; vermelho; de costas      │
│ 3 · Vira de frente                  │
│                                     │
│ [ Montar vídeo ]                    │
│ Não gera novos blocos.              │
└─────────────────────────────────────┘
```

Cadeia concreta das tentativas aceitas, não quaisquer trêsruns. Ao concluir, player/`Abrir vídeo`/`Baixar vídeo`. Parcial: **“Prévia: 2 de 3 blocos”**. Incerto/erro: `Reler montagem` do mesmo UUID; Voltar ao roteiro disponível. Não remonta ao aceitar/reload/SSE.

## T07 · Ajustes — escopo explícito, sem três editores abertos

```text
┌─────────────────────────────────────┐
│ ←      Ajustes                   ⚙ │
├─────────────────────────────────────┤
│ Este bloco · rascunho                │
│ Duração [ 8 ] s                      │
│ Seed [ 2026101205 ]                  │
│ Não altera tentativas enviadas.      │
│                                     │
│ [ Instruções do roteirista ▾ ]       │
│ [ Instruções do detalhamento ▾ ]     │
│                                     │
│ [ Concluir ajustes ]                │
└─────────────────────────────────────┘
```

- Seção local só para rascunho não enviado. Nas outras origens: **“Abra um bloco ainda não enviado para ajustar duração e seed.”**
- Abrir roteirista revela textarea/modelo fixo/`Salvar instruções do roteirista`; abrir detalhamento revela seu sistema atual/modelo/`Salvar instruções do detalhamento`. Não sobrescrever um pelo outro.
- Concluir/Back não salva sistemas implicitamente nem chama provider. Campos locais seguem o rascunho; seu salvamento deve ser confirmado antes de enviar a intenção do bloco.
- Sem controles de RAM/lifecycle/modelo nativo/sampler. Preservar scroll/foco e não abrir teclado sozinho.

## Revisão rápida

A proposta é: **ideia →lista preenchida/editável →bancada do próximo bloco →pedido/revisão →próximo**. Mudanças técnicas de segurança não precisam virar etapas extras para o usuário.

Mapeamento do desenho anterior: T02+T03+T04 viraram T02; T05+T06+T07 viraram T03; status/revisão/montagem/ajustes viraram T04–T07. Biblioteca/criação preservadas. Os IDs atuais são os desta v2.

**Aguardar revisão humana antes de implementar.** O desenho foi criticado e simplificado; não significa que a proposta já esteja validada em browser.
