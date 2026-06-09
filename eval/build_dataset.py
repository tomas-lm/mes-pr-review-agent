#!/usr/bin/env python3
"""
build_dataset.py -- Filtra e enriquece o CodeReviewer dataset para avaliacao
do MES PR Review Agent.

FASE 1 : Filtros de selecao  (linguagem, tamanho, qualidade do comentario)
FASE 2 : Enriquecimento      (file_path, pr_title, pr_body, repo_rules)
FASE 3 : Injecao LGTM        (10 exemplos sinteticos y=0 em Python e JS)

Uso:
    cd mes-pr-review-agent
    python eval/build_dataset.py

Saida:
    eval/mes_filtered_dataset.json  (40 itens: 30 reais + 10 sinteticos)
"""
from __future__ import annotations

import difflib
import hashlib
import json
import random
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuracao
# ---------------------------------------------------------------------------
DATASET_PATH = Path(__file__).parent.parent / "msg-test.jsonl"
OUTPUT_PATH  = Path(__file__).parent / "mes_filtered_dataset.json"

RANDOM_SEED  = 42
SAMPLE_SIZE  = 30   # exemplos reais filtrados
LGTM_SIZE    = 10   # exemplos sinteticos y=0

# Limites de contexto
OLDF_MIN_LINES  = 30    # arquivo base muito pequeno nao oferece contexto
OLDF_MAX_LINES  = 300   # arquivo base muito grande estoura a janela do LLM
DIFF_MIN_LINES  = 5     # diff trivial demais (< 5 linhas alteradas)
DIFF_MAX_LINES  = 30    # diff gigante demais (> 30 linhas alteradas)

# ---------------------------------------------------------------------------
# FASE 1 -- Filtros de selecao
# ---------------------------------------------------------------------------

ALLOWED_LANGS = {"py", "js"}

# Palavras que indicam comentario de ESTILO/FORMATACAO (nao de logica)
_TRIVIAL_RE = re.compile(
    r"\b(spaces?|typos?|camel.?case|pascal.?case|formatting?|indent(ation)?|"
    r"newlines?|whitespace|semicolons?|trailing|linting?|blank.line|"
    r"missing.comma|unused.import|import.order|alphabetical)\b",
    re.IGNORECASE,
)

# Palavras que indicam comentario de SUBSTANCIA (logica, bug, seguranca)
_SUBSTANCE_RE = re.compile(
    r"\b(bug|error|exception|null|none|undefined|crash|fail|logic|incorrect|"
    r"wrong|missing|should|must|need|check|validat|handle|return|value|"
    r"type|secur|performance|race.condition|memory|leak|thread|async|"
    r"await|promise|overflow|underflow|condition|loop|inject|escape|"
    r"unsafe|vulnerab|off.by.one|index|bound|division|zero)\b",
    re.IGNORECASE,
)


def filter_lang(item: dict) -> bool:
    """Manter apenas Python e JavaScript."""
    return item.get("lang") in ALLOWED_LANGS


def filter_oldf_lines(item: dict) -> bool:
    """Arquivo base deve ter entre OLDF_MIN_LINES e OLDF_MAX_LINES."""
    lines = len(item.get("oldf", "").splitlines())
    return OLDF_MIN_LINES <= lines <= OLDF_MAX_LINES


def filter_diff_size(item: dict) -> bool:
    """
    Contagem de linhas adicionadas + removidas no patch.
    Ignora as linhas de cabecalho (+++ / ---) e de hunk (@@).
    """
    patch = item.get("patch", "")
    added   = sum(1 for ln in patch.splitlines()
                  if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in patch.splitlines()
                  if ln.startswith("-") and not ln.startswith("---"))
    total = added + removed
    return DIFF_MIN_LINES <= total <= DIFF_MAX_LINES


def filter_quality(item: dict) -> bool:
    """
    Descarta comentarios triviais de formatacao/estilo.
    Regra: tem palavra trivial E nao tem palavra de substancia.
    Tambem descarta mensagens vazias ou curtissimas (< 15 chars).
    """
    msg = item.get("msg", "").strip()
    if len(msg) < 15:
        return False
    has_trivial   = bool(_TRIVIAL_RE.search(msg))
    has_substance = bool(_SUBSTANCE_RE.search(msg))
    if has_trivial and not has_substance:
        return False
    return True


