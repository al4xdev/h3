# Interpolação de sequência — geração entre duas âncoras

Estado: promovido para implementação em `.plan/task/edicao-entre-ancoras.md` por
autorização posterior do dono. Primeira entrega: um vídeo por edição, inserção
entre vizinhos ou nova versão de um bloco, com interface e Grok próprios.
Inserção de N blocos em lote permanece evolução futura.

## Objetivo

Inserir N novos blocos entre pontos de um roteiro, por exemplo dez blocos entre
uma cena de saída e uma cena de chegada. A cena anterior fornece o vídeo completo
e seu último frame; a cena de destino fornece uma âncora visual final explícita.
Imagens adicionais podem trazer contexto, com papéis identificados.

Nome do modo: **Interpolação de sequência**. Trata-se de construir uma ponte
narrativa e visual; o nome não promete interpolação matemática de pixels.

## Separação de Tail

Tail acrescenta blocos ao fim e parte do resultado anterior real, sem impor um
frame de chegada. Interpolação tem duas âncoras e precisa aproximar gradualmente
o estado visual de destino. Não adicionar essa segunda condição ao modo Tail.

Preservar as duas etapas: planejar os blocos e depois melhorar cada prompt com o
frame real recém-gerado. Um plano inicial com tempos definidos não prova que a
pose, roupa ou ação final estarão perto da âncora desejada.

## Investigação necessária antes da implementação

- Verificar no schema instalado e no grafo nativo como condicionar o início e
  o destino: imagem de identidade, vídeo de contexto, frame inicial e frame final
  desejado têm papéis diferentes. Não tratar `last_frame` do pai como frame de
  destino.
- Hoje `V2V_CONFIG` usa `initial_frame`, `identity` e `motion_video`. O frame
  inicial é derivado do fim do pai aceito. A integração de uma imagem final de
  destino não está comprovada por esse contrato.
- Definir a origem e propriedade de cada referência, a duração de cada bloco,
  o ponto de inserção e o destino da nova sequência. Preservar os runs e decisões
  anteriores; inserir não pode reescrever o histórico ou fazer continuação
  existente apontar silenciosamente para um novo pai.
- Definir como revisar a aproximação à âncora sem presumir sucesso artístico,
  fazer retries cegos ou alterar sampler/modelos/parâmetros para compensar.
- Separar prompts e configuração desse modo se suas instruções forem diferentes
  das de planejamento de roteiro e melhoria Tail.

## Critérios futuros

Uma nova sequência comprova ambos os contextos, mantém mídia/histórico originais,
gera somente após ação explícita e exibe o resultado para revisão. Testes fake/CPU
devem provar ordenação, referências, ownership, cancelamento e ausência de replay.
Uma eventual validação real precisa de intenção própria e não é autorizada por
este registro de backlog.
