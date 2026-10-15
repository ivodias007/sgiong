"""
alertas.py — Avisos automáticos de falhas.

Se SGIONGS_ALERTA_WEBHOOK estiver definido (URL de um canal Slack/Teams/Discord/
Mattermost ou de um serviço próprio que aceite JSON com o campo "text"), cada
falha grave é enviada para lá. Sem webhook, a falha fica apenas nos registos
(data/logs/erros.log) e na auditoria — e a página de erro NÃO afirma que alguém
foi avisado (ver alertas_activos()).

Evita inundar o canal: a mesma mensagem só é reenviada após 10 minutos.
Nunca levanta excepções (um alerta falhado não pode agravar a falha original).
"""
import json
import logging
import os
import threading
import time
import urllib.request

log = logging.getLogger('sgiongs.alertas')
INTERVALO = 600
_ultimos = {}
_lock = threading.Lock()


def webhook():
    return (os.environ.get('SGIONGS_ALERTA_WEBHOOK') or '').strip() or None


def alertas_activos():
    return webhook() is not None


def _enviar(url, texto):
    try:
        pedido = urllib.request.Request(url, data=json.dumps({'text': texto, 'content': texto}).encode('utf-8'),
                                        headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(pedido, timeout=8).read()
    except Exception as e:  # noqa: BLE001
        log.error('Não consegui enviar o alerta: %r', e)


def alertar(chave, mensagem, sincrono=False):
    """Envia `mensagem` (uma vez por INTERVALO para a mesma `chave`). Devolve True se enviou/agendou."""
    url = webhook()
    if not url:
        return False
    agora = time.time()
    with _lock:
        if agora - _ultimos.get(chave, 0) < INTERVALO:
            return False
        _ultimos[chave] = agora
    texto = f'[SGIONGs] {mensagem}'
    if sincrono:
        _enviar(url, texto)
    else:
        threading.Thread(target=_enviar, args=(url, texto), daemon=True).start()
    return True
