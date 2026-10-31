# Sistema de Gestão Corporativo

Aplicação web local para gestão de pessoas, executada em Python/Flask e acessada
no navegador. O aplicativo mantém o nome, o banco SQLite, as tabelas, as contas
e as configurações já usadas pela versão desktop.

## Executar

1. Instale o Python 3.10 ou superior.
2. Instale as dependências: `python -m pip install -r requirements.txt`.
3. Inicie o sistema: `python main.py`.
4. O navegador abrirá em `http://127.0.0.1:5000`.

Na primeira execução, crie a conta de administrador. Se o banco já tiver contas,
use as credenciais existentes.

O servidor escuta apenas em `127.0.0.1` e não expõe a aplicação à rede. É possível
definir outra porta local com a variável de ambiente `PORT`.

## Recursos

- Colaboradores, departamentos, cargos, dependentes e contracheques.
- Registros de ponto, solicitações de férias e treinamentos com inscrições.
- Banco SQLite com 10 chaves estrangeiras, incluindo benefícios e avaliações de desempenho.
- Contas com perfis de administrador e usuário.
- Painel com indicadores, impressão de relatórios e seleção de registros para impressão.
- Tema claro/escuro e configuração administrativa do diretório do banco.

As configurações continuam em `settings.json` no diretório de dados `NexusRHPro`
do usuário. O banco permanece em `nexus_rh_pro.db`; mudar o diretório nas
configurações vale a partir da próxima inicialização e não move os dados.

## Testes

Execute `python -m unittest discover -s tests`.

## Executável Windows

Com as dependências instaladas, execute `.\build_exe.ps1`. O artefato gerado
continua se chamando **Sistema de Gestão Corporativo** e abre a aplicação local
no navegador.
