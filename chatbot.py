"""chatbot.py — Assistente de perguntas e respostas rápidas do SGIONGs.

Sem IA externa: faz correspondência por palavras-chave (sem acentos) sobre uma
lista de perguntas frequentes, e responde a duas perguntas com dados reais da
base (quantas ONGs há, e quantas há numa província).
"""
from tagging import normalizar, PROVINCIAS

SUGESTOES = [
    'O que é o SGIONGs?',
    'Quantas ONGs estão registadas?',
    'Como pesquisar uma ONG?',
    'Como registar uma ONG?',
    'Esqueci a palavra-passe',
    'O que é uma ONG, OSC e Fundação?',
]

# (palavras-chave, pergunta, resposta, ligação opcional (rótulo, url))
FAQ = [
    (['o que e', 'sgiongs', 'sistema', 'para que serve'],
     'O que é o SGIONGs?',
     'O SGIONGs é o Sistema de Gestão de Informação de ONGs do Ministério da Planificação e Desenvolvimento (Direcção Nacional de Promoção do Desenvolvimento Integrado). Reúne o registo das ONGs que actuam nas 11 províncias, por distrito e área temática.',
     ('Ver o painel de indicadores', '/dashboard')),
    (['pesquisar', 'procurar', 'encontrar', 'listagem', 'filtrar', 'buscar'],
     'Como pesquisar uma ONG?',
     'Abra "Pesquisar ONGs" (Listagem), escreva o nome ou a sigla e filtre por província — ao escolher a província aparece logo a caixa de distritos. Também pode filtrar por área temática, natureza e origem.',
     ('Abrir a listagem', '/ongs')),
    (['registar', 'registo', 'cadastrar', 'nova ong', 'adicionar ong', 'criar ong'],
     'Como registar uma ONG?',
     'É preciso ter sessão iniciada. Vá a "Nova ONG" e preencha o formulário: só o nome é obrigatório. Não é possível registar duas ONGs com o mesmo nome. Pode guardar como rascunho e submeter depois; o registo segue para aprovação.',
     ('Nova ONG', '/ong/novo')),
    (['palavra passe', 'senha', 'password', 'esqueci', 'recuperar', 'nao consigo entrar', 'login', 'entrar'],
     'Esqueci a palavra-passe / não consigo entrar',
     'O acesso é feito com o seu e-mail. Se esqueceu a palavra-passe, use "Esqueci a minha senha" no ecrã de entrada (quando disponível) e siga a ligação enviada para o seu e-mail; senão, peça ao Administrador para a repor. Se perdeu o telemóvel do 2FA, use um dos seus códigos de recuperação ou peça ao Administrador para repor o 2FA.',
     ('Acesso interno', '/login')),
    (['alterar senha', 'mudar senha', 'mudar palavra', 'trocar senha', 'minha conta', '2fa', 'autenticacao'],
     'Como alterar a minha palavra-passe ou activar o 2FA?',
     'Com sessão iniciada, abra "A minha conta" no menu: aí altera a palavra-passe e pode activar a verificação em dois passos (2FA) com uma aplicação autenticadora e gerar códigos de recuperação. O 2FA é obrigatório para Super Administradores e Administradores.',
     ('A minha conta', '/conta')),
    (['ong', 'osc', 'fundacao', 'natureza', 'diferenca'],
     'O que é uma ONG, OSC e Fundação?',
     'São as três naturezas usadas no sistema: ONG (Organização Não Governamental), OSC (Organização da Sociedade Civil) e Fundação. Uma organização pode ter mais do que uma natureza. Os números de cada tipo aparecem no painel de indicadores.',
     None),
    (['mapa', 'indicadores', 'dashboard', 'painel', 'grafico', 'percentagem'],
     'Como funciona o mapa e os indicadores?',
     'O painel mostra o mapa de Moçambique por província e distrito, com o número de ONGs e a percentagem. Clique numa província para ver os seus distritos, e num distrito para filtrar os indicadores.',
     ('Abrir o painel', '/dashboard')),
    (['aprovar', 'aprovacao', 'pendente', 'workflow', 'validar'],
     'Como funciona a aprovação?',
     'Os registos e edições entram como "Pendentes" e são revistos por quem tem perfil de aprovação (Gestor Provincial, Gestor Nacional, Administrador). Ninguém aprova o que ele próprio submeteu.',
     None),
    (['duplicad', 'repetid', 'mesmo nome'],
     'E se a ONG já existir? (duplicados)',
     'O sistema não aceita duas ONGs com o mesmo nome e avisa enquanto escreve. Nomes parecidos aparecem agrupados em "Possíveis Duplicados" para o gestor decidir.',
     ('Possíveis duplicados', '/duplicados')),
    (['sobreposicao', 'mesmo trabalho', 'mesmo distrito', 'alerta', 'notificac'],
     'O que é a sobreposição de actuação?',
     'É o alerta que aparece quando duas ou mais ONGs trabalham na mesma área temática no mesmo distrito, para facilitar a coordenação. Vê-se no sino de notificações e na página "Sobreposição de Actuação" (perfis de gestão).',
     None),
    (['provincial', 'gestor', 'perfil', 'permiss', 'quem pode'],
     'Quem pode fazer o quê?',
     'Super Administrador e Administrador gerem tudo (incluindo utilizadores e notícias); Gestor Nacional vê e aprova todo o país; Gestor Provincial só a sua província; Operador regista e edita; Consulta só visualiza.',
     None),
    (['relatorio', 'exportar', 'pdf', 'excel', 'descarregar'],
     'Como exportar relatórios?',
     'Em "Relatórios" gera PDF e Excel com os indicadores e a listagem, com os filtros que escolher.',
     ('Relatórios', '/relatorios')),
    (['noticia', 'novidade'],
     'Onde vejo as notícias?',
     'Na página inicial e no menu "Notícias". Os administradores publicam e editam as notícias em "Gerir notícias".',
     ('Notícias', '/noticias')),
    (['importar', 'excel', 'matriz', 'carregar dados'],
     'Como importar dados em Excel?',
     'Os administradores usam "Importar" para carregar uma matriz Excel/CSV: o sistema mostra uma pré-visualização com avisos e erros antes de gravar.',
     None),
    (['logotipo', 'logo', 'imagem'],
     'Como colocar o logótipo de uma ONG?',
     'No formulário da ONG há o campo "Logótipo": envie PNG, JPG, SVG ou WEBP até 2 MB.',
     None),
    (['contacto', 'ajuda', 'suporte', 'telefone', 'falar'],
     'Contactos e apoio',
     'Para apoio, contacte a Direcção Nacional de Promoção do Desenvolvimento Integrado do Ministério da Planificação e Desenvolvimento, ou o Administrador do sistema.',
     None),
]


