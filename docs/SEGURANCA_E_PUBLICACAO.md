# Segurança e publicação — estado e checklist

## Checklist antes de publicar
- [ ] `SGIONGS_PRODUCAO=1`. Com isto as contas de demonstração/legadas (`admin2026`, `superadmin2026`, ou quaisquer contas por variável de ambiente) **são sempre recusadas**, e o 2FA dos administradores passa a ser obrigatório. Sem esta variável as contas de demonstração funcionam — nunca publique sem ela.
- [ ] Criar o 1.º Super Administrador com `SGIONGS_BOOTSTRAP_EMAIL/PASSWORD` e mudar a senha no primeiro acesso.
- [ ] `SGIONGS_SECRET_KEY` própria; HTTPS activo.
- [ ] Disco persistente (`SGIONGS_DATA_DIR`) **e** `SGIONGS_BACKUP_EXTRA_DIR` externo.
- [ ] Criar as 11 contas provinciais e trocar os e-mails provisórios pelos reais.
- [ ] Cada Super Administrador/Administrador activa o 2FA no primeiro acesso e guarda os 10 códigos de recuperação.
- [ ] E-mail de recuperação: pedir ao TI `SGIONGS_SMTP_*` e `SGIONGS_URL_BASE` (opcional, mas recomendado).
- [ ] `SGIONGS_ALERTA_WEBHOOK` e monitor externo em `/saude`.
- [ ] Um teste de recuperação feito e anotado.

## O que está verificado por testes automáticos (`pytest`)
2FA obrigatório, códigos de recuperação de uso único, anti-repetição de códigos, recuperação de senha por e-mail (token em hash, 30 min, uso único, sem enumeração, com limite), produção sem contas de demonstração, sessão que cai ao desactivar/despromover uma conta, matriz de permissões sobre **todas** as rotas por perfil, login (e-mail, maiúsculas, bloqueio por conta e por IP, limpeza após sucesso), CSRF, redirecções abertas, cookies/cabeçalhos, 2FA completo e recuperação, política de senha, matriz de permissões por perfil, que **toda a rota interna exige login** (falha se alguém acrescentar uma rota sem protecção), aprovações e rejeições com rasto, edições propostas, importação (validação, repetição, província errada), integridade dos dados reais, totais do dashboard = listagem = CSV = Excel = PDF, filtros por província/distrito/área/natureza, backups (verificação, corrupção, restauro real, retenção, cópia externa), concorrência (vários utilizadores em simultâneo), contas provinciais, nomes repetidos, chatbot e alertas.

## Limitações conhecidas
- A recuperação de senha por e-mail só funciona com um servidor SMTP configurado (sem ele, faz-se por um administrador ou por `recuperar_conta.py`).
- Contas legadas por variável de ambiente não existem em produção (não suportam 2FA nem rasto individual).
- O plano gratuito do Render perde tudo a cada deploy; serve só para demonstração.

## SQLite ou PostgreSQL?
**Situação actual:** SQLite em modo WAL, ~850 organizações, poucas dezenas de utilizadores, escritas raras. Com disco persistente, backup diário verificado e cópia externa, isto é adequado e simples de operar, e os testes de concorrência passam.

**Quando passar a PostgreSQL gerido:** (a) mais de um servidor/instância da aplicação, (b) dezenas de utilizadores a escrever ao mesmo tempo, (c) exigência institucional de recuperação num ponto no tempo (PITR) e réplica, (d) o alojamento não oferece disco persistente.

**Esforço:** a aplicação usa `sqlite3` directamente (SQL com `?`, `INSERT OR…`, `PRAGMA`, `lastrowid`, índices parciais). A migração exige uma camada de acesso, reescrever essas partes e converter o esquema; é um projecto próprio (estimativa: 1–2 semanas com testes), que a suite actual de testes torna seguro. Recomenda-se decidir após o primeiro mês de uso real.
