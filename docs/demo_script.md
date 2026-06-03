# Roteiro de apresentacao

Tempo sugerido: 5 a 7 minutos.

## 1. Contexto rapido

Este projeto e um revisor automatico de Pull Requests. A ideia e aplicar no TP os
conceitos do trabalho: dynamic prompt, maquina de estados e agentic loop.

O agente nao simplesmente recebe um diff e responde. Ele passa por fases, usa
tools para coletar contexto, registra observacoes, valida os findings e so depois
publica no GitHub.

## 2. Mostrar arquitetura

Use o desenho do README ou explique:

```text
PR no GitHub -> Webhook -> FastAPI local -> Agente -> Validador -> GitHub API
```

Ponto importante para falar:

- O sistema roda local em Docker.
- O tunnel e apenas uma ponte temporaria para o GitHub entregar o webhook.
- A publicacao ainda acontece no GitHub real: check run e comentario no PR.

## 3. Mostrar configuracao local

Mostre:

```bash
docker compose up --build
curl http://localhost:8020/health
```

Explique que as credenciais ficam no `.env` e a private key fica em
`secrets/github-app-private-key.pem`, fora do git.

## 4. Mostrar o GitHub App

Mostre as permissoes:

- Contents: read, para ler arquivos do PR.
- Pull requests: write, para publicar review.
- Checks: write, para criar o check run.
- Issues: write, porque comentarios de PR usam a area de comentarios/issues em
  alguns fluxos da API.

Mostre o webhook apontando para:

```text
https://<tunnel>/webhooks/github
```

## 5. Abrir PR com bug simples

Exemplo:

```python
def normalize_email(email: str | None) -> str:
    return email.strip().lower()
```

Fala sugerida:

> O tipo aceita `None`, mas o codigo chama `.strip()` sem verificar. Esse e um bug
> bom para demo porque e pequeno, objetivo e facil de entender.

## 6. Mostrar resultado no PR

Mostre:

- check run `MES PR Reviewer`;
- comentario inline;
- corpo da review com contagem de findings aceitos, resumidos e descartados.

Fala sugerida:

> O comentario nao sai direto do LLM. Antes de publicar, o backend valida se a
> linha existe no diff, se ha evidencia, se a confianca e suficiente e se nao ha
> segredo ou raciocinio interno no texto.

## 7. Mostrar trace sanitizado

Abra:

```text
review_runs/<run_id>.md
```

Mostre:

- estado inicial/final;
- historico de transicoes;
- tools chamadas;
- erros de tool, se houver;
- findings publicaveis, de resumo e descartados;
- check run id e quantidade de comentarios.

Fala sugerida:

> Esse arquivo e importante para a disciplina porque mostra que o agente seguiu
> um processo controlado. Ele e auditavel, mas nao salva resposta bruta do modelo,
> token de instalacao nem secrets.

## 8. Fechamento

Mensagem final:

> A contribuicao do projeto e transformar a revisao de PR em um processo agentico:
> o prompt muda conforme o estado, a maquina de estados guia as fases, as tools
> trazem evidencia concreta e o validador impede publicacoes fracas.
