# MES PR Review Agent

Revisor automatico de Pull Requests para o TP de MES.

Quando um PR e aberto ou atualizado, o sistema recebe um webhook do GitHub, cria uma run de revisao, coleta contexto do PR e prepara a execucao de um agente com Dynamic Prompt, maquina de estados e loop agentico.

## Arquitetura

```text
GitHub Pull Request
  -> GitHub App webhook
  -> FastAPI /webhooks/github
  -> validacao X-Hub-Signature-256
  -> run local de revisao
  -> state machine
  -> dynamic prompt
  -> agentic loop + tools
  -> validador de findings
  -> PR review comments + check run
```

## Rodando local

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Webhook local

Para testar com GitHub App real, exponha a API local com ngrok ou smee e configure o webhook para:

```text
POST https://<tunnel>/webhooks/github
```

Eventos iniciais:

- `pull_request.opened`
- `pull_request.reopened`
- `pull_request.synchronize`
- `pull_request.ready_for_review`

## GitHub App

Permissoes minimas planejadas:

- Metadata: read
- Contents: read
- Pull requests: read/write
- Issues: read/write
- Checks: read/write

O app deve usar installation access tokens, gerados a partir do `installation.id` recebido no webhook.

Guia de configuracao: [docs/github_app_setup.md](docs/github_app_setup.md)

## Estado atual

Implementado neste primeiro corte:

- API FastAPI.
- `GET /health`.
- `POST /webhooks/github`.
- Validacao HMAC SHA-256 via `X-Hub-Signature-256`.
- Idempotencia por `X-GitHub-Delivery`.
- Criacao de run em estado `RECEIVED`.
- Esqueletos de Dynamic Prompt, state machine, loop agentico e schema de findings.
