# Hangy Backend

Backend do projeto Hangy desenvolvido com FastAPI e organizado segundo os
princípios de Clean Architecture.

## Pré-requisitos

- Docker
- Docker Compose (incluído nas versões atuais do Docker Desktop)

## Executar com Dev Container (Recomendado)

O Dev Container reutiliza os serviços `api` e `db` do Docker Compose, monta o
repositório em `/app` e instala automaticamente as dependências de
desenvolvimento. Para usá-lo, instale o Docker, o Visual Studio Code e a extensão
[Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers).

Se o arquivo `.env` ainda não existir, crie-o a partir do exemplo:

```bash
cp .env.example .env
```

Abra o repositório no Visual Studio Code, pressione `F1` e execute
`Dev Containers: Reopen in Container`. Na primeira execução, o Visual Studio
Code construirá a imagem, iniciará o PostgreSQL, aplicará as migrações e iniciará
a API com recarregamento automático. A API estará disponível em
<http://localhost:8000> e a documentação em <http://localhost:8000/docs>.

No terminal integrado do Dev Container, execute os testes e o lint normalmente:

```bash
alembic upgrade head
python -m app.seed
pytest
ruff check .
```

Esses comandos usam o serviço PostgreSQL `db` definido pelo Docker Compose. Por
isso, mantenha `db` como o hostname do `DATABASE_URL` no `.env` ao trabalhar no
Dev Container. O seed é idempotente e pode ser executado novamente com
segurança.

Depois de alterar o `.devcontainer/Dockerfile`, o
`.devcontainer/docker-compose.yml`, o `requirements-dev.txt` ou o
`devcontainer.json`, execute `Dev Containers: Rebuild Container` para recriar o
ambiente. Para sair, execute `Dev Containers: Reopen Folder Locally`; com
`shutdownAction` configurado como `stopCompose`, os serviços iniciados pelo Dev
Container serão encerrados.

## Executar com Docker

Na raiz do repositório, construa a imagem e inicie a API:

```bash
docker compose -f .devcontainer/docker-compose.yml up --build
```

O Docker Compose lê as configurações de desenvolvimento do arquivo `.env` e
inicia a API e o PostgreSQL. Antes de usar esses valores fora do ambiente local,
troque `POSTGRES_PASSWORD` e `JWT_SECRET_KEY` por segredos seguros. O arquivo
`.env.example` documenta todas as variáveis necessárias.

A aplicação ficará disponível em:

- API: <http://localhost:8000>
- Health check: <http://localhost:8000/health>
- Cadastro: `POST http://localhost:8000/auth/register`
- Login: `POST http://localhost:8000/auth/login`
- Usuário autenticado: `GET http://localhost:8000/users/me`
- Feed da Home: `GET http://localhost:8000/feed`
- Swagger UI: <http://localhost:8000/docs>
- Especificação OpenAPI: <http://localhost:8000/openapi.json>

O ambiente de desenvolvimento também popula o banco, de forma idempotente, com
usuários, tags, interesses e eventos de exemplo (`python -m app.seed`, executado
a cada start do contêiner). Os usuários têm as mesmas permissões até que regras
de autorização sejam adicionadas:

| E-mail            | Senha            | Tipo     | Interesses             |
| ----------------- | ---------------- | -------- | ---------------------- |
| `user@hangy.com`  | `user-password`  | PERSONAL | Futebol, Corrida, Rock |
| `maria@hangy.com` | `maria-password` | PERSONAL | Samba                  |
| `joao@hangy.com`  | `joao-password`  | PERSONAL | nenhum                 |
| `ana@hangy.com`   | `ana-password`   | PERSONAL | nenhum                 |
| `pedro@hangy.com` | `pedro-password` | PERSONAL | nenhum                 |
| `carla@hangy.com` | `carla-password` | PERSONAL | nenhum                 |
| `lucas@hangy.com` | `lucas-password` | PERSONAL | nenhum                 |
| `bia@hangy.com`   | `bia-password`   | PERSONAL | nenhum                 |
| `admin@hangy.com` | `admin-password` | BUSINESS | nenhum                 |

O seed também cria o evento `Rachão fechado` como `INVITE_ONLY`. Para testar o
aceite por link com `user@hangy.com`, use o token
`seed-invite-racha-fechado`.

Há também o evento `Confraternização da equipe`, `PRIVATE`, criado por
`admin@hangy.com` e sem nenhum participante.

