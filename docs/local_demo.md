# Demo local com GitHub App

Este guia sobe o revisor localmente com Docker e conecta o GitHub a ele por um
tunnel temporario. Nao e deploy: o container roda na sua maquina, e o tunnel so
encaminha webhooks do GitHub durante a demonstracao.

## Fluxo da demo

```text
GitHub PR
  -> GitHub App webhook
  -> tunnel HTTPS temporario
  -> container local em http://localhost:8020
  -> agente revisa o PR
  -> GitHub API publica check run e review
  -> review_runs/<run_id>.md guarda o trace sanitizado
```

## 1. Preparar ambiente

Copie o exemplo de ambiente:

```bash
cp .env.example .env
mkdir -p secrets review_runs
```

Edite `.env`:

```text
APP_PORT=8020
GITHUB_APP_ID=<app-id>
GITHUB_WEBHOOK_SECRET=<mesmo-secret-configurado-no-github>
LLM_API_BASE_URL=https://api.telnyx.com/v2/ai
LLM_MODEL=moonshotai/Kimi-K2.6
LLM_API_KEY=<telnyx-api-key>
```

Baixe a private key do GitHub App e salve em:

```text
secrets/github-app-private-key.pem
```

Esse arquivo nao deve ser commitado. O Compose monta a chave dentro do container
como `/run/secrets/github-app-private-key.pem`.

## 2. Criar ou ajustar o GitHub App

No GitHub:

```text
Settings -> Developer settings -> GitHub Apps -> New GitHub App
```

Configuracao sugerida:

- GitHub App name: `MES PR Reviewer`
- Homepage URL: `https://github.com/tomas-lm/mes-pr-review-agent`
- Webhook URL: preencher depois que o tunnel estiver ativo
- Webhook secret: igual ao `GITHUB_WEBHOOK_SECRET`
- Webhook content type: `application/json`

Permissoes de repositorio:

- Metadata: read
- Contents: read
- Pull requests: read/write
- Issues: read/write
- Checks: read/write

Eventos:

- `pull_request`
- opcional para evolucao futura: `check_run`

Acoes de PR tratadas pelo backend:

- `opened`
- `reopened`
- `synchronize`
- `ready_for_review`

Fontes oficiais usadas para esta configuracao:

- GitHub Apps e permissoes: https://docs.github.com/apps/building-github-apps/setting-permissions-for-github-apps
- Webhooks: https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks
- Validacao de webhook: https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries

## 3. Subir o container

```bash
docker compose up --build
```

Em outro terminal, confira:

```bash
curl http://localhost:8020/health
```

Resposta esperada:

```json
{"status":"ok"}
```

## 4. Abrir tunnel temporario

Opcao com ngrok:

```bash
ngrok http 8020
```

Opcao com cloudflared:

```bash
cloudflared tunnel --url http://localhost:8020
```

Copie a URL HTTPS gerada e configure o Webhook URL do GitHub App:

```text
https://<url-do-tunnel>/webhooks/github
```

Depois clique em `Redeliver` em um delivery antigo ou abra um PR novo.

## 5. Instalar o app no repo

Instale o GitHub App em:

```text
tomas-lm/mes-pr-review-agent
```

Para a demo, use um PR criado em branch do proprio repo. Isso evita limitacoes de
permissao comuns em forks.

## 6. Criar PR de exemplo

Crie uma branch com uma falha simples:

```python
def normalize_email(email: str | None) -> str:
    return email.strip().lower()
```

O problema esperado: quando `email` for `None`, `.strip()` quebra com
`AttributeError`.

Ao abrir o PR, o GitHub envia o webhook para o tunnel, o container processa a run
e o app publica:

- check run `MES PR Reviewer`;
- review no PR;
- ate 3 comentarios inline;
- trace sanitizado em `review_runs/<run_id>.md`.

## 7. O que mostrar na apresentacao

Mostre nesta ordem:

1. Container local rodando e `/health` respondendo.
2. GitHub App com webhook apontando para `/webhooks/github`.
3. PR de demo aberto.
4. Check run `MES PR Reviewer` no PR.
5. Comentario inline publicado pelo app.
6. Arquivo `review_runs/<run_id>.md`.

No trace, destaque:

- `run_id`, repo, PR e head SHA;
- transicoes da maquina de estados;
- tools chamadas pelo agente;
- findings aceitos, resumidos e descartados;
- check run id e quantidade de comentarios;
- ausencia de resposta bruta do modelo, token de instalacao e secrets.

## Troubleshooting rapido

- `403` no webhook: `GITHUB_WEBHOOK_SECRET` diferente do secret no GitHub App.
- Run vai para `NEEDS_HUMAN`: `LLM_API_KEY` ausente.
- Sem check/comment no PR: confira `GITHUB_APP_ID`, private key, instalacao do app e
  permissoes de `Pull requests` e `Checks`.
- GitHub nao chama o app: tunnel desligado ou Webhook URL antigo.
- Compose falha montando a chave: confira se
  `secrets/github-app-private-key.pem` existe.
