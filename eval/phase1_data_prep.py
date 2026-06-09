#!/usr/bin/env python3
"""
FASE 1 -- Preparação e Enriquecimento dos Dados
================================================
Lê msg-test.jsonl, filtra exemplos Python, atribui fake paths
determinísticos e injeta 10 exemplos sintéticos limpos (y=0).
Salva o resultado em eval/golden_dataset_mes.json.

Uso:
    cd mes-pr-review-agent
    python eval/phase1_data_prep.py
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
DATASET_PATH = Path(__file__).parent.parent / "msg-test.jsonl"
OUTPUT_PATH = Path(__file__).parent / "golden_dataset_mes.json"

RANDOM_SEED = 42
SAMPLE_SIZE = 30
SYNTHETIC_SIZE = 10  # exemplos limpos injetados

# Pool de paths Python realistas usados para atribuição determinística
FAKE_PATH_POOL = [
    "src/utils.py",
    "src/models.py",
    "src/validators.py",
    "src/processors.py",
    "src/handlers.py",
    "src/services.py",
    "src/api/views.py",
    "src/api/serializers.py",
    "src/auth/middleware.py",
    "src/auth/backends.py",
    "src/db/queries.py",
    "src/db/migrations.py",
    "src/core/config.py",
    "src/core/errors.py",
    "src/core/utils.py",
    "app/main.py",
    "app/routes.py",
    "app/schemas.py",
    "app/crud.py",
    "app/dependencies.py",
    "utils/helpers.py",
    "utils/formatters.py",
    "utils/parsers.py",
    "lib/client.py",
    "lib/cache.py",
]

# Paths fixos para os exemplos sintéticos (sem colisão com os amostrados)
SYNTHETIC_FAKE_PATHS = [
    "src/math_utils.py",
    "src/geometry.py",
    "src/fs_utils.py",
    "src/itertools_ext.py",
    "src/functools_ext.py",
    "src/enums.py",
    "src/parsing.py",
    "src/logging_utils.py",
    "src/pagination.py",
    "src/retry.py",
]

# ---------------------------------------------------------------------------
# 10 exemplos sintéticos -- código limpo e correto (y=0)
# Cada patch é um unified diff válido; os números de linha no cabeçalho @@
# foram verificados manualmente para que _changed_lines_by_side() os aceite.
# ---------------------------------------------------------------------------
SYNTHETIC_EXAMPLES: list[dict] = [
    # 1 -- Funções matemáticas puras
    {
        "oldf": (
            "def clamp(value: float, low: float, high: float) -> float:\n"
            "    return max(low, min(value, high))\n"
        ),
        "patch": (
            "@@ -1,2 +1,8 @@\n"
            " def clamp(value: float, low: float, high: float) -> float:\n"
            "     return max(low, min(value, high))\n"
            "+\n"
            "+\n"
            "+def normalize(value: float, low: float, high: float) -> float:\n"
            "+    if high == low:\n"
            "+        return 0.0\n"
            "+    return (value - low) / (high - low)\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "Utilitários matemáticos puros -- normalização e clamp, sem bugs",
    },
    # 2 -- Dataclass com midpoint correto
    {
        "oldf": (
            "from dataclasses import dataclass\n"
            "\n"
            "\n"
            "@dataclass\n"
            "class Point:\n"
            "    x: float\n"
            "    y: float\n"
            "\n"
            "    def distance_to(self, other: 'Point') -> float:\n"
            "        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5\n"
        ),
        "patch": (
            "@@ -9,2 +9,7 @@\n"
            "     def distance_to(self, other: 'Point') -> float:\n"
            "         return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5\n"
            "+\n"
            "+    def midpoint(self, other: 'Point') -> 'Point':\n"
            "+        return Point(\n"
            "+            x=(self.x + other.x) / 2,\n"
            "+            y=(self.y + other.y) / 2,\n"
            "+        )\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "Dataclass Point com midpoint -- operação aritmética correta",
    },
    # 3 -- Context manager com parâmetro extra
    {
        "oldf": (
            "class TempDirectory:\n"
            "    def __init__(self, prefix: str = 'tmp') -> None:\n"
            "        self.prefix = prefix\n"
            "        self.path: str | None = None\n"
            "\n"
            "    def __enter__(self) -> str:\n"
            "        import tempfile\n"
            "        self.path = tempfile.mkdtemp(prefix=self.prefix)\n"
            "        return self.path\n"
            "\n"
            "    def __exit__(self, *args: object) -> None:\n"
            "        import shutil\n"
            "        if self.path:\n"
            "            shutil.rmtree(self.path, ignore_errors=True)\n"
        ),
        "patch": (
            "@@ -1,4 +1,5 @@\n"
            " class TempDirectory:\n"
            "-    def __init__(self, prefix: str = 'tmp') -> None:\n"
            "+    def __init__(self, prefix: str = 'tmp', suffix: str = '') -> None:\n"
            "         self.prefix = prefix\n"
            "+        self.suffix = suffix\n"
            "         self.path: str | None = None\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "Context manager TempDirectory com parâmetro suffix -- refactor seguro",
    },
    # 4 -- Generator com validação de entrada
    {
        "oldf": (
            "from collections.abc import Iterator\n"
            "\n"
            "\n"
            "def batched(iterable, n: int) -> Iterator[list]:\n"
            "    batch: list = []\n"
            "    for item in iterable:\n"
            "        batch.append(item)\n"
            "        if len(batch) == n:\n"
            "            yield batch\n"
            "            batch = []\n"
            "    if batch:\n"
            "        yield batch\n"
        ),
        "patch": (
            "@@ -4,9 +4,11 @@\n"
            " def batched(iterable, n: int) -> Iterator[list]:\n"
            "+    if n <= 0:\n"
            "+        raise ValueError(f'n must be positive, got {n}')\n"
            "     batch: list = []\n"
            "     for item in iterable:\n"
            "         batch.append(item)\n"
            "         if len(batch) == n:\n"
            "             yield batch\n"
            "             batch = []\n"
            "     if batch:\n"
            "         yield batch\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "Generator batched com guard de n <= 0 -- prevenção correta",
    },
    # 5 -- Decorator memoize com tipo explícito
    {
        "oldf": (
            "import functools\n"
            "from typing import Callable, TypeVar\n"
            "\n"
            "F = TypeVar('F', bound=Callable)\n"
            "\n"
            "\n"
            "def memoize(func: F) -> F:\n"
            "    cache: dict = {}\n"
            "\n"
            "    @functools.wraps(func)\n"
            "    def wrapper(*args):\n"
            "        if args not in cache:\n"
            "            cache[args] = func(*args)\n"
            "        return cache[args]\n"
            "\n"
            "    return wrapper  # type: ignore[return-value]\n"
        ),
        "patch": (
            "@@ -7,3 +7,3 @@\n"
            " def memoize(func: F) -> F:\n"
            "-    cache: dict = {}\n"
            "+    cache: dict[tuple, object] = {}\n"
            " \n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "Decorator memoize com anotação de tipo explícita -- refactor seguro",
    },
    # 6 -- Enum com novos valores
    {
        "oldf": (
            "from enum import StrEnum\n"
            "\n"
            "\n"
            "class HttpMethod(StrEnum):\n"
            "    GET = 'GET'\n"
            "    POST = 'POST'\n"
            "    PUT = 'PUT'\n"
            "    PATCH = 'PATCH'\n"
            "    DELETE = 'DELETE'\n"
        ),
        "patch": (
            "@@ -9,1 +9,3 @@\n"
            "     DELETE = 'DELETE'\n"
            "+    HEAD = 'HEAD'\n"
            "+    OPTIONS = 'OPTIONS'\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "Enum HttpMethod com HEAD e OPTIONS adicionados -- sem bugs",
    },
    # 7 -- Parsing com guard para string vazia
    {
        "oldf": (
            "def parse_int_list(raw: str, sep: str = ',') -> list[int]:\n"
            "    parts = raw.split(sep)\n"
            "    result = []\n"
            "    for part in parts:\n"
            "        stripped = part.strip()\n"
            "        if stripped:\n"
            "            result.append(int(stripped))\n"
            "    return result\n"
        ),
        "patch": (
            "@@ -1,8 +1,10 @@\n"
            " def parse_int_list(raw: str, sep: str = ',') -> list[int]:\n"
            "+    if not raw.strip():\n"
            "+        return []\n"
            "     parts = raw.split(sep)\n"
            "     result = []\n"
            "     for part in parts:\n"
            "         stripped = part.strip()\n"
            "         if stripped:\n"
            "             result.append(int(stripped))\n"
            "     return result\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "Parser de lista de inteiros com guard para input vazio -- correto",
    },
    # 8 -- Logging com validação de ID
    {
        "oldf": (
            "import logging\n"
            "\n"
            "logger = logging.getLogger(__name__)\n"
            "\n"
            "\n"
            "def process_item(item_id: int) -> bool:\n"
            "    logger.info('Processing item %s', item_id)\n"
            "    return True\n"
        ),
        "patch": (
            "@@ -6,3 +6,6 @@\n"
            " def process_item(item_id: int) -> bool:\n"
            "     logger.info('Processing item %s', item_id)\n"
            "+    if item_id <= 0:\n"
            "+        logger.warning('Received non-positive item_id: %s', item_id)\n"
            "+        return False\n"
            "     return True\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "process_item com logging correto e guard de ID não-positivo",
    },
    # 9 -- Pydantic model com campos extras
    {
        "oldf": (
            "from pydantic import BaseModel, Field\n"
            "\n"
            "\n"
            "class PaginatedResponse(BaseModel):\n"
            "    items: list\n"
            "    total: int\n"
            "    page: int = Field(ge=1)\n"
            "    page_size: int = Field(ge=1, le=100)\n"
        ),
        "patch": (
            "@@ -5,4 +5,6 @@\n"
            "     items: list\n"
            "     total: int\n"
            "     page: int = Field(ge=1)\n"
            "     page_size: int = Field(ge=1, le=100)\n"
            "+    has_next: bool = False\n"
            "+    has_prev: bool = False\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "PaginatedResponse com campos de navegação -- modelo correto",
    },
    # 10 -- Função retry com validação de parâmetro
    {
        "oldf": (
            "import time\n"
            "from collections.abc import Callable\n"
            "from typing import TypeVar\n"
            "\n"
            "T = TypeVar('T')\n"
            "\n"
            "\n"
            "def retry(func: Callable[[], T], *, attempts: int = 3, delay: float = 1.0) -> T:\n"
            "    last_exc: Exception | None = None\n"
            "    for _ in range(attempts):\n"
            "        try:\n"
            "            return func()\n"
            "        except Exception as exc:\n"
            "            last_exc = exc\n"
            "            time.sleep(delay)\n"
            "    raise RuntimeError('All attempts failed') from last_exc\n"
        ),
        "patch": (
            "@@ -8,9 +8,11 @@\n"
            " def retry(func: Callable[[], T], *, attempts: int = 3, delay: float = 1.0) -> T:\n"
            "+    if attempts < 1:\n"
            "+        raise ValueError(f'attempts must be >= 1, got {attempts}')\n"
            "     last_exc: Exception | None = None\n"
            "     for _ in range(attempts):\n"
            "         try:\n"
            "             return func()\n"
            "         except Exception as exc:\n"
            "             last_exc = exc\n"
            "             time.sleep(delay)\n"
            "     raise RuntimeError('All attempts failed') from last_exc\n"
        ),
        "msg": "",
        "y": 0,
        "lang": "py",
        "synthetic": True,
        "description": "retry com validação de attempts < 1 -- prevenção de loop infinito",
    },
]


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def deterministic_path(item: dict, index: int) -> str:
    """Atribui um fake path de forma determinística via hash do conteúdo."""
    fingerprint = (item.get("patch", "") + item.get("oldf", ""))[:400]
    digest = int(hashlib.md5(fingerprint.encode(), usedforsecurity=False).hexdigest(), 16)
    return FAKE_PATH_POOL[(digest + index) % len(FAKE_PATH_POOL)]


def load_python_examples(path: Path) -> list[dict]:
    """Lê o JSONL e retorna apenas exemplos com lang=='py'."""
    examples = []
    total_lines = 0
    parse_errors = 0

    with path.open(encoding="utf-8") as fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            total_lines += 1
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError:
                parse_errors += 1
                continue
            if item.get("lang") == "py":
                examples.append(item)

    print(f"  Lidas {total_lines} linhas, {parse_errors} erros de parse.")
    return examples


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("FASE 1 -- Preparação e Enriquecimento dos Dados")
    print("=" * 60)

    if not DATASET_PATH.exists():
        print(f"[ERRO] Dataset não encontrado: {DATASET_PATH}", file=sys.stderr)
        sys.exit(1)

    # 1. Carregar e filtrar exemplos Python
    print(f"\n[1/4] Carregando dataset: {DATASET_PATH}")
    py_examples = load_python_examples(DATASET_PATH)
    print(f"  -> {len(py_examples)} exemplos Python encontrados.")

    if len(py_examples) < SAMPLE_SIZE:
        print(
            f"[AVISO] Apenas {len(py_examples)} exemplos disponíveis; "
            f"reduzindo SAMPLE_SIZE para {len(py_examples)}.",
            file=sys.stderr,
        )

    # 2. Amostragem aleatória determinística
    print(f"\n[2/4] Amostrando {SAMPLE_SIZE} exemplos (seed={RANDOM_SEED})...")
    random.seed(RANDOM_SEED)
    sampled = random.sample(py_examples, min(SAMPLE_SIZE, len(py_examples)))
    print(f"  -> {len(sampled)} exemplos selecionados.")

    # Enriquecer com fake_path e flag
    for idx, item in enumerate(sampled):
        item["fake_path"] = deterministic_path(item, idx)
        item["synthetic"] = False
        # Garantir campo 'description' ausente não quebre Phase 2
        item.setdefault("description", "")

    # 3. Injetar exemplos sintéticos (y=0)
    print(f"\n[3/4] Injetando {SYNTHETIC_SIZE} exemplos sintéticos (y=0)...")
    assert len(SYNTHETIC_EXAMPLES) == SYNTHETIC_SIZE, (
        f"Esperado {SYNTHETIC_SIZE} exemplos sintéticos, encontrado {len(SYNTHETIC_EXAMPLES)}"
    )
    assert len(SYNTHETIC_FAKE_PATHS) == SYNTHETIC_SIZE, "SYNTHETIC_FAKE_PATHS deve ter exatamente 10 itens"

    synthetic_enriched = []
    for i, ex in enumerate(SYNTHETIC_EXAMPLES):
        enriched = {**ex}
        enriched["fake_path"] = SYNTHETIC_FAKE_PATHS[i]
        enriched.setdefault("id", f"synthetic_{i:02d}")
        enriched.setdefault("idx", -(i + 1))
        enriched.setdefault("proj", "synthetic")
        synthetic_enriched.append(enriched)

    # Embaralhar sintéticos entre os reais para evitar viés de posição
    random.seed(RANDOM_SEED + 1)
    insert_positions = sorted(random.sample(range(len(sampled) + SYNTHETIC_SIZE), SYNTHETIC_SIZE))
    dataset: list[dict] = list(sampled)
    for offset, pos in enumerate(insert_positions):
        dataset.insert(pos + offset, synthetic_enriched[offset])

    print(f"  -> Dataset final: {len(dataset)} itens ({SAMPLE_SIZE} reais + {SYNTHETIC_SIZE} sinteticos).")

    # 4. Salvar
    print(f"\n[4/4] Salvando em {OUTPUT_PATH}...")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(dataset, fh, indent=2, ensure_ascii=False)

    # Relatório de distribuição
    n_real = sum(1 for x in dataset if not x.get("synthetic"))
    n_synth = sum(1 for x in dataset if x.get("synthetic"))
    n_buggy = sum(1 for x in dataset if x.get("y") == 1)
    n_clean = sum(1 for x in dataset if x.get("y") == 0)
    langs = {}
    for x in dataset:
        if not x.get("synthetic"):
            langs[x.get("lang", "?")] = langs.get(x.get("lang", "?"), 0) + 1

    print("\n--- Distribuição do Dataset ---")
    print(f"  Total    : {len(dataset)}")
    print(f"  Reais    : {n_real}  (y=1: {n_buggy - n_synth*0}, y=0: 0)")
    print(f"  Sintéticos: {n_synth} (y=0: {n_synth})")
    print(f"  Com bug (y=1): {n_buggy}")
    print(f"  Limpos  (y=0): {n_clean}")
    print(f"  Salvo em: {OUTPUT_PATH.resolve()}")
    print("\n[OK] Fase 1 concluída.")


if __name__ == "__main__":
    main()

