# H3 · Roteiro v2 — contrato implementado (plano41)

Conferido em `src/h3_backend/roteiro.py`, `web/app.js`, `api.py` e pipes nativos. Identificadores congelados informados pelo integrador: backend `ee18b5d`, frontend `b688`. Não são resultados de inferência.

## Endereços e autoridade

- Página HTML: `/roteiro?roteiro=<UUID>&block=<UUID>&intent=<UUID>`. `block`/`intent` só aparecem quando existem. `/` e `/index` continuam servindo a mesma shell.
- API JSON: `/roteiros`. Singular/plural evita colisão com HTML. Configuração anuncia `roteiro_enabled: true` em `/app/config`.
- Estado no PC: `.data/roteiros/<UUID>/plan.json`, `proposal-<UUID>.json` e marcador de correlação em `.data/roteiros/.locks/<intentUUID>.json`. Sistema macro: `.data/roteiros/editor.json`.
- UUIDs canônicos, arquivos regulares próprios, leitura limitada, locks locais e escrita atômica. HTTP é ponte; browser não é autoridade de histórico ou revisão.

## Documento e limites

```json
{
  "id":"UUID do roteiro","revision":1,"name":"Dança",
  "idea":"Intenção original",
  "reference":{"source_root":"assets","path":"dance_reference.png"},
  "reference_sha256":"SHA256 derivado pelo servidor","adopted":false,
  "blocks":[{"id":"UUID estável do item planejado","action":"Dança de preto.",
             "duration_seconds":8,"seed":2026101205,"prompt":"Dança de preto."}],
  "attempts":[]
}
```

`reference_sha256` e `attempts` são readonly. Chave planejada não é Run futuro. Limites operacionais, não garantias de modelo/memória:

| Campo/recurso | Limite efetivo |
| --- | --- |
| Blocos por plano/proposta | 50; count explícito de 1 a 50 |
| Listagem de roteiros | Até 1000 documentos; acima disso falha, sem paginação implícita |
| JSON de request/arquivo | 1 MiB; `plan.json` inclui todo o histórico; candidata inclui raw e blocos estruturados no mesmo orçamento |
| Texto bruto da proposta | 512 KiB em UTF-8; sem truncar |
| Nome | 256 caracteres; nome proposto não vazio |
| Ideia, ação, prompt | 12000 caracteres cada; não vazios/brancos |
| Sistema macro | 100000 caracteres; não vazio/branco |
| Seed | Inteiro estrito de 0 a 2^53−1, sem bool/string/coerção |
| Duração solicitada | (0,10], finita, até duas casas; default atual 8s pelas capabilities |
| Identidade do roteiro/editor | JPEG/PNG próprio, até 20 MiB e 16 milhões de pixels |

JSON rejeita chaves duplicadas, extras e números não finitos. Orçamentos agregados podem impedir uma combinação de campos individualmente válida. Não preencher campos ausentes da resposta do modelo nem clamp. Resolução, sampler, grafos, fórmula24fps/5+17k/Python half-even e tail3/audioTrue permanecem nativos; benchmark2,3s é explícito/histórico.

## Plano: criação e alteração

| Operação | Body/resultado |
| --- | --- |
| `GET /roteiros` | 200 `{items:[documentos completos],total}` |
| `POST /roteiros` | `{name?,idea,reference,blocks?,adopted?}` →201 documento; defaults nome `""`, blocos `[]`, adopted false |
| `GET /roteiros/{ident}` | 200 documento com tentativas reconciliadas |
| `PUT /roteiros/{ident}` | `{expected_revision,name,idea,reference,adopted,blocks}` →200 documento revision+1 |

PUT exige todos os campos editáveis, sem id/revision/attempts/reference_sha256. Adoção exige blocos válidos. Depois de qualquer intenção: identidade/ideia/adoção ficam congeladas, e o prefixo até a última posição enviada não pode ser alterado, removido ou reordenado. Só sufixo não enviado permanece editável. Conflito409 conserva edição local; não repetir save com outra revisão automaticamente.

Respostas JSON do router usam `Cache-Control: no-store`. Body acima de1MiB retorna413; JSON/DTO inválido,422. Handlers compartilhados da ponte retornam400 para ValueError,409 para conflito/slot/arquivo existente e404 para arquivo ausente. Esses códigos não substituem a consulta da própria intenção após erro de admissão.

