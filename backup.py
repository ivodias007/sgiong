"""
backup.py — Backup automático e manual da base de dados do SGIONGs.

AVISO IMPORTANTE SOBRE O RENDER (PLANO GRATUITO)
-------------------------------------------------
O disco do Render, no plano gratuito, NÃO é persistente entre deploys —
cada novo deploy (ou reinício do serviço) começa com um disco limpo, feito
a partir do código e dos CSVs em data/, não dos ficheiros escritos em
tempo de execução (como esta pasta backups/). Isto significa que os
backups gerados por este módulo protegem contra:
  - Erros humanos durante a sessão em curso (apagar/estragar dados por engano)
  - Poder restaurar rapidamente sem re-importar tudo do zero
Mas NÃO protegem, por si só, contra a perda do disco num redeploy. Para
uma cópia verdadeiramente segura: (1) use um disco persistente
(SGIONGS_DATA_DIR) e (2) defina SGIONGS_BACKUP_EXTRA_DIR para uma pasta
EXTERNA ao servidor (volume de rede, outro disco, pasta sincronizada),
onde cada backup é copiado automaticamente. Cada backup é VERIFICADO
(integrity_check + contagens) logo depois de criado, e pode ser restaurado
em /backup (guarda antes uma cópia de segurança do estado actual).
"""

import os
import glob
import shutil
import sqlite3
import logging
import zipfile
from datetime import datetime

import database
from database import DB_PATH, BASE_DIR, DATA_DIR

log = logging.getLogger('sgiongs.backup')

PASTA_BACKUPS = os.environ.get('SGIONGS_BACKUP_DIR') or os.path.join(DATA_DIR, 'backups')
PASTA_EXTERNA = os.environ.get('SGIONGS_BACKUP_EXTRA_DIR') or None
RETENCAO_MAXIMA = 14  # mantém sempre os últimos 14 backups, apaga os mais antigos
PASTA_UPLOADS = os.path.join(BASE_DIR, 'static', 'uploads')


def _garantir_pasta():
    os.makedirs(PASTA_BACKUPS, exist_ok=True)


def _contagens(caminho):
    conn = sqlite3.connect(caminho)
    try:
        r = {'integridade': conn.execute('PRAGMA integrity_check').fetchone()[0]}
        for t in ('ongs', 'utilizadores', 'noticias', 'historico_auditoria'):
            try:
                r[t] = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
            except sqlite3.DatabaseError:
                r[t] = None
        return r
    finally:
        conn.close()


def verificar_backup(caminho):
    """(ok, detalhes). Um backup é válido se abre, passa o integrity_check e
    tem a tabela de ONGs."""
    try:
        d = _contagens(caminho)
    except sqlite3.DatabaseError as e:
        return False, {'erro': str(e)}
    return (d['integridade'] == 'ok' and d['ongs'] is not None), d


def criar_backup(prefixo='ongs'):
    """Cópia CONSISTENTE (API de backup do SQLite — segura mesmo com a base em
    uso), verificada, e copiada para a pasta externa se configurada. Devolve o
    caminho do backup, ou None se não houver BD ou se a verificação falhar."""
    _garantir_pasta()
    if not os.path.exists(DB_PATH):
        return None
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    destino = os.path.join(PASTA_BACKUPS, f'{prefixo}_{timestamp}.db')
    temp = destino + '.tmp'
    origem = sqlite3.connect(DB_PATH)
    copia = sqlite3.connect(temp)
    try:
        origem.backup(copia)
    finally:
        copia.close()
        origem.close()
    ok, detalhes = verificar_backup(temp)
    if not ok:
        os.remove(temp)
        log.error('Backup REJEITADO na verificação: %s', detalhes)
        try:
            import alertas
            alertas.alertar('backup', f'Backup REJEITADO na verificação: {detalhes}')
        except Exception:  # noqa: BLE001
            pass
        return None
    os.replace(temp, destino)
    if prefixo == 'ongs':
        _aplicar_retencao()
        _copiar_para_externa(destino)
    return destino


