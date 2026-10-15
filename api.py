"""
api.py — API HTTP para integrações externas com o SGIONGs.

Fornece acesso de LEITURA (só ONGs aprovadas) a organizações, províncias,
áreas temáticas e indicadores agregados, protegido por chave de API.

INTEGRAÇÃO NO app.py EXISTENTE
-------------------------------
    from api import api_bp
    app.register_blueprint(api_bp)

Isto não interfere com nenhuma rota nem template actual — é só um conjunto
novo de rotas sob o prefixo /api/v1.

AUTENTICAÇÃO
------------
Cada pedido tem de incluir o cabeçalho:
    X-API-Key: <chave>

As chaves são geridas com gerir_api_keys.py (criar, listar, revogar) e
guardadas na base de dados como hash (nunca em texto simples), tal como
as palavras-passe dos utilizadores.

LIMITES
-------
Reaproveita o mesmo mecanismo de rate-limiting já usado no login (ver
app.py) — aqui implementado de forma simples e independente, por chave de
API, para não depender da sessão de utilizador (a API não tem sessão).
"""

import time
from functools import wraps
from flask import Blueprint, request, jsonify, g

from database import get_connection
from werkzeug.security import check_password_hash

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')

# --------------------------------------------------------------------------
# Rate limiting simples em memória (por chave de API). Para múltiplos
# processos/workers (ex. gunicorn com vários workers), substitua por Redis
# ou por uma tabela na base de dados — isto é suficiente para um único
# processo, como o resto do projecto já assume no rate-limit do login.
# --------------------------------------------------------------------------
_PEDIDOS_POR_CHAVE = {}
LIMITE_PEDIDOS_POR_MINUTO = 60


def _dentro_do_limite(chave_id):
    agora = time.time()
    historico = _PEDIDOS_POR_CHAVE.setdefault(chave_id, [])
    historico[:] = [t for t in historico if agora - t < 60]
    if len(historico) >= LIMITE_PEDIDOS_POR_MINUTO:
        return False
    historico.append(agora)
    return True


