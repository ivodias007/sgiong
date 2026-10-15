# SGIONGs — Manual de administração

## 1. Gestão de utilizadores (`/utilizadores`)
- **Novo utilizador:** e-mail válido (é o nome de entrada), nome, perfil e senha temporária. A conta obriga a mudar a senha no primeiro acesso.
- **Contas das 11 províncias:** botão *Criar contas dos Gestores Provinciais* (ou `python contas_iniciais.py <dominio>`). Cria uma conta por província, sem duplicar (também garantido na base de dados). As senhas temporárias aparecem **uma só vez** — descarregue o CSV ou imprima. Os e-mails `gestor.<provincia>@<dominio>` são provisórios: use **Alterar e-mail** para pôr os reais.
- **Repor senha:** gera uma senha temporária e desbloqueia a conta.
- **Repor 2FA:** quando alguém perde o telemóvel.
- **Desactivar:** impede a entrada sem apagar o histórico.
- Um Administrador só gere perfis abaixo do seu; só o Super Administrador gere Administradores.

## 2. 2FA obrigatório e recuperação de contas

**2FA dos administradores.** Em produção, Super Administradores e Administradores são obrigados a activar o 2FA: depois de entrar só acedem a *A minha conta* e à configuração do 2FA até o concluírem, e não o podem desactivar. Ao activar, recebem **10 códigos de recuperação** (uso único, mostrados uma só vez, guardados apenas em hash). Cada código TOTP só pode ser usado uma vez (anti-repetição). Para desligar esta exigência, só em testes: `SGIONGS_EXIGIR_2FA=0`.

**Perdi a senha.**
- *Com e-mail configurado* (`SGIONGS_SMTP_*`, `SGIONGS_URL_BASE`): o ecrã de entrada mostra «Esqueci a minha senha». O utilizador recebe uma ligação de uso único, válida 30 minutos, e define a nova senha. A resposta é igual exista ou não o e-mail; há limite de pedidos; fica tudo na auditoria. A recuperação de senha **não contorna o 2FA**.
- *Sem e-mail:* um administrador usa *Repor senha* em /utilizadores (gera senha temporária; a pessoa é obrigada a mudá-la).

**Perdi o telemóvel (2FA).** 1.º: entrar com um **código de recuperação** no campo do código. 2.º: se não os tem, um administrador usa *Repor 2FA* em /utilizadores; a pessoa terá de configurar o 2FA de novo (e receberá códigos novos). Cada reposição fica na auditoria.

**Perdeu o acesso o único Super Administrador.** No servidor: `python recuperar_conta.py o.email@dominio.mz` (acrescente `--sem-2fa` se perdeu o telemóvel e os códigos). Gera uma senha temporária, mostrada uma só vez, desbloqueia e reactiva a conta, e fica na auditoria. Guarde também este procedimento fora do sistema.

**Contas desactivadas** perdem a sessão no pedido seguinte; alterações de perfil ou província aplicam-se de imediato.

## 3. Importação de dados
- Em **Importar** carregue o Excel; vê-se uma **pré-visualização** com erros, duplicados e relações território incoerentes. Nada é gravado até confirmar; confirmar revalida contra a base. O mesmo ficheiro não pode ser importado duas vezes.
- O Gestor Provincial só importa para a sua província.
- **Nunca** corra `python importar_dados.py --substituir` com dados reais: substitui os registos das províncias presentes nos CSV. Sem essa opção o script recusa-se a correr numa base que já tem dados — por isso é seguro ficar no arranque do Render.

## 4. Backups
- Automático todos os dias às 02:00; manual em **/backup** (só Super Administrador).
- Cada backup é **verificado** (integridade + contagens) antes de ser aceite; um backup inválido é rejeitado e gera alerta.
- Guarda os últimos 14. Defina `SGIONGS_BACKUP_EXTRA_DIR` para uma pasta **fora** do servidor (volume de rede, disco externo, pasta sincronizada) — é onde cada backup é copiado automaticamente.
- Copie também `uploads/` (logótipos e imagens de notícias).
- **Restaurar:** `/backup` → *Restaurar* → escrever `RESTAURAR`. Antes de restaurar o sistema guarda uma cópia do estado actual.
- **Faça um teste de recuperação** a cada trimestre: descarregue um backup, restaure-o num servidor de teste, confirme o número de ONGs e que consegue entrar.

## 5. Monitoria e alertas
- `/saude` devolve 200 se a base responde e o último backup tem menos de 36 h; 503 caso contrário. Aponte um monitor externo (UptimeRobot, Better Stack…) a este endereço.
- Defina `SGIONGS_ALERTA_WEBHOOK` (Slack/Teams/Discord/Mattermost) para receber avisos de: erro interno, falha de saúde, backup rejeitado ou falhado. Cada aviso repete-se no máximo de 10 em 10 minutos. Sem webhook, as falhas ficam em `data/logs/erros.log` e em **/auditoria**.
- **/auditoria** regista quem criou, alterou, aprovou, rejeitou ou eliminou, com data, IP e resumo; inclui falhas de login, acessos negados e erros.

## 6. Variáveis de ambiente
| Variável | Função |
|---|---|
| `SGIONGS_PRODUCAO=1` | **Obrigatória em produção**: cookies seguros, HTTPS, IP real atrás de proxy, recusa senhas de demonstração |
| `SGIONGS_DATA_DIR` | Pasta persistente da base, logs, backups e uploads |
| `SGIONGS_SECRET_KEY` | Chave das sessões |
| `SGIONGS_BOOTSTRAP_EMAIL` / `_PASSWORD` | Cria o 1.º Super Administrador (só se não existir) |
| `SGIONGS_EXIGIR_2FA` | 2FA dos administradores (por omissão `1` em produção) |
| `SGIONGS_SMTP_HOST/PORT/USER/PASSWORD/FROM`, `SGIONGS_URL_BASE` | E-mail para recuperação de senha (587/STARTTLS ou 465/SSL) |
| `SGIONGS_ADMIN_PASSWORD_HASH` / `SGIONGS_SUPERADMIN_PASSWORD_HASH` | Contas legadas — **ignoradas em produção** |
| `SGIONGS_BACKUP_EXTRA_DIR` | Destino externo dos backups |
| `SGIONGS_ALERTA_WEBHOOK` | Canal de alertas |