def passes_all_filters(item: dict) -> bool:
    return (
        filter_lang(item)
        and filter_oldf_lines(item)
        and filter_diff_size(item)
        and filter_quality(item)
    )


# ---------------------------------------------------------------------------
# FASE 2 -- Enriquecimento
# ---------------------------------------------------------------------------

_PY_PATHS = [
    "src/utils.py",         "src/models.py",       "src/validators.py",
    "src/processors.py",    "src/handlers.py",      "src/services.py",
    "src/api/views.py",     "src/api/serializers.py","src/auth/middleware.py",
    "src/db/queries.py",    "src/core/config.py",   "src/core/errors.py",
    "app/routes.py",        "app/schemas.py",        "utils/helpers.py",
]

_JS_PATHS = [
    "frontend/app.js",       "src/utils.js",          "components/Button.js",
    "services/api.js",       "utils/helpers.js",       "lib/client.js",
    "hooks/useData.js",      "store/actions.js",       "pages/index.js",
    "middleware/auth.js",    "src/core/config.js",     "components/Form.js",
    "frontend/index.js",     "api/routes.js",          "lib/request.js",
]

_PR_TITLES = [
    "fix: correct edge case in validation logic",
    "feat: add helper function for data processing",
    "refactor: simplify error handling in service layer",
    "fix: handle null/undefined values in utility function",
    "feat: extend module with additional functionality",
    "fix: resolve incorrect behavior in core logic",
    "refactor: improve readability of processing pipeline",
    "fix: prevent runtime error in data transformation",
    "feat: add input validation to public API",
    "fix: correct off-by-one error in loop condition",
    "fix: avoid unhandled exception in async path",
    "feat: expose new endpoint for resource management",
    "refactor: extract duplicated code into shared helper",
    "fix: ensure resource cleanup on early return",
    "feat: add boundary checks to collection operations",
]

_PR_BODIES = [
    "This PR introduces changes to fix the recent edge case found during testing.",
    "Adds validation to prevent unexpected behavior when input is malformed.",
    "Refactors the module to improve readability and reduce cyclomatic complexity.",
    "Fixes a regression introduced in the last release affecting the data pipeline.",
    "Extends the existing API with a new utility that covers the missing use case.",
]

_PY_RULES = [
    "All new functions must have type hints (PEP 484).",
    "Use f-strings for string formatting (no % or .format).",
    "Every public function requires a one-line docstring.",
    "Raise specific exceptions, never bare `raise Exception`.",
    "Avoid mutable default arguments in function signatures.",
]

_JS_RULES = [
    "Use arrow functions for callbacks; avoid `function` expressions.",
    "Prefer `const` over `let`; never use `var`.",
    "All async functions must have explicit error handling (try/catch).",
    "Use optional chaining (`?.`) instead of manual null checks.",
    "Export only named exports; avoid default exports in utility modules.",
]


def _hash_idx(item: dict, pool_size: int, salt: int = 0) -> int:
    content = (item.get("patch", "") + item.get("oldf", ""))[:300]
    digest  = int(hashlib.md5(
        (content + str(salt)).encode(), usedforsecurity=False
    ).hexdigest(), 16)
    return digest % pool_size


def enrich(item: dict, index: int) -> dict:
    """Adiciona os campos de mock que simulam metadados de um PR real."""
    lang = item.get("lang", "py")
    path_pool = _PY_PATHS if lang == "py" else _JS_PATHS
    rule_pool = _PY_RULES if lang == "py" else _JS_RULES

    item["file_path"]  = path_pool[_hash_idx(item, len(path_pool))]
    item["pr_title"]   = _PR_TITLES[index % len(_PR_TITLES)]
    item["pr_body"]    = _PR_BODIES[index % len(_PR_BODIES)]
    item["repo_rules"] = rule_pool[_hash_idx(item, len(rule_pool), salt=1)]

    # Alias para compatibilidade com phase2_mock_runner.py
    item["fake_path"]  = item["file_path"]
    return item


