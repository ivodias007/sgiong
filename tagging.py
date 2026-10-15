# tagging.py
# Lógica partilhada: normalização de texto, lista oficial de províncias/distritos
# de Moçambique e deteção automática de província/distritos/áreas a partir de
# texto livre (usado pelo importador e pela aplicação web).

import unicodedata

PROVINCIAS = [
    'Niassa', 'Cabo Delgado', 'Nampula', 'Zambézia', 'Tete', 'Manica',
    'Sofala', 'Gaza', 'Inhambane', 'Maputo Província', 'Maputo Cidade',
]

PROVINCIA_ALIASES = {
    'Niassa': ['niassa'],
    'Cabo Delgado': ['cabo delgado', 'c. delgado', 'c delgado', 'cdelgado'],
    'Nampula': ['nampula'],
    'Zambézia': ['zambezia'],
    'Tete': ['tete'],
    'Manica': ['manica'],
    'Sofala': ['sofala'],
    'Gaza': ['gaza'],
    'Inhambane': ['inhambane'],
    'Maputo Província': ['maputo provincia', 'maputo prov.', 'maputo prov'],
    'Maputo Cidade': ['maputo cidade', 'cidade de maputo'],
}

DISTRITOS_POR_PROVINCIA = {
    'Niassa': {
        'Chimbonila': ['chimbonila'], 'Cuamba': ['cuamba'], 'Lago': ['lago'],
        'Lichinga': ['lichinga'], 'Majune': ['majune'], 'Mandimba': ['mandimba'],
        'Marrupa': ['marrupa'], 'Maúa': ['maua'], 'Mavago': ['mavago'],
        'Mecanhelas': ['mecanhelas'], 'Mecula': ['mecula'], 'Metarica': ['metarica'],
        'Muembe': ['muembe'], "N'gauma": ['ngauma', "n'gauma"], 'Nipepe': ['nipepe'],
        'Sanga': ['sanga'],
    },
    'Cabo Delgado': {
        'Ancuabe': ['ancuabe'], 'Balama': ['balama'], 'Chiúre': ['chiure'],
        'Ibo': ['ibo'], 'Macomia': ['macomia'], 'Mecúfi': ['mecufi'],
        'Meluco': ['meluco'], 'Metuge': ['metuge'],
        'Mocímboa da Praia': ['mocimboa', 'm. da praia', 'm da praia', 'mdapraia', 'micimboa'], 'Montepuez': ['montepuez'],
        'Mueda': ['mueda'], 'Muidumbe': ['muidumbe'], 'Namuno': ['namuno'],
        'Nangade': ['nangade'], 'Palma': ['palma'], 'Pemba': ['pemba'],
        'Quissanga': ['quissanga'],
    },
    'Nampula': {
        'Angoche': ['angoche'], 'Eráti': ['erati'],
        'Ilha de Moçambique': ['ilha de mocambique'], 'Lalaua': ['lalaua'],
        'Larde': ['larde'], 'Liúpo': ['liupo'], 'Malema': ['malema'],
        'Meconta': ['meconta'], 'Mecubúri': ['mecuburi'], 'Memba': ['memba'],
        'Mogincual': ['mogincual'], 'Mogovolas': ['mogovolas'], 'Moma': ['moma'],
        'Monapo': ['monapo'], 'Mossuril': ['mossuril'], 'Muecate': ['muecate'],
        'Murrupula': ['murrupula'], 'Nacala-a-Velha': ['nacala-a-velha', 'nacala a velha'],
        'Nacala Porto': ['nacala porto', 'nacala-porto'], 'Nacarôa': ['nacaroa'],
        'Nampula': ['nampula'], 'Rapale': ['rapale'], 'Ribaué': ['ribaue'],
    },
    'Zambézia': {
        'Alto Molócue': ['alto molocue'], 'Chinde': ['chinde'], 'Derre': ['derre'],
        'Gilé': ['gile'], 'Gurué': ['gurue'], 'Ile': ['ile'],
        'Inhassunge': ['inhassunge'], 'Luabo': ['luabo'], 'Lugela': ['lugela'],
        'Maganja da Costa': ['maganja da costa'], 'Milange': ['milange'],
        'Mocuba': ['mocuba'], 'Mocubela': ['mocubela'], 'Molumbo': ['molumbo'],
        'Mopeia': ['mopeia'], 'Morrumbala': ['morrumbala'], 'Mulevala': ['mulevala'],
        'Namacurra': ['namacurra'], 'Namarroi': ['namarroi'], 'Nicoadala': ['nicoadala'],
        'Pebane': ['pebane'], 'Quelimane': ['quelimane'],
    },
    'Tete': {
        'Angónia': ['angonia'], 'Cahora-Bassa': ['cahora-bassa', 'cahora bassa'],
        'Changara': ['changara'], 'Chifunde': ['chifunde'], 'Chiuta': ['chiuta'],
        'Dôa': ['doa'], 'Macanga': ['macanga'], 'Magoé': ['magoe'],
        'Marara': ['marara'], 'Marávia': ['maravia'], 'Moatize': ['moatize'],
        'Mutarara': ['mutarara'], 'Tete': ['tete'], 'Tsangano': ['tsangano'],
        'Zumbo': ['zumbo'],
    },
    'Manica': {
        'Bárue': ['barue'], 'Chimoio': ['chimoio'], 'Gondola': ['gondola'],
        'Guro': ['guro'], 'Machaze': ['machaze'], 'Macate': ['macate'],
        'Macossa': ['macossa'], 'Manica': ['manica'], 'Mossurize': ['mossurize'],
        'Sussundenga': ['sussundenga'], 'Tambara': ['tambara'], 'Vanduzi': ['vanduzi'],
    },
    'Sofala': {
        'Beira': ['beira'], 'Búzi': ['buzi'], 'Caia': ['caia'],
        'Chemba': ['chemba'], 'Cheringoma': ['cheringoma'], 'Chibabava': ['chibabava'],
        'Dondo': ['dondo'], 'Gorongosa': ['gorongosa'], 'Machanga': ['machanga'],
        'Maringué': ['maringue'], 'Marromeu': ['marromeu'], 'Muanza': ['muanza'],
        'Nhamatanda': ['nhamatanda'],
    },
    'Gaza': {
        'Bilene': ['bilene'], 'Chibuto': ['chibuto'], 'Chicualacuala': ['chicualacuala'],
        'Chigubo': ['chigubo'], 'Chókwè': ['chokwe', 'chokwé'], 'Chongoene': ['chongoene'],
        'Guijá': ['guija'], 'Limpopo': ['limpopo'], 'Mabalane': ['mabalane'],
        'Mandlakazi': ['mandlakazi', 'manjacaze', 'mandlacaze'], 'Massangena': ['massangena'],
        'Massingir': ['massingir', 'massinguir'], 'Xai-Xai': ['xai-xai', 'xai xai', 'xaixai'],
    },
    'Inhambane': {
        'Funhalouro': ['funhalouro'], 'Govuro': ['govuro'], 'Homoíne': ['homoine'],
        'Inharrime': ['inharrime'], 'Inhambane': ['inhambane'], 'Inhassoro': ['inhassoro'],
        'Jangamo': ['jangamo'], 'Mabote': ['mabote'], 'Massinga': ['massinga'],
        'Maxixe': ['maxixe'], 'Morrumbene': ['morrumbene'], 'Panda': ['panda'],
        'Vilanculos': ['vilanculos', 'vilankulo'], 'Zavala': ['zavala'],
    },
    'Maputo Província': {
        'Boane': ['boane'], 'Magude': ['magude'], 'Manhiça': ['manhica'],
        'Marracuene': ['marracuene'], 'Matola': ['matola'], 'Matutuíne': ['matutuine'],
        'Moamba': ['moamba'], 'Namaacha': ['namaacha'],
    },
    'Maputo Cidade': {
        'KaMpfumo': ['kampfumo'], 'Nlhamankulu': ['nlhamankulu'],
        'KaMaxaquene': ['kamaxaquene'], 'KaMavota': ['kamavota'],
        'KaMubukwana': ['kamubukwana'], 'KaTembe': ['katembe'], 'KaNyaka': ['kanyaka'],
    },
}

