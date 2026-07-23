# Changelog

## 0.4.0

- Durações mínimas passam a ser respeitadas também na recuperação após falhas.
- Sessões que atravessam a meia-noite são divididas pelo dia no fuso local.
- Migrações SQLite são transacionais e criam backup versionado antes de alterar
  bancos existentes.
- Registros de recuperação inválidos são preservados para diagnóstico e geram
  aviso sem impedir novas sessões.
- O reset preserva o histórico sem contabilizá-lo no novo total.
- Corrigidos o total da semana atual, a retomada após inatividade, projetos não
  salvos e o comportamento de `Salvar como`.
- Caminhos equivalentes são consolidados, incluindo diferenças de caixa e
  separadores no Windows.
- Indicadores incluem a sessão ativa e passam a atualizar ao vivo.
- A exportação CSV inclui o detalhamento de cada sessão.
- Corrigidas a ordenação numérica de tempos e datas e a precisão do limite de
  inatividade.
- A interface foi traduzida para português e ganhou estados textuais acessíveis
  para execução e pausas.
- O descarregamento remove integralmente barra, widgets, filtros e atalhos.
- Adicionada suíte automatizada para persistência, rastreamento, migrações e UI.