# ---------------------------------------------------------------------------
# FASE 3 -- Geracao de exemplos sinteticos LGTM (y=0)
# ---------------------------------------------------------------------------

def _make_patch(old_content: str, new_content: str) -> str:
    """
    Usa difflib para gerar um unified diff correto entre dois textos.
    Remove as linhas de cabecalho (--- / +++) e retorna apenas os hunks.
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    hunks = [ln for ln in diff
             if not ln.startswith("---") and not ln.startswith("+++")]
    return "\n".join(hunks)


# ---- Definicao dos 10 exemplos (5 Python + 5 JavaScript) ----
# Cada entrada: (oldf, new_content, lang, file_path, description)

def _build_synthetic_specs() -> list[dict]:
    specs = []

    # --- Python 1: validadores de email e URL ---
    py1_old = (
        "import re\n"
        "\n"
        "\n"
        "def is_valid_email(email: str) -> bool:\n"
        "    return bool(re.match(r'^[^@]+@[^@]+\\.[^@]+$', email))\n"
    )
    py1_new = py1_old + (
        "\n"
        "\n"
        "def is_valid_url(url: str) -> bool:\n"
        "    return url.startswith(('http://', 'https://')) and '.' in url\n"
    )
    specs.append((py1_old, py1_new, "py", "src/validators.py",
                  "Adicao de is_valid_url junto a is_valid_email -- sem bugs"))

    # --- Python 2: truncagem de string ---
    py2_old = (
        "def truncate(text: str, max_length: int, suffix: str = '...') -> str:\n"
        "    if len(text) <= max_length:\n"
        "        return text\n"
        "    return text[:max_length - len(suffix)] + suffix\n"
    )
    py2_new = (
        "def truncate(text: str, max_length: int, suffix: str = '...') -> str:\n"
        "    if max_length <= 0:\n"
        "        raise ValueError(f'max_length must be positive, got {max_length}')\n"
        "    if len(text) <= max_length:\n"
        "        return text\n"
        "    return text[:max_length - len(suffix)] + suffix\n"
    )
    specs.append((py2_old, py2_new, "py", "src/string_utils.py",
                  "Guard de max_length <= 0 em truncate -- prevencao correta"))

    # --- Python 3: deduplicacao de lista ---
    py3_old = (
        "from typing import Callable, TypeVar\n"
        "\n"
        "T = TypeVar('T')\n"
        "\n"
        "\n"
        "def deduplicate(items: list[T]) -> list[T]:\n"
        "    seen: set = set()\n"
        "    result: list[T] = []\n"
        "    for item in items:\n"
        "        if item not in seen:\n"
        "            seen.add(item)\n"
        "            result.append(item)\n"
        "    return result\n"
    )
    py3_new = py3_old + (
        "\n"
        "\n"
        "def deduplicate_by(\n"
        "    items: list[T],\n"
        "    key: Callable[[T], object],\n"
        ") -> list[T]:\n"
        "    seen: set = set()\n"
        "    result: list[T] = []\n"
        "    for item in items:\n"
        "        k = key(item)\n"
        "        if k not in seen:\n"
        "            seen.add(k)\n"
        "            result.append(item)\n"
        "    return result\n"
    )
    specs.append((py3_old, py3_new, "py", "src/collections_utils.py",
                  "Adicao de deduplicate_by com key function -- correto"))

    # --- Python 4: acesso seguro em dict aninhado ---
    py4_old = (
        "from typing import Any\n"
        "\n"
        "\n"
        "def safe_get(data: dict, *keys: str, default: Any = None) -> Any:\n"
        "    current: Any = data\n"
        "    for key in keys:\n"
        "        if not isinstance(current, dict):\n"
        "            return default\n"
        "        current = current.get(key, default)\n"
        "    return current\n"
    )
    py4_new = py4_old + (
        "\n"
        "\n"
        "def safe_set(data: dict, value: Any, *keys: str) -> None:\n"
        "    if not keys:\n"
        "        return\n"
        "    for key in keys[:-1]:\n"
        "        data = data.setdefault(key, {})\n"
        "    data[keys[-1]] = value\n"
    )
    specs.append((py4_old, py4_new, "py", "src/dict_utils.py",
                  "Adicao de safe_set simetrico ao safe_get -- sem bugs"))

    # --- Python 5: formatacao de numero ---
    py5_old = (
        "def format_bytes(n: int) -> str:\n"
        "    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):\n"
        "        if abs(n) < 1024:\n"
        "            return f'{n:.1f} {unit}'\n"
        "        n //= 1024\n"
        "    return f'{n:.1f} PB'\n"
    )
    py5_new = (
        "def format_bytes(n: int) -> str:\n"
        "    if n < 0:\n"
        "        raise ValueError(f'n must be non-negative, got {n}')\n"
        "    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):\n"
        "        if abs(n) < 1024:\n"
        "            return f'{n:.1f} {unit}'\n"
        "        n //= 1024\n"
        "    return f'{n:.1f} PB'\n"
    )
    specs.append((py5_old, py5_new, "py", "src/formatters.py",
                  "Guard de n < 0 em format_bytes -- validacao correta"))

    # --- JavaScript 1: utilitarios aritmeticos ---
    js1_old = (
        "function add(a, b) {\n"
        "  return a + b;\n"
        "}\n"
    )
    js1_new = (
        "function add(a, b) {\n"
        "  return a + b;\n"
        "}\n"
        "\n"
        "function subtract(a, b) {\n"
        "  return a - b;\n"
        "}\n"
    )
    specs.append((js1_old, js1_new, "js", "src/math_utils.js",
                  "Adicao de subtract junto a add -- sem bugs"))

    # --- JavaScript 2: helpers de array ---
    js2_old = (
        "function filterByPredicate(arr, predicate) {\n"
        "  if (!Array.isArray(arr)) {\n"
        "    throw new TypeError('arr must be an array');\n"
        "  }\n"
        "  return arr.filter(predicate);\n"
        "}\n"
    )
    js2_new = js2_old + (
        "\n"
        "function groupBy(arr, keyFn) {\n"
        "  return arr.reduce((acc, item) => {\n"
        "    const key = keyFn(item);\n"
        "    if (!acc[key]) acc[key] = [];\n"
        "    acc[key].push(item);\n"
        "    return acc;\n"
        "  }, {});\n"
        "}\n"
    )
    specs.append((js2_old, js2_new, "js", "frontend/array_helpers.js",
                  "Adicao de groupBy ao lado de filterByPredicate -- correto"))

    # --- JavaScript 3: fetch com timeout ---
    js3_old = (
        "async function fetchData(url) {\n"
        "  const response = await fetch(url);\n"
        "  if (!response.ok) {\n"
        "    throw new Error(`HTTP error: ${response.status}`);\n"
        "  }\n"
        "  return response.json();\n"
        "}\n"
    )
    js3_new = (
        "async function fetchData(url, timeout = 5000) {\n"
        "  const controller = new AbortController();\n"
        "  const timerId = setTimeout(() => controller.abort(), timeout);\n"
        "  try {\n"
        "    const response = await fetch(url, { signal: controller.signal });\n"
        "    if (!response.ok) {\n"
        "      throw new Error(`HTTP error: ${response.status}`);\n"
        "    }\n"
        "    return response.json();\n"
        "  } finally {\n"
        "    clearTimeout(timerId);\n"
        "  }\n"
        "}\n"
    )
    specs.append((js3_old, js3_new, "js", "services/api.js",
                  "fetchData com AbortController e timeout -- correto"))

    # --- JavaScript 4: Stack com pop ---
    js4_old = (
        "class Stack {\n"
        "  constructor() {\n"
        "    this.items = [];\n"
        "  }\n"
        "\n"
        "  push(item) {\n"
        "    this.items.push(item);\n"
        "  }\n"
        "}\n"
    )
    js4_new = (
        "class Stack {\n"
        "  constructor() {\n"
        "    this.items = [];\n"
        "  }\n"
        "\n"
        "  push(item) {\n"
        "    this.items.push(item);\n"
        "  }\n"
        "\n"
        "  pop() {\n"
        "    if (this.items.length === 0) return undefined;\n"
        "    return this.items.pop();\n"
        "  }\n"
        "\n"
        "  get size() {\n"
        "    return this.items.length;\n"
        "  }\n"
        "}\n"
    )
    specs.append((js4_old, js4_new, "js", "components/Stack.js",
                  "Stack com pop() e getter size -- sem bugs"))

    # --- JavaScript 5: request com defaults ---
    js5_old = (
        "const DEFAULT_TIMEOUT = 5000;\n"
        "\n"
        "function createRequest(url, options = {}) {\n"
        "  return fetch(url, { ...options });\n"
        "}\n"
    )
    js5_new = (
        "const DEFAULT_TIMEOUT = 5000;\n"
        "const DEFAULT_HEADERS = { 'Content-Type': 'application/json' };\n"
        "\n"
        "function createRequest(url, options = {}) {\n"
        "  return fetch(url, {\n"
        "    timeout: DEFAULT_TIMEOUT,\n"
        "    headers: DEFAULT_HEADERS,\n"
        "    ...options,\n"
        "  });\n"
        "}\n"
    )
    specs.append((js5_old, js5_new, "js", "lib/request.js",
                  "createRequest com headers e timeout padrao -- correto"))

    return specs


def build_synthetic_lgtm(index: int) -> dict:
    """Constroi o i-esimo exemplo sintetico LGTM (y=0)."""
    specs = _build_synthetic_specs()
    old_content, new_content, lang, file_path, description = specs[index]

    patch = _make_patch(old_content, new_content)

    # Contar linhas adicionadas para verificacao interna
    added = sum(1 for ln in patch.splitlines()
                if ln.startswith("+") and not ln.startswith("+++"))

    rule_pool = _PY_RULES if lang == "py" else _JS_RULES

    return {
        "patch":       patch,
        "oldf":        old_content,
        "lang":        lang,
        "msg":         "",
        "y":           0,
        "file_path":   file_path,
        "fake_path":   file_path,   # alias para compatibilidade
        "pr_title":    "refactor: clean up and extend utility module",
        "pr_body":     "Minor improvements to the utility module. No logic changes.",
        "repo_rules":  rule_pool[index % len(rule_pool)],
        "synthetic":   True,
        "description": description,
        "id":          f"synthetic_{index:02d}",
        "idx":         -(index + 1),
        "proj":        "synthetic",
        # Metadados de verificacao (util para debug)
        "_added_lines": added,
    }


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def load_and_filter(path: Path) -> list[dict]:
    """Carrega o JSONL e aplica todos os filtros da Fase 1."""
    raw: list[dict] = []
    parse_errors = 0

    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                item = json.loads(raw_line)
                raw.append(item)
            except json.JSONDecodeError:
                parse_errors += 1

    print(f"  Linhas lidas    : {len(raw) + parse_errors}")
    print(f"  Erros de parse  : {parse_errors}")

    # Contagem por etapa (para rastreabilidade)
    after_lang   = [x for x in raw if filter_lang(x)]
    after_oldf   = [x for x in after_lang if filter_oldf_lines(x)]
    after_diff   = [x for x in after_oldf if filter_diff_size(x)]
    after_qual   = [x for x in after_diff if filter_quality(x)]

    print(f"\n  Apos filtro de linguagem ({', '.join(sorted(ALLOWED_LANGS))}):")
    print(f"    {len(after_lang):>6} itens")
    print(f"  Apos filtro oldf ({OLDF_MIN_LINES}-{OLDF_MAX_LINES} linhas):")
    print(f"    {len(after_oldf):>6} itens  (descartados: {len(after_lang) - len(after_oldf)})")
    print(f"  Apos filtro diff ({DIFF_MIN_LINES}-{DIFF_MAX_LINES} linhas):")
    print(f"    {len(after_diff):>6} itens  (descartados: {len(after_oldf) - len(after_diff)})")
    print(f"  Apos filtro qualidade (sem triviais de estilo):")
    print(f"    {len(after_qual):>6} itens  (descartados: {len(after_diff) - len(after_qual)})")

    if len(after_qual) < SAMPLE_SIZE:
        print(
            f"\n[AVISO] Apenas {len(after_qual)} itens passaram em todos os filtros; "
            f"reducindo SAMPLE_SIZE de {SAMPLE_SIZE} para {len(after_qual)}.",
            file=sys.stderr,
        )

    return after_qual


def main() -> None:
    print("=" * 62)
    print("  build_dataset.py -- MES PR Review Agent Dataset Builder")
    print("=" * 62)

    if not DATASET_PATH.exists():
        print(f"[ERRO] Dataset nao encontrado: {DATASET_PATH}", file=sys.stderr)
        sys.exit(1)

    # ---- FASE 1: Filtrar ------------------------------------------------
    print(f"\n[FASE 1] Filtrando {DATASET_PATH.name}...")
    candidates = load_and_filter(DATASET_PATH)

    # Amostragem reproduzivel
    random.seed(RANDOM_SEED)
    n = min(SAMPLE_SIZE, len(candidates))
    sampled = random.sample(candidates, n)
    print(f"\n  Amostrados      : {n} itens (seed={RANDOM_SEED})")

    # ---- FASE 2: Enriquecer ---------------------------------------------
    print(f"\n[FASE 2] Enriquecendo com metadados de PR...")
    enriched = [enrich(item, idx) for idx, item in enumerate(sampled)]

    # Estatisticas por linguagem apos enriquecimento
    py_count = sum(1 for x in enriched if x.get("lang") == "py")
    js_count = sum(1 for x in enriched if x.get("lang") == "js")
    print(f"  Python : {py_count} | JavaScript : {js_count}")

    # ---- FASE 3: Injetar exemplos LGTM ----------------------------------
    print(f"\n[FASE 3] Gerando {LGTM_SIZE} exemplos sinteticos LGTM (y=0)...")
    lgtm_examples = [build_synthetic_lgtm(i) for i in range(LGTM_SIZE)]

    # Verificacao basica: todos os patches tem pelo menos 1 linha adicionada
    for ex in lgtm_examples:
        added = ex["_added_lines"]
        if added == 0:
            print(f"  [AVISO] Exemplo {ex['id']} tem 0 linhas adicionadas!", file=sys.stderr)
        else:
            print(f"  {ex['id']:>14}  lang={ex['lang']}  +lines={added:>2}  {ex['description'][:50]}")

    # Embaralhar LGTM entre os exemplos reais (evita vies de posicao)
    random.seed(RANDOM_SEED + 1)
    combined: list[dict] = list(enriched)
    positions = sorted(random.sample(range(len(combined) + LGTM_SIZE), LGTM_SIZE))
    for offset, pos in enumerate(positions):
        combined.insert(pos + offset, lgtm_examples[offset])

    # ---- Salvar ---------------------------------------------------------
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=2, ensure_ascii=False)

    # ---- Relatorio final ------------------------------------------------
    total   = len(combined)
    n_real  = sum(1 for x in combined if not x.get("synthetic"))
    n_synth = sum(1 for x in combined if x.get("synthetic"))
    n_y1    = sum(1 for x in combined if x.get("y") == 1)
    n_y0    = sum(1 for x in combined if x.get("y") == 0)

    print(f"\n{'=' * 62}")
    print(f"  Dataset salvo em: {OUTPUT_PATH.resolve()}")
    print(f"  Total           : {total} itens")
    print(f"    Reais  (y=1)  : {n_real}")
    print(f"    LGTM   (y=0)  : {n_synth} sinteticos")
    print(f"  Distribuicao y  : y=1={n_y1}  y=0={n_y0}")
    print(f"{'=' * 62}")
    print("\n[OK] build_dataset.py concluido.")
    print("     Proximo passo: python eval/phase2_mock_runner.py")
    print("     (certifique-se de apontar DATASET_PATH para mes_filtered_dataset.json)")


if __name__ == "__main__":
    main()