ESTRUTURA_AREAS_TEMATICAS = {
    'Educação': {
        'Construção e Apetrechamento de Infraestruturas Escolares': [
            'construcao escolar', 'construcao de salas de aula', 'apetrechamento de salas',
            'apetrechamento escolar', 'infraestrutura escolar', 'sala de aula', 'biblioteca',
            'reabilitacao de escola', 'construcao de escola',
        ],
        'Alimentação Escolar': [
            'alimentacao escolar', 'lanche escolar', 'merenda escolar', 'refeicao escolar',
        ],
        'Fornecimento de Material Didáctico': [
            'material didactico', 'material escolar', 'kit escolar', 'livros escolares',
            'uniforme escolar',
        ],
        'Treinamento e Capacitação': [
            'treinamento', 'capacitacao', 'formacao de professores', 'formacao docente',
            'alfabetizacao', 'educac', 'matricula', 'pedagog', 'docente', 'professor',
        ],
    },
    'Saúde': {
        'Construção de Infraestruturas Hospitalares': [
            'construcao hospitalar', 'infraestrutura hospitalar', 'centro de saude',
            'unidade sanitaria', 'hospital', 'clinica', 'posto de saude', 'farmacia',
            'laboratorio',
        ],
        'Prevenção e Tratamento de Doenças de Saúde Pública': [
            'prevencao de doencas', 'saude publica', 'malaria', 'colera', 'epidemia',
            'vacinacao', 'vacina', 'doencas transmissiveis', 'doencas nao transmissiveis',
        ],
        'Prevenção e Assistência do HIV': [
            'hiv', 'sida', 'aids', 'antiretroviral', 'tarv', 'preservativo',
        ],
        'Saúde Sexual e Reprodutiva': [
            'saude sexual', 'saude reprodutiva', 'planeamento familiar', 'circuncisao',
        ],
        'Despiste e Seguimento de TB': [
            'tuberculose', ' tb ', 'despiste de tb', 'tuberculos',
        ],
        'Nutrição e Saúde Materno Infantil': [
            'nutric', 'saude materno infantil', 'materno infantil', 'desnutricao', 'smi',
            'saude da crianca', 'saude da mulher',
        ],
    },
    'Agricultura e Segurança Alimentar': {
        'Construção e Manutenção de Infraestruturas Agrárias': [
            'infraestrutura agraria', 'irrigac', 'regadio', 'represa', 'furo agricola',
            'sistema de rega',
        ],
        'Serviços de Extensão': [
            'extensao rural', 'extensao agraria', 'servicos de extensao', 'extensionista',
        ],
        'Produção de Sementes': [
            'producao de sementes', 'multiplicacao de sementes', 'banco de sementes',
        ],
        'Disponibilização de Insumos': [
            'insumos agricolas', 'insumos', 'fertilizantes', 'pesticidas',
            'ferramentas agricolas', 'alfaias agricolas',
        ],
        'Processamento e Comercialização': [
            'processamento', 'comercializacao', 'agro processamento', 'valor agregado',
            'pos colheita',
        ],
        'Estabelecimento e Assistência de Cooperativas e Associações': [
            'cooperativa', 'associacao de camponeses', 'associativismo agricola',
            'agricultura', 'agricola', 'agro', 'pesca', 'sementes', 'pecuari',
        ],
    },
    'Conservação e Meio Ambiente': {
        'Maneio Comunitário': [
            'maneio comunitario', 'maneio de recursos naturais', 'gestao comunitaria de recursos',
            'conservacao', 'florest', 'reflorest', 'ambiente', 'climatic',
        ],
        'Gestão de Resíduos Sólidos': [
            'residuos solidos', 'gestao de residuos', 'lixo', 'reciclagem', 'saneamento do meio',
        ],
    },
    'Acção Social': {
        'Empoderamento e Empreendedorismo': [
            'empoderamento', 'empreendedorismo', 'geracao de renda', 'autoemprego',
        ],
        'Apoio a Pessoas com Deficiência e Idosos': [
            'pessoas com deficiencia', 'deficiencia', 'idosos', 'terceira idade',
        ],
        'Apoio a Crianças Vulneráveis': [
            'criancas vulneraveis', 'orfaos', 'covs', 'crianca vulneravel', 'apadrinha',
        ],
        'Desenvolvimento Comunitário': [
            'desenvolvimento comunitario', 'mobilizacao comunitaria', 'organizacao comunitaria',
            'assistencia social',
        ],
    },
    'Ajuda Humanitária': {
        'Assistência às Vítimas de Eventos Climáticos Extremos': [
            'vitimas de ciclones', 'vitimas de cheias', 'desastres naturais',
            'emergencia climatica', 'ciclone', 'cheias', 'seca',
        ],
        'Advocacia e Defesa dos Direitos Humanos': [
            'advocacia', 'direitos humanos', 'defesa de direitos', 'genero', 'mulher',
            'lgbt', 'violencia baseada no genero', 'vbg', 'governac', 'associativismo', 'ocb',
        ],
        'Assistência às Famílias Vítimas de Conflitos Armados': [
            'conflito armado', 'deslocad', 'vitimas de conflito', 'retornad',
            'assistencia humanitaria',
        ],
    },
    'Infraestruturas': {
        'Água e Saneamento': [
            'agua e saneamento', 'agua potavel', 'furos', 'saneamento', 'latrina', 'tip tap',
            'agua',
        ],
        'Tecnologias de Informação e Comunicação': [
            'tecnologias de informacao', ' tic ', 'comunicacao digital', 'internet',
        ],
        'Abertura e Manutenção de Vias de Acesso': [
            'vias de acesso', 'estradas', 'pontes', 'manutencao de estradas', 'abertura de vias',
        ],
    },
    'Resiliência e Mudanças Climáticas': {
        'Projectos de Reassentamento': [
            'reassentamento', 'realojamento',
        ],
        'Construção de Infraestruturas Sociais Resilientes': [
            'infraestrutura resiliente', 'construcao resiliente', 'infraestrutura social resiliente',
            'resiliencia',
        ],
        'Projectos de Formação em Meios de Vida': [
            'meios de vida', 'formacao em meios de vida', 'sustento', 'livelihoods',
            'juventude', 'jovens', 'desporto',
        ],
    },
}

