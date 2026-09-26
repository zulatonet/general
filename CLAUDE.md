# CLAUDE.md

Monorepo: cada pasta na raiz é um projeto independente, publicado como um
serviço separado no Easypanel (Build Path = `/<pasta>`, build via Dockerfile).

## Regras

- Um projeto por pasta, autocontido: `Dockerfile`, `README.md`, `.env.example`.
  Nunca referenciar arquivos de outra pasta (o contexto de build é só a pasta).
- Segredos e configuração vêm de variáveis de ambiente. Não commitar `.env`,
  senhas, chaves ou bancos de dados.
- Serviço HTTP escuta em `0.0.0.0:$PORT` numa única porta; HTTPS fica a cargo
  do proxy do Easypanel. Expor `/health` para o healthcheck.
- Logs no stdout.
- Ao criar ou renomear um projeto, atualizar a tabela de roteamento no `README.md` da raiz.
- Código, mensagens e documentação em português, seguindo o estilo existente.
