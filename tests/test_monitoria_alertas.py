"""Alertas de falhas e rasto de auditoria das acções de gestão."""
import pytest
import alertas
from conftest import cliente_com, criar_conta, texto
import app as app_modulo


@pytest.fixture(autouse=True)
def _limpar():
    alertas._ultimos.clear()
    yield
    alertas._ultimos.clear()


def test_sem_webhook_nao_ha_alerta_nem_promessa_falsa(monkeypatch):
    monkeypatch.delenv('SGIONGS_ALERTA_WEBHOOK', raising=False)
    assert alertas.alertar('x', 'teste') is False
    assert not alertas.alertas_activos()


def test_alerta_enviado_uma_vez_por_intervalo(monkeypatch):
    enviados = []
    monkeypatch.setenv('SGIONGS_ALERTA_WEBHOOK', 'https://exemplo.invalid/hook')
    monkeypatch.setattr(alertas, '_enviar', lambda url, t: enviados.append(t))
    assert alertas.alertar('k', 'falha A', sincrono=True) is True
    assert alertas.alertar('k', 'falha A', sincrono=True) is False      # repetido: suprimido
    assert alertas.alertar('outra', 'falha B', sincrono=True) is True
    assert enviados == ['[SGIONGs] falha A', '[SGIONGs] falha B']


def test_webhook_em_baixo_nao_parte_nada(monkeypatch):
    monkeypatch.setenv('SGIONGS_ALERTA_WEBHOOK', 'http://127.0.0.1:9/nada')
    alertas.alertar('k', 'x', sincrono=True)   # não pode levantar excepção


def test_erro_500_gera_alerta_e_pagina_honesta(monkeypatch):
    enviados = []
    monkeypatch.setenv('SGIONGS_ALERTA_WEBHOOK', 'https://exemplo.invalid/hook')
    monkeypatch.setattr(alertas, '_enviar', lambda url, t: enviados.append(t))
    monkeypatch.setattr(alertas.threading, 'Thread',
                        lambda target, args, daemon: type('T', (), {'start': lambda s: target(*args)})())
    import app as m
    def _rebenta(*a, **k):
        raise RuntimeError('falha provocada')
    monkeypatch.setattr(m.chatbot, 'responder', _rebenta)
    r = m.app.test_client().get('/chatbot/perguntar?q=ola')
    assert r.status_code == 500
    assert 'avisada' in texto(r)
    assert enviados and '/chatbot/perguntar' in enviados[0]


def test_pagina_500_sem_webhook_nao_diz_que_avisou(monkeypatch):
    monkeypatch.delenv('SGIONGS_ALERTA_WEBHOOK', raising=False)
    import app as m
    monkeypatch.setattr(m.chatbot, 'responder', lambda *a, **k: 1 / 0)
    r = m.app.test_client().get('/chatbot/perguntar?q=ola')
    assert r.status_code == 500 and 'avisada' not in texto(r) and 'informada' not in texto(r)


def test_saude_falha_gera_alerta(monkeypatch):
    enviados = []
    monkeypatch.setenv('SGIONGS_ALERTA_WEBHOOK', 'https://exemplo.invalid/hook')
    monkeypatch.setattr(alertas, '_enviar', lambda url, t: enviados.append(t))
    monkeypatch.setattr(alertas.threading, 'Thread',
                        lambda target, args, daemon: type('T', (), {'start': lambda s: target(*args)})())
    import app as m, backup
    monkeypatch.setattr(m, 'PRODUCAO', True)
    monkeypatch.setattr(backup, 'idade_ultimo_backup_horas', lambda: None)
    r = m.app.test_client().get('/saude')
    assert r.status_code == 503 and enviados


def test_backup_rejeitado_gera_alerta(monkeypatch):
    enviados = []
    monkeypatch.setenv('SGIONGS_ALERTA_WEBHOOK', 'https://exemplo.invalid/hook')
    monkeypatch.setattr(alertas, '_enviar', lambda url, t: enviados.append(t))
    monkeypatch.setattr(alertas.threading, 'Thread',
                        lambda target, args, daemon: type('T', (), {'start': lambda s: target(*args)})())
    import backup
    monkeypatch.setattr(backup, 'verificar_backup', lambda c: (False, 'corrompido'))
    assert backup.criar_backup() is None
    assert enviados and 'REJEITADO' in enviados[0]


# ── auditoria das acções de gestão ─────────────────────────────────────────
def _accoes(db):
    return [r[0] for r in db.execute('SELECT accao FROM historico_auditoria').fetchall()]


def test_gestao_de_utilizadores_e_noticias_fica_registada(super_admin, db):
    super_admin.post('/utilizadores/novo', {'email': 'novo@x.mz', 'nome_completo': 'Novo', 'senha': 'Abcdefgh1234', 'perfil': 'consulta'})
    uid = db.execute("SELECT id FROM utilizadores WHERE email='novo@x.mz'").fetchone()[0]
    super_admin.post(f'/utilizadores/{uid}/repor-senha')
    super_admin.post(f'/utilizadores/{uid}/email', {'email': 'novo2@x.mz'})
    super_admin.post(f'/utilizadores/{uid}/desactivar')
    super_admin.post('/utilizadores/gestores-provinciais', {'dominio': 'mpd.gov.mz'})
    super_admin.post('/admin/noticias/nova', {'titulo': 'Titulo', 'resumo': 'r', 'corpo': 'c'})
    super_admin.post('/admin/capa', {'remover': '1'})
    linhas = db.execute('SELECT accao, resumo, utilizador, ip, data_hora FROM historico_auditoria').fetchall() \
        if False else db.execute('SELECT * FROM historico_auditoria').fetchall()
    accoes = _accoes(db)
    assert len(accoes) >= 6, accoes
    for l in linhas:
        assert l['utilizador'] or l['accao'] in ('erro_sistema', 'login_falhado'), dict(l)
