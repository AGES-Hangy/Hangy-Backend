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
pytest
ruff check .
```

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
- Swagger UI: <http://localhost:8000/docs>
- Especificação OpenAPI: <http://localhost:8000/openapi.json>

O ambiente de desenvolvimento também cria, de forma idempotente, os usuários
`user` (senha `user-password`) e `admin` (senha `admin-password`). Eles têm as
mesmas permissões até que regras de autorização sejam adicionadas.

Para encerrar os contêineres:

```bash
docker compose -f .devcontainer/docker-compose.yml down
```

O PostgreSQL é armazenado no volume Docker `hangy_postgres_data`. Para também
remover os dados locais, execute
`docker compose -f .devcontainer/docker-compose.yml down -v`.

## Autenticação

Cadastre um usuário enviando JSON:

```bash
curl -X POST http://localhost:8000/register \
  -H "Content-Type: application/json" \
  -d '{"username":"felipe","password":"strong-password"}'
```

O login segue o fluxo OAuth2 Password e, por isso, recebe os campos como
`application/x-www-form-urlencoded`:

```bash
curl -X POST http://localhost:8000/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=felipe&password=strong-password"
```

A resposta contém um JWT no campo `access_token`. Envie-o como Bearer token
para acessar uma rota protegida:

```bash
curl http://localhost:8000/users/me \
  -H "Authorization: Bearer SEU_ACCESS_TOKEN"
```

No Swagger UI, o botão **Authorize** oferece duas opções: `OAuth2Password`
recebe usuário e senha e chama `/login`; `BearerToken` permite colar diretamente
um JWT existente. As duas opções enviam o mesmo header `Authorization: Bearer`.

As senhas são protegidas com Argon2 por meio do `pwdlib`; somente o hash é
persistido. Os tokens são criados e verificados com PyJWT e expiram conforme
`ACCESS_TOKEN_EXPIRE_MINUTES`.

## Migrações

Com a API em execução, crie uma nova migração após adicionar ou alterar models:

```bash
docker compose -f .devcontainer/docker-compose.yml exec api alembic revision --autogenerate -m "descricao"
```

Para aplicar as migrações:

```bash
docker compose -f .devcontainer/docker-compose.yml exec api alembic upgrade head
```

## Desenvolvimento local

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

| Camada | Responsabilidade |
| --- | --- |
| `presentation` | Recebe requisições do cliente, define DTOs e converte dados de entrada em entidades. |
| `domain` | Mantém entidades, enums e serviços com a lógica de negócio, além de montar os DTOs de resposta. |
| `infrastructure` | Implementa repositórios e os detalhes técnicos de persistência. |

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

| Tipo | Local | Finalidade |
| --- | --- | --- |
| DTO | `presentation/dtos` | Define os dados recebidos e devolvidos pela API. |
| Mapper | `presentation/mappers` | Transforma DTOs recebidos do cliente em entidades de domínio. |
| Entidade | `domain/entities` | Representa os dados usados pelas regras de negócio. |
| Serviço | `domain/services` | Executa a lógica de negócio sobre entidades e valores do domínio. |
| Assembler | `domain/assemblers` | Transforma entidades em DTOs que os controllers devolvem ao cliente. |
| Enum | `domain/enums` | Centraliza conjuntos fechados de valores válidos no domínio. |
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