## Proposta macro separada

`POST /roteiros/{ident}/proposal`, body `{expected_revision,count,duration_seconds?,seed}`. Duração omitida usa default nativo8s. Resposta200:

```json
{
  "id":"UUID da candidata","roteiro_id":"UUID do roteiro","source_revision":1,
  "source":{"name":"Nome na origem","idea":"Ideia na origem",
            "reference":{"source_root":"assets","path":"dance_reference.png"},
            "reference_sha256":"SHA256 na origem"},
  "name":"Título proposto",
  "blocks":[{"id":"nova chave planejada","action":"Texto da ação",
             "duration_seconds":8,"seed":2026101205,"prompt":"Instrução-base"}],
  "raw_text":"JSON literal recebido","stale":false
}
```

A candidata não altera blocos/revision do plano. Adoção é PUT explícito. `source_revision` e `source` vinculam o contexto original; mudança da revisão durante a chamada marca stale. Provider precisa retornar exatamente `{name,blocks:[{action,duration_seconds,prompt}]}`, count exato. Aplicação atribui chaves e seed, não o provider.

Antes da chamada explícita, salva reserva da candidata com state uncertain, request/source; não mantém lock durante await do provider. JSON de proposta inválido retorna422 com `{error:"invalid_proposal",detail,id,roteiro_id,source_revision,source,raw_text,stale}` e conserva texto limitado. Erros de OAuth/provider usam `{error,detail}` com status do adaptador. Não há replay automático, adoção de inválido ou recuperação pública da candidata por GET dedicado.

## Sistemas e detalhamento do bloco

- `GET /roteiros/editor` →200 `{system_prompt,model}`; ausente usa sistema macro próprio. GET não cria arquivo nem chama auth/provider.
- `PUT /roteiros/editor` aceita só `{system_prompt}` →200 mesma forma. Pin lido pelo editor público deve ser `grok-4.20-0309-non-reasoning`; diferente resulta409. Não enviar model.
- Sistema macro separado de `.data/grok/editor.json`; reutiliza `Grok.complete`/`PromptRequest`, sem editar sistema custom, OAuth ou grant.
- Detalhar bloco usa POST `/grok` existente, somente por clique. Prompt inclui macro, intenções dos aceitos/prompt enviado, trecho atual/duração/frames e próximo planejado; texto não é prova de resultado visual. Limite12000 do prompt inclui esse contexto, sistema é separado. Excesso informa erro, preserva instrução e caminho manual, sem truncar.
- Continuação envia identidade original e `continuation_parent_id` aceito real para obter o último frame real. Sem fallback silencioso de duas imagens para uma. Resposta tardia fica candidata vinculada ao rascunho/contexto; Usar proposta e Gerar continuam ações distintas.

## Intenção de geração

`POST /roteiros/{ident}/blocks/{key}/attempts/{intent_id}` exige:

```json
{"expected_revision":2,"prompt":"Texto literal escolhido","seed":2026101205,
 "duration_seconds":8,"parent_id":null}
```

Root usa null; continuação usa a tentativa aceita concreta do predecessor, mesma identidade/cadeia. Primeira geração exige prompt/seed/duração iguais ao bloco salvo: clique Gerar salva rascunho viaPUT, confirma revisão e só então envia intenção. Save inválido/conflitante interrompe antes doPOST.

Posição já enviada permanece congelada. Retry rejeitado/interrompido copia inicialmente Run.prompt FINAL literal, seed/duração/referência e pai original; ajuste explícito pode ficar no novo snapshot, sem PUT sobre bloco congelado. Nova tentativa exige nova revisão artística.

UUID de intenção nasce somente ao Gerar, é registrado na URL antes doPOST e será o mesmo RunID. Backend salva intenção/snapshot/marcador antes de admissão. Setters opcionais puros `with_run_id`/`with_identity_proof` compõem metadados: prova compara origem/path/SHA esperado com hash recém calculado pelo pipe **antes de ensure_idle, Store.create e worker**. Não mudam DTO público legado ou parâmetros. Worker mantém verificações nativas próprias.

