# SGIONGs — Sistema de Gestão de Informação de ONGs (Moçambique — 11 províncias)

Aplicação web para registar, gerir e consultar ONGs/OSCs/Fundações a operar
em Moçambique, desenvolvida sob tutela do Ministério da Planificação e
Desenvolvimento (MPD).

**Stack:** Python 3 + Flask + SQLite (sqlite3 puro) + Bootstrap 5

---

## Novidades 2026 — resumo do que foi acrescentado

Esta versão evoluiu de um site de listagem simples (sem login) para um
sistema de gestão institucional completo:

### Requisitos de 07.10.2026
- **Só o nome é obrigatório** no registo/edição de ONG (natureza, origem, província, distrito e áreas são opcionais).
- **Distritos por província**: caixa de selecção agrupada por província, com filtro de pesquisa e "todos/nenhum" por grupo. Ao escolher 2 ou 3 províncias aparecem os distritos de todas, em blocos separados; o servidor só aceita distritos que pertençam às províncias escolhidas.
- **Possíveis duplicados em grupo**: todos os registos com nome igual ou parecido aparecem numa única linha (não só pares).
- **Sofala — Relação Nominal 2026** (`importar_sofala_relacao_2026.py`): junta as folhas Nacionais, Estrangeiras, Estrangeiras (2) e ONG Activas ao `data/SOFALA.csv` sem duplicar nomes exactos; depois `python importar_dados.py`.
- **Mapa**: tooltip com nº de ONGs e % do total nacional, legenda de cores e tabela de percentagens; Maputo (Cidade + Província) usa contagem distinta.

### Notícias (página inicial)
A página inicial abre com uma faixa institucional (Ministério da Planificação e Desenvolvimento, Direcção Nacional, etiqueta MOÇAMBIQUE, título e a data do dia em que a pessoa entra) sobre uma foto de capa escolhida em Gerir notícias, e por baixo as últimas notícias; `/noticias` lista todas, por categoria. Super Administrador e Administrador têm **Gerir notícias** (`/admin/noticias`): criar, editar, publicar/retirar, pôr em destaque, imagem de capa (JPG/PNG/WEBP até 5 MB) e eliminar — tudo registado na auditoria. O texto é simples (sem HTML), por isso é seguro. Três notícias de exemplo são criadas na primeira importação — edite-as ou apague-as. No Render gratuito as imagens enviadas perdem-se em cada novo deploy (disco não persistente).

### Perfis e permissões (`perfis.py`)
6 perfis — Super Administrador, Administrador, Gestor Nacional, Gestor
Provincial, Operador, Consulta — cada um com permissões próprias. O Gestor
Provincial fica automaticamente limitado à sua província em toda a
aplicação (listagem, dashboard, pendências, auditoria). Ninguém aprova um
registo ou edição que tenha submetido, mesmo tendo permissão para aprovar.
Contas geridas em `/utilizadores`.

### Auditoria completa (`auditoria.py`)
Toda a acção relevante (criar, editar, aprovar, rejeitar, eliminar,
gerir utilizadores, login) fica registada com quem, quando, IP e um resumo
legível — uma entrada por campo alterado numa edição. Consultar em
`/auditoria` (geral) ou na ficha de cada ONG (histórico individual).

### Workflow com sub-estados
Por cima dos 3 estados principais (Aprovado/Pendente/Rejeitado), agora há
sub-estados: **Rascunho** (privado, antes de submeter) → **Submetida** →
**Em Análise** → publicada; e, depois de publicada, o ciclo
**Necessita Actualização → Em Revisão → Publicada** quando alguém sinaliza
um registo desactualizado. "Os meus rascunhos" na barra lateral.

### Pesquisa avançada
Além de nome/sigla/província/área/natureza/origem, agora também por
distrito, público-alvo, contacto (nome/telefone/email) e intervalo de ano
de entrada no país — em `/ongs`, botão "Mais filtros".