O `user@hangy.com` recebe notificações dos 11 tipos, com cinco solicitações
(Maria, João, Ana, Pedro e Carla) e duas aceitações de conexão (Lucas e Bia):
10 não lidas, 6 lidas, já com o `payload` preenchido. O banco reflete o que cada
uma diz: quem pediu para participar está `PENDING`, quem cancelou está
`CANCELLED` (fora da lista de participantes), quem foi removido está `REMOVED`
(e não consegue pedir de novo), e assim por diante. Cada par de usuários tem
uma única conexão. O `created_at` é recalculado a partir
do horário atual a cada execução do seed, de alguns minutos a 4 dias atrás. O
estado de leitura só volta ao original para a notificação do `joao@hangy.com`
descrita abaixo.

Para testar `PATCH /notifications/{notification_id}/read`, use
`joao@hangy.com`: a notificação `76331ed0-0a64-55c8-819a-35958e434add` é dele e
volta a ficar não lida a cada execução do seed. A
`d3bcd888-24d8-5fe0-a022-e0e5aae5920d` é da `maria@hangy.com` e serve para o
caso `403`. A collection `postman/tid219_patch_notifications_read.postman_collection.json`
percorre todos os cenários.

As tags de exemplo seguem a hierarquia macro → micro usada pelo feed:
`Esportes` (Futebol, Corrida), `Música` (Rock, Samba, Sertanejo),
`Gastronomia` (Churrasco, Culinária Italiana, Confeitaria) e `Arte e Cultura`
(Teatro, Cinema).

Para encerrar os contêineres:

```bash
docker compose -f .devcontainer/docker-compose.yml down
```

O PostgreSQL é armazenado no volume Docker `hangy_postgres_data`. Para também
remover os dados locais, execute
`docker compose -f .devcontainer/docker-compose.yml down -v`.

## Deploy na AWS

O desenvolvimento e os merges acontecem no GitHub. O espelhamento sobrescreve
`main`, `develop` e tags no GitLab com force push. Quando a `main` protegida de
`2026-2/2jk-4jk/hangy/hangy-backend` na AGES é atualizada, o
[pipeline do GitLab](.gitlab-ci.yml) publica o backend.
O [Terraform](infra/terraform/) cria a infraestrutura do zero:
EC2 `t4g.medium` ARM64, RDS PostgreSQL com 50 GB gp2, S3 Standard, rede, ECR,
Secrets Manager e permissões AWS em Ohio (`us-east-2`), conforme a estimativa.
O pipeline cria/atualiza a infraestrutura e publica a API automaticamente.
Configure as variáveis CI/CD `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` e
`FRONTEND_BASE_URL` no GitLab e um runner com Docker-in-Docker, conforme o
[guia de deploy](docs/deploy-aws.md). A `main` do GitLab deve permitir force push
à identidade do espelhamento e continuar protegida para autorizar o deploy.

### Acesso ao GitLab e registro do runner

A URL da instância é **https://tools.ages.pucrs.br/**. Use essa URL base
no registro do runner, sem acrescentar o caminho do projeto.

Para obter o token de registro no GitLab 14.8.2:

