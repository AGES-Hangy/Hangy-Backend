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
- Cadastro: `POST http://localhost:8000/register`
- Login: `POST http://localhost:8000/login`
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
| `admin@hangy.com` | `admin-password` | BUSINESS | nenhum                 |

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

`POST /register` é um único endpoint que decide o tipo de conta pelo campo
`user_type` do próprio corpo (`PERSONAL` ou `BUSINESS`), uma união
discriminada validada pelo Pydantic. Os dois formatos aparecem no Swagger UI.

Cadastro de pessoa física:

```bash
curl -X POST http://localhost:8000/register \
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
curl -X POST http://localhost:8000/register \
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

`POST /login` recebe e-mail e senha como JSON:

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/json" \
  -d '{"email": "felipe@hangy.com", "password": "strong-password"}'
```

Credenciais inválidas (e-mail inexistente ou senha errada) sempre devolvem o
mesmo `401` com `{"detail": "Incorrect email or password"}`, para não indicar
qual dos dois estava errado. Uma conta excluída (`deleted_at` preenchido)
devolve `403` mesmo com a senha correta.

A resposta, igual à de `/register`, contém um JWT no campo `access_token` e o
usuário autenticado. Envie o token como Bearer para acessar uma rota
protegida:

```bash
curl http://localhost:8000/users/me \
  -H "Authorization: Bearer SEU_ACCESS_TOKEN"
```

No Swagger UI, o botão **Authorize** oferece `BearerToken`: cole ali um JWT
obtido em `/login` ou `/register`.

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