AREAS_TEMATICAS = list(ESTRUTURA_AREAS_TEMATICAS.keys())

# Ícones sugestivos (Bootstrap Icons) para cada área temática — usados no
# dashboard, na listagem e na página de sector para tornar as áreas mais
# reconhecíveis visualmente.
ICONES_AREAS = {
    'Educação': 'bi-mortarboard',
    'Saúde': 'bi-heart-pulse',
    'Agricultura e Segurança Alimentar': 'bi-flower3',
    'Conservação e Meio Ambiente': 'bi-tree',
    'Acção Social': 'bi-people',
    'Ajuda Humanitária': 'bi-life-preserver',
    'Infraestruturas': 'bi-signpost-2',
    'Resiliência e Mudanças Climáticas': 'bi-cloud-lightning-rain',
}


def icone_area(nome_area):
    return ICONES_AREAS.get(nome_area, 'bi-tag')


def normalizar(texto):
    if not texto:
        return ''
    texto = str(texto).lower()
    texto = unicodedata.normalize('NFKD', texto)
    texto = ''.join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace('_', ' ').replace('-', ' ').replace('/', ' ')
    return ' '.join(texto.split())


def detetar_provincia(texto):
    """Identifica a província a partir de texto livre, ex.: 'Província de: Gaza'
    ou 'Província de: C. Delgado/Quissanga' (formatos abreviados incluídos)."""
    if not texto:
        return None
    norm = normalizar(texto)
    # ordenar aliases dos mais longos para os mais curtos evita falsos positivos
    # (ex.: "maputo" sozinho não deve confundir Maputo Cidade com Maputo Província)
    candidatos = []
    for provincia, aliases in PROVINCIA_ALIASES.items():
        for alias in aliases:
            if alias in norm:
                candidatos.append((len(alias), provincia))
    if candidatos:
        candidatos.sort(reverse=True)
        return candidatos[0][1]
    # fallback: tentar o nome completo da província (sem aliases)
    for provincia in PROVINCIAS:
        if normalizar(provincia) in norm:
            return provincia
    return None


