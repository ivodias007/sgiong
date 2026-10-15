"""Vários utilizadores ao mesmo tempo."""
import threading
import database
import app as m
from conftest import criar_conta, Cliente, SENHA


def correr_em_paralelo(alvos):
    erros, resultados = [], [None] * len(alvos)
    def envolver(i, f):
        try:
            resultados[i] = f()
        except Exception as e:           # noqa
            erros.append(repr(e))
    ts = [threading.Thread(target=envolver, args=(i, f)) for i, f in enumerate(alvos)]
    [t.start() for t in ts]; [t.join() for t in ts]
    return resultados, erros


def test_mesmo_nome_registado_em_simultaneo_so_cria_uma():
    contas = [criar_conta('operador', email=f'op{i}@teste.mz') for i in range(8)]
    clientes = []
    for i, e in enumerate(contas):
        c = Cliente(ip=f'10.20.0.{i}'); assert c.login(e).status_code == 302; clientes.append(c)
    dados = {'nome': 'ONG Corrida Simultanea', 'provincias': ['Tete'], 'natureza': 'ONG', 'origem': 'Nacional', 'area_intervencao': 'Saúde'}
    _, erros = correr_em_paralelo([lambda c=c: c.post('/ong/novo', dados) for c in clientes])
    assert not erros, erros
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM ongs WHERE nome='ONG Corrida Simultanea'").fetchone()[0] == 1


def test_muitas_escritas_e_leituras_simultaneas_sem_erros():
    contas = [criar_conta('operador', email=f'p{i}@teste.mz') for i in range(6)]
    cls = []
    for i, e in enumerate(contas):
        c = Cliente(ip=f'10.21.0.{i}'); c.login(e); cls.append(c)
    anon = [Cliente(ip=f'10.22.0.{i}') for i in range(6)]
    def escrever(i, c):
        for k in range(5):
            r = c.post('/ong/novo', {'nome': f'ONG Concorrente {i}-{k}', 'provincias': ['Gaza'], 'natureza': 'ONG',
                                      'origem': 'Nacional', 'area_intervencao': 'Saúde'})
            assert r.status_code in (200, 302), r.status_code
    def ler(c):
        for url in ('/ongs', '/dashboard', '/organizacoes?provincia=Sofala', '/chatbot/perguntar?q=quantas+ongs'):
            assert c.get(url).status_code == 200, url
    alvos = [lambda i=i, c=c: escrever(i, c) for i, c in enumerate(cls)] + [lambda c=c: ler(c) for c in anon]
    _, erros = correr_em_paralelo(alvos)
    assert not erros, erros[:3]
    conn = database.get_connection()
    assert conn.execute("SELECT COUNT(*) FROM ongs WHERE nome LIKE 'ONG Concorrente %'").fetchone()[0] == 30
    assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_aprovacao_simultanea_da_mesma_ong_aplica_uma_vez():
    from conftest import cliente_com
    conn = database.get_connection()
    oid = conn.execute("SELECT id FROM ongs WHERE aprovacao='Aprovado' LIMIT 1").fetchone()[0]
    conn.execute("UPDATE ongs SET aprovacao='Pendente', criado_por='alguem' WHERE id=?", (oid,)); conn.commit()
    gs = [cliente_com('gestor_nacional', ip=f'10.23.0.{i}') if False else None for i in range(0)]
    cls = []
    for i in range(5):
        e = criar_conta('gestor_nacional', email=f'gn{i}@teste.mz'); c = Cliente(ip=f'10.23.0.{i}'); c.login(e); cls.append(c)
    _, erros = correr_em_paralelo([lambda c=c: c.post(f'/ong/{oid}/aprovar') for c in cls])
    assert not erros
    assert conn.execute("SELECT COUNT(*) FROM historico_auditoria WHERE accao='aprovar_ong' AND ong_id=?", (oid,)).fetchone()[0] == 1


def test_logins_simultaneos_de_utilizadores_diferentes():
    contas = [criar_conta('consulta', email=f'c{i}@teste.mz') for i in range(10)]
    rs, erros = correr_em_paralelo([lambda e=e, i=i: Cliente(ip=f'10.24.0.{i}').login(e).status_code for i, e in enumerate(contas)])
    assert not erros and all(r == 302 for r in rs)
