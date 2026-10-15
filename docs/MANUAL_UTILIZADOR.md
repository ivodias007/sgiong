# SGIONGs — Manual do utilizador

## Entrar
1. Abra o endereço do sistema e clique em **Entrar**.
2. Escreva o seu **e-mail** (é o nome de entrada) e a senha.
3. Na primeira entrada com uma conta nova, o sistema leva-o a **/conta** para mudar a senha (mínimo 10 caracteres, com letras e números). Só depois acede ao resto.
4. Cinco tentativas falhadas bloqueiam a conta durante 15 minutos. Se precisar de acesso já, peça a um administrador para repor a senha.
5. **2FA:** é obrigatório para Super Administradores e Administradores (o sistema leva-os a configurá-lo logo após entrar) e recomendado para todos. Instale uma aplicação autenticadora, leia o QR e escreva o código. No fim recebe **10 códigos de recuperação**: guarde-os impressos ou num gestor de senhas. Se perder o telemóvel, escreva um deles no campo do código (cada um serve uma vez). Pode gerar novos em *A minha conta*.
6. **Esqueci a senha:** no ecrã de entrada, «Esqueci a minha senha» (quando disponível) envia uma ligação ao seu e-mail, válida 30 minutos. Caso contrário, peça a um administrador para repor a senha.

## Pesquisar e consultar
- **Listagem (`/ongs`) e Organizações:** escolha a **Província**; surge a caixa de **Distrito** com os distritos dessa província. Pode juntar área temática, natureza (ONG/OSC/Fundação) e origem.
- **Dashboard:** totais, mapa por província/distrito e percentagens. Os números respeitam os filtros escolhidos.
- **Assistente (balão no canto):** responde a perguntas rápidas, p. ex. "Quantas ONGs há em Sofala?".

## Registar uma ONG
1. **Nova ONG** → preencha. Só o **nome** é obrigatório.
2. Escolha as províncias e, em cada uma, marque os distritos (há filtro de pesquisa).
3. Enquanto escreve o nome, o sistema avisa se **já existe** uma ONG com o mesmo nome (ignora maiúsculas, acentos e pontuação). Nesse caso **não deixa gravar**: procure a existente e proponha uma alteração. Nomes apenas parecidos geram um aviso.
4. Ao gravar, o registo fica **Pendente** até um aprovador o validar.

## Editar
- Operadores e gestores **propõem** a alteração; só entra em vigor depois de aprovada.
- Super Administrador/Administrador editam directamente; tudo fica registado na auditoria.

## Aprovar ou rejeitar (gestores/administradores)
- **Pendentes** mostra registos novos e alterações propostas, com as diferenças lado a lado.
- Ninguém aprova o que ele próprio submeteu.
- Ao **rejeitar**, escreva o motivo — fica guardado com o seu nome e a data.

## Relatórios
**Relatórios** → escolha filtros → PDF, Excel ou CSV. Os três formatos dão os mesmos totais para os mesmos filtros. O Gestor Provincial só vê a sua província.

## Perfis
| Perfil | Pode |
|---|---|
| Super Administrador | Tudo, incluindo eliminar ONGs e gerir backups |
| Administrador | Utilizadores, notícias, aprovar; não elimina nem faz backups |
| Gestor Nacional | Aprovar e ver todas as províncias |
| Gestor Provincial | Aprovar/registar apenas na sua província (uma conta por província) |
| Operador | Registar e propor alterações |
| Consulta | Só ver |

## Mensagens que pode ver
- *"Já existe uma ONG com este nome"* — procure-a na listagem.
- *"Demasiadas tentativas falhadas"* — aguarde 15 min ou peça reposição.
- *"Sem autorização"* — o seu perfil não permite essa acção.
- *"Algo correu mal"* — o erro ficou registado; tente de novo e, se persistir, avise o administrador indicando a hora.
