# Evidência — tasks 269 e 270

Transcrição de chamadas HTTP reais contra a API local (uvicorn + PostgreSQL 17, banco migrado com `alembic upgrade head` e populado com `python -m app.seed`), em 11/10/2026.

## Task 269 — POST e PATCH /events

### 1. Criar evento privado com bairro e cidade

`POST /events` — como user@hangy.com (organizador)

Body:
```json
{
  "title": "Futebol no Planet",
  "event_date": "2026-10-14T22:31:41.026362+00:00",
  "end_date": "2026-10-15T00:31:41.026362+00:00",
  "location": {
    "latitude": -30.0512,
    "longitude": -51.1789
  },
  "location_name": "Planet Ball — Av. Ipiranga, 6681",
  "location_neighborhood": "Partenon",
  "location_city": "Porto Alegre",
  "privacy": "PRIVATE"
}
```

Status: **201**

```json
{
  "event_id": "008f51f9-8e6e-47a8-8a71-00dace04bfdf",
  "title": "Futebol no Planet",
  "status": "PUBLISHED",
  "privacy": "PRIVATE",
  "event_date": "2026-10-14T22:31:41.026362Z",
  "creator": {
    "id": "c2e8f67a-1b3f-4dc0-b58e-043a984a169d",
    "name": "Usuário Hangy"
  }
}
```

### 2. Erro: bairro com mais de 120 caracteres

`POST /events` — como user@hangy.com

Body:
```json
{
  "title": "Futebol no Planet",
  "event_date": "2026-10-14T22:31:41.026362+00:00",
  "end_date": "2026-10-15T00:31:41.026362+00:00",
  "location": {
    "latitude": -30.0512,
    "longitude": -51.1789
  },
  "location_name": "Planet Ball — Av. Ipiranga, 6681",
  "location_neighborhood": "aaaaaaaaaaaa… (121 caracteres)",
  "location_city": "Porto Alegre",
  "privacy": "PRIVATE"
}
```

Status: **422**

```json
{
  "detail": [
    {
      "type": "string_too_long",
      "loc": [
        "body",
        "location_neighborhood"
      ],
      "msg": "String should have at most 120 characters",
      "input": "aaaaaaaaaaaa… (121 caracteres)",
      "ctx": {
        "max_length": 120
      }
    }
  ]
}
```

### 3. Erro: criar evento sem token

`POST /events` — sem token

Body:
```json
{
  "title": "Futebol no Planet",
  "event_date": "2026-10-14T22:31:41.026362+00:00",
  "end_date": "2026-10-15T00:31:41.026362+00:00",
  "location": {
    "latitude": -30.0512,
    "longitude": -51.1789
  },
  "location_name": "Planet Ball — Av. Ipiranga, 6681",
  "location_neighborhood": "Partenon",
  "location_city": "Porto Alegre",
  "privacy": "PRIVATE"
}
```

Status: **401**

```json
{
  "detail": "Could not validate credentials"
}
```

## Task 270 — localização por quem pede

### 4. Detalhe do evento privado para quem não foi aprovado

`GET /events/008f51f9-8e6e-47a8-8a71-00dace04bfdf` — como joao@hangy.com (sem participação)

Status: **200**

```json
{
  "event_id": "008f51f9-8e6e-47a8-8a71-00dace04bfdf",
  "title": "Futebol no Planet",
  "location": {
    "latitude": -30.052047187412686,
    "longitude": -51.17680499038403
  },
  "location_name": "Partenon, Porto Alegre",
  "location_precision": "APPROXIMATE",
  "location_radius_m": 500,
  "privacy": "PRIVATE",
  "viewer": {
    "is_organizer": false,
    "participation_status": null,
    "can_see_participants": false,
    "available_action": "REQUEST"
  }
}
```

### 5. O mesmo evento para o organizador

`GET /events/008f51f9-8e6e-47a8-8a71-00dace04bfdf` — como user@hangy.com (organizador)

Status: **200**

```json
{
  "event_id": "008f51f9-8e6e-47a8-8a71-00dace04bfdf",
  "title": "Futebol no Planet",
  "location": {
    "latitude": -30.0512,
    "longitude": -51.1789
  },
  "location_name": "Planet Ball — Av. Ipiranga, 6681",
  "location_precision": "EXACT",
  "location_radius_m": null,
  "privacy": "PRIVATE",
  "viewer": {
    "is_organizer": true,
    "participation_status": null,
    "can_see_participants": true,
    "available_action": "MANAGE"
  }
}
```

### 6. PATCH só do título

`PATCH /events/008f51f9-8e6e-47a8-8a71-00dace04bfdf` — como user@hangy.com (organizador)

Body:
```json
{
  "title": "Futebol no Planet (novo)"
}
```

Status: **200**

```json
{
  "event_id": "008f51f9-8e6e-47a8-8a71-00dace04bfdf",
  "title": "Futebol no Planet (novo)",
  "event_date": "2026-10-14T22:31:41.026362Z",
  "status": "PUBLISHED",
  "updated_at": "2026-10-11T22:31:41.073098Z"
}
```

### 7. Depois de editar o título, o ponto aproximado é o mesmo do item 4

`GET /events/008f51f9-8e6e-47a8-8a71-00dace04bfdf` — como joao@hangy.com