### Dashboard executivo (`/dashboard`)
Indicadores completos (registadas/aprovadas/pendentes/rejeitadas/nacionais/
estrangeiras), mapa interactivo de Moçambique (clicável, filtra por
província), evolução anual de registos, ONGs por distrito, e percentagem
de cobertura provincial/distrital. O mapa é georreferenciado a dois níveis — 11 províncias e 159 distritos
(`static/data/provincias_mocambique.geojson` e `distritos_mocambique.geojson`,
geoBoundaries.org ADM2, CC BY 4.0 — mantenha a atribuição no rodapé do mapa).
Clique numa província para ver os seus distritos, com nº de ONGs e
percentagem; clique num distrito para filtrar o painel. Maputo Cidade e
Maputo Província aparecem separadas (os 7 distritos urbanos da Cidade de
Maputo são uma só área no mapa). Para refazer os ficheiros: `gerar_mapas.py`.

### Relatórios (`relatorios.py`)
PDF (capa institucional, indicadores, gráficos, listagem), Excel (folha de
resumo + listagem completa com formatação) e CSV — todos filtráveis por
província/área/período, em `/relatorios`. Nunca incluem ONGs pendentes,
rejeitadas ou rascunhos.

### Segurança reforçada (`seguranca.py`)
Verificação em duas etapas (2FA/TOTP, compatível com Google Authenticator e
Authy) para contas criadas em `/utilizadores` — configurável em "A minha
conta" (`/conta`). Política de senha mínima (8+ caracteres, letra e
número) aplicada na criação de contas e na alteração de senha própria.
As contas legadas por variável de ambiente não suportam 2FA — mais uma
razão para migrar para contas individuais.

### API (`api.py` + `gerir_api_keys.py`)
Endpoints de leitura (`/api/v1/ongs`, `/provincias`, `/areas-tematicas`,
`/indicadores`) para integrações externas, protegidos por chave de API.
Ver `API.md`.

### Identidade visual
Nova paleta institucional (verde-mata/terracota/dourado), tipografia
Newsreader + Public Sans, mantendo a estrutura de sidebar já existente.

### Backup automático (`backup.py`)
Backup diário automático às 02:00 (agendado com APScheduler), retendo
sempre os últimos 14. Gestão em `/backup` (só Super Administrador):
histórico de backups, botão para gerar um na hora, e download individual.

**Aviso importante para quem estiver no Render gratuito**: o disco desse
plano não sobrevive a um redeploy — estes backups protegem contra erros
durante a sessão em curso, mas não substituem descarregar uma cópia
periodicamente para fora do servidor (o botão "Descarregar" em `/backup`
serve exactamente para isso).

### Logótipos de ONGs por upload
O formulário de registo/edição aceita agora um ficheiro (PNG, JPG, SVG ou
WEBP, até 2 MB) em vez de um link de texto — validado por formato e
tamanho, guardado em `static/uploads/logos/`. Aparece na ficha da ONG, na
listagem e nas "Registadas recentemente" da página inicial. **Mesmo aviso
dos backups**: no Render gratuito este ficheiro não sobrevive a um
redeploy — para durabilidade real a prazo, considerar um serviço de
armazenamento externo (S3 ou equivalente).

### Portal público separado
Quem não tem sessão iniciada vê uma barra de navegação simples e um
rodapé institucional (sem a sidebar de gestão) em `/`, `/ongs`,
`/organizacoes`, `/dashboard`, `/sector/<área>` e `/levantamento-nacional`
— a mesma informação (só ONGs aprovadas), mas com uma experiência pensada
para cidadãos, parceiros e investigadores, não para quem gere o sistema.
Um botão "Acesso interno" leva ao login; depois de autenticado, a área
interna (sidebar completa) aparece normalmente, com um link "Ver portal
público" para trocar de volta.

### Sobreposição de actuação (`sobreposicoes.py`)
Diferente da deteção de duplicados acima: aqui as ONGs são mesmo
diferentes, mas sinaliza quando **várias ONGs fazem a mesma actividade
específica (ramificação, ex.: "Água e Saneamento") no mesmo distrito** —
útil para perceber onde pode haver falta de coordenação entre
organizações. Página `/sobreposicoes`, com filtro por província e por
número mínimo de ONGs, e botão para marcar um grupo como "já coordenado"
(deixa de ser sinalizado). Um **sino de notificações** na barra superior
mostra a contagem e os 5 casos mais graves, para quem tem permissão de
auditoria — não precisa de ir à página para saber que há algo a rever.

