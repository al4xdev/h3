# H3 · Bancada de filme

## Entrega independente (task 15, revisão 1)

Assets HTML/CSS/JavaScript sem framework, build, CDN, fontes remotas ou dependências de frontend. A bancada grafite coloca o vídeo em retrato no centro; cobre indica seleção e ações. A régua numerada representa a **cadeia ancestral real**, não a ordem da biblioteca. Fontes locais: títulos condensados, corpo system-ui, dados monoespaçados. No celular, vídeo e decisões vêm antes do formulário e da biblioteca.

Esta entrega **não integra a API nem conclui a task 15**. O agente principal é responsável pela migração `.data`, integração HTTP, empacotamento dos assets, documentação raiz e validação final com os vídeos reais. Nenhum arquivo de backend foi alterado aqui.

## Mount/contrato para integração

Servir same-origin, sem expor a árvore do projeto:

| Caminho | Asset/contrato |
| --- | --- |
| `GET /` | `src/h3_backend/web/index.html` |
| `GET /ui/app.css` | `src/h3_backend/web/app.css` (`text/css`) |
| `GET /ui/app.js` | `src/h3_backend/web/app.js` (`text/javascript`, ES module) |
| `GET /app/config` | `{default_prompt, continuation_prompt, reference_image: "dance_reference.png", duration_seconds: 2.3, workflow_output_profile}` |
| `GET /runs?limit=50&offset=0` | `{items, total, limit, offset}` |

Cada item da coleção: `{id, state, prompt, seed, duration_seconds, created_at, updated_at, parent_id, video_url}`. Ordenação recente e validação de manifests pertencem ao backend. Paginação: 50 itens, offset não negativo; a UI não faz discovery fora dessa coleção. `video_url` deve ser `/runs/{id}/video` somente quando o arquivo próprio estiver publicado em estado `ready_for_review`, `accepted` ou `rejected`; outros estados recebem `null`.

Rotas existentes, preservadas:

- `GET /runs/{id}`: Run completo, inclusive `output.path`, `error`, seed, prompt e timestamps. O caminho interno é apenas evidência de publicação, nunca URL/arquivo arbitrário no navegador.
- `GET /runs/{id}/sequence`: `{schema_version:1, root_id, end_run_id, blocks:[{index,id,parent_id,state,accepted,duration_seconds,duration_source,video_url}]}`. A UI mantém a ordem `blocks` (origem → seleção), sem ordenar IDs ou escolher irmãos. As fronteiras exibidas usam as durações retornadas. A régua não produz montagem nem modifica frames.
- `GET /runs/{id}/video`: um único player HTML5 com controls, playsinline, preload metadata, object-fit contain, sem autoplay. Sem thumbnails ou dezenas de players. Estado terminal **sozinho** não basta: a UI exige `output.path` no detalhe e URL própria explícita na coleção ou cadeia. Ausência de arquivo, falha ou interrupção não vira vídeo pronto.
- `POST /runs/{id}/accept` e `/reject`: somente `ready_for_review`; POST sem body, resposta Run. Aceitar não é certificação automática artística. Rejeitar mantém a evidência histórica.
- `POST /runs/i2v`: `{seed, prompt, duration_seconds:2.3, image:"dance_reference.png"}`. Única referência existente autorizada nesta UI; não há upload/file browser.
- `POST /runs/{accepted_parent_id}/v2v`: `{seed, prompt, duration_seconds:2.3, reference_tail_seconds:3, include_audio:true}`. Pai e campos são capturados no envio, sem incremento automático de seed ou knobs privados.

Seed: somente dígitos, inteiro seguro de `0` a `9007199254740991`; não aceita sinal, espaços, expoente ou decimal. Prompt não vazio/whitespace, até 12000 caracteres; conteúdo é preservado, sem trim do payload. Duração é somente leitura; resolução, sampler e demais parâmetros não são controles da UI.

Recomenda-se CSP same-origin (`default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; media-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`), Content-Type correto e inclusão explícita dos três assets no wheel. Não há scripts/styles inline no HTML.

