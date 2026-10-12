# H3 — Backend API fiel ao workflow, validação de dança e continuação antes de otimizar

## 1. Objetivo e decisões do dono

Organizar `/home/alex/git/my/h3`, iniciar Git e implementar primeiro um backend API em Python, sem frontend. Reproduzir o workflow que já funcionou, gerar um vídeo curto de dança com a imagem indicada, aguardar aprovação humana e então usar o trecho final aprovado como referência para a próxima geração. Só depois de validar essa cadeia avaliar remoção de pós-processamento do ComfyUI.

Diretrizes:
- Fidelidade antes de otimização: não reduzir arbitrariamente a quantidade de nós nem substituir condicionamentos/modelos.
- Não alterar o workflow original em `/home/alex/comfyui/user/default/workflows/`.
- Sem frontend de produto nesta etapa. Uma exportação técnica via navegador do ComfyUI pode ser necessária para resolver subgraphs e links virtuais; o backend de execução deve funcionar sem navegador.
- Prompts e referências dos testes serão SFW. A dança será natural, não sexualizada e manterá a roupa da referência.
- Gerar apenas um trecho por vez; nenhum loop autônomo sem aceitação do dono.
- Não alterar inicialização/perfil de memória do ComfyUI, reiniciar seu processo ou limpar sua fila/cache sem autorização específica.

## 2. Evidências já verificadas — substituem as premissas do Markdown antigo

- Workflow real: `minimaxH3SEEDHUNTERLatent_v251.json`, com 158 nós, 239 links e seis definições de subgraph.
- SHA256 original preservado: `14e09cd1a3873966ecfa52ff73878f8642a5236155d1b509adab60e4148072fd`.
- Cópia sanitizada existente: `workflow_h3_seedhunter_sfw.json`. Preserva grafo/modos/modelos, mas loader vazio com continuação ativa não é configuração pronta para executar.
- Cópia normal já testada: `workflow_h3_normal_sfw_validated.json`, usando imagem SFW de carrinho. ComfyUI local: `http://127.0.0.1:8001`, versão 0.37.0, frontend 1.53.6, RTX 5060 Ti.
- Teste concluído: prompt ID `277b40c4-9001-418d-9f1a-38a444488ec8`, 56 frames a 24 fps, 480×864, áudio AAC estéreo 32000 Hz, vídeo de 2.333333 s, aproximadamente 131.57 s de execução incluindo preparação.
- Telemetria anterior a cada cinco segundos: menor RAM disponível do host 3.32 GiB, maior total menos disponível 27.81 GiB de 31.13 GiB físicos, VRAM ocupada até 15.26 GiB e swap zero nas amostras. São números globais/amostrados, não RSS exclusivo do backend nem picos exatos. Não houve OOM reportado.
- Houve dois decodes de vídeo (176/259), dois de áudio (177/258) e duas codificações (18/34). São candidatos futuros; preservá-los no baseline.
- RIFE165, upscaler243 e passe adicional135 estão bypassados. Não atribuir a eles o consumo atual.
- `Anything Everywhere107` fornece VAE/sampler/sigmas por links virtuais. Export simples por `graphToPrompt()` deixou links ausentes; a exportação validada usou `app.ue_modified_prompt()`.
- Modos: 2 é muted; 4 é bypass. Switch rgthree não é lazy nessa implementação.

### Duração e modos

O nó raiz22 (`Video Settings`) expõe sampler, scheduler, passos, MP, proporção e duração em segundos; a duração passa pelos internos23/24. A fórmula arredonda para `17k+5` frames. Oito segundos produzem192 frames; três segundos produzem73 frames, ou3.041667 s. Para testes estritamente até três segundos, usar56 frames/2.333333 s, controlados por entrada2.3 s, mantendo a fórmula original.

Referência normal pelo nó5 não equivale ao modo seamless com guide296. O snapshot contém ambos os caminhos ativos; configurar explicitamente o modo normal desejado pelo dono e registrar essa diferença, sem otimizar outros ramos. No modo normal, não descartar automaticamente o início da saída como overlap: primeiro verificar se houve repetição.

No seamless, overlap297 está em22 frames, não dois segundos. O blend389 é50% constante entre pares, não `xfade`; o áudio326 usa concatenação, não `acrossfade`. Esses comportamentos não devem ser trocados silenciosamente.

## 3. Organização e migração documental

1. Ler integralmente os Markdown existentes antes de removê-los; conferir o estado atual dos arquivos e ausência de Git. `git rev-parse` já indicou que a pasta não pertence a um repositório.
2. Este artefato gerenciado passa a ser o plano principal. Migrar nele evidências úteis do README.md, PLAN.md e ANALYSIS.md; não manter a arquitetura especulativa como especificação vigente.
3. Remover recuperavelmente esses três Markdown antigos somente após aprovação deste plano, usando `trash`, com os caminhos absolutos conferidos. Não editar mirrors/registry de `.plan` nem remover os artefatos gerenciados.
4. Criar organização simples: `workflows/` para baseline sanitizado e configuração API; `assets/` para referências SFW; `src/` e `tests/` quando começar implementação; `runs/` para vídeos/manifestos; `.dumps/` para scripts/evidências temporárias.
5. Mover os workflows existentes apenas depois de ler seus conteúdos completos por inspeção estruturada e verificar integridade. Não atualizar os arquivos do ComfyUI original.
6. Ignorar `.dumps/`, `.venv/`, caches Python e `runs/` no Git. Manter referências SFW pequenas e workflows versionáveis; não versionar dados NSFW, vídeos/cache de execução ou credenciais.
7. Executar `git init` em `/home/alex/git/my/h3` e verificar o root/status. Não criar remoto nem fazer push. Não criar commit automaticamente nesta etapa.