1. Entre no [GitLab da AGES](https://tools.ages.pucrs.br/) com sua conta.
2. Abra o projeto `2026-2/2jk-4jk/hangy/hangy-backend`.
3. Acesse **Settings → CI/CD → Runners** e expanda a seção.
4. Na área de configuração manual de um runner específico do projeto,
   copie o **registration token**. Se a seção não estiver disponível,
   solicite acesso ao responsável pelo projeto ou à equipe da AGES.
5. Informe o token no prompt interativo de registro do runner. Não use um
   token de acesso pessoal e não salve o token no README, em commits,
   capturas de tela ou comandos que fiquem no histórico do terminal.

O pipeline exige executor Docker, tag `hangy-docker` e modo privilegiado para
Docker-in-Docker. Montar `/var/run/docker.sock` dá ao runner controle do Docker;
jobs privilegiados podem comprometer o ambiente que os executa. Por isso, este
guia não recomenda executar essa configuração no Docker de um PC de uso diário.
Use um host ou uma VM dedicada ao runner, com seu próprio Docker e apenas jobs
confiáveis, conforme os [requisitos de deploy](docs/deploy-aws.md).
Consulte também a [documentação de instalação do runner em Docker](https://docs.gitlab.com/runner/install/docker/).

No Windows, abra o **PowerShell** com o Docker Desktop iniciado no modo
**Linux containers**. Os comandos abaixo usam a série 14.8 do runner para
acompanhar a instância GitLab 14.8.2; essa versão antiga não deve ser tratada
como uma versão atual com correções de segurança.

Inicie o runner com um volume persistente para sua configuração:

```powershell
docker run -d --name gitlab-runner --restart unless-stopped `
  -v gitlab-runner-config:/etc/gitlab-runner `
  -v /var/run/docker.sock:/var/run/docker.sock `
  gitlab/gitlab-runner:v14.8.0
```

Registre o runner no projeto:

```powershell
docker exec -it gitlab-runner gitlab-runner register `
  --url "https://tools.ages.pucrs.br/" `
  --executor docker `
  --docker-image alpine:3.21 `
  --docker-privileged `
  --description "Hangy local PC" `
  --tag-list hangy-docker `
  --run-untagged=false `
  --locked=true
```

Cole o **registration token** obtido acima quando solicitado e aceite os
valores já preenchidos nos demais prompts. Execute o registro apenas uma vez
para este runner; reiniciar o contêiner preserva a configuração.

Confira a conexão e os logs:

```powershell
docker exec gitlab-runner gitlab-runner verify
docker logs --tail 100 gitlab-runner
```

Em **Settings → CI/CD → Runners**, confirme que o runner aparece online.
Para atender também a merge requests de branches não protegidas, ele não deve
estar marcado como **Protected**. A verificação confirma a conexão; a execução
de um pipeline valida o funcionamento dos jobs.

Mantenha o PC acordado e o Docker Desktop em execução enquanto houver jobs.
Para parar ou iniciar novamente o runner:

```powershell
docker stop gitlab-runner
docker start gitlab-runner
```

## Feed da Home

`GET /feed?limit=10` exige um Bearer token e retorna `sections`, agrupadas
pela tag macro dos interesses do usuário. Cada seção contém `tag`, `items`
e `has_more`. O limite vale por seção (1 a 50); `has_more` indica que existem
outros eventos, mas este endpoint ainda não aceita cursor ou página seguinte.

Entram apenas eventos futuros, não excluídos e com status `PUBLISHED`.
Eventos `INVITE_ONLY` não aparecem. Nos eventos `PRIVATE`, `event_date` e
`location_name` são nulos; nos públicos, o local é o nome salvo no evento.
A contagem de participantes inclui somente os confirmados.

Sem interesses, a resposta é `{"sections": []}`. O feed padrão para esse
caso ainda depende de definição de produto. O filtro de criadores que
bloquearam o usuário depende da implementação de `USER_BLOCK`.

Os eventos de desenvolvimento usam IDs determinísticos para que o seed
não altere eventos de usuários com o mesmo título. Dados gerados pela versão
anterior do seed, com IDs aleatórios, são preservados e podem coexistir com
os novos exemplos.

## Autenticação

`POST /auth/register` é um único endpoint que decide o tipo de conta pelo campo
`user_type` do próprio corpo (`PERSONAL` ou `BUSINESS`), uma união
discriminada validada pelo Pydantic. Os dois formatos aparecem no Swagger UI.

Cadastro de pessoa física:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
        "user_type": "PERSONAL",
        "email": "felipe@hangy.com",
        "password": "strong-password",
        "name": "Felipe Souza",
        "cpf": "52998224725",
        "phone": "51999990000",
        "date_of_birth": "2000-04-12",
        "country": "BR",
        "state": "RS",
        "city": "Porto Alegre",
        "accepted_terms_version": "2026-08-01"
      }'
```

Cadastro de pessoa jurídica:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{
        "user_type": "BUSINESS",
        "email": "contato@bar.com",
        "password": "strong-password",
        "business_name": "Bar do Zé",
        "cnpj": "11222333000181",
        "phone": "5133330000",
        "description": "Bar e petiscaria",
        "location": {"latitude": -30.0331, "longitude": -51.23},
        "address": "Av. Independência, 100 — Porto Alegre",
        "accepted_terms_version": "2026-08-01"
      }'
```

CPF e CNPJ são validados por dígito verificador (400 se inválidos); cadastro
`PERSONAL` exige 18 anos completos na data de nascimento (403 caso contrário).
E-mail, CPF e CNPJ são únicos entre contas ativas (409 em caso de duplicidade;
o e-mail é único por conta, não por tipo). O sucesso devolve `201` já com o
`access_token`, no mesmo formato de resposta do login.

`POST /auth/login` recebe e-mail e senha como JSON:

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "felipe@hangy.com", "password": "strong-password"}'
```

Credenciais inválidas (e-mail inexistente ou senha errada) sempre devolvem o
mesmo `401` com `{"detail": "Incorrect email or password"}`, para não indicar
qual dos dois estava errado. Uma conta excluída (`deleted_at` preenchido)
devolve `403` mesmo com a senha correta.

A resposta, igual à de `/auth/register`, contém um JWT no campo `access_token` e o
usuário autenticado. Envie o token como Bearer para acessar uma rota
protegida:

```bash
curl http://localhost:8000/users/me \
  -H "Authorization: Bearer SEU_ACCESS_TOKEN"
```

No Swagger UI, o botão **Authorize** oferece `BearerToken`: cole ali um JWT
obtido em `/auth/login` ou `/auth/register`.

As senhas são protegidas com Argon2 por meio do `pwdlib`; somente o hash é
persistido. Os tokens são criados e verificados com PyJWT, carregam a data de
emissão (`iat`) e expiram conforme `ACCESS_TOKEN_EXPIRE_MINUTES`. Trocar a
senha atualiza `password_changed_at` e invalida tokens emitidos antes dessa
troca, mesmo que ainda não tenham expirado.

## Migrações

Com a API em execução, crie uma nova migração após adicionar ou alterar models:

```bash
docker compose -f .devcontainer/docker-compose.yml exec api alembic revision --autogenerate -m "descricao"
```

Para aplicar as migrações:

```bash
docker compose -f .devcontainer/docker-compose.yml exec api alembic upgrade head
```

Para executar o seed manualmente:

```bash
docker compose -f .devcontainer/docker-compose.yml exec api python -m app.seed
```

## Desenvolvimento local

### Convenção de branches

Os commits locais são bloqueados quando a branch não segue o formato
`tidXXX/name-of-branch`, em que `XXX` é um número (por exemplo,
`tid123/add-login-endpoint`). O nome após a barra segue as regras normais do
Git. Ative o hook uma vez após clonar o repositório:

```bash
git config core.hooksPath .githooks
```

Com uma instância PostgreSQL disponível e o `.env` configurado, crie e ative um
ambiente virtual e instale as dependências de desenvolvimento:

```bash
python -m venv .venv
pip install -r requirements-dev.txt
alembic upgrade head
```

Execute os testes e o lint:

```bash
pytest
ruff check .
```

## Arquitetura

O projeto separa a interface HTTP, as regras de negócio e os detalhes de
persistência em três camadas. O fluxo de uma requisição parte da apresentação,
passa pelo domínio e usa a infraestrutura apenas quando precisa persistir ou
consultar dados.

```text
Cliente HTTP
    │ request DTO
    ▼
route → mapper → entity → service
                            │
                            ▼
Cliente HTTP ← response DTO ← assembler

service ↔ infrastructure/repository (quando houver persistência)
```

| Camada           | Responsabilidade                                                                                |
| ---------------- | ----------------------------------------------------------------------------------------------- |
| `presentation`   | Recebe requisições do cliente, define DTOs e converte dados de entrada em entidades.            |
| `domain`         | Mantém entidades, enums e serviços com a lógica de negócio, além de montar os DTOs de resposta. |
| `infrastructure` | Implementa repositórios e os detalhes técnicos de persistência.                                 |

### Estrutura de diretórios

```text
app/
├── presentation/
│   ├── routes/                # Controllers e endpoints FastAPI
│   ├── dtos/                  # Dados trocados com o cliente
│   └── mappers/               # Convertem DTOs de entrada em entidades
├── domain/
│   ├── assemblers/            # Convertem entidades em DTOs de resposta
│   ├── entities/              # Estruturas de dados do domínio
│   ├── services/              # Regras e operações de negócio
│   └── enums/                 # Enumerações do domínio
├── infrastructure/
│   └── repository/            # Persistência, sessão e modelos SQLAlchemy
├── config.py                   # Configurações carregadas do ambiente
└── main.py                    # Cria e configura a aplicação FastAPI
```

### Responsabilidades e conversões

O mesmo conceito pode ter representações diferentes entre o cliente, o domínio
e o banco de dados:

| Tipo        | Local                       | Finalidade                                                            |
| ----------- | --------------------------- | --------------------------------------------------------------------- |
| DTO         | `presentation/dtos`         | Define os dados recebidos e devolvidos pela API.                      |
| Mapper      | `presentation/mappers`      | Transforma DTOs recebidos do cliente em entidades de domínio.         |
| Entidade    | `domain/entities`           | Representa os dados usados pelas regras de negócio.                   |
| Serviço     | `domain/services`           | Executa a lógica de negócio sobre entidades e valores do domínio.     |
| Assembler   | `domain/assemblers`         | Transforma entidades em DTOs que os controllers devolvem ao cliente.  |
| Enum        | `domain/enums`              | Centraliza conjuntos fechados de valores válidos no domínio.          |
| Repositório | `infrastructure/repository` | Encapsula banco de dados, modelos de persistência e acesso aos dados. |

Por exemplo, o endpoint `GET /health` recebe a requisição em
`presentation/routes` e chama o serviço `GetHealth` em `domain/services`. O
serviço retorna a entidade `HealthStatus`, que `HealthAssembler` transforma no
DTO `HealthOutput` antes de o controller responder ao cliente. Como o health
check não persiste dados, ele não usa `infrastructure/repository`.

No fluxo de autenticação, `UserMapper` converte o DTO de cadastro em
`UserCredentials`; `AuthService` valida credenciais, protege senhas e emite os
tokens; `SqlAlchemyUserRepository` persiste usuários no PostgreSQL; e
`AuthAssembler` produz os DTOs devolvidos pelos controllers.
