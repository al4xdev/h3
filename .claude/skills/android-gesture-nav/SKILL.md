---
name: android-gesture-nav
description: Reproduzir em outro app Android (Kotlin + Jetpack Compose) a navegação do H3 Studio — tela cheia sem botão Voltar, arrasto interativo estilo iOS para voltar E avançar, integrado ao gesto de voltar do sistema (voltar preditivo), com estado de cada tela preservado. Use quando pedirem "app com a navegação/fluidez do H3", "voltar por gesto estilo iPhone", "swipe back/forward no Compose" ou para corrigir conflitos de gesto com slider, player ou campo de texto.
---

# Navegação por gestos estilo iOS (Compose) — receita do H3 Studio

O código de referência está neste repositório. **Copie o padrão, não as telas do H3.**
Todos os caminhos abaixo são relativos a `mobile_app/app/src/main/java/com/al4xdev/h3/`.

| Arquivo | O que copiar |
|---|---|
| `ui/gestures/FullscreenWorkspace.kt` | o container: duas camadas, arrasto, mola, voltar preditivo, bloqueio de toques durante a animação |
| `ui/gestures/WorkspaceGesturePolicy.kt` | regras puras (testáveis): faixa de início, eixo, decisão ao soltar, exclusões |
| `ui/Nav.kt` | `NavStack` com pilha de voltar **e** de avançar, serializada em texto |
| `ui/MainActivity.kt` | `rememberSaveableStateHolder` por tela + ligação do container |
| `ui/components/Motion.kt` | `pressScale` (aperto 0.97) e `appearOnce` (entrada de itens) |
| `ui/components/Tiles.kt` → `reducedMotion()` | respeitar "remover animações" do Android |
| `app/src/test/.../ui/NavStackTest.kt`, `ui/gestures/GesturePolicyTest.kt` | testes JVM das regras |

Requisitos: `minSdk 34`, `androidx.activity:activity-compose` ≥ 1.8 (`PredictiveBackHandler`),
e no `AndroidManifest.xml`, na tag `<application>`: `android:enableOnBackInvokedCallback="true"`.

## Como funciona (o modelo mental)

1. **Uma pilha de voltar e uma de avançar** (`NavStack`).
   - `push(tela)` limpa a de avançar, **exceto** se a tela é exatamente a próxima de avançar.
   - `pop()` move o topo para a pilha de avançar. `goForward()` faz o inverso.
   - As duas pilhas são serializadas como texto curto (`"lib|rot:<uuid>|blk:<uuid>:<uuid>"`)
     num `SavedStateHandle` do ViewModel, para sobreviver à morte do processo.
2. **Cada tela tem seu estado salvo** com `rememberSaveableStateHolder()`, usando como chave a
   tela codificada. Estado só é descartado quando a tela sai das DUAS pilhas (`liveKeys()`).
   Por isso voltar e avançar devolvem a rolagem, o texto digitado e a posição do vídeo.
3. **O container desenha duas camadas**: `under` (tela de baixo) e `over` (a que se move).
   Uma única variável `t` em [0,1] controla tudo:
   - `over.translationX = t * largura` (segue o dedo 1:1);
   - `under.translationX = -0.30 * largura * (1 - t)` (paralaxe);
   - véu preto sobre `under` com `alpha = 0.25 * (1 - t)`;
   - sombra de 24 dp na borda esquerda de `over`.
   Voltar anima `t` de 0 → 1; avançar, de 1 → 0 (a tela nova entra pela direita).
4. **A mesma tela mantém a composição ao trocar de camada**: renderize as duas camadas no
   mesmo ponto com `key(chaveDaTela) { ... }`. Sem isso, a tela é recriada no fim do gesto e "pisca".
5. **Três origens, mesma geometria**:
   - arrasto do app (faixa esquerda = voltar, faixa direita = avançar);
   - gesto do sistema via `PredictiveBackHandler` (usa `BackEventCompat.swipeEdge` e `progress`);
   - toque em botão/push (animação de 350 ms, easing `CubicBezierEasing(0.05f, 0.7f, 0.1f, 1f)`).

## Números que dão a sensação (não invente outros)

| Parâmetro | Valor |
|---|---|
| Faixa de início do arrasto | 45% da largura (esquerda para voltar, direita para avançar) |
| Reconhecer horizontal | passou do `touchSlop` E `dx ≥ 1.25 × |dy|`; se vertical, desiste (deixa a lista rolar) |
| Completa ao soltar | velocidade ≥ 500 dp/s com dx ≥ 16 dp; OU arrastou ≥ 40% da largura |
| Cancela ao soltar | velocidade ≤ −300 dp/s (lançou de volta) |
| Mola de assentamento | `spring(dampingRatio = 1f, stiffness = Spring.StiffnessMedium)` com a velocidade do dedo |
| Paralaxe / véu | 30% / alpha 0.25 |
| Push/pop por toque | 350 ms, emphasized decelerate |
| Aperto em cards | escala 0.97, `spring(0.6f, StiffnessMedium)`, só no desenho (área de toque não encolhe) |
| Entrada de itens | fade + subir 12 dp em 240 ms, uma vez por item |

