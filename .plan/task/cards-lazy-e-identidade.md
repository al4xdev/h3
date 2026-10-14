# Cards progressivos e identidade do estúdio

Estado: concluído por pedido do dono.

- Adaptar a referência real do ha_app: cards próximos da rolagem, entrada suave
  e resposta elástica, preservando os controles nativos de vídeo e o gesto Voltar.
- Materializar o conteúdo dos blocos progressivamente, mantendo posição, rascunhos,
  foco e estado na navegação. Abrir, rolar e voltar não iniciam geração.
- Paleta própria azul-petróleo/turquesa: fundo #0b191e, superfície #132b33,
  destaque #75ddd0, texto #edf8f8, secundário #a5bbc0, erro #ffb7b0.
- Manter fontes, hierarquia e componentes atuais. Entrada dos cards é a assinatura
  de movimento; evitar deslocar mídia ou controles e respeitar reduced-motion.
- Testar listas longas, atualização de estado, navegação, requests e redução de
  movimento. Validar no navegador com mocks; produção permanece na versão estável.

## Evidência

- 305 testes frontend aprovados, incluindo lista de 200 cards, histórico de 80
  versões, fallback sem IntersectionObserver, preservação de rascunhos, foco,
  navegação entre roteiros e bloqueios de movimento.
- Corrigida restauração de scroll antecipada em ViewTransition: a posição é
  restaurada depois da pintura do destino, sem esperar o fim da animação.
- Navegador desktop mockado 1280×900, DPR 1, touch 0: 50 shells leves, 2 cards
  completos iniciais, nenhum histórico montado antecipadamente; 5 cards completos
  depois de saltar ao fim. Ajustes/Voltar preservou o mesmo DOM e scroll 18657px.
  Movimento normal e reduzido passaram, sem erros JS ou requests de mutação.
- Capturas inspecionadas em `.dumps/tests/lazy-ui/`; não é prova de fluidez em
  dispositivo físico. Nenhuma chamada real a Grok/GPU para esta validação.
- Contraste calculado: texto secundário/card 6.54:1; botão principal 8.99:1.
- Após reset do PC, servidor estável bf7305a reaberto pelo agente na porta 8888;
  nenhum pedido foi reenviado automaticamente.
