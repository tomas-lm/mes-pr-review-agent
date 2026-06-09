# Pipeline de Avaliação do MES PR Review Agent

Este documento descreve o pipeline de avaliação automatizada criado para medir a qualidade e
resiliência do agente revisor de Pull Requests em contexto acadêmico. O pipeline não depende do
GitHub: todas as chamadas de API são interceptadas por um mock que injeta dados do dataset
[CodeReviewer](https://github.com/microsoft/CodeBERT/tree/master/CodeReviewer).

---

## Estrutura dos Arquivos

```
mes-pr-review-agent/
└── eval/
    ├── __init__.py
    ├── build_dataset.py         # Dataset avancado (py+js, filtros extras)
    ├── phase1_data_prep.py      # Dataset basico (apenas py, legado)
    ├── phase2_mock_runner.py    # Fase 2: executa o agente com mock
    ├── phase3_metrics.py        # Fase 3: calcula metricas e LaTeX
    ├── mes_filtered_dataset.json # Criado por build_dataset.py
    ├── golden_dataset_mes.json  # Criado pela Fase 1 (legado)
    ├── results/
    │   └── run_results.jsonl    # Criado pela Fase 2
    └── review_runs/
        └── <run_id>.md          # Log de cada run (criado pela Fase 2)
```

---

## Pré-requisitos

1. Dataset `msg-test.jsonl` na raiz do projeto (já incluso no repositório).
2. Variável de ambiente `LLM_API_KEY` configurada no `.env`.
3. Dependências instaladas (`pydantic`, `pydantic-settings`, `httpx`).
   - `pip install pydantic pydantic-settings httpx`

---

## Execução (ordem obrigatória)

> **Importante:** todos os comandos devem ser rodados a partir do diretório
> `mes-pr-review-agent/` (não da raiz `PR-Revisor/`).

```powershell
cd "...\PR-Revisor\mes-pr-review-agent"

# PREPARO — Gera o dataset filtrado avancado (30 reais + 10 sinteticos LGTM)
#   Filtros: lang py|js, oldf 30-300 linhas, diff 5-30 linhas, sem triviais de estilo
#   Enriquece com file_path, pr_title, pr_body, repo_rules
#   Saida: eval/mes_filtered_dataset.json  (40 itens)
python eval/build_dataset.py

# FASE 2 — Executa o agente nos 40 itens (usa LLM real, ~20-40 min)
python eval/phase2_mock_runner.py

# Flags uteis na Fase 2:
#   --dry-run         executa apenas os 3 primeiros itens (smoke test rapido)
#   --item 5          executa apenas o item de indice 5
#   --resume          pula runs ja salvas em run_results.jsonl (retomada)

# FASE 3 — Calcula metricas e gera tabelas LaTeX
python eval/phase3_metrics.py

# Para listagem por item + salvar relatorio completo:
python eval/phase3_metrics.py --qualitative --out eval/results/report.md
```

### Dataset legado (apenas Python)

O script `eval/phase1_data_prep.py` gera `golden_dataset_mes.json` com filtro
exclusivo para Python. Mantido para compatibilidade; **prefira `build_dataset.py`**
para experimentos novos.

---

## Fase 1 — Preparação dos Dados

**Script:** `eval/phase1_data_prep.py`

**O que faz:**
- Lê `msg-test.jsonl` e filtra apenas exemplos com `"lang": "py"`.
- Amostra 30 exemplos aleatoriamente com `RANDOM_SEED=42` (reproduzível).
- Atribui um **fake path** determinístico a cada exemplo (ex: `src/utils.py`) usando
  hash MD5 do conteúdo — garante que o mesmo item sempre receba o mesmo path.
- Injeta 10 exemplos sintéticos de código limpo (`y=0`, `msg=""`) distribuídos
  aleatoriamente entre os reais.
- Salva `eval/golden_dataset_mes.json` (array JSON de 40 objetos).

**Formato de cada item no golden dataset:**

| Campo        | Tipo    | Descrição                                         |
|--------------|---------|---------------------------------------------------|
| `patch`      | string  | Unified diff (hunk de alteração)                  |
| `oldf`       | string  | Conteúdo do arquivo antes da alteração            |
| `msg`        | string  | Comentário humano real (vazio em exemplos limpos) |
| `y`          | int     | 1 = tem bug/issue, 0 = código limpo               |
| `lang`       | string  | Linguagem ("py")                                  |
| `fake_path`  | string  | Path fictício atribuído (ex: `src/validators.py`) |
| `synthetic`  | bool    | True = exemplo criado artificialmente             |

**Por que exemplos sintéticos?**
O dataset CodeReviewer contém apenas exemplos com review comments (`y=1`). Para testar
**Falsos Positivos** (o agente alucina findings em código correto), é necessário injetar
exemplos limpos sem nenhum bug real. Os 10 exemplos sintéticos cobrem padrões típicos de
Python (dataclasses, context managers, generators, decorators etc.).

---

## Fase 2 — Motor de Mocking e Execução

**Script:** `eval/phase2_mock_runner.py`

**Arquitetura do mock:**

```
golden_dataset_mes.json
    │
    ▼
MockGitHubPRClient(item)          ← implementa GitHubPRClient protocol
    │  list_pull_request_files()  → retorna fake_path + patch real
    │  get_file_contents_at_ref() → retorna oldf (base) ou oldf+patch (head)
    │  list_check_runs_for_ref()  → retorna [] (sem CI no dataset)
    ▼
PullRequestToolContext(mock_client, owner="eval", repo="mock-repo", ...)
    │
    ├─ DynamicPromptSession(state=RECEIVED, runtime_context={...})
    ├─ ReviewNotesWriter(notes_dir="eval/review_runs/")
    ├─ build_review_tool_registry(session, notes_writer, pr_payload, pr_context)
    │     Todas as 11 tools registradas; ferramentas de contexto usam o mock.
    │
    └─ AgenticLoop(model_client=real_llm, tool_executor=registry.call)
           │
           └─ validate_agent_review_payload(final_payload, pr_context=mock)
                  │  Validação de linha usa _changed_lines_by_side(patch_real)
                  └─ ValidatedReviewPayload → métricas
```

**O que é mockado:**

| Tool do agente          | O mock retorna                                              |
|-------------------------|-------------------------------------------------------------|
| `list_changed_files`    | `[{"filename": fake_path, "patch": patch, ...}]`            |
| `get_diff_hunks`        | Hunks extraídos do `patch` real via `_extract_hunks()`      |
| `read_file_at_ref(head)`| `apply_unified_diff(oldf, patch)` — arquivo pós-alteração   |
| `read_file_at_ref(base)`| `oldf` — arquivo original antes da alteração                |
| `read_repo_rules`       | Retorna `repo_rules` do dataset via `CONTRIBUTING.md` mock  |
| `get_ci_status`         | `{"total_count": 0, "check_runs": []}` — sem CI             |

**O que NÃO é mockado (usa a implementação real):**
- LLM (`OpenAICompatibleModelClient`)
- Máquina de estados (`DynamicPromptSession`, `rewrite_state_prompt`)
- Registro de findings (`record_finding_candidate`)
- Validação de linha (`validate_line_mapping` e `validate_agent_review_payload`)
- Registro de observações (`append_review_observation`, `ReviewNotesWriter`)

**Saída por run (`eval/results/run_results.jsonl`):**

```json
{
  "run_id": "uuid-...",
  "item_index": 7,
  "item_id": "1234",
  "y": 1,
  "synthetic": false,
  "fake_path": "src/validators.py",
  "original_msg": "This can throw NullPointerException...",
  "agent_decision": "request_changes",
  "publishable_count": 1,
  "summary_count": 0,
  "discarded_count": 2,
  "blocked_by_validator": 2,
  "validator_discard_reasons": {"line_not_in_diff": 1, "low_confidence": 1},
  "final_state": "VALIDATE_FINDINGS",
  "turns_used": 9,
  "agent_error": null,
  "validator_error": null,
  "notes_path": "eval/review_runs/<run_id>.md"
}
```

---

## Fase 3 — Analisador de Métricas

**Script:** `eval/phase3_metrics.py`

**Lógica de classificação binária:**

O agente é considerado **positivo** (encontrou problema) se `publishable_count + summary_count > 0`.

| Combinação                    | Classe | Significado                                          |
|-------------------------------|--------|------------------------------------------------------|
| `y=1` + `agent_flagged=True`  | TP     | Detectou bug real corretamente                       |
| `y=0` + `agent_flagged=True`  | FP     | Alucinação — finding em código limpo                 |
| `y=1` + `agent_flagged=False` | FN     | Perdeu o bug real                                    |
| `y=0` + `agent_flagged=False` | TN     | Corretamente ignorou código limpo                    |

**Métricas calculadas:**

```
Precision  = TP / (TP + FP)
Recall     = TP / (TP + FN)
F1         = 2 * P * R / (P + R)
Accuracy   = (TP + TN) / N

Validator blocking rate = total_discarded / (total_discarded + total_publishable)
```

**Saída LaTeX (4 tabelas prontas para inserção em artigo):**

1. `tab:eval-config` — configuração do experimento
2. `tab:confusion` — matriz de confusão
3. `tab:metrics` — precision, recall, F1, accuracy + análise de FP por camada
4. `tab:validator` — razões de descarte do validador e taxa de bloqueio

---

## Análise Qualitativa dos Logs Markdown

Cada run gera um arquivo `eval/review_runs/<run_id>.md` com:
- Estado atual e histórico de transições
- Observações registradas via `append_review_observation`
- Finding candidates registrados

**Categorias de análise:**

| Categoria      | Critério                                                       | Nota de investigação              |
|----------------|----------------------------------------------------------------|-----------------------------------|
| **SUCESSO**    | `y=1`, `publishable≥1`, finding alinha com `original_msg`      | Comparar títulos/evidências       |
| **RESILIÊNCIA**| `y=0`, `publishable=0` (com ou sem discarded)                  | `discarded>0` = validador agiu    |
| **FN / FALHA** | `y=1`, `publishable=0`                                         | Verificar se chegou a EVALUATE    |
| **FP VAZADO**  | `y=0`, `publishable>0`                                         | Alucinação que escapou ao validador|

Execute com `--qualitative` para obter o guia completo de extração.

---

## Reprodutibilidade

- Fase 1 é 100% determinística (seed fixo `RANDOM_SEED=42`).
- Fase 2 depende do modelo LLM: use `temperature=0.1` (já configurado no script)
  para resultados mais estáveis entre execuções.
- Fase 3 é puramente determinística (leitura de arquivo).

Para arquivar os resultados de uma sessão:
```bash
cp eval/results/run_results.jsonl eval/results/run_results_$(date +%Y%m%d).jsonl
```