def _pontuar(pergunta_norm, palavras):
    pontos = 0
    for p in palavras:
        if p in pergunta_norm:
            pontos += 2 if ' ' in p else 1
    return pontos


def responder(conn, pergunta):
    q = normalizar(pergunta or '')
    if not q:
        return {'resposta': 'Escreva uma pergunta ou escolha uma das sugestões.', 'sugestoes': SUGESTOES}

    # 1) Dados reais: quantas ONGs (no país ou numa província)
    if any(x in q for x in ('quantas', 'quantos', 'numero de', 'total')) and 'ong' in q or 'quantas' in q:
        for prov in PROVINCIAS:
            if normalizar(prov) in q:
                n = conn.execute("SELECT COUNT(DISTINCT op.ong_id) c FROM ong_provincias op JOIN ongs o ON o.id=op.ong_id "
                                 "WHERE o.aprovacao='Aprovado' AND op.provincia=?", (prov,)).fetchone()['c']
                return {'resposta': f'Há {n} ONGs aprovadas a actuar em {prov}.',
                        'ligacao': ['Ver a lista de ' + prov, '/ongs?provincia=' + prov], 'sugestoes': SUGESTOES[:3]}
        n = conn.execute("SELECT COUNT(*) c FROM ongs WHERE aprovacao='Aprovado'").fetchone()['c']
        np_ = conn.execute('SELECT COUNT(DISTINCT provincia) c FROM ong_provincias').fetchone()['c']
        nd = conn.execute('SELECT COUNT(DISTINCT distrito_id) c FROM ong_distritos').fetchone()['c']
        return {'resposta': f'Há {n} ONGs aprovadas no sistema, com actuação em {np_} províncias e {nd} distritos.',
                'ligacao': ['Ver o painel', '/dashboard'], 'sugestoes': SUGESTOES[:3]}

    # 2) FAQ por palavras-chave
    melhor, melhor_pts = None, 0
    for palavras, titulo, resposta, ligacao in FAQ:
        pts = _pontuar(q, palavras)
        if pts > melhor_pts:
            melhor, melhor_pts = (titulo, resposta, ligacao), pts
    if melhor:
        out = {'resposta': melhor[1], 'sugestoes': SUGESTOES[:4]}
        if melhor[2]:
            out['ligacao'] = list(melhor[2])
        return out

    return {'resposta': 'Não encontrei uma resposta para isso. Experimente reformular, ou escolha uma das perguntas abaixo.',
            'sugestoes': SUGESTOES}
