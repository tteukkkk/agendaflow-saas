# Checklist para lançar o AgendaFlow como SaaS comercial

**Status em 20/11/2026: candidato a piloto, ainda não homologado para produção remunerada.**

## Implementado e verificado localmente

- [x] Multiempresa: equipes, serviços, agendamentos e assinaturas isolados por organização
- [x] RBAC (proprietário, gerente, profissional) e proteção de acesso cruzado
- [x] Autenticação com Argon2, CSRF, email verification e recuperação com tokens
- [x] Horários, bloqueios, regras de agenda, reserva e reagendamento sem conflito em testes locais
- [x] Landing SaaS com preços sob consulta e teste grátis
- [x] Integração de código com Stripe Checkout, Billing Portal, webhook autenticado e idempotência
- [x] Fila SMTP e worker básico, exportação CSV e anonimização
- [x] Tema claro/escuro, responsividade e movimento reduzido
- [x] Alembic, Docker, testes automatizados e capturas de interface

## Obrigatório antes de cobrar clientes reais

- [ ] Registrar domínio, DNS, TLS, hospedagem segura e banco PostgreSQL gerenciado
- [ ] Criar assinatura Stripe real/teste e validar todo o ciclo de pagamento na plataforma
- [ ] Definir mensalidades reais, impostos, política de reembolso e emissão de notas fiscais
- [ ] Configurar SMTP validado (SPF, DKIM, DMARC), envio real, falha, bounce e monitoramento
- [ ] Executar testes de concorrência em PostgreSQL e testes de carga sob múltiplas réplicas
- [ ] Auditar autorização, CSRF, controle de acesso, IDOR, logs, secrets, dependências e rate limits; realizar pentest
- [ ] Backups cifrados automáticos e restauração comprovada, RPO/RTO definidos
- [ ] Configurar alertas de uptime, incidentes, webhook e disponibilidade de e-mail
- [ ] Revisar juridicamente contratos, aviso de privacidade, LGPD, DPA, atendimento a titulares, retenção e canal de suporte
- [ ] Implantar antispam e mitigação adicional de abusos (captcha opcional, WAF, quotas por IP e tenant)
- [ ] Verificar fluxo real de onboarding e documentação com clientes pilotos
- [ ] Criar rotinas de suporte, faturamento, cancelamento, reembolso e tratamento de disputas

## Melhorias estratégicas pós-piloto

- [ ] Autenticação multifator/SSO e logs de sessão
- [ ] Calendário arrastar-e-soltar com atualizações em tempo real
- [ ] Notificações por WhatsApp/SMS com provedores e consentimento específico
- [ ] Página pública com branding customizável (logo, URL própria, textos)
- [ ] Relatórios avançados de no-show, ocupação e retenção
- [ ] Cupons, add-ons, equipes avançadas e múltiplas unidades
- [ ] Monitoramento de webhooks, reconciliação periódica com Stripe e mecanismos de retry mais sofisticados
- [ ] Opções avançadas de LGPD: relatório de acesso, políticas de retenção, fluxos de anonimização e eliminação

## Sinais para considerar “pronto para vender”

1. Assinatura cobrada e cancelada integralmente em modo de teste, com atualização correta no sistema.
2. Reservas de duas empresas independentes sob concorrência real e sem vazamento de dados.
3. Deploy, HTTPS, backup-restauração, alertas e suporte testados.
4. Contratos e privacidade adaptados e revisados para a atividade e para os clientes-alvo.
5. Pelo menos 3 estabelecimentos pilotos completando cadastro, agendamento e operação sem ajuda técnica frequente.

**Uma aplicação com testes automatizados passando não equivale a uma solução auditada, homologada ou comprovadamente escalável.**
