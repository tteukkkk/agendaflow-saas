# Arquitetura e limites de segurança — AgendaFlow SaaS

## Fluxo

Cliente -> HTTPS/proxy reverso -> FastAPI -> PostgreSQL

Processo separado de e-mails -> PostgreSQL outbox -> SMTP

Proprietário -> Checkout Stripe -> Stripe Webhook assinado -> assinatura local

## Isolamento entre empresas

- `Organization` é o escopo de cada conta empresarial.
- `Membership` associa uma conta global a uma empresa, com função (owner / manager / staff).
- Toda rota administrativa usa `tenant_guard` e filtra por organização.
- Os identificadores de serviço e de profissional são conferidos contra a empresa antes de criar reservas.
- Reservas têm relações compostas `(organization_id, id)` com clientes, profissionais e serviços.
- A empresa visualiza somente suas próprias reservas e clientes; usuário staff tem acesso limitado aos seus atendimentos.
- Link público de gerenciamento de reserva é um segredo e é armazenado somente como SHA-256. Não compartilhar links de cancelamento publicamente.
- O modelo é **banco compartilhado com chave de empresa**. Para escala e maior isolamento, considere políticas PostgreSQL RLS e auditoria externa de cada rota (não foram implementadas nesta versão).

## Segurança

- Senhas em Argon2id com sal próprio; login com throttling persistente em banco.
- Cookies assinados, secure em produção, SameSite Lax; CSRF token por sessão para operações com escrita.
- Cabeçalhos CSP/X-Frame-Options/HSTS em produção.
- HTML gerado por Jinja2, entradas validadas por Pydantic, sem SQL concatenado com dados de clientes.
- Stripe sem dados de cartão locais, webhook com HMAC, janela temporal e deduplicação.
- Logs de auditoria por empresa (não equivalem a SIEM). Exportações CSV neutralizam injeção de fórmulas em células.
- O projeto não contempla autenticação multifator, SSO, pentest independente, WAF, detecção de fraudes nem certificação de segurança.

## Concorrência

- Em SQLite (apenas desenvolvimento), o endpoint de criação usa `BEGIN IMMEDIATE`.
- No PostgreSQL, reserva usa lock transacional de sessão por profissional (`pg_advisory_xact_lock`).
- Atualização e consulta de disponibilidade ocorrem na mesma transação, evitando duas reservas para o mesmo profissional no mesmo horário, desde que todas as escritas de reservas passem pelos serviços de domínio.
- A quota de reservas é bloqueada por assinatura para evitar corridas entre pedidos. Para alta escala, recomendado teste de carga PostgreSQL e restrição adicional de exclusão temporal no banco.

## Operação

- Migrations: Alembic. A migração inicial instala o esquema completo em banco novo. Migrações futuras devem ser incrementais e revisadas.
- Banco em produção: PostgreSQL; nunca SQLite em múltiplas réplicas.
- Worker de e-mails: execução independente, com teste de entrega real e alertas.
- Termos e privacidade são modelos; necessidade de aprovação jurídica e operacional.
- Rotas `/health` e `/ready`: liveness e readiness; readiness depende de acesso ao banco.
- Backups, recuperação, monitoramento, medição de uso, suporte e faturas fiscais precisam ser contratados/configurados.