## 4. Referência de dança e teste anatômico

Fonte localizada e inspecionada: `/home/alex/Downloads/Qwen_image_2.1_00119.png`, 1024×1024, SHA256 `4e91fe89eb68a42bcb925a4eef727b7ed39f2ff8f646b2ae2e3e479c45e6fe61`. A imagem mostra uma mulher com vestido preto em frente a uma parede geométrica; é apropriada para uma dança não sexualizada. O conteúdo real é WebP apesar da extensão.

- Copiar a referência para `assets/` sem modificar ou mover a origem; verificar hash.
- Criar uma cópia PNG real com nome inequívoco para upload, preservando orientação/cor/resolução. Inspecionar metadados antes de carregar/exportar; não transportar prompts ou workflows embutidos desnecessários para o teste.
- Prompt de teste em inglês, com `<Picture 1>`: dança suave e coordenada, passos laterais pequenos, movimentos naturais de braços/mãos, preservação de rosto/cabelo/roupa, câmera estável, sem nudez ou erotização. Documentar o prompt exato e seed.
- A foto corta pernas/pés; avaliar bem rosto, mãos, braços e tronco, mas reconhecer que partes fora do enquadramento são inferidas. Não chamar um único clipe de prova completa de anatomia. Evitar giro rápido ou mudança de enquadramento agressiva no primeiro teste.
- Baseline: mesmos modelos/atenção/sampler/scheduler/passos/resolução efetiva já utilizados, mudando apenas referência, prompt, seed explícita, modo normal e duração curta. Mudança de proporção/enquadramento só em teste separado aprovado.

## 5. Execução fiel por API e saída dentro do projeto

### Exportação e contrato

- Exportar o grafo pela integração real do ComfyUI, resolvendo subgraphs e Anything Everywhere. Guardar JSON API com links explícitos e identificar campos parametrizáveis; não deduzir conexões pelo título/posição nem reconstruir sampler manualmente.
- Verificar `/object_info`, modelos selecionados, formatos e inputs obrigatórios antes de enfileirar. Nunca substituir checkpoint ausente por outro silenciosamente.
- Congelar baseline e comparar alterações permitidas: prompt, referências, seed, duração, modo escolhido e destino/nome da saída. Usar assinatura/hash para detectar mudanças inesperadas.

### Saída — preferência do dono

Primeiro investigar o saver existente `VHS_VideoCombine`: testar em fixture leve se permite gravar diretamente em um diretório permitido dentro de `h3/runs/<run_id>/`, sem redirecionar globalmente as saídas do ComfyUI e sem path traversal.

Se o saver não permitir o destino direto, usar fallback explícito: ao receber conclusão pelo WebSocket, resolver o output daquela execução no histórico e publicar o arquivo em `runs/` por cópia/rename atômico local. O dono deve saber qual mecanismo foi utilizado. Não afirmar que a API de `/prompt` fornece streaming dos bytes do vídeo.

Não criar poller para procurar arquivos. Conectar WebSocket antes de submeter, correlacionar `client_id`/`prompt_id`, tratar `execution_error`, `execution_interrupted` e conclusão. Consultar histórico pontualmente para resultados/reconexão, não em polling contínuo. Mensagem `executed` isolada de um nó não basta para declarar toda a execução concluída.

### Backend mínimo

Python com uv e `.venv/`; servidor API simples (preferencialmente FastAPI), cliente HTTP/WebSocket e subprocessos FFmpeg. Não carregar Torch, modelos ou batches de frames no orquestrador.

Contrato sugerido:
- `POST /runs`: iniciar um único primeiro trecho ou continuação, com referências, prompt, seed e parâmetros permitidos.
- `GET /runs/{id}`: estado, Comfy prompt ID, manifesto, métricas e caminhos relativos dos artefatos.
- `GET /runs/{id}/video`: baixar o clipe pronto.
- `POST /runs/{id}/accept`: aceitar um clipe concluído; nunca implica gerar o seguinte sozinho.
- `POST /runs/{id}/reject`: rejeitar sem avançar a cadeia; permitir refazer com outra seed.
- `POST /runs/{id}/continue`: gerar um próximo trecho somente se o pai foi aceito, com `reference_tail_seconds` de2 ou3 e áudio pareado opcional.