### Deteção de duplicados por semelhança (`duplicados.py`)
Complementa o `reconciliar_duplicados.py` (que só junta nomes idênticos):
compara nome, sigla, telefone e e-mail, com pontuação de confiança (ex.:
"87% de correspondência"). Aviso ao vivo no formulário de registo, e uma
página `/duplicados` com revisão em lote de todas as ONGs aprovadas.
Nomes institucionais genéricos ("Associação", "Fundação", "Internacional")
são ignorados no cálculo, para não confundir duas ONGs diferentes só por
partilharem essas palavras comuns.

### Importação com pré-visualização e validação (`importacao_web.py`)
Fluxo completo pedido: Excel → validação → pré-visualização → confirmação
→ só aí grava. Em `/importar`: mostra quantas linhas foram encontradas,
quantas são válidas, quantas já existem (duplicado exacto), quantas são
possíveis duplicados (por semelhança) e quantas têm erros — a pessoa
escolhe o que importar, linha a linha. Cobre o layout "padrão" das
matrizes (a maioria); layouts especiais continuam a usar o pipeline por
linha de comandos já existente. Respeita o âmbito de província do Gestor
Provincial e o fluxo de aprovação normal (Pendente para quem não é Super
Admin).

**As 15 ideias da lista original estão todas feitas**, incluindo o mapa
geográfico do dashboard, que já vem pronto a usar. Única ideia fora dessa
lista que pode valer a pena no futuro: documentação OpenAPI/Swagger para
a API.

---

## 1. Estrutura do projeto

```
sigeong_gaza/
├── app.py                      → aplicação Flask (rotas, filtros, CRUD)
├── database.py                 → ligação e inicialização da base SQLite
├── converter_excel_para_csv.py → converte matrizes .xlsx novas em .csv (só quando chega ficheiro novo)
├── importar_dados.py           → lê os .csv de data/ e popula a base de dados (corre sempre, local e no Render)
├── tagging.py                  → lista oficial das 11 províncias/distritos + deteção de áreas
├── schema.sql                  → estrutura das tabelas
├── requirements.txt
├── origem_excel/               → guarda aqui as matrizes .xlsx originais (só para conversão futura)
├── data/
│   ├── GAZA.csv, CABO_DELGADO.csv, ...  → um .csv por província (gerados pelo conversor)
│   └── ongs.db                 → base de dados SQLite (gerada automaticamente)
├── templates/                  → páginas HTML (Bootstrap 5)
└── static/css/style.css
```

**Porquê dois passos (Excel → CSV → base de dados)?** O site (e o Render) só
precisam de ler `.csv`, que é um formato mais leve e simples do que `.xlsx`.
A conversão de Excel só é necessária quando chega uma matriz nova; depois
disso, tudo o resto (local e online) trabalha só com os `.csv`.

## 2. Pré-requisitos

- Python 3.10 ou superior instalado
- Não precisa de MySQL, Laragon nem servidor web — tudo corre localmente com SQLite

## 3. Instalação (passo a passo)

```bash
cd sigeong_gaza
python -m venv venv
venv\Scripts\activate          (Windows)  /  source venv/bin/activate (Linux/Mac)
pip install -r requirements.txt
python importar_dados.py
python app.py
```

Abrir no browser: **http://127.0.0.1:5000**

## 4. Importar dados de várias províncias

Os dados que o site usa vivem em ficheiros **`.csv`** dentro de `data/`
(um por província). Há dois cenários:

### 4.1 — Já tens os `.csv` prontos (caso normal)

```bash
python importar_dados.py
```

Isto importa **todos** os `.csv` encontrados em `data/`. Cada ficheiro só
substitui os registos da sua própria província — importar Nampula não
apaga os dados já existentes de Gaza, Sofala, etc.

### 4.2 — Chegou uma matriz nova em Excel (.xlsx)

1. Coloca o ficheiro `.xlsx` dentro da pasta `origem_excel/`.
2. Corre o conversor (só precisas do Excel para este passo):
   ```bash
   python converter_excel_para_csv.py
   ```
   Isto lê o `.xlsx`, deteta a província automaticamente (pelo nome do
   ficheiro e/ou pela célula `"Província de: <nome>"` no cabeçalho), e
   escreve/substitui o `.csv` dessa província em `data/`.
3. Importa o `.csv` gerado para a base de dados:
   ```bash
   python importar_dados.py
   ```

Também é possível converter/importar um único ficheiro ou uma pasta
diferente:

