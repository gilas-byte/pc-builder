# Contributing

**English** · [Português](#contribuindo)

- Open an issue first for anything bigger than a small fix, so we agree on the approach.
- Tests first: add or change a test that fails, then make it pass. Run the backend tests
  (`cd backend && uv run python -B -m pytest -q`), the frontend tests (`cd frontend && npx vitest run`) and
  `python3 tools/check_public.py` (must report 0 findings).
- Never add an HTTP route that writes prices. Prices only enter through `app.ingest` or the collectors.
- No secrets, tokens, real hostnames, e-mails or absolute home paths in code, tests or docs. Use environment
  variables (see `.env.example`) and example values (`user@example.com`, `203.0.113.7`).
- Store parsers are tested with saved HTML in `backend/tests/fixtures/`; tests never hit the network.
- Keep pull requests small and describe what changed and how you tested it.

## Contribuindo

- Para algo maior que uma correção pequena, abra uma issue antes, para combinar o caminho.
- Testes primeiro: escreva ou mude um teste que falha e depois faça passar. Rode os testes do backend
  (`cd backend && uv run python -B -m pytest -q`), do frontend (`cd frontend && npx vitest run`) e o
  `python3 tools/check_public.py` (tem que dar 0 achados).
- Nunca crie rota HTTP que grave preço. Preço só entra pelo `app.ingest` ou pelos coletores.
- Nada de segredo, token, host real, e-mail ou caminho absoluto de home no código, nos testes ou na documentação.
  Use variável de ambiente (veja `.env.example`) e valores de exemplo (`user@example.com`, `203.0.113.7`).
- Os parsers das lojas são testados com HTML salvo em `backend/tests/fixtures/`; teste nunca acessa a rede.
- Pull request pequeno, dizendo o que mudou e como você testou.
