# wsgi.py
# Ponto de entrada para publicar o SGIONGs na internet (Render, Railway, etc.)
#
# Diferença em relação a "executar_rede.py":
#   - Este ficheiro lê a porta a partir da variável de ambiente PORT,
#     que é definida automaticamente pelos serviços de alojamento na nuvem.
#     Localmente (no teu PC), continua a usar-se "python app.py" ou
#     "python executar_rede.py" normalmente — este ficheiro só é
#     necessário quando publicas o site na internet.

import os
from waitress import serve
from app import app  # o app.py já garante a criação da base de dados sozinho

if __name__ == '__main__':
    porta = int(os.environ.get('PORT', 5000))
    serve(app, host='0.0.0.0', port=porta)