```bash
python converter_excel_para_csv.py "C:\caminho\para\NAMPULA.xlsx"
python importar_dados.py "C:\caminho\para\GAZA.csv"
```

⚠️ Se o ficheiro Excel não tiver forma de identificar a província (nem
pelo nome do ficheiro, nem pela célula `"Província de: <nome>"`), a
conversão desse ficheiro é ignorada (com aviso no terminal).

## 5. Funcionalidades

- **Listagem com filtros**: nome, **província**, origem (Nacional/Internacional),
  distrito, área de intervenção e estado (Ativo/Inativo/Suspenso)
- **Deteção automática** de província, distritos beneficiários e áreas de
  intervenção a partir do texto livre da matriz
- **Detalhe de cada ONG** com todos os campos
- **Registar / Editar / Eliminar** ONGs diretamente na aplicação (com
  seletor de província)
- **Paginação** (12 organizações por página)
- Cobertura das **11 províncias**: Niassa, Cabo Delgado, Nampula, Zambézia,
  Tete, Manica, Sofala, Gaza, Inhambane, Maputo Província e Maputo Cidade

## 6. Disponibilizar na rede interna do escritório

Por defeito (`python app.py`), o site só é acessível no teu próprio computador
(`http://127.0.0.1:5000`). Para os colegas conseguirem aceder a partir dos
computadores deles, **na mesma rede** (Wi-Fi ou cabo do escritório):

```bash
python executar_rede.py
```

Depois:

1. Descobre o IP deste computador — abre outro CMD e escreve:
   ```
   ipconfig
   ```
   Procura "Endereço IPv4" (ex.: `192.168.1.45`).

2. Nos outros computadores, **ligados à mesma rede**, abrir no browser:
   ```
   http://192.168.1.45:5000
   ```
   (substituir pelo IP que encontraste)

**Importante:**
- O computador que corre `executar_rede.py` tem de ficar **ligado e com a
  app aberta** enquanto os colegas estiverem a usar.
- Isto só funciona dentro da mesma rede local (não funciona fora do
  escritório, nem pela internet, sem configuração adicional).
- O IP pode mudar se o router atribuir IPs automaticamente (DHCP). Se isso
  for um problema, pede ao responsável de TI para reservar um IP fixo para
  este computador.
- **Muda a senha do administrador** em `config.py` antes de partilhar — com
  mais pessoas a aceder, a senha por defeito deixa de ser segura.
- Liberta a porta 5000 na firewall do Windows se o acesso falhar a partir de
  outros computadores: Firewall do Windows Defender → Definições Avançadas
  → Regras de Entrada → Nova Regra → Porta → TCP → 5000 → Permitir.

## 7. Limitações conhecidas / próximos passos sugeridos

- As listas de distritos em `tagging.py` baseiam-se na divisão
  administrativa oficial mais recente disponível; se um distrito novo for
  criado ou o nome mudar, basta adicionar/ajustar uma entrada no dicionário
  `DISTRITOS_POR_PROVINCIA`.
- A deteção de distritos/áreas é feita por palavras-chave em texto livre —
  revisar `tagging.py` para ajustar ou ampliar.
