"""
emails.py — Envio de e-mail (SMTP) para a recuperação de senhas.

Configuração por variáveis de ambiente (pedir ao TI do Ministério):
  SGIONGS_SMTP_HOST, SGIONGS_SMTP_PORT (587 por omissão, STARTTLS), SGIONGS_SMTP_USER,
  SGIONGS_SMTP_PASSWORD, SGIONGS_SMTP_FROM (remetente), SGIONGS_URL_BASE (endereço público,
  p. ex. https://sgiong.mpd.gov.mz — usado nas ligações enviadas).
Sem SMTP configurado a recuperação por e-mail fica desligada e a recuperação faz-se
por um administrador (ver docs/MANUAL_ADMINISTRACAO.md).
"""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger('sgiongs.emails')


def disponivel():
    return bool(os.environ.get('SGIONGS_SMTP_HOST') and os.environ.get('SGIONGS_SMTP_FROM'))


def url_base(fallback):
    return (os.environ.get('SGIONGS_URL_BASE') or fallback).rstrip('/')


def enviar(para, assunto, corpo):
    """True se o servidor aceitou a mensagem. Nunca levanta excepções."""
    if not disponivel():
        return False
    try:
        msg = EmailMessage()
        msg['From'] = os.environ['SGIONGS_SMTP_FROM']
        msg['To'] = para
        msg['Subject'] = assunto
        msg.set_content(corpo)
        host = os.environ['SGIONGS_SMTP_HOST']
        porta = int(os.environ.get('SGIONGS_SMTP_PORT', '587'))
        ctx = ssl.create_default_context()
        if porta == 465:
            servidor = smtplib.SMTP_SSL(host, porta, timeout=15, context=ctx)
        else:
            servidor = smtplib.SMTP(host, porta, timeout=15)
            servidor.starttls(context=ctx)
        with servidor:
            if os.environ.get('SGIONGS_SMTP_USER'):
                servidor.login(os.environ['SGIONGS_SMTP_USER'], os.environ.get('SGIONGS_SMTP_PASSWORD', ''))
            servidor.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001
        log.error('Falha ao enviar e-mail: %r', e)
        return False