def mapear_distrito_por_nome_aproximado(texto, provincia):
    """Tenta casar um texto curto (ex.: nome de uma folha/separador do Excel,
    como 'M. DA PRAIA') com um distrito conhecido da província indicada.
    Se o texto corresponder à própria província (ex.: folha chamada 'Nampula'
    dentro do ficheiro de Nampula), devolve None — não é um distrito específico,
    é apenas a folha geral da província."""
    if not texto or not provincia or provincia not in DISTRITOS_POR_PROVINCIA:
        return None
    if detetar_provincia(texto) == provincia:
        return None
    encontrados = detetar_distritos(texto, provincia)
    return encontrados[0] if len(encontrados) == 1 else None


def detetar_distritos(texto_distritos, provincia=None):
    """Deteta distritos mencionados em texto livre.
    Se 'provincia' for indicada, procura apenas nos distritos dessa província
    (mais rigoroso). Caso contrário, procura em todas as províncias."""
    if not texto_distritos:
        return []
    norm = normalizar(texto_distritos)

    if provincia and provincia in DISTRITOS_POR_PROVINCIA:
        universo = DISTRITOS_POR_PROVINCIA[provincia]
    else:
        universo = {}
        for distritos in DISTRITOS_POR_PROVINCIA.values():
            universo.update(distritos)

    if 'todos' in norm:
        return sorted(universo.keys())

    encontrados = set()
    for distrito, aliases in universo.items():
        if any(alias in norm for alias in aliases):
            encontrados.add(distrito)
    return sorted(encontrados)


