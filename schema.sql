-- SGIONGs | Base de dados de ONGs/OSCs
-- SQLite

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS ongs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_original INTEGER,
    nome TEXT NOT NULL,
    sigla TEXT,                     -- Sigla/abreviatura (opcional), separada do nome completo
    natureza TEXT,                  -- ONG / OSC / Fundação
    origem TEXT,                    -- Nacional / Internacional / Nacional e Internacional
    ano_entrada_pais INTEGER,       -- Ano em que a organização estrangeira entrou no país
    logo_url TEXT,                  -- Logótipo da organização (opcional; sem logótipo usa-se o emblema automático)
    provincia TEXT,
    area_intervencao TEXT,          -- "Área/s Temática/s" no template oficial
    programas TEXT,                 -- "Programas" (distinto de Projectos em Curso)
    projetos_em_curso TEXT,         -- "Projectos" / "Projectos em Curso"
    fonte_financiamento TEXT,
    distritos_texto TEXT,           -- "Distrito/Município" / "Distritos Beneficiários"
    perfil_grupo_alvo TEXT,
    pessoa_contacto TEXT,           -- "Ponto Focal" / "Pessoa de Contacto"
    telefone TEXT,
    email TEXT,
    coordenada_x TEXT,               -- "Coordenadas UTM" X
    coordenada_y TEXT,               -- "Coordenadas UTM" Y
    estado TEXT DEFAULT 'Ativo',    -- Ativo / Inativo / Suspenso
    aprovacao TEXT DEFAULT 'Aprovado', -- Pendente / Aprovado / Rejeitado
    motivo_rejeicao TEXT,            -- preenchido pelo Super Admin ao rejeitar
    aprovado_por TEXT,               -- utilizador que aprovou/rejeitou
    aprovado_em TIMESTAMP,           -- quando foi aprovado/rejeitado
    criado_por TEXT,                 -- 'admin' ou 'superadmin' ou 'importacao'
    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS distritos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT UNIQUE NOT NULL,
    provincia TEXT
);

