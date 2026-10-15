from conftest import texto

def test_paginas_publicas(anonimo):
    for url in ['/', '/ongs', '/organizacoes', '/dashboard', '/noticias', '/login', '/saude', '/levantamento-nacional']:
        r = anonimo.get(url)
        assert r.status_code in (200, 503), (url, r.status_code)

def test_404_amigavel(anonimo):
    r = anonimo.get('/nao-existe')
    assert r.status_code == 404 and 'Página não encontrada' in texto(r)