def detetar_areas(texto_area):
    """Deteta a(s) área(s) temática(s) principais mencionadas no texto
    (uma área é considerada presente se pelo menos uma das suas
    ramificações/sub-categorias for encontrada)."""
    if not texto_area:
        return []
    norm = normalizar(texto_area)
    encontradas = set()
    for area, ramificacoes in ESTRUTURA_AREAS_TEMATICAS.items():
        for palavras in ramificacoes.values():
            if any(palavra in norm for palavra in palavras):
                encontradas.add(area)
                break
    return sorted(encontradas)


def detetar_ramificacoes(texto, area=None):
    """Deteta as ramificações (sub-categorias) mencionadas no texto.
    Se 'area' for indicada, procura só dentro das ramificações dessa área;
    caso contrário, procura em todas as áreas."""
    if not texto:
        return []
    norm = normalizar(texto)
    if area and area in ESTRUTURA_AREAS_TEMATICAS:
        universo = ESTRUTURA_AREAS_TEMATICAS[area]
    else:
        universo = {}
        for ramificacoes in ESTRUTURA_AREAS_TEMATICAS.values():
            universo.update(ramificacoes)

    encontradas = []
    for sub, palavras in universo.items():
        if any(palavra in norm for palavra in palavras):
            encontradas.append(sub)
    return sorted(encontradas)