def exigir_chave_api(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        chave_recebida = request.headers.get('X-API-Key')
        if not chave_recebida:
            return jsonify({'erro': 'Cabeçalho X-API-Key em falta.'}), 401

        conn = get_connection()
        chaves = conn.execute(
            'SELECT id, chave_hash, nome_integracao, activa FROM api_keys WHERE activa = 1'
        ).fetchall()
        conn.close()

        chave_valida = None
        for c in chaves:
            if check_password_hash(c['chave_hash'], chave_recebida):
                chave_valida = c
                break

        if not chave_valida:
            return jsonify({'erro': 'Chave de API inválida ou inactiva.'}), 401

        if not _dentro_do_limite(chave_valida['id']):
            return jsonify({'erro': 'Limite de pedidos excedido. Tente novamente dentro de um minuto.'}), 429

        g.api_key_id = chave_valida['id']
        g.api_key_nome = chave_valida['nome_integracao']
        return f(*args, **kwargs)
    return decorada


def _paginar(query_base, params, pagina, por_pagina):
    conn = get_connection()
    total = conn.execute(f'SELECT COUNT(*) as n FROM ({query_base})', params).fetchone()['n']
    offset = (pagina - 1) * por_pagina
    linhas = conn.execute(
        f'{query_base} LIMIT ? OFFSET ?', params + [por_pagina, offset]
    ).fetchall()
    conn.close()
    return linhas, total


def _ong_para_json(conn, ong_row):
    ong_id = ong_row['id']
    provincias = [r['provincia'] for r in conn.execute(
        'SELECT provincia FROM ong_provincias WHERE ong_id = ?', (ong_id,)
    ).fetchall()]
    areas = [r['nome'] for r in conn.execute(
        '''SELECT a.nome FROM areas a
           JOIN ong_areas oa ON oa.area_id = a.id
           WHERE oa.ong_id = ?''', (ong_id,)
    ).fetchall()]
    distritos = [r['nome'] for r in conn.execute(
        '''SELECT d.nome FROM distritos d
           JOIN ong_distritos od ON od.distrito_id = d.id
           WHERE od.ong_id = ?''', (ong_id,)
    ).fetchall()]

    return {
        'id': ong_id,
        'nome': ong_row['nome'],
        'sigla': ong_row['sigla'],
        'natureza': ong_row['natureza'],
        'origem': ong_row['origem'],
        'provincia_principal': ong_row['provincia'],
        'provincias': provincias,
        'distritos': distritos,
        'area_intervencao': ong_row['area_intervencao'],
        'areas_tematicas': areas,
        'ano_entrada_pais': ong_row['ano_entrada_pais'],
        'contacto': {
            'pessoa': ong_row['pessoa_contacto'],
            'telefone': ong_row['telefone'],
            'email': ong_row['email'],
        },
    }


@api_bp.route('/ongs', methods=['GET'])
@exigir_chave_api
def listar_ongs_api():
    """Lista ONGs aprovadas, com filtros e paginação.

    Parâmetros de query: provincia, area, q (nome), pagina (default 1),
    por_pagina (default 25, máx. 100).
    """
    provincia = request.args.get('provincia')
    area = request.args.get('area')
    q = request.args.get('q')
    pagina = max(1, request.args.get('pagina', 1, type=int))
    por_pagina = min(100, max(1, request.args.get('por_pagina', 25, type=int)))

    # SELECT DISTINCT o.* — mesma precaução contra duplicação de linhas por
    # JOIN *-to-many já usada na listagem principal do site (app.py).
    query = '''
        SELECT DISTINCT o.* FROM ongs o
        LEFT JOIN ong_provincias op ON op.ong_id = o.id
        LEFT JOIN ong_areas oa ON oa.ong_id = o.id
        LEFT JOIN areas a ON a.id = oa.area_id
        WHERE o.aprovacao = 'Aprovado'
    '''
    params = []
    if provincia:
        query += ' AND op.provincia = ?'
        params.append(provincia)
    if area:
        query += ' AND a.nome = ?'
        params.append(area)
    if q:
        query += ' AND o.nome LIKE ?'
        params.append(f'%{q}%')
    query += ' ORDER BY o.nome'

    linhas, total = _paginar(query, params, pagina, por_pagina)

    conn = get_connection()
    resultado = [_ong_para_json(conn, linha) for linha in linhas]
    conn.close()

    return jsonify({
        'total': total,
        'pagina': pagina,
        'por_pagina': por_pagina,
        'total_paginas': (total + por_pagina - 1) // por_pagina,
        'resultados': resultado,
    })


@api_bp.route('/ongs/<int:ong_id>', methods=['GET'])
@exigir_chave_api
def detalhe_ong_api(ong_id):
    conn = get_connection()
    ong_row = conn.execute(
        "SELECT * FROM ongs WHERE id = ? AND aprovacao = 'Aprovado'", (ong_id,)
    ).fetchone()
    if not ong_row:
        conn.close()
        return jsonify({'erro': 'ONG não encontrada ou não aprovada.'}), 404
    resultado = _ong_para_json(conn, ong_row)
    conn.close()
    return jsonify(resultado)


@api_bp.route('/provincias', methods=['GET'])
@exigir_chave_api
def provincias_api():
    conn = get_connection()
    linhas = conn.execute('''
        SELECT op.provincia AS nome, COUNT(DISTINCT o.id) AS total
        FROM ong_provincias op
        JOIN ongs o ON o.id = op.ong_id
        WHERE o.aprovacao = 'Aprovado'
        GROUP BY op.provincia
        ORDER BY total DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(l) for l in linhas])


@api_bp.route('/areas-tematicas', methods=['GET'])
@exigir_chave_api
def areas_tematicas_api():
    conn = get_connection()
    linhas = conn.execute('''
        SELECT a.nome AS nome, COUNT(DISTINCT oa.ong_id) AS total
        FROM areas a
        JOIN ong_areas oa ON oa.area_id = a.id
        JOIN ongs o ON o.id = oa.ong_id
        WHERE o.aprovacao = 'Aprovado'
        GROUP BY a.nome
        ORDER BY total DESC
    ''').fetchall()
    conn.close()
    return jsonify([dict(l) for l in linhas])


@api_bp.route('/indicadores', methods=['GET'])
@exigir_chave_api
def indicadores_api():
    conn = get_connection()
    total_ongs = conn.execute("SELECT COUNT(*) AS n FROM ongs WHERE aprovacao = 'Aprovado'").fetchone()['n']
    total_pendentes = conn.execute("SELECT COUNT(*) AS n FROM ongs WHERE aprovacao = 'Pendente'").fetchone()['n']
    total_nacionais = conn.execute(
        "SELECT COUNT(*) AS n FROM ongs WHERE aprovacao = 'Aprovado' AND origem = 'Nacional'"
    ).fetchone()['n']
    total_estrangeiras = conn.execute(
        "SELECT COUNT(*) AS n FROM ongs WHERE aprovacao = 'Aprovado' AND origem = 'Estrangeira'"
    ).fetchone()['n']
    total_provincias_cobertas = conn.execute(
        "SELECT COUNT(DISTINCT provincia) AS n FROM ong_provincias"
    ).fetchone()['n']
    conn.close()

    return jsonify({
        'total_ongs_aprovadas': total_ongs,
        'total_pendentes_aprovacao': total_pendentes,
        'total_nacionais': total_nacionais,
        'total_estrangeiras': total_estrangeiras,
        'total_provincias_cobertas': total_provincias_cobertas,
    })


@api_bp.errorhandler(404)
def _api_404(e):
    return jsonify({'erro': 'Endpoint não encontrado.'}), 404
