# Task 279 — evidência local

Capturas reais do Swagger UI em 2026-11-09, usando a aplicação com banco SQLite
em memória, um usuário sintético e `get_email_sender` sobrescrito por um sender
de teste. Nenhuma chamada à AWS nem entrega real de e-mail foi realizada.

| Cenário | Resultado | Captura |
| --- | --- | --- |
| Endereço cadastrado, sender de teste aceita o envio | `202`, corpo vazio | [Swagger 202](swagger-202.png) |
| Mesmo endereço, sender lança exceção simulando indisponibilidade | `202`, corpo vazio | [Falha de envio 202](swagger-delivery-failure-202.png) |
| Quarto pedido para o mesmo endereço em 15 minutos | `429`, `{"detail":"Too many reset requests"}` | [Swagger 429](swagger-429.png) |

Para reproduzir com a API local, abra `/docs`, expanda
`POST /auth/password-reset/request`, clique em **Try it out**, informe um e-mail
de teste cadastrado e execute. O quarto pedido para o mesmo endereço retorna
`429`. Use `EMAIL_BACKEND=console` somente em desenvolvimento. Os testes em
`tests/test_password_reset.py` usam um sender falso e comprovam que endereços
desconhecidos/excluídos não recebem mensagem, que falhas preservam o token e que
o código não aparece no log. `tests/test_email_sender.py` valida o conteúdo SESv2
com Stubber e moto, sem credenciais reais.

A verificação do remetente, o acesso de produção SES e a entrega real após o
deploy continuam sendo verificações operacionais; veja
[o guia de deploy](../../deploy-aws.md#e-mail-de-redefinição-de-senha-ses).
