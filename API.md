# API do SGIONGs — guia rápido

API de leitura (só ONGs aprovadas) para integrações externas: portais de
dados abertos, outros sistemas do Ministério, parceiros, etc.

## Autenticação

Todos os pedidos precisam do cabeçalho:

```
X-API-Key: <chave>
```

### Criar uma chave

```
python gerir_api_keys.py criar "Nome da integração"
```

A chave só é mostrada nesse momento — guarde-a num local seguro (gestor de
senhas, variável de ambiente do sistema que a vai consumir). Não fica
recuperável depois; se a perder, revogue e crie outra.

### Listar / revogar chaves

```
python gerir_api_keys.py listar
python gerir_api_keys.py revogar <id>
```

## Limites

60 pedidos por minuto, por chave. Ultrapassar devolve `429`.

## Endpoints

### `GET /api/v1/ongs`

Lista ONGs aprovadas.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `provincia` | texto | Filtra por província (nome exacto, ex. `Gaza`) |
| `area` | texto | Filtra por área temática |
| `q` | texto | Pesquisa por nome (parcial) |
| `pagina` | inteiro | Página, começa em 1 |
| `por_pagina` | inteiro | Resultados por página, máx. 100 (default 25) |

```
curl -H "X-API-Key: SUA_CHAVE" \
  "https://<dominio>/api/v1/ongs?provincia=Gaza&pagina=1"
```

Resposta:
```json
{
  "total": 65,
  "pagina": 1,
  "por_pagina": 25,
  "total_paginas": 3,
  "resultados": [
    {
      "id": 271,
      "nome": "...",
      "sigla": null,
      "natureza": "ONG",
      "origem": "Nacional",
      "provincia_principal": "Gaza",
      "provincias": ["Gaza"],
      "distritos": ["..."],
      "area_intervencao": "...",
      "areas_tematicas": [],
      "ano_entrada_pais": null,
      "contacto": { "pessoa": null, "telefone": null, "email": null }
    }
  ]
}
```

### `GET /api/v1/ongs/<id>`

Detalhe de uma ONG aprovada. `404` se não existir ou não estiver aprovada.

### `GET /api/v1/provincias`

Contagem de ONGs aprovadas por província.

### `GET /api/v1/areas-tematicas`

Contagem de ONGs aprovadas por área temática.

### `GET /api/v1/indicadores`

Resumo agregado: total de ONGs aprovadas, pendentes, nacionais,
estrangeiras, e número de províncias cobertas.

## O que a API NÃO expõe

- ONGs pendentes ou rejeitadas
- Dados de utilizadores/administradores
- Operações de escrita (registar, editar, aprovar) — é só leitura, de propósito

Se precisar de escrita para alguma integração futura (ex.: um parceiro
submeter directamente um registo para revisão), isso deve ser um endpoint
novo e deliberado, com o seu próprio nível de permissão — não uma extensão
destes.

## Integração no projecto

Em `app.py`:
```python
from api import api_bp
app.register_blueprint(api_bp)
```

A tabela `api_keys` é criada automaticamente na primeira vez que corre
`gerir_api_keys.py` (não precisa de alterar `schema.sql` manualmente,
embora possa acrescentar lá o `CREATE TABLE` para consistência com o resto
do schema).
