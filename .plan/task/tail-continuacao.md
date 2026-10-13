# Tail — extensão de cauda de um roteiro

Estado: plano ativo, preparação da implementação. Pedido do dono em 2026-10-13.
Arquivo mantido diretamente, fora do harness. Interpolação permanece no backlog.

## Resultado esperado

Dentro de um roteiro, o usuário fornece uma frase indicando o que deve acontecer
a seguir e quantos blocos quer acrescentar. Grok planeja as intenções em JSON;
depois, no lote confirmado, melhora cada bloco com o resultado visual real do
anterior antes de gerar. Não exigir que o usuário escreva o prompt final ou clique
manualmente em “Melhorar” para cada bloco do lote.

Freestyle permanece legado, com seu caminho de conversão já existente.

## Regras de partida

1. Usar o fim confirmado da sequência aceita do roteiro, com vídeo materializado,
   identidade original comprovada e frame final derivado desse mesmo pai.
2. Se ainda não houver vídeo, completar a primeira geração I2V antes de continuar.
   A aceitação do pai continua obrigatória; no lote confirmado ela pode ser técnica.
3. Não avançar por cima de bloco pendente de revisão, geração ativa, resultado
   incerto ou tentativa falha/interrompida. Essas situações exigem revisão ou
   recuperação explícita, sem nova inferência automática.
4. Distinguir planos futuros ainda não enviados de uma cauda de vídeos já existente.
   O formulário deve deixar claro onde os novos blocos serão acrescentados; não
   sobrescrever rascunhos, candidatos ou blocos pendentes silenciosamente.

## Duas etapas do Grok

**Planejamento:** a frase vira proposta estruturada de novos blocos, com ações e
durações solicitadas válidas. Usar o contexto do roteiro e o estado de partida
comprovado. Os blocos futuros descrevem intenção, não frames observados ou uma
cronologia artística já garantida. A proposta é editável e sua adoção explícita
salva o plano, sem iniciar geração.

**Melhoria durante execução:** imediatamente antes de cada bloco, usar a identidade
original, o último frame real do pai aceito atual e as intenções dos blocos vizinhos.
Guardar a proposta literal efetivamente usada e o vínculo com esse pai. Depois da
geração e aceitação intermediária, a próxima melhoria recebe o novo frame real.

O lote não usa um único frame congelado para todos os blocos. Falha ou resultado
incerto do Grok interrompe a execução, sem fallback para o roteiro bruto.

## Implementação proposta

- Reaproveitar `roteiro.py`, a proposta JSON e `roteiro_batch.py`; manter uma única
  orquestração vertical, o dispatcher existente e o slot global. Não criar outra
  fila, framework de agentes ou motor de geração.
- Acrescentar o fluxo de cauda na UI do roteiro: frase, quantidade e preparação da
  proposta; edição/adoção; início explícito do lote com os consentimentos atuais.
- Salvar intenção, revisão de origem, ponto de extensão, IDs e referências em
  `.data`. Publicar os novos blocos atomicamente, sem sobrescrever o prefixo aceito
  ou alterar as tentativas anteriores. Proposta atrasada deve permanecer ligada
  ao contexto de origem e exigir reconciliação se o roteiro tiver mudado.
- Preservar prompts/configurações distintos de planejamento e melhoria, modelo
  fixo e limites atuais: 20000 tokens de saída para roteiro, 12000 para editor de
  bloco. Novos prompts de provider devem ser escritos em inglês.
- Manter V2V nativo com frame inicial real, identidade e vídeo/cauda do pai, sem
  alterar modelos, sampler, scheduler, passos, resolução, condicionamento, decode,
  áudio ou parâmetros de contexto. Duração segue a política existente por bloco:
  default8s, orçamento solicitado até10s,24fps e alinhamento5+17k.
- Reutilizar Parar, avisos, leitura SSE, recuperação por mesmo ID e loading genérico.
  Intermediários podem ser aceitos tecnicamente no lote confirmado; o último fica
  para revisão. Não iniciar montagem automaticamente.

## Verificação e conclusão

Testar com clientes falsos e fixtures CPU: extensão após pai aceito; raiz completada
antes de V2V; frame atualizado em cada melhoria; JSON inválido; plano/rascunho
concorrente; duração; cancelamento; falha de provider; queda/reinício sem replay;
histórico preservado e último bloco pronto para revisão. Testes e abertura da UI
não chamam provider/GPU.

Rodar checks adequados, Node, Ruff e diff. Registrar evidências e commit local.
Não considerar Tail concluído apenas por reapresentar o lote já existente: a nova
frase deve produzir uma extensão ligada ao fim correto do roteiro. Geração real,
se necessária, requer intenção explícita própria e não está iniciada por este plano.