- **Autenticação multiutilizador com perfis já existe** (ver "Novidades
  2026" acima) — crie as contas reais das pessoas em `/utilizadores` após
  o primeiro login com as credenciais de arranque.
- Ainda por fazer: 2FA, mapa geográfico interactivo, relatórios PDF/Excel
  agendados, deteção automática de duplicados por semelhança percentual,
  backups agendados, portal público separado.

## 8. Resolução de problemas

- **"python não é reconhecido..."** → instalar Python e marcar "Add Python
  to PATH" durante a instalação.
- **Porta 5000 ocupada** → editar a última linha de `app.py` para
  `app.run(debug=True, port=5050)`.
- **Província não detetada ao importar** → confirmar que existe uma célula
  com o texto `"Província de: <nome>"` nas primeiras linhas da folha, e que
  o nome corresponde a uma das 11 províncias (ver `tagging.py` → `PROVINCIAS`).

## 9. Publicar na internet (Render.com)

Este projeto já inclui `wsgi.py`, `Procfile` e `render.yaml`, prontos para o
Render detetar sozinho. Passos resumidos:

1. Enviar o conteúdo **desta pasta** (`sigeong_gaza`) para um repositório no
   GitHub — o `app.py`, `wsgi.py` e `requirements.txt` têm de ficar na
   **raiz do repositório**, não dentro de outra subpasta.
2. Criar um "New Web Service" no Render, escolher o repositório e deixar o
   `render.yaml` configurar tudo automaticamente.

**Erro mais comum:** `python: can't open file '.../src/wsgi.py': No such
file or directory`. Isto acontece quando o repositório tem esta pasta
(`sigeong_gaza`) aninhada dentro de outra no GitHub. Duas formas de resolver:

- No Render, ir a **Settings → Root Directory** e escrever `sigeong_gaza`; ou
- Reorganizar o repositório para que o conteúdo desta pasta fique
  diretamente na raiz (fazer `git init`/`git add .` **de dentro** desta
  pasta, não da pasta que a contém).

No plano gratuito, o serviço "adormece" após inatividade — o primeiro
acesso pode demorar 30–60 segundos a responder; isto é normal e não é falha
de código.

## 10. Checklist antes de publicar de vez (produção real)

Ver **`docs/SEGURANCA_E_PUBLICACAO.md`** (checklist completa, limitações, SQLite vs PostgreSQL),
**`docs/MANUAL_UTILIZADOR.md`** e **`docs/MANUAL_ADMINISTRACAO.md`** (procedimentos de registo, aprovação,
importação, utilizadores, backups e recuperação).

O essencial: `SGIONGS_PRODUCAO=1` (recusa as senhas de demonstração), 1.º Super Administrador por
`SGIONGS_BOOTSTRAP_EMAIL/PASSWORD`, disco persistente + cópia externa dos backups, 2FA nos administradores,
`SGIONGS_ALERTA_WEBHOOK` e monitor em `/saude`.

Testes: `pip install pytest && pytest -q` (≈150 testes; usam uma base temporária, nunca tocam em `data/ongs.db`).

---

## Actualização 13.10.2026

### Caixa de distritos
Nas abas **Organizações** e **Listagem**, ao escolher a província aparece logo a caixa de **Distrito** (só com os distritos dessa província).

### Chatbot
Botão flutuante em todas as páginas (também no portal público), com perguntas rápidas e texto livre. Responde com números reais ("Quantas ONGs em Sofala?") e liga às páginas certas. Conteúdo editável em `chatbot.py` (lista `FAQ`).

### Entrada com e-mail
O nome de entrada é o **e-mail**. Novos utilizadores exigem e-mail válido. Os administradores podem repor a senha (gera senha temporária) e alterar o e-mail em *Utilizadores*. Contas novas são obrigadas a **mudar a senha no primeiro acesso**.
Contas de fábrica (`adminong`, `superadmin`): mude as senhas e defina `SGIONGS_ADMIN_EMAIL` / `SGIONGS_SUPERADMIN_EMAIL` no ambiente.

### 11 contas provinciais (sem duplicar)
*Utilizadores → Contas das 11 províncias* (ou `python contas_iniciais.py [dominio]`) cria um **Gestor Provincial** por província. Só uma conta por província (garantido também na base de dados). Repetir a acção não duplica. As credenciais aparecem **uma só vez** (CSV/impressão). Os e-mails `gestor.<provincia>@sgiong.mpd.gov.mz` são provisórios: troque-os pelos reais com *Alterar e-mail*.

### Nome repetido
Não é possível registar nem editar uma ONG para um nome já existente (ignora maiúsculas, acentos e pontuação; ignora registos rejeitados). A verificação é também feita enquanto se escreve.

### Servidor do Ministério — a base de dados mantém-se?
Sim. A base é o ficheiro `data/ongs.db`; num servidor com disco persistente mantém-se entre reinícios. Pode-se adicionar, editar e apagar pelo sistema (segundo o perfil; só o Super Admin apaga ONGs).
- **Nunca** corra `importar_dados.py --substituir` depois de ter dados reais. Sem a opção, o script recusa-se a correr se a base já tem dados.
- Faça cópias de segurança regulares (módulo de backup) de `data/ongs.db` e `static/uploads/` (logótipos e imagens de notícias).
- Use HTTPS e defina senhas/e-mails por variáveis de ambiente.
- SQLite serve bem para poucos utilizadores em simultâneo; para carga maior pode migrar-se para PostgreSQL.
- No Render gratuito o disco **não** é persistente: tudo se perde em cada novo deploy.
