<!--
Preencha as seções aplicáveis de forma objetiva.
Se algo não se aplicar, escreva "Não se aplica" e explique brevemente o motivo.
Os comentários de orientação não aparecem no PR publicado e podem permanecer.
-->

## Contexto

<!-- Qual problema este PR resolve? Inclua o link da tarefa ou história. -->

- Tarefa: <!-- link -->
- PR relacionado do frontend: <!-- link ou "Não se aplica" -->

## O que foi feito

<!-- Liste as principais mudanças e regras de negócio afetadas. Evite apenas repetir nomes de arquivos. -->

-
-

## Detalhes do backend

### Regras de negócio

<!-- Explique o comportamento esperado, validações e casos especiais. -->


### Contrato da API

<!-- Liste apenas endpoints criados ou alterados. Use "Não se aplica" se não houver. -->

| Método | Rota | O que mudou | Autenticação/perfil |
| --- | --- | --- | --- |
| <!-- GET/POST/... --> | <!-- /rota --> | <!-- resumo --> | <!-- público/perfis --> |

### Dados, migrações e configuração

<!-- Descreva alterações de modelo, migrações, seeds, variáveis de ambiente ou serviços externos. Nunca informe valores secretos. Use "Não se aplica" se não houver. -->

- Banco de dados/migração:
- Nova configuração ou variável:
- Estratégia de rollback:

### Impacto no frontend

<!-- Explique o que o front precisa adaptar, a compatibilidade com versões atuais e se há mudança quebrável. -->


## Evidência de funcionamento — obrigatória

> PRs sem evidência de teste não devem ser aprovados.

<!--
Todo PR deve conter pelo menos uma evidência de que a mudança foi testada.
Para rotas criadas ou alteradas, anexe um print ou vídeo curto do teste feito no
Postman, Insomnia, Swagger ou ferramenta equivalente. A evidência deve mostrar
o método, a rota, o status HTTP e a resposta. Quando o PR alterar validações,
autenticação ou tratamento de erros, mostre também o cenário de erro relevante.
Se o PR não alterar uma rota, anexe uma evidência equivalente do comportamento
testado e explique abaixo. Não exponha tokens, senhas ou dados sensíveis.
-->

Evidência: <!-- arraste o print/vídeo aqui -->

O que foi testado nesta evidência:


## Como validar

<!-- Escreva um passo a passo curto, incluindo pré-condições e dados de teste não sensíveis. -->

1.
2.
3.

## Validações realizadas

<!-- Informe os comandos/testes realmente executados e os resultados. -->

- [ ] Testes automatizados
- [ ] Teste manual dos endpoints alterados
- [ ] Casos de sucesso verificados
- [ ] Casos de erro e validação verificados
- [ ] Migração aplicada e revertida localmente

Resultado, comandos executados ou pendências:
