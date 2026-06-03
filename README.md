# MES PR Review Agent

Revisor automatico de Pull Requests criado para o trabalho de MES.

A ideia do projeto e demonstrar como um agente de IA pode revisar um PR de forma
mais controlada do que uma chamada simples para um LLM. Em vez de mandar o diff e
pedir "revise isso", o sistema guia o modelo por estados, oferece ferramentas
para buscar evidencias e valida os achados antes de publicar qualquer comentario
no GitHub.

Este projeto foi pensado para apresentacao academica e demo local. Nao precisa de
deploy permanente: ele roda na maquina com Docker e usa um tunnel temporario para
receber webhooks do GitHub.

## O Que O Projeto Faz

Quando alguem abre ou atualiza um Pull Request:

1. O GitHub envia um webhook para o backend.
2. O backend valida se o webhook veio mesmo do GitHub.
3. Uma run de revisao e criada.
4. O agente entra em um loop de investigacao.
5. O agente usa tools para ler contexto do PR.
6. O backend valida os findings do agente.
7. O resultado e publicado no GitHub como check run e review.
8. Um arquivo Markdown com trace sanitizado e salvo em `review_runs/`.

Fluxo resumido:

```text
Pull Request no GitHub
  -> GitHub App webhook
  -> FastAPI /webhooks/github
  -> validacao da assinatura HMAC
  -> maquina de estados
  -> dynamic system prompt
  -> agentic loop + tools
  -> validador de findings
  -> check run + review no PR
  -> trace em Markdown
```

## Conceito Principal

O projeto combina tres ideias:

- **Dynamic System Prompt**: o prompt do sistema muda durante a revisao.
- **Maquina de estados**: o agente precisa passar por fases claras.
- **Agentic Loop**: o modelo pode chamar tools, receber respostas e decidir o
  proximo passo.

Essas tres partes fazem o LLM trabalhar como um revisor guiado, nao como um chat
solto.

## Dynamic System Prompt

O system prompt e a instrucao principal que orienta o modelo. Neste projeto, ele
nao e fixo.

Ele tem camadas:

- regras gerais da revisao;
- contrato de saida;
- lista de tools disponiveis;
- contexto do PR;
- maquina de estados;
- estado atual da revisao;
- observacoes ja registradas.

A parte dinamica e a camada de estado. Ela muda conforme o agente avanca.

Exemplo simples:

```text
Estado atual: TRIAGE.

Objetivo imediato:
- entender se o PR deve ser analisado;
- identificar risco inicial;
- decidir se precisa coletar mais contexto.
```

Depois, o proprio agente pode chamar uma tool para reescrever essa camada:

```xml
<tool name="rewrite_state_prompt">
{
  "state": "COLLECT_CONTEXT",
  "state_prompt": "Listar arquivos alterados e ler regras do repositorio.",
  "reason": "A triagem indicou que o PR deve ser analisado."
}
</tool>
```

Isso simula um revisor que muda de foco conforme aprende mais sobre o PR.

## Maquina De Estados No Prompt

A maquina de estados tambem aparece dentro do prompt. O modelo recebe quais
estados existem e quais transicoes sao permitidas.

Estados principais:

- `RECEIVED`: o webhook chegou.
- `TRIAGE`: decidir se o PR deve ser revisado.
- `COLLECT_CONTEXT`: coletar arquivos, diff, regras e status de CI.
- `INVESTIGATE`: ler trechos especificos e entender o problema.
- `EVALUATE`: registrar findings candidatos.
- `VALIDATE_FINDINGS`: conferir se os findings realmente apontam para linhas do
  diff.
- `COMMENT_PLAN`: organizar o que sera publicado.
- `PUBLISH`: publicar check run e review no GitHub.
- `DONE`: revisao finalizada.

Estados de saida:

- `SKIPPED`: PR ignorado, por exemplo se for draft.
- `NEEDS_HUMAN`: faltou configuracao ou o caso precisa de pessoa.
- `ERROR`: houve erro tecnico.

O ponto importante para a apresentacao: o estado nao fica apenas no codigo. Ele
tambem e mostrado para o modelo no prompt, e o modelo precisa pedir a mudanca de
estado usando a tool correta.

## Agentic Loop

O agentic loop e o ciclo de interacao entre modelo, backend e tools.

Em cada turno:

1. O backend monta o system prompt atualizado.
2. O modelo responde chamando uma tool ou entregando uma resposta final.
3. Se chamou tool, o backend executa a tool.
4. O resultado da tool volta para o modelo.
5. O prompt pode mudar.
6. O ciclo continua ate a resposta final ou ate atingir o limite de turnos.

Formato de chamada de tool:

```xml
<tool name="list_changed_files">
{"max_files": 100}
</tool>
```

Formato da resposta final:

```xml
<final>
{
  "decision": "comment",
  "summary": "Resumo curto da revisao",
  "findings": []
}
</final>
```

Se o modelo chamar uma tool inexistente, repetir chamada ou entregar JSON final
invalido, o backend trata isso como erro controlado. A revisao nao e publicada
sem validacao.

## Tools Disponiveis

As tools sao as acoes que o modelo pode pedir para o backend executar.

Tools de controle:

- `get_state_machine`: mostra o estado atual e as transicoes permitidas.
- `rewrite_state_prompt`: muda o estado e reescreve a camada dinamica do prompt.
- `append_review_observation`: grava uma observacao no Markdown da run.

Tools de contexto do PR:

- `get_pr_metadata`: retorna titulo, autor, branch, SHA e dados do PR.
- `list_changed_files`: lista arquivos alterados.
- `get_diff_hunks`: retorna trechos do diff.
- `read_file_at_ref`: le um arquivo no head, base ou outro ref.
- `read_repo_rules`: tenta ler README, CONTRIBUTING e arquivos `.github`.
- `get_ci_status`: consulta checks do commit do PR.

Tools de revisao:

- `record_finding_candidate`: registra um achado candidato sem publicar.
- `validate_line_mapping`: confirma se path, linha e lado existem no diff.

Essa separacao deixa claro que o LLM nao tem acesso livre ao mundo. Ele atua por
ferramentas controladas pelo backend.

## Validacao Antes De Publicar

O projeto nao publica diretamente tudo que o LLM escreveu.

Antes de comentar no PR, o validador confere:

- se o finding tem formato valido;
- se a linha existe no diff;
- se o comentario aponta para o lado correto do diff;
- se existe evidencia concreta;
- se a confianca e suficiente;
- se nao e duplicado;
- se nao contem segredo completo;
- se nao contem raciocinio interno do modelo.

Findings ruins sao descartados ou movidos para resumo. Findings fortes podem
gerar comentario inline e, se forem graves, solicitar mudancas no PR.

## Observabilidade

Cada run gera um arquivo em:

```text
review_runs/<run_id>.md
```

Esse arquivo ajuda na apresentacao porque mostra o processo seguido pelo agente:

- repo, PR e head SHA;
- estado inicial e final;
- historico de transicoes;
- tools chamadas;
- erros de tool;
- findings aceitos, resumidos e descartados;
- status da publicacao no GitHub;
- check run id;
- quantidade de comentarios publicados.

Por seguranca, o trace nao salva:

- resposta bruta do modelo;
- installation token do GitHub;
- secrets encontrados no repositorio.

## Como Usar

### 1. Configurar ambiente

Copie o arquivo de exemplo:

```bash
cp .env.example .env
mkdir -p secrets review_runs
```

Edite `.env` com:

```text
GITHUB_APP_ID=<app-id>
GITHUB_WEBHOOK_SECRET=<secret-do-webhook>
LLM_API_BASE_URL=https://api.telnyx.com/v2/ai
LLM_MODEL=moonshotai/Kimi-K2.6
LLM_API_KEY=<telnyx-api-key>
```

Baixe a private key do GitHub App e salve em:

```text
secrets/github-app-private-key.pem
```

### 2. Subir local com Docker

```bash
docker compose up --build
```

Health check:

```bash
curl http://localhost:8020/health
```

Resposta esperada:

```json
{"status":"ok"}
```

### 3. Abrir tunnel para o GitHub

Com ngrok:

```bash
ngrok http 8020
```

Ou com cloudflared:

```bash
cloudflared tunnel --url http://localhost:8020
```

Configure o Webhook URL do GitHub App:

```text
https://<url-do-tunnel>/webhooks/github
```

### 4. Configurar GitHub App

Permissoes minimas:

- Metadata: read
- Contents: read
- Pull requests: read/write
- Issues: read/write
- Checks: read/write

Eventos:

- `pull_request`

Acoes tratadas:

- `opened`
- `reopened`
- `synchronize`
- `ready_for_review`

Guia detalhado: [docs/github_app_setup.md](docs/github_app_setup.md)

### 5. Abrir PR de demo

Crie uma branch no proprio repo e abra um PR com um bug simples:

```python
def normalize_email(email: str | None) -> str:
    return email.strip().lower()
```

O revisor deve perceber que `email` pode ser `None` e que `.strip()` quebraria.

Na apresentacao, mostre:

- webhook chegando;
- check run `MES PR Reviewer`;
- review/comment no PR;
- trace em `review_runs/<run_id>.md`.

## Rodando Sem Docker

Tambem e possivel rodar direto com `uv`:

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Nesse caso, use um tunnel para a porta `8000`:

```bash
ngrok http 8000
```

## Documentos De Apoio

- [Demo local](docs/local_demo.md)
- [Roteiro de apresentacao](docs/demo_script.md)
- [Configuracao do GitHub App](docs/github_app_setup.md)

## Resumo Para Apresentacao

Este projeto demonstra um revisor de PR agentico. O modelo nao apenas responde:
ele navega por uma maquina de estados, atualiza o proprio foco pelo dynamic system
prompt, usa tools para coletar evidencia e so publica depois que o backend valida
os findings.