Status: **200**

```json
{
  "event_id": "008f51f9-8e6e-47a8-8a71-00dace04bfdf",
  "title": "Futebol no Planet (novo)",
  "location": {
    "latitude": -30.052047187412686,
    "longitude": -51.17680499038403
  },
  "location_name": "Partenon, Porto Alegre",
  "location_precision": "APPROXIMATE",
  "location_radius_m": 500,
  "privacy": "PRIVATE",
  "viewer": {
    "is_organizer": false,
    "participation_status": null,
    "can_see_participants": false,
    "available_action": "REQUEST"
  }
}
```

### 8. PATCH do endereço

`PATCH /events/008f51f9-8e6e-47a8-8a71-00dace04bfdf` — como user@hangy.com (organizador)

Body:
```json
{
  "location": {
    "latitude": -30.0277,
    "longitude": -51.2287
  },
  "location_name": "Parcão — Rua Comendador Caminha",
  "location_neighborhood": "Moinhos de Vento"
}
```

Status: **200**

```json
{
  "event_id": "008f51f9-8e6e-47a8-8a71-00dace04bfdf",
  "title": "Futebol no Planet (novo)",
  "event_date": "2026-10-14T22:31:41.026362Z",
  "status": "PUBLISHED",
  "updated_at": "2026-10-11T22:31:41.091627Z"
}
```

### 9. Depois de editar o endereço, o ponto aproximado foi recalculado

`GET /events/008f51f9-8e6e-47a8-8a71-00dace04bfdf` — como joao@hangy.com

Status: **200**

```json
{
  "event_id": "008f51f9-8e6e-47a8-8a71-00dace04bfdf",
  "title": "Futebol no Planet (novo)",
  "location": {
    "latitude": -30.02854718742839,
    "longitude": -51.22660548723286
  },
  "location_name": "Moinhos de Vento, Porto Alegre",
  "location_precision": "APPROXIMATE",
  "location_radius_m": 500,
  "privacy": "PRIVATE",
  "viewer": {
    "is_organizer": false,
    "participation_status": null,
    "can_see_participants": false,
    "available_action": "REQUEST"
  }
}
```

### 10. Evento privado do seed para participante CONFIRMED

`GET /events/1ec9079d-ae72-584f-bee3-588ba3ea6f97` — como user@hangy.com (CONFIRMED)

Status: **200**

```json
{
  "event_id": "1ec9079d-ae72-584f-bee3-588ba3ea6f97",
  "title": "Aniversário da Maria",
  "location": {
    "latitude": -30.0368,
    "longitude": -51.209
  },
  "location_name": "Casa da Maria",
  "location_precision": "EXACT",
  "location_radius_m": null,
  "privacy": "PRIVATE",
  "viewer": {
    "is_organizer": false,
    "participation_status": "CONFIRMED",
    "can_see_participants": true,
    "available_action": "CANCEL_PRESENCE"
  }
}
```

### 11. O mesmo evento para solicitação PENDING

`GET /events/1ec9079d-ae72-584f-bee3-588ba3ea6f97` — como joao@hangy.com (PENDING)

Status: **200**

```json
{
  "event_id": "1ec9079d-ae72-584f-bee3-588ba3ea6f97",
  "title": "Aniversário da Maria",
  "location": {
    "latitude": -30.034458561061204,
    "longitude": -51.20917728183014
  },
  "location_name": "Bom Fim, Porto Alegre",
  "location_precision": "APPROXIMATE",
  "location_radius_m": 500,
  "privacy": "PRIVATE",
  "viewer": {
    "is_organizer": false,
    "participation_status": "PENDING",
    "can_see_participants": false,
    "available_action": "CANCEL_PRESENCE"
  }
}
```

### 12. Preview de compartilhamento de evento privado

`GET /events/1ec9079d-ae72-584f-bee3-588ba3ea6f97/share` — como ana@hangy.com

Status: **200**

```json
{
  "url": "hangy://event/1ec9079d-ae72-584f-bee3-588ba3ea6f97",
  "web_url": "http://localhost:8081/e/1ec9079d-ae72-584f-bee3-588ba3ea6f97",
  "title": "Aniversário da Maria",
  "event_date": null,
  "location_name": "Bom Fim, Porto Alegre",
  "cover_photo_url": null
}
```

### 13. Cards privados no feed

`GET /feed` — como user@hangy.com

Status: **200** (só os itens `PRIVATE`, campos de local)

```json
[
  {
    "title": "Aniversário da Maria",
    "privacy": "PRIVATE",
    "location_name": "Casa da Maria",
    "location_precision": "EXACT"
  },
  {
    "title": "Corrida da Redenção",
    "privacy": "PRIVATE",
    "location_name": "Parque Farroupilha (Redenção)",
    "location_precision": "EXACT"
  },
  {
    "title": "Confraternização da equipe",
    "privacy": "PRIVATE",
    "location_name": "Partenon, Porto Alegre",
    "location_precision": "APPROXIMATE"
  }
]
```

### 14. Erro: detalhe sem token

`GET /events/008f51f9-8e6e-47a8-8a71-00dace04bfdf` — sem token

Status: **401**

```json
{
  "detail": "Could not validate credentials"
}
```