CREATE TABLE IF NOT EXISTS ong_distritos (
    ong_id INTEGER NOT NULL,
    distrito_id INTEGER NOT NULL,
    PRIMARY KEY (ong_id, distrito_id),
    FOREIGN KEY (ong_id) REFERENCES ongs(id) ON DELETE CASCADE,
    FOREIGN KEY (distrito_id) REFERENCES distritos(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS ong_areas (
    ong_id INTEGER NOT NULL,
    area_id INTEGER NOT NULL,
    PRIMARY KEY (ong_id, area_id),
    FOREIGN KEY (ong_id) REFERENCES ongs(id) ON DELETE CASCADE,
    FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ramificacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT UNIQUE NOT NULL,
    area_id INTEGER NOT NULL,
    FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ong_ramificacoes (
    ong_id INTEGER NOT NULL,
    ramificacao_id INTEGER NOT NULL,
    PRIMARY KEY (ong_id, ramificacao_id),
    FOREIGN KEY (ong_id) REFERENCES ongs(id) ON DELETE CASCADE,
    FOREIGN KEY (ramificacao_id) REFERENCES ramificacoes(id) ON DELETE CASCADE
);

-- Uma organização pode actuar em várias províncias simultaneamente.
CREATE TABLE IF NOT EXISTS ong_provincias (
    ong_id INTEGER NOT NULL,
    provincia TEXT NOT NULL,
    PRIMARY KEY (ong_id, provincia),
    FOREIGN KEY (ong_id) REFERENCES ongs(id) ON DELETE CASCADE
);

-- Uma organização pode ter mais do que uma natureza (ex.: "ONG, OSC").
-- Guardar cada uma separadamente permite contagens correctas no dashboard.
CREATE TABLE IF NOT EXISTS ong_naturezas (
    ong_id INTEGER NOT NULL,
    natureza TEXT NOT NULL,
    PRIMARY KEY (ong_id, natureza),
    FOREIGN KEY (ong_id) REFERENCES ongs(id) ON DELETE CASCADE
);

-- Quando um Administrador (não Super Admin) edita uma ONG já aprovada, a
-- alteração fica aqui em espera até o Super Administrador a validar.
CREATE TABLE IF NOT EXISTS alteracoes_pendentes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ong_id INTEGER NOT NULL,
    dados_json TEXT NOT NULL,        -- novos valores propostos (JSON)
    dados_antigos_json TEXT NOT NULL, -- valores anteriores, para comparação
    solicitado_por TEXT,
    solicitado_em TEXT,
    estado TEXT DEFAULT 'Pendente',  -- Pendente / Aprovado / Rejeitado
    motivo_rejeicao TEXT,
    revisto_por TEXT,
    revisto_em TEXT,
    FOREIGN KEY (ong_id) REFERENCES ongs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_alteracoes_pendentes_estado ON alteracoes_pendentes(ong_id, estado);

CREATE INDEX IF NOT EXISTS idx_ongs_nome ON ongs(nome);
CREATE INDEX IF NOT EXISTS idx_ongs_origem ON ongs(origem);
CREATE INDEX IF NOT EXISTS idx_ongs_estado ON ongs(estado);
CREATE INDEX IF NOT EXISTS idx_ongs_provincia ON ongs(provincia);

-- Contas de acesso individuais, com perfil granular (ver perfis.py).
-- As duas contas antigas (definidas por variável de ambiente) continuam a
-- funcionar em paralelo durante a transição — ver login() em app.py.
CREATE TABLE IF NOT EXISTS utilizadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    nome_completo TEXT,
    password_hash TEXT NOT NULL,
    perfil TEXT NOT NULL,        -- super_admin / admin / gestor_nacional / gestor_provincial / operador / consulta
    provincia TEXT,              -- só relevante para gestor_provincial
    activo INTEGER NOT NULL DEFAULT 1,
    criado_por TEXT,
    criado_em TEXT DEFAULT (datetime('now')),
    ultimo_login TEXT
);

-- Histórico de auditoria: uma linha por acção relevante no sistema.
-- ong_id fica NULL para acções que não são sobre uma ONG específica
-- (gestão de utilizadores, login falhado, etc.).
CREATE TABLE IF NOT EXISTS historico_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ong_id INTEGER,
    accao TEXT NOT NULL,
    utilizador TEXT,
    ip TEXT,
    resumo TEXT NOT NULL,
    detalhes_json TEXT,
    criado_em TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_auditoria_ong ON historico_auditoria(ong_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_criado_em ON historico_auditoria(criado_em);
CREATE INDEX IF NOT EXISTS idx_auditoria_utilizador ON historico_auditoria(utilizador);

-- Pares de ONGs marcados como "não são duplicados" na revisão em lote,
-- para não voltarem a ser sugeridos em /duplicados.
CREATE TABLE IF NOT EXISTS duplicados_ignorados (
    ong_id_1 INTEGER NOT NULL,
    ong_id_2 INTEGER NOT NULL,
    ignorado_por TEXT,
    ignorado_em TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ong_id_1, ong_id_2)
);

-- Grupos (distrito + ramificação) marcados como "já coordenados" na
-- revisão de sobreposição de actuação, para deixarem de ser sinalizados.
CREATE TABLE IF NOT EXISTS sobreposicoes_ignoradas (
    distrito_id INTEGER NOT NULL,
    ramificacao_id INTEGER NOT NULL,
    ignorado_por TEXT,
    ignorado_em TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (distrito_id, ramificacao_id)
);


-- Notícias da página inicial (geridas por quem tem a permissão gerir_noticias)
CREATE TABLE IF NOT EXISTS noticias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    categoria TEXT DEFAULT 'Moçambique',
    resumo TEXT,
    conteudo TEXT,
    imagem_url TEXT,
    autor TEXT,
    publicada INTEGER NOT NULL DEFAULT 1,
    destaque INTEGER NOT NULL DEFAULT 0,
    publicado_em TEXT DEFAULT (datetime('now')),
    criado_por TEXT,
    criado_em TEXT DEFAULT (datetime('now')),
    actualizado_em TEXT
);

-- Pequenas configurações editáveis (ex.: imagem de capa da página inicial)
CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT
);


-- Tentativas de login falhadas (por IP e por conta) — bloqueio persistente
CREATE TABLE IF NOT EXISTS login_tentativas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave TEXT NOT NULL,
    momento REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_tentativas_chave ON login_tentativas(chave, momento);

-- Ficheiros de importação já processados (impede importar o mesmo ficheiro duas vezes)
CREATE TABLE IF NOT EXISTS importacoes_feitas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash_ficheiro TEXT NOT NULL UNIQUE,
    nome_ficheiro TEXT,
    utilizador TEXT,
    total INTEGER,
    criado_em TEXT DEFAULT (datetime('now'))
);

-- Códigos de recuperação do 2FA (uso único; guardados só como hash)
CREATE TABLE IF NOT EXISTS codigos_recuperacao_2fa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utilizador_id INTEGER NOT NULL,
    codigo_hash TEXT NOT NULL,
    usado_em TEXT,
    criado_em TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cod_rec_utilizador ON codigos_recuperacao_2fa(utilizador_id);

-- Pedidos de recuperação de senha por e-mail (token guardado só como hash)
CREATE TABLE IF NOT EXISTS reset_senha_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utilizador_id INTEGER NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expira_em REAL NOT NULL,
    usado_em TEXT,
    criado_em TEXT DEFAULT (datetime('now')),
    ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_reset_utilizador ON reset_senha_tokens(utilizador_id);
