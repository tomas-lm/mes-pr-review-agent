# GitHub App setup

Este projeto usa GitHub App para revisar PRs. O cadastro do app e feito no GitHub, mas o backend ja espera os dados abaixo via `.env`.

## 1. Criar o app

No GitHub:

```text
Settings -> Developer settings -> GitHub Apps -> New GitHub App
```

Configuracao sugerida:

- GitHub App name: `MES PR Reviewer`
- Homepage URL: `https://github.com/tomas-lm/mes-pr-review-agent`
- Webhook URL: `https://<tunnel-ou-deploy>/webhooks/github`
- Webhook secret: gerar uma string forte e colocar tambem em `GITHUB_WEBHOOK_SECRET`

## 2. Permissoes

Repository permissions:

- Metadata: read
- Contents: read
- Pull requests: read/write
- Issues: read/write
- Checks: read/write

Opcionais futuros:

- Actions: read
- Commit statuses: write

Nao pedir no MVP:

- Administration
- Secrets
- Contents: write
- Deployments

## 3. Eventos

Assinar:

- `pull_request`
- `check_run`, opcional para rerun via UI
- `installation`
- `installation_repositories`

Acoes de PR tratadas hoje:

- `opened`
- `reopened`
- `synchronize`
- `ready_for_review`

## 4. Private key

Depois de criar o app:

1. Gere uma private key.
2. Copie o App ID.
3. Configure o `.env`:

```text
GITHUB_APP_ID=<app-id>
GITHUB_APP_PRIVATE_KEY="<private-key-com-\\n-ou-multilinha>"
GITHUB_WEBHOOK_SECRET=<mesmo-secret-configurado-no-github>
```

## 5. Rodar local com tunnel

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Em outro terminal:

```bash
ngrok http 8000
```

Use a URL HTTPS do ngrok como webhook URL do app:

```text
https://<subdominio>.ngrok-free.app/webhooks/github
```

## 6. Instalar no repo

Instale o app no repo:

```text
tomas-lm/mes-pr-review-agent
```

Depois abra um PR de teste. O webhook deve criar uma run em estado `RECEIVED`.

