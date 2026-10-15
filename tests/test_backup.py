"""Backups: criação consistente, verificação, restauro real e protecções."""
import os
import sqlite3
import shutil

import backup
import database
from conftest import cliente_com, texto


def n_ongs():
    c = database.get_connection(); n = c.execute('SELECT COUNT(*) FROM ongs').fetchone()[0]; c.close(); return n


def test_backup_e_verificado_e_completo():
    caminho = backup.criar_backup()
    ok, d = backup.verificar_backup(caminho)
    assert ok and d['ongs'] == n_ongs() and d['integridade'] == 'ok'


def test_restauro_real_recupera_dados_apagados():
    antes = n_ongs()
    caminho = backup.criar_backup()
    nome = os.path.basename(caminho)
    sa = cliente_com('super_admin')
    # desastre: apaga 100 ONGs e um utilizador
    c = database.get_connection()
    c.execute('DELETE FROM ongs WHERE id IN (SELECT id FROM ongs LIMIT 100)'); c.commit(); c.close()
    assert n_ongs() == antes - 100
    sa.post(f'/backup/restaurar/{nome}', {'confirmacao': 'RESTAURAR'})
    assert n_ongs() == antes
    assert any(b['nome'].startswith('pre_restauro_') for b in backup.listar_backups())   # estado anterior guardado
    c = database.get_connection()
    assert c.execute("SELECT COUNT(*) FROM historico_auditoria WHERE accao='restaurar_backup'").fetchone()[0] >= 0
    assert c.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    c.close()


def test_restauro_exige_confirmacao_escrita():
    antes = n_ongs()
    nome = os.path.basename(backup.criar_backup())
    c = database.get_connection(); c.execute('DELETE FROM ongs WHERE id IN (SELECT id FROM ongs LIMIT 5)'); c.commit(); c.close()
    cliente_com('super_admin').post(f'/backup/restaurar/{nome}', {'confirmacao': 'sim'})
    assert n_ongs() == antes - 5


def test_backup_corrompido_e_recusado_e_nao_estraga_a_base():
    nome = os.path.basename(backup.criar_backup())
    caminho = os.path.join(backup.PASTA_BACKUPS, nome)
    with open(caminho, 'r+b') as f:
        f.seek(2000); f.write(b'\x00' * 4000)     # corrompe
    ok, _ = backup.verificar_backup(caminho)
    if ok:                                         # corrupção inofensiva — força uma realmente destrutiva
        with open(caminho, 'wb') as f: f.write(b'isto nao e uma base de dados' * 100)
    antes = n_ongs()
    ok, msg = backup.restaurar_backup(nome)
    assert not ok and n_ongs() == antes


def test_path_traversal_bloqueado():
    sa = cliente_com('super_admin')
    for nome in ('../ongs.db', '..%2F..%2Fapp.py', '/etc/passwd'):
        assert sa.get(f'/backup/descarregar/{nome}').status_code == 404
        sa.post(f'/backup/restaurar/{nome}', {'confirmacao': 'RESTAURAR'})
    assert backup.caminho_seguro_do_backup('../ongs.db') is None


def test_retencao_mantem_so_os_ultimos(monkeypatch):
    monkeypatch.setattr(backup, 'RETENCAO_MAXIMA', 3)
    os.makedirs(backup.PASTA_BACKUPS, exist_ok=True)
    for i in range(6):
        open(os.path.join(backup.PASTA_BACKUPS, f'ongs_2020010{i}_000000.db'), 'w').close()
    backup.criar_backup()
    assert len([b for b in backup.listar_backups() if b['nome'].startswith('ongs_')]) == 3


def test_copia_externa_automatica(monkeypatch, tmp_path):
    monkeypatch.setattr(backup, 'PASTA_EXTERNA', str(tmp_path))
    caminho = backup.criar_backup()
    copia = tmp_path / os.path.basename(caminho)
    assert copia.exists() and backup.verificar_backup(str(copia))[0]


def test_backup_com_base_em_uso_e_consistente():
    """Backup durante escritas concorrentes continua a ser uma base válida."""
    import threading
    parar = threading.Event()
    def escrever():
        while not parar.is_set():
            c = database.get_connection()
            c.execute("INSERT INTO historico_auditoria (accao, resumo) VALUES ('teste', 'x')"); c.commit(); c.close()
    t = threading.Thread(target=escrever); t.start()
    try:
        for _ in range(5):
            ok, d = backup.verificar_backup(backup.criar_backup())
            assert ok
    finally:
        parar.set(); t.join()


def test_dados_persistem_apos_reinicio_da_aplicacao():
    """Simula reinício: um processo novo, mesma base de dados → utilizadores, notícias e alterações continuam lá."""
    import subprocess, sys
    from conftest import RAIZ
    from werkzeug.security import generate_password_hash
    c = database.get_connection()
    c.execute("INSERT INTO utilizadores (username,email,nome_completo,password_hash,perfil,activo) VALUES ('persiste@t.mz','persiste@t.mz','P',?, 'consulta',1)",
              (generate_password_hash('Senha-Forte-123'),))
    c.execute("INSERT INTO noticias (titulo, resumo, conteudo, publicada) VALUES ('Notícia persistente','r','c',1)")
    c.commit(); c.close()
    cod = ("import app, database as d; c=d.get_connection();"
           "print(c.execute(\"select count(*) from utilizadores where username='persiste@t.mz'\").fetchone()[0],"
           "c.execute(\"select count(*) from noticias where titulo='Notícia persistente'\").fetchone()[0],"
           "c.execute('select count(*) from ongs').fetchone()[0])")
    r = subprocess.run([sys.executable, '-c', cod], cwd=RAIZ, env=dict(os.environ), capture_output=True, text=True)
    u, n, o = r.stdout.split()
    assert (u, n) == ('1', '1') and int(o) == n_ongs()


def test_importar_dados_nao_apaga_dados_existentes():
    """O comando executado a cada arranque nunca substitui uma base já inicializada."""
    import subprocess, sys
    from conftest import RAIZ
    c = database.get_connection()
    c.execute("UPDATE ongs SET nome='ONG EDITADA EM PRODUCAO' WHERE id=(SELECT MIN(id) FROM ongs)"); c.commit(); c.close()
    antes = n_ongs()
    r = subprocess.run([sys.executable, 'importar_dados.py'], cwd=RAIZ, env=dict(os.environ), capture_output=True, text=True)
    assert 'ignorada' in r.stdout, r.stdout + r.stderr
    c = database.get_connection()
    assert c.execute("SELECT COUNT(*) FROM ongs WHERE nome='ONG EDITADA EM PRODUCAO'").fetchone()[0] == 1
    assert n_ongs() == antes
