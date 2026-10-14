# Edição entre âncoras e versões de blocos

Estado: concluído. Implementação autorizada pelo dono nesta sessão.

## Contrato

- Tela própria de edição e rota Grok própria, com system prompt separado em inglês.
- Refazer o bloco 2 entre 1 e 3 cria uma versão alternativa do bloco 2.
- Inserir antes/depois de um bloco cria um bloco novo entre os vizinhos escolhidos.
- Os vídeos antigos e seus pais permanecem imutáveis. Seleção editorial pertence
  ao roteiro, separada da ancestralidade de geração. Versões aceitas são selecionáveis.
- Primeira entrega gera um bloco por edição. Exige duas âncoras aceitas; extensão
  sem vizinho à direita usa Tail. Inserção antes da primeira raiz não possui vídeo pai.
- Grok recebe identidade, último frame real do anterior, primeiro frame real do
  seguinte e ambos os prompts efetivamente enviados, marcados como histórico.
  O vídeo anterior é contexto nativo do motor de vídeo, não upload de vídeo ao Grok.
- Proposta editável, geração, revisão e aplicação à sequência são ações explícitas.
  UUIDs e estados incertos ficam em disco; GET/startup/SSE nunca reenviam.
- A operação nativa bridge deriva V2V e adiciona somente a âncora final permitida
  via MiniMaxH3AddGuide(frame_idx=-1), comprovada no código instalado. Preservar
  modelos/parâmetros, grafos golden e comportamento I2V/V2V existentes.
- Montagem editorial precisa seguir os vídeos selecionados no roteiro, mantendo
  os pais originais em sua procedência, sem exigir que a nova ordem seja genealógica.

## Validação

Testes fake/CPU de âncoras, prompts, bloqueios, versões, posicionamento, publicação,
montagem e cancelamento; frontend com navegação/rascunhos sem geração incidental.
Nenhuma inferência real/provider/GPU nem reinício do servidor de produção.

Resultados: suíte Python completa com 1028 testes aprovados; 29 testes focados
após ajustes finais de seleção/Tail e 4 verificações adicionais do histórico.
Frontend: 299 testes aprovados. Ruff e git diff --check sem erros.
Fluxo desktop em navegador com API mockada validado com movimento normal e
reduzido, sem POST no reload e com rascunho preservado em Ajustes/Voltar.
Evidência local em `.dumps/tests/edit-ui/` e `.dumps/tasks/edit-full-python.txt`.
Não houve validação de geração GPU real nem de fluidez em dispositivo mobile.
Servidor estável bf7305a continua isolado para preservar o lote do dono.

## Trabalho paralelo

Operação nativa bridge e guards; tela de edição; encerramento HTTP/SSE; operação
vertical de edição/Grok/seleção editorial e integração pela sessão principal.