Estados persistidos e validados: `queued`, `running`, `ready_for_review`, `accepted`, `rejected`, `failed`, `interrupted`. Concorrência de inferência limitada a um job do backend; não interferir em jobs externos. Manifesto registra workflow hash, versão, seed, prompt, pai aceito, inputs, outputs e aprovação.

## 6. Cadeia com aprovação humana

1. Executar um teste curto de dança no baseline normal, salvar o clipe no projeto, verificar com ffprobe e apresentar ao dono. A execução inicial está autorizada somente após aprovação deste plano.
2. Avaliar anatomia visível, identidade, roupa, cenário, artefatos, áudio e estabilidade. A aprovação do plano não substitui a aprovação visual do clipe.
3. Aguardar resposta humana antes de usar esse resultado para continuar. Rejeição conserva o último pai aceito e não avança a cadeia.
4. Após aceite, extrair com FFmpeg apenas o tail2 ou3 s do clipe aprovado, normalizado a24 fps, preservando imagens fixas de identidade. Se o vídeo for menor que o tail solicitado, usar explicitamente sua duração disponível e registrá-la; não preencher tempo fictício. No primeiro teste de2.33 s, tail2 cabe; tail3 não cabe.
5. Colocar esse pequeno vídeo no loader como `<Video 1>`, com áudio pareado opcional, e gerar outro trecho curto pelo modo normal.
6. Comparar fim do pai/início do filho sem crossfade para não mascarar falhas. Não assumir continuação temporal perfeita só por haver referência.
7. Aguardar nova aprovação do dono. Manter chunks originais separados; produzir prévia acumulada por concatenação externa após verificar compatibilidade, sem truncamento arbitrário de overlap ou crossfade escondido. Registrar claramente se o crescimento ocorre por montagem externa, não pela saída interna do modo normal.

## 7. Métricas, segurança operacional e testes

- Medir tempo por etapa, RAM disponível/uso global, RSS e swap do processo ComfyUI, memória do orquestrador e VRAM disponível/uso global; distinguir backend, navegador e host. Registrar intervalo de amostragem e limitações.
- Instalar dependências do projeto com uv; não modificar o ambiente Python do ComfyUI.
- Guardas de duração/frame count, paths dentro de `runs/`, extensão real de mídia, espaço em disco e proteção contra sobrescrita. FFmpeg via lista de argumentos, sem shell concatenado.
- Não disparar teste se houver fila externa ocupada sem consultar o dono. Cancelamento e proteção de memória atuam somente sobre o prompt ID criado pelo backend; não limpar fila compartilhada.
- Testes unitários: estados/aceitação, pai rejeitado, duração/alinhamento, tail maior que vídeo, parametrização/diff de workflow, caminho proibido, persistência/retomada e mensagens WebSocket fora de ordem.
- Fixtures curtas de mídia para extração/concatenação; mocks para API/WS antes de testes GPU. Integração real: um primeiro clipe de dança, depois continuação apenas após aceite.

## 8. Otimização posterior — não executar junto com o baseline

Depois de o dono aprovar a reprodução e a continuação, registrar proposta separada de otimização e evidência de comparação:
- Preview/decode/export duplicados176/177/18 versus259/258/34.
- Montagem pós-decode388/392/389/391/317/368 e áudio321/326.
- Evitar carregar todo o vídeo acumulado no loader; manter apenas tail curto.
- Pré-processamento externo mantendo resize/crop/FPS/áudio equivalentes.

Não remover condicionamento5/296, sampler125 ou VAEs como se fossem edição. Não trocar blend constante por xfade nem RIFE por minterpolate sem decidir mudança de comportamento. Cada alteração terá comparação isolada e reversível; não prometer RAM <50 MB, costura instantânea ou reprodução idêntica sem medir.

## 9. Critérios de conclusão desta etapa

- Git iniciado e documentação antiga migrada/removida recuperavelmente; plano gerenciado preservado.
- Referência copiada com origem intacta, formato correto e prompt SFW.
- Baseline/API versionáveis com conexões explícitas e diff controlado.
- Backend inicia um trecho, recebe eventos sem poller contínuo e entrega arquivo/manifesta dentro do projeto.
- Teste de dança curto validado tecnicamente e apresentado ao dono; aceitação registrada antes da continuação.
- Continuação por vídeo curto demonstrada somente após aceite, com chunks individuais e eventual montagem claramente distinguida.
- Métricas e limites registrados; nenhum frontend e nenhuma otimização prematura do grafo.

## 10. Ordem de execução após aprovação

1. Organização, referência, migração dos Markdown e Git.
2. Congelar/exportar baseline API e validar destino da saída com fixture leve.
3. Implementar backend mínimo, persistência/estado e testes sem GPU.
4. Rodar um teste curto de dança e **parar para aprovação visual do dono**.
5. Após aceite, rodar uma continuação curta, analisar a transição e parar para novo aceite.
6. Encerrar baseline; discutir separadamente quais nós podem sair e como medir a melhoria.

Usar o objetivo persistido desta sessão para manter o trabalho focado no plano aprovado. Os checkpoints de aprovação visual são bloqueios deliberados de produto, não autorização para avançar automaticamente.
