# H3 benchmark MCP — adapter local, não outro gerador

O MCP reutiliza **uma única invocação** de `tools/benchmark_h3.py`. O cenário, seeds, validação, revisão técnica e montagem continuam definidos somente nessa CLI. O adapter não inicia API, não chama ComfyUI e não muda modelos/cache/parâmetros.

## Registro real do host

O plugin instalado `dsh-customs/plugins/project-mcp` lê `<Git root>/.agents/mcp.json` na criação/retomada de um Agent. O registro deste projeto é:

```json
{"mcpServers":{"h3_benchmark":{"builtin":true,"toolsDir":".agents/tools","timeoutMs":30000,"failOnStartupError":true}}}
```

O shim `.agents/tools/benchmark.mjs` exporta o adapter `tools/benchmark_mcp.mjs`. **Não** apontar `toolsDir` para `tools/`: o loader importa todos os `.mjs` imediatos e isso incluiria o exporter executável. O registro é configuração executável confiável, não sandbox.

O servidor genérico do plugin usa o SDK oficial instalado `@modelcontextprotocol/server` **2.3.1**; cliente nativo DSH usa `@modelcontextprotocol/client` **2.0.0**. Não há protocolo JSON-RPC manual, novas dependências Python ou edição de plugins/config globais. `.agents/config.json` e `dshCustoms.managedPlans.autoApprove=true` ficam intactos.

**Descoberta exige um Agent novo/retomado.** Editar esses arquivos não garante atualização do catálogo do Agent já ativo. O teste offline comprova schema/registro, handshake e chamadas pelo cliente real; não é prova de disponibilidade retroativa em todas as sessões.

## Ferramentas

- `mcp__h3_benchmark__benchmark_info`: contrato/comando/hash da CLI, sem spawn/HTTP/GPU.
- `mcp__h3_benchmark__benchmark_start`: `{"label":"comparison-one","technical_acceptance":true}`. A API precisa estar ativa em `http://127.0.0.1:8010`. Consome **três gerações GPU reais**; retorna UUID próprio imediatamente, não completion.
- `mcp__h3_benchmark__benchmark_status`: `{"job_id":"<UUID retornado>"}`. Lê somente estado/relatório limitado desse job, sem process control, polling interno ou replay.

O start aceita somente label minúscula `[a-z][a-z0-9-]{0,63}` e opt-in explícito. Não permite comandos, env, paths, URLs externas, IDs de parents ou cenário arbitrários. Apenas os dois novos parents do benchmark recebem aceite técnico para avançar; aprovação visual continua pendente e o último chunk fica pronto para revisão.

O processo recebe exatamente `uv run --no-sync python tools/benchmark_h3.py --api-url http://127.0.0.1:8010 --output-dir .dumps/benchmarks/mcp-<label> --technical-acceptance`, cwd do projeto e `PYTHONDONTWRITEBYTECODE=1`. stdout/stderr do worker vão para arquivos próprios, nunca para stdout do protocolo. Nenhuma importação, initialize, list, info ou status gera vídeos.

## Estado durável e concorrência honesta

- `.data/benchmark-mcp/jobs/<UUID>/job.json`: intenção/comando/hash antes de spawn, PID/identidade Linux depois, estado terminal/erro quando observado.
- No mesmo diretório: `stdout.log`, `stderr.log` privados.
- `.data/benchmark-mcp/jobs/active.json`: lock atômico O_EXCL compartilhado por servidores MCP do projeto; liberação exige UUID proprietário.
- `label-<label>.json` nesse diretório reserva labels permanentemente: falhas não autorizam reciclar um teste.
- `.dumps/benchmarks/mcp-<label>/report.json` e `benchmark.mp4`: scratch do benchmark, sem migrar os chunks legados em `runs/`.

O lock serializa **starts MCP**, não invocações diretas da CLI/API. O slot global/RAM/own-prompt do backend continuam sendo a autoridade de geração. Labels/diretórios existentes nunca são sobrescritos; mesmo dois servidores concorrentes não conseguem repetir o mesmo start. Não há resume automático.

O worker pode continuar se o call/server terminar: é assíncrono, detached, com logs próprios. Na reconexão, status correlaciona PID e `/proc` start-time/argv, mas não mata PID nem libera lock por suposição. Um record `running` com `process_identity_confirmed=false` é **resultado incerto**, não sucesso/falha inferidos. Um CLI report completo não promove automaticamente o estado terminal perdido do servidor.

Se houver crash/resultado incerto: preservar job/lock/ledger; inspecionar o UUID, identidade do processo e IDs conhecidos do relatório, sem nova inferência. Só o operador pode resolver o lock próprio depois de provar ausência de worker e resultado terminal; nunca limpar lock de outro UUID, apagar outputs ou escolher novo label para repetir um POST incerto. O adapter não oferece ferramenta genérica de cancelamento/kill ou recuperação automática.

## Verificação offline

```fish
node --test tests/test_benchmark_mcp.mjs
env PYTHONDONTWRITEBYTECODE=1 uv run pytest -q -p no:cacheprovider
uv run ruff check --no-cache src tests tools/benchmark_h3.py
```

Os testes usam EventEmitter/worker inerte injetado somente pelo código de teste, nunca por argumento MCP. O handshake usa o SDK/registro nativos, sem iniciar a API ou executar a CLI real. A saída técnica não certifica identidade facial, cor/pose corretas ou continuidade perceptual: revisar a montagem e contact sheet continua necessário.