## Receita passo a passo para um app novo

1. Copie `WorkspaceGesturePolicy.kt` e `FullscreenWorkspace.kt` sem mudar a lógica.
   O container é genérico (`FullscreenWorkspace<T>`): recebe `stack`, `nextForward`, `keyOf`,
   `onBack`, `onForward` e o conteúdo de cada tela.
2. Crie o seu `sealed interface Screen` e um `NavStack` igual ao de `ui/Nav.kt`
   (troque só os tipos de tela e o `encode`/`decode`).
3. No ViewModel: guarde o `NavStack` em estado observável e salve `Nav.encode(back)` e
   `Nav.encode(forward)` no `SavedStateHandle` a cada mudança. `back()` = `pop()`, `forward()` = `goForward()`.
4. Na raiz (como `H3Root` em `MainActivity.kt`):
   - `val holder = rememberSaveableStateHolder()`;
   - `FullscreenWorkspace(...) { tela -> holder.SaveableStateProvider(Nav.key(tela)) { Conteudo(tela) } }`;
   - um `LaunchedEffect(liveKeys)` que chama `holder.removeState` para chaves que saíram das duas pilhas.
5. Manifesto: `enableOnBackInvokedCallback="true"`. **Não** use `BackHandler` comum junto: o
   `PredictiveBackHandler` do container já trata o voltar do sistema e o botão de 3 teclas.
6. Em todo controle que tem arrasto horizontal próprio, aplique `Modifier.noSwipeBack()`:
   - `Slider`;
   - a barra de busca / linha de controles do player (só a faixa inferior de ~88 dp, não o vídeo inteiro);
   - campos de texto **só enquanto focados**: `.onFocusChanged { focused = it.isFocused }.noSwipeBack { focused }`;
   - alça de rolagem rápida e carrosséis horizontais.
7. Nenhuma tela tem botão Voltar. O topo tem só título (e ícone de ajustes, se houver).
8. Respeite `reducedMotion()`: sem paralaxe e transições instantâneas, mas o gesto continua funcionando.

## Erros que já aconteceram — não repita

- **Fundo preto atrás da tela arrastada**: a versão inicial só transladava a tela de cima.
  Tem que desenhar a tela anterior REAL por baixo (camada `under`).
- **Avançar pela borda direita voltava**: no Android com navegação por gestos, as DUAS bordas são
  "voltar" do sistema e o sistema captura o toque antes do app. A solução é o
  `PredictiveBackHandler` + `swipeEdge == EDGE_RIGHT` → avançar (se houver para onde); caso contrário, voltar.
- **Gesto não funcionava sobre campos de texto e sobre o vídeo**: excluir campos sempre e o vídeo
  inteiro deixou telas de formulário sem como voltar. Exclua só controles com arrasto real e
  campos focados. Leia os toques no `PointerEventPass.Initial` (antes dos filhos), senão uma
  superfície de vídeo que consome tudo bloqueia o gesto.
- **Voltar duas vezes num deslize rápido**: enquanto algo anima (`busy`), engula os toques com
  uma camada por cima e não aceite novo gesto até assentar.
- **Mudar a pilha durante a composição** (ex.: `removeAt` dentro de um `when`) causa telas que
  somem sozinhas. Navegação só em callbacks/efeitos.
- **Criar o player (ExoPlayer) durante a composição** vaza recursos. Crie em `DisposableEffect`.
- **Limitação conhecida**: na tela raiz, se existe pilha de avançar, o voltar pela borda esquerda
  não sai do app. Se incomodar, na raiz trate o voltar como "sair" e limpe a pilha de avançar.

## Como verificar

1. Testes JVM das regras (copie e adapte `NavStackTest.kt` e `GesturePolicyTest.kt`):
   push limpa avançar; pop/goForward simétricos; dx/velocidade decidem completar/cancelar;
   arrasto vertical não vira gesto; toque em área excluída não inicia gesto.
2. No emulador dentro do Docker deste repo (`mobile_app/docker/`, ver `box.sh`):
   ```bash
   zdocker exec h3-android box build && zdocker exec h3-android box install
   zdocker exec h3-android box swipe 20 1200 900 1200 250    # voltar pela borda
   zdocker exec h3-android box swipe 850 1500 100 1500 300   # avançar pela faixa direita
   zdocker exec h3-android box screenshot depois-do-gesto
   ```
   Confira: a tela anterior aparece por baixo, rolagem e textos voltam iguais, slider e
   barra do player não disparam o gesto.
3. Fluidez real só se avalia no celular físico; o emulador desenha em poucos quadros por segundo.
