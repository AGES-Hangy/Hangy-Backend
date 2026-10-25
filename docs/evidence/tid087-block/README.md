# Bloqueio bilateral — evidência e contrato

Contrato confirmado pelo usuário em 25/10/2026, após esclarecimento do Gabriel:
A bloqueia B → desfazer conexão, cancelar participações pendentes/confirmadas
cruzadas, remover notificações relacionadas nas duas caixas e impedir novas
inscrições/convites/aprovações enquanto houver bloqueio em qualquer direção.
Depois de desbloquear, uma **nova inscrição explícita** é permitida. Nada é
restaurado automaticamente. Referência: [task 087](https://app.clickup.com/t/90171450474/86e2v0v8m)
e [US8.4](https://app.clickup.com/t/90171450474/86e2v0ukx). O esclarecimento amplia
os critérios originais da descrição dessas tarefas.

## Persistência e concorrência

- A retirada usa `CANCELLED`; preserva a linha e registros/fotos históricos.
  Convites passam a reaproveitar explicitamente essa linha cancelada, assim
  como a inscrição comum. `REJECTED`/`REMOVED` preexistentes não são restaurados.
- Bloqueio, conexão, participações e exclusão de notificações usam uma transação.
  Erro na limpeza desfaz tudo. Nenhum aviso de saída/remoção é gerado por bloquear.
- O lock transacional de par no PostgreSQL é adquirido antes de locks de
  participante/conexão. A limpeza de bloqueio não adquire lock de evento.
- São limpas notificações dos vínculos históricos do par, de participações e
  eventos da outra pessoa, incluindo `EVENT_STARTING_SOON`, que não possui
  remetente humano. As caixas de terceiros e eventos não relacionados ficam.
- A escrita das notificações resolve a outra pessoa e suprime INSERT e push
  quando bloqueada. Não há tentativa de remover push já entregue ao sistema
  operacional do aparelho.
- Repetir POST conserva 409 e repara efeitos legados antes de retornar.

## Evidência HTTP real

`http-results.json` contém resultados de chamadas à API local (sem headers nem
tokens); `http-results.png` e `http-rejoin.png` são capturas do painel desses
resultados. `null` representa **ausência de corpo no 204**, não um JSON enviado.
O painel resume `/notifications` a tipos/contador; o restante mantém a resposta.
Todas as contas/IDs são fictícios; banco SQLite exclusivo, sem mocks de rota.

1. Desbloquear (204), inscrever novamente (201), bloquear (204).
2. Ana conserva apenas o aviso de Carla (200, unread=1); Bruno fica sem avisos
   relacionados (200, unread=0); tentar ingressar bloqueado retorna 404.
3. Desbloquear (204) não restaura avisos. Nova inscrição explícita retorna 201.

## Checks

- Suíte completa final: 950 passed, 16 skipped, 1 xfailed, cobertura 96,87%.
  Os dois testes de concorrência são pulados no SQLite e passaram no PostgreSQL.
- `tests/test_block_effects.py` no PostgreSQL 16 descartável: **16 passed**,
  com schema criado por `alembic upgrade head`; inclui as duas ordens da corrida
  bloquear/inscrever e verifica que a segunda operação espera o lock.
- Regressões: seis combinações de ingresso, quatro retiradas/negação de aprovação,
  limpeza/supressão dos 11 tipos em ambas as direções, terceiros, rollback e 409.
- `ruff check .`, `ruff format --check .`, `git diff --check`.
- Sem alterações de schema/migração neste PR. Sem validação de produção/push real.
  A execução Web integrada e suas imagens ficam no PR correspondente do frontend.

## Bloqueios legados

`python -m scripts.repair_block_effects` só conta os bloqueios (dry-run).
Após conferir DATABASE_URL e revisar o alcance, `--apply` repara cada bloqueio
atomicamente e pode ser repetido. Não é executado automaticamente no deploy;
nenhum banco real foi saneado nesta entrega.

Para repetir PostgreSQL em uma base **descartável dedicada**: aplicar as migrações,
configurar `HANGY_BLOCK_TEST_DATABASE_URL` para essa base e rodar
`pytest tests/test_block_effects.py -q`. Esses testes limpam todas as tabelas da
base indicada entre casos. Não apontar para banco compartilhado ou real.
