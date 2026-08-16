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