202 retornado não significa conclusão:

```json
{
  "intent_id":"UUID conhecido","run_id":"MESMO UUID","roteiro_id":"UUID",
  "block_id":"chave planejada","source_revision":2,"state":"queued","admission":"admitted",
  "snapshot":{"prompt":"Texto literal","seed":2026101205,"duration_seconds":8,
              "parent_id":null,"reference":{"source_root":"assets",
              "path":"dance_reference.png","sha256":"prova do servidor"}},
  "run":{"id":"MESMO UUID","state":"queued"}
}
```

Run acima abreviado; retorno real inclui Run nativo completo. Marcador, Store.request/snapshot, Store.get/projeção imutável e hidratação canônica provam associação. Decisão/pai/publicação nativos são autoridade. Uma intenção duplicada retorna409, nunca reexecuta. Falha inesperada durante admissão conserva resultado incerto e UUID conhecido, podendo retornar202 sem Run confirmado.

## Recuperação e novo envio confirmado

`GET /roteiros/{ident}/blocks/{key}/attempts/{intent_id}` consulta exatamente a intenção própria, sem execução. Documento contém attempts serverowned achatadas por block_id.

1. **Todo erro de admissão de roteiro, inclusive4xx/409, mantém submitted/statusOnly e incerteza até consulta própria.** Status HTTP sozinho não prova que não entrou. 404 desconhecido, arquivo/vínculo ausente ou corrompido também não libera Gerar/rePOST.
2. Front compara roteiro/bloco/intenção atuais com owner canônico **antes do GET** e novamente após resposta. Intenção antiga de root ao preparar filho não faz HTTP nem limpa incerteza de outra operação.
3. Ausência/corrupção de prova após reserva mantém `admission:"uncertain",state:"uncertain",run:null`. Se Run confirmado: admission admitted e estado observado nativo. Só incerteza pertencente àquela intenção pode ser limpa.
4. Recusa confirmada exige GET próprio com `admission:"rejected",state:"not_admitted",run:null`; mesma intenção como última tentativa da posição no histórico, source_revision válida e snapshot/identidade/SHA/duração/seed comprovados. Para continuação, mesmo pai original ainda aceito/publicado e mesma identidade.
5. Só então habilita **Preparar novo envio**: rascunho isolado `not-admitted:<intentUUID>`, prompt literal/seed/duração/referência/pai copiados do snapshot. Preparar não faz POST, PUT nem aloca UUID; histórico antigo permanece. Fences de upload/montagem/busy/incerteza independente continuam.
6. Somente próximo clique Gerar cria novo UUID e POST com o rascunho escolhido. Não faz PUT sobre posição congelada, nem repete intenção antiga. Snapshot inicial idêntico não promete bytes/pixels idênticos.

Após admissão confirmada, espera do próprio RunID e leitura/SSE de metadados reutilizam mecanismo nativo, sem polling de conclusão/replay. Aceitar não gera próximo; montagem da cadeia aceita é explícita. Fluxo avulso mantém semântica nativa anterior, inclusive tratamento de4xx; regras conservadoras acima são das intenções de roteiro.

## Responsabilidade arquitetural e evidência

`roteiro.py` concentra plano/configuração/proposta/correlação/router; I2V/V2V executam pela composição e dispatcher existentes. Sem segundo worker, broker, fila, política de RAM ou controle do script ComfyUI. Grok permanece editor isolado; roteiro chama seu contrato público sem acoplar Grok ao Store/dispatcher.

Validação final informada pelo integrador:171 testesNode,859pytest e Ruff passaram. Protocolo mock `b688`:409 permaneceu fenced →GET próprio →reload →Preparar semPOST →Gerar novoUUID/snapshot copiado/semPUT. Três posições aceitas e montagem explícita também exercitadas; edição futura do terceiro para8,1s/seed0 preservada.

São provas de protocolo/UI fake, não nova inferência ou certificação física: mock de montagem mantém576frames constantes mesmo quando pedidos alinhados totalizam593; não usar esse fixture para afirmar duração/frame count reais. Não foi executado teste/provider/GPU/processo nesta atualização documental. Autorização realGrok37 já consumida, sem repetição; não certificar obediência visual, quota, RAM/VRAM ou prazo.
