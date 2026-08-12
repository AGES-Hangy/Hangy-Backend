# Hangy Backend

Backend do projeto Hangy desenvolvido com FastAPI e organizado segundo os
princípios de Clean Architecture.

## Pré-requisitos

- Docker
- Docker Compose (incluído nas versões atuais do Docker Desktop)

## Executar com Docker

Na raiz do repositório, construa a imagem e inicie a API:

```bash
docker compose up --build
```

A aplicação ficará disponível em:

- API: <http://localhost:8000>
- Health check: <http://localhost:8000/health>
- Swagger UI: <http://localhost:8000/docs>
- Especificação OpenAPI: <http://localhost:8000/openapi.json>

Para encerrar os contêineres:

```bash
docker compose down
```

O banco SQLite é armazenado no volume Docker `hangy_data`. Para também remover
esse volume, execute `docker compose down -v`.

## Migrações

Com a API em execução, crie uma nova migração após adicionar ou alterar models:

```bash
docker compose exec api alembic revision --autogenerate -m "descricao"
```

Para aplicar as migrações:

```bash
docker compose exec api alembic upgrade head
```

## Desenvolvimento local

Crie e ative um ambiente virtual e instale as dependências de desenvolvimento:

```bash
python -m venv .venv
pip install -r requirements-dev.txt
```

Execute os testes e o lint:

```bash
pytest
ruff check .
```

## Arquitetura

O projeto segue os princípios de **Clean Architecture**: as regras de negócio ficam no centro da aplicação e não dependem de FastAPI, SQLAlchemy, banco de dados ou outros detalhes externos. As dependências sempre apontam para dentro.

```text
Cliente HTTP
    │
    ▼
presentation  →  application  →  domain
    │
    ▼
infrastructure
```

| Camada | Responsabilidade | Não deve conhecer |
| --- | --- | --- |
| `domain` | Conceitos e regras puras do negócio, representados por entidades. | HTTP, FastAPI, Pydantic, SQLAlchemy e banco de dados. |
| `application` | Casos de uso que coordenam as regras de domínio para realizar uma ação da aplicação. | Detalhes de rotas, requests e respostas HTTP. |
| `infrastructure` | Implementações técnicas: conexão com banco, modelos SQLAlchemy, repositórios e integrações externas. | Regras específicas de apresentação HTTP. |
| `presentation` | Interface HTTP: rotas FastAPI, validação de entrada e formatação de respostas. | Detalhes de persistência e regras de baixo nível. |

### Estrutura de diretórios

```text
app/
├── domain/
│   └── entities/              # Entidades e regras de negócio
├── application/
│   ├── dtos/                  # Contratos de entrada e saída dos casos de uso
│   └── use_cases/             # Ações da aplicação, como GetHealth
├── infrastructure/
│   └── database/              # Sessão, base e modelos SQLAlchemy
├── presentation/
│   └── routes/                # Endpoints FastAPI
└── main.py                    # Cria e configura a aplicação FastAPI
```

### Entidades, modelos e DTOs

O mesmo conceito de negócio pode ter representações diferentes em cada limite
da aplicação:

| Tipo | Local | Finalidade |
| --- | --- | --- |
| Entidade de domínio | `domain/entities` | Representa o significado e as regras de negócio, sem dependências de frameworks. |
| Modelo de banco | `infrastructure/database/models` | Define como os dados são persistidos usando SQLAlchemy. |
| DTO de aplicação | `application/dtos` | Define os dados de entrada e saída dos casos de uso, sem depender de frameworks. |

Por exemplo, o endpoint `GET /health` recebe a requisição em
`presentation/routes` e chama o caso de uso `GetHealth` em `application`.
O caso de uso trabalha com a entidade `HealthStatus` de `domain` e retorna o
DTO `HealthOutput`. A camada de apresentação somente o serializa como resposta
HTTP. Como o health check não persiste dados, ele não precisa de um modelo de
banco.
