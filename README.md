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

## Demo local com Docker

Para o TP, o caminho recomendado e rodar tudo localmente com Docker e usar um
tunnel temporario para o GitHub entregar webhooks:

```bash
cp .env.example .env
mkdir -p secrets review_runs
docker compose up --build
```

Depois abra um tunnel para a porta `8020`:

```bash
ngrok http 8020
```

Configure o webhook do GitHub App para:

```text
https://<tunnel>/webhooks/github
```

Guia completo: [docs/local_demo.md](docs/local_demo.md)
Roteiro de apresentacao: [docs/demo_script.md](docs/demo_script.md)

## LLM / Kimi 2.6

O loop agentico usa um cliente OpenAI-compatible. Para Kimi 2.6 via Telnyx:

```text
LLM_API_BASE_URL=https://api.telnyx.com/v2/ai
LLM_MODEL=moonshotai/Kimi-K2.6
LLM_API_KEY=<telnyx-api-key>
AGENT_MAX_TURNS=12
```

Sem `LLM_API_KEY`, o webhook nao inventa revisao: ele registra a run como `NEEDS_HUMAN` e escreve a pendencia no Markdown da run.

## Loop agentico

O agente segue o protocolo inspirado no Model Garden:

```xml
<tool name="rewrite_state_prompt">
{"state":"TRIAGE","state_prompt":"...","reason":"..."}
</tool>
```

Resposta final:

```xml
<final>
{"decision":"comment","summary":"...","findings":[],"trace_notes":[]}
</final>
```

Tools iniciais:

- `get_state_machine`: mostra estado atual e transicoes permitidas.
- `rewrite_state_prompt`: reescreve a camada dinamica de estado do system prompt.
- `append_review_observation`: registra observacoes e pendencias em Markdown.
- `get_pr_metadata`: retorna metadados conhecidos do PR.

As observacoes ficam em `review_runs/<run_id>.md` por padrao.

## Webhook local sem Docker

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

## Observabilidade da demo

Cada run escreve um Markdown em `review_runs/<run_id>.md` com:

- estado atual e camada dinamica do prompt;
- observacoes registradas pelas tools;
- trace sanitizado com repo, PR, head SHA, transicoes, tool calls, erros,
  validacao e publicacao.

O trace nao grava resposta bruta do modelo, installation token ou secrets.

## Estado atual

Implementado:

- API FastAPI.
- `GET /health`.
- `POST /webhooks/github`.
- Validacao HMAC SHA-256 via `X-Hub-Signature-256`.
- Idempotencia por `X-GitHub-Delivery`.
- Criacao de run em estado `RECEIVED`.
- Dynamic System Prompt em camadas, inspirado na BAMAQ.
- Maquina de estados dentro do proprio prompt.
- Tool para reescrever a camada dinamica de estado.
- Tool para escrever observacoes e pendencias em Markdown.
- Loop agentico multi-turn inspirado no Model Garden.
- Cliente LLM OpenAI-compatible configurado para Kimi 2.6/Telnyx.
- Schema de findings.