def _copiar_para_externa(caminho):
    if not PASTA_EXTERNA:
        return
    try:
        os.makedirs(PASTA_EXTERNA, exist_ok=True)
        shutil.copy2(caminho, os.path.join(PASTA_EXTERNA, os.path.basename(caminho)))
        # uploads (logótipos, imagens de notícias) — um zip por dia
        if os.path.isdir(PASTA_UPLOADS):
            zip_destino = os.path.join(PASTA_EXTERNA, f'uploads_{datetime.now():%Y%m%d}.zip')
            with zipfile.ZipFile(zip_destino, 'w', zipfile.ZIP_DEFLATED) as z:
                for raiz, _, fich in os.walk(PASTA_UPLOADS):
                    for f in fich:
                        c = os.path.join(raiz, f)
                        z.write(c, os.path.relpath(c, PASTA_UPLOADS))
        ficheiros = sorted(glob.glob(os.path.join(PASTA_EXTERNA, 'ongs_*.db')))
        for velho in ficheiros[:-RETENCAO_MAXIMA]:
            os.remove(velho)
    except OSError as e:
        log.error('Falha ao copiar o backup para a pasta externa %s: %s', PASTA_EXTERNA, e)


def _aplicar_retencao():
    ficheiros = sorted(glob.glob(os.path.join(PASTA_BACKUPS, 'ongs_*.db')))
    excedentes = ficheiros[:-RETENCAO_MAXIMA] if len(ficheiros) > RETENCAO_MAXIMA else []
    for caminho in excedentes:
        os.remove(caminho)


def listar_backups():
    _garantir_pasta()
    ficheiros = sorted(glob.glob(os.path.join(PASTA_BACKUPS, '*.db')), reverse=True)
    resultado = []
    for caminho in ficheiros:
        info = os.stat(caminho)
        resultado.append({
            'nome': os.path.basename(caminho),
            'tamanho_kb': round(info.st_size / 1024, 1),
            'criado_em': datetime.fromtimestamp(info.st_mtime).strftime('%d/%m/%Y %H:%M'),
        })
    return resultado


def idade_ultimo_backup_horas():
    ficheiros = glob.glob(os.path.join(PASTA_BACKUPS, 'ongs_*.db'))
    if not ficheiros:
        return None
    ultimo = max(os.path.getmtime(f) for f in ficheiros)
    return (datetime.now().timestamp() - ultimo) / 3600


def caminho_seguro_do_backup(nome_ficheiro):
    """Valida que o nome pedido corresponde mesmo a um backup existente,
    para impedir Path Traversal (ex.: nome_ficheiro='../../app.py')."""
    nomes_validos = {b['nome'] for b in listar_backups()}
    if nome_ficheiro not in nomes_validos:
        return None
    return os.path.join(PASTA_BACKUPS, nome_ficheiro)


def restaurar_backup(nome_ficheiro):
    """Repõe a base de dados a partir de um backup. Antes, VERIFICA o backup e
    guarda o estado actual em pre_restauro_*.db (para se poder desfazer).
    Devolve (ok, mensagem)."""
    caminho = caminho_seguro_do_backup(nome_ficheiro)
    if not caminho:
        return False, 'Backup não encontrado.'
    ok, detalhes = verificar_backup(caminho)
    if not ok:
        return False, f'O backup está corrompido e não foi restaurado ({detalhes}).'
    seguranca = criar_backup(prefixo='pre_restauro') if os.path.exists(DB_PATH) else None
    origem = sqlite3.connect(caminho)
    destino = sqlite3.connect(DB_PATH, timeout=30)
    try:
        origem.backup(destino)
    finally:
        destino.close()
        origem.close()
    database.init_db()  # aplica migrações caso o backup seja de uma versão mais antiga
    return True, (f'Base de dados restaurada ({detalhes["ongs"]} ONGs, {detalhes["utilizadores"]} utilizadores). '
                  f'Estado anterior guardado em {os.path.basename(seguranca) if seguranca else "—"}.')


# ─── AGENDAMENTO ──────────────────────────────────────────────────────────────
_agendador = None


def iniciar_agendamento_diario(hora=2, minuto=0):
    """Agenda um backup automático diário. Chamar uma única vez, a partir
    de app.py, protegido contra o duplo arranque do recarregador do Flask
    em modo debug (ver app.py)."""
    global _agendador
    if _agendador is not None:
        return _agendador

    from apscheduler.schedulers.background import BackgroundScheduler
    _agendador = BackgroundScheduler(daemon=True)
    def _backup_diario():
        try:
            if criar_backup() is None:
                raise RuntimeError('o backup diário não foi criado')
        except Exception as e:  # noqa: BLE001
            log.error('Backup diário falhou: %r', e)
            import alertas
            alertas.alertar('backup_diario', f'Backup diário FALHOU: {e!r}')

    _agendador.add_job(_backup_diario, 'cron', hour=hora, minute=minuto, id='backup_diario')
    _agendador.start()
    return _agendador