## Admissão e recuperação sem replay

1. Apenas submit explícito envia POST. Formulário e decisões ficam bloqueados durante admissão/wait; um guard no handler e outro no cliente impedem duplo envio.
2. Geração exige HTTP **202** e ID real da resposta. Mostra que admissão não significa conclusão.
3. Um único `GET /runs/{own_id}?wait=true`, usando AbortController. Sem polling, intervalos, inferência automática ou retry de API. Depois do resultado há leitura única da coleção e cadeia; não há segundo GET wait implícito.
4. Falha de rede, resposta inesperada, ID ausente, 5xx ou falha do wait tornam o resultado **incerto**. O botão Gerar permanece desabilitado nessa sessão; a UI não oferece "Gerar novamente" como recuperação. Atualizar faz somente GETs para reconciliação manual dos IDs. Não contorne o bloqueio recarregando para repetir a mesma intenção sem verificar a admissão no backend.
5. 400/404/409 explícitos são erros sem repetição automática. O usuário pode corrigir a instrução ou aguardar o slot livre. Falha de leitura posterior a um resultado confirmado não é confundida com falha de admissão.
6. Fechar a página aborta apenas a espera local, **não cancela** o job Comfy. Nenhum endpoint de cancelamento ou controle global é usado.

Estado transitório existe somente em memória. Não há localStorage/sessionStorage de negócio; JSON/backend permanece a autoridade durável. Prompts, detalhes HTTP e erros usam textContent/createElement, nunca innerHTML. Labels, foco visível, aria-live, skip link, estados textuais e reduced-motion estão presentes.

## Testes CPU e navegador totalmente fake

Comandos fish, no root do projeto:

```fish
node --check src/h3_backend/web/app.js
node --test tests/frontend_ui.test.mjs
node tests/frontend_browser_mock.mjs
```

O browser harness usa **Playwright já instalado**, sem instalar dependências ou iniciar servidor. Todas as requests de `http://h3.mock.invalid` são interceptadas/fulfill; qualquer origem diferente é abortada e falha o teste. **Não apontar para 8010, 8001 ou Comfy.** POSTs são somente fixtures em memória. Se Playwright/Chromium não estiver instalado, executar os contratos Node e comunicar a validação browser pendente ao responsável; não alterar configuração global.

Opcionalmente, fornecer um vídeo próprio existente, somente para leitura e reprodução fake:

```fish
env H3_UI_TEST_CLIP=runs/02cf408f-c985-47a2-887d-731569d7827a/chunk.mp4 node tests/frontend_browser_mock.mjs
```

Esse clip histórico pré-existente foi usado na validação desta entrega. Seu buffer foi servido exclusivamente pela interceptação fake. O teste verifica dimensões reais 480×864, playback explícito/pausa (não autoplay), contain, nenhuma exceção JS, nenhum request externo, keyboard/galeria read-only, cadeia `z-root → a-child` apesar dos IDs, estados sem arquivo, seeds inválidos, aceita/rejeita, continuação com pai e payload exatos, novo bloco, duplo-submit, um wait por ID, 409, admissão ambígua, config/list indisponível e recuperação read-only. Não valida qualidade perceptual da geração.

Evidência local/gitignored em `.dumps/tests/ui/`:

- `desktop-1440.png`, `mobile-390.png`, `mobile-320.png`;
- `failed-evidence.png`, `empty.png`, `api-error.png`, `admission-uncertain.png`;
- `mock-requests.json`: trace completo de métodos, paths e payloads fake, exceções e violações de origem.

## Pendências do responsável pela integração

Implementar coleção/config e mount estreito após a migração segura; testar coleção com manifests reais, MIME/CSP, compatibilidade do Run/sequence, GET de vídeo/range e wheel contendo os assets. Validar playback real em API própria somente após os gates de benchmark/migração. Nenhum benchmark, inferência, alteração de recursos/dados ou controle de GPU foi executado pelos testes de frontend.
