# executar_rede.py
#
# Inicia o SGIONGs de forma acessível a partir de OUTROS computadores
# ligados à mesma rede (Wi-Fi ou cabo do escritório).
#
# Diferença em relação a "python app.py":
#   - "python app.py"        -> só funciona no teu próprio computador (127.0.0.1)
#   - "python executar_rede.py" -> funciona também nos computadores dos colegas,
#                                   desde que estejam ligados à mesma rede
#
# Usa o Waitress (servidor mais robusto e adequado para deixar a correr durante
# várias horas) em vez do servidor de desenvolvimento do Flask.
#
# Como usar:
#   1. Corre:  python executar_rede.py
#   2. Descobre o IP deste computador: abre outro CMD e escreve "ipconfig",
#      procura "Endereço IPv4" (ex.: 192.168.1.45)
#   3. Nos outros computadores da mesma rede, abrir no browser:
#      http://<o_IP_que_encontraste>:5000

from waitress import serve
from app import app

PORTA = 5000

if __name__ == '__main__':
    print('=' * 60)
    print('SGIONGs disponível na rede local.')
    print(f'Porta: {PORTA}')
    print('Descobre o teu IP com "ipconfig" (campo "Endereço IPv4")')
    print(f'Os colegas acedem em: http://<TEU_IP>:{PORTA}')
    print('Para parar: Ctrl+C')
    print('=' * 60)
    serve(app, host='0.0.0.0', port=PORTA)
