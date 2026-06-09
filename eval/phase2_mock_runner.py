#!/usr/bin/env python3
"""
FASE 2 -- Motor de Mocking e Execução (Integration Test)
=========================================================
Itera sobre mes_filtered_dataset.json, instancia o agente completo
com todas as ferramentas reais mas GitHub mockado, e persiste os
metadados de cada run em eval/results/run_results.jsonl.

Pré-requisitos:
  1. Dataset gerado: python eval/build_dataset.py
  2. LLM_API_KEY configurado em .env (ou env var).

Uso:
    cd mes-pr-review-agent
    python eval/phase2_mock_runner.py

Flags:
    --dry-run   : executa apenas os 3 primeiros itens (smoke test)
    --resume    : pula itens cujo run_id já está em run_results.jsonl
    --item N    : executa apenas o item de índice N (0-based)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Garante que o pacote `app` seja importável mesmo rodando de qualquer diretório
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agent.llm_client import OpenAICompatibleModelClient
from app.agent.loop import AgenticLoop
from app.config import get_settings
from app.prompts.session import DynamicPromptSession
from app.review.notes import ReviewNotesWriter
from app.review.pr_context import PullRequestToolContext
from app.review.validator import validate_agent_review_payload
from app.state_machine.states import ReviewState
from app.tools.review_tools import build_review_tool_registry

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
EVAL_DIR = Path(__file__).parent
DATASET_PATH = EVAL_DIR / "mes_filtered_dataset.json"
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_PATH = RESULTS_DIR / "run_results.jsonl"
NOTES_DIR = EVAL_DIR / "review_runs"

# SHA fictícios usados no mock
MOCK_HEAD_SHA = "mock-head-sha-eval"
MOCK_BASE_SHA = "mock-base-sha-eval"

# ---------------------------------------------------------------------------
# Patch applier: aplica unified diff ao conteúdo original
# ---------------------------------------------------------------------------
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def apply_unified_diff(original: str, patch_text: str) -> str:
    """
    Aplica um patch unified diff ao conteúdo original.
    Retorna o conteúdo patched ou o original em caso de falha.
    """
    try:
        original_lines = original.splitlines(keepends=True)
        if original_lines and not original_lines[-1].endswith("\n"):
            original_lines[-1] += "\n"

        result = list(original_lines)
        delta = 0
        hunks: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None

        for raw_line in patch_text.splitlines():
            m = _HUNK_RE.match(raw_line)
            if m:
                if current is not None:
                    hunks.append(current)
                current = {"old_start": int(m.group(1)) - 1, "ops": []}
            elif current is not None:
                current["ops"].append(raw_line)
        if current is not None:
            hunks.append(current)

        for hunk in hunks:
            start = hunk["old_start"] + delta
            old_block: list[str] = []
            new_block: list[str] = []

            for op in hunk["ops"]:
                if op.startswith("\\"):
                    continue  # "No newline at end of file"
                if op.startswith("-"):
                    text = op[1:]
                    old_block.append(text if text.endswith("\n") else text + "\n")
                elif op.startswith("+"):
                    text = op[1:]
                    new_block.append(text if text.endswith("\n") else text + "\n")
                else:
                    # Linha de contexto: o marcador de posição é um espaço
                    text = op[1:] if len(op) >= 1 else ""
                    normalized = text if text.endswith("\n") else text + "\n"
                    old_block.append(normalized)
                    new_block.append(normalized)

            # Substituição segura: garante que o slice não vai além do array
            end = min(start + len(old_block), len(result))
            result[start:end] = new_block
            delta += len(new_block) - len(old_block)

        return "".join(result)

    except Exception as exc:  # noqa: BLE001
        # Fallback: retorna o original para não travar a execução
        print(f"    [AVISO] apply_unified_diff falhou ({exc}); usando oldf como head.", flush=True)
        return original


# ---------------------------------------------------------------------------
# Mock do cliente GitHub
# ---------------------------------------------------------------------------
class MockGitHubPRClient:
    """
    Implementa o protocolo GitHubPRClient de pr_context.py sem nenhuma
    chamada HTTP real. Fornece dados a partir do item do dataset.
    """

    def __init__(self, item: dict[str, Any]) -> None:
        self.fake_path: str = item["fake_path"]
        self.patch_text: str = item.get("patch", "")
        self.oldf: str = item.get("oldf", "")
        self.head_content: str = apply_unified_diff(self.oldf, self.patch_text)
        self.repo_rules: str | None = item.get("repo_rules")

        # Contagem básica de adições/deleções no patch
        add = sum(1 for ln in self.patch_text.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
        rem = sum(1 for ln in self.patch_text.splitlines() if ln.startswith("-") and not ln.startswith("---"))
        self._additions = add
        self._deletions = rem

    # Caminho virtual que representa as regras do repositório no mock
    _RULES_PATH = "CONTRIBUTING.md"

    async def list_pull_request_files(
        self, *, owner: str, repo: str, number: int
    ) -> list[dict[str, Any]]:
        return [
            {
                "filename": self.fake_path,
                "patch": self.patch_text,
                "status": "modified",
                "additions": self._additions,
                "deletions": self._deletions,
                "changes": self._additions + self._deletions,
                "previous_filename": None,
                "sha": "mock-blob-sha",
                "blob_url": "",
                "raw_url": "",
            }
        ]

    async def get_file_contents_at_ref(
        self, *, owner: str, repo: str, path: str, ref: str
    ) -> dict[str, Any]:
        # Retorna repo_rules quando o agente solicita CONTRIBUTING.md
        if path == self._RULES_PATH and self.repo_rules:
            content = self.repo_rules
            return {
                "content": content,
                "path": path,
                "sha": "mock-rules-sha",
                "size": len(content),
                "encoding": "utf-8",
            }

        if path != self.fake_path:
            raise FileNotFoundError(f"[mock] arquivo não existe neste PR: {path}")

        content = self.head_content if ref == MOCK_HEAD_SHA else self.oldf
        return {
            "content": content,
            "path": path,
            "sha": "mock-content-sha",
            "size": len(content),
            "encoding": "utf-8",
        }

    async def list_check_runs_for_ref(
        self, *, owner: str, repo: str, ref: str
    ) -> dict[str, Any]:
        # Sem CI nos exemplos do dataset
        return {"total_count": 0, "check_runs": []}


# ---------------------------------------------------------------------------
# Harness de avaliação
# ---------------------------------------------------------------------------

def _build_pr_payload(item: dict[str, Any], item_index: int) -> dict[str, Any]:
    """Cria o webhook payload sintético que alimenta get_pr_metadata."""
    item_id = item.get("id", f"item_{item_index}")
    title = item.get("pr_title") or f"[eval] item {item_id} -- lang={item.get('lang', 'py')}"
    body  = item.get("pr_body")  or "Automated evaluation run for MES PR Reviewer."
    return {
        "action": "opened",
        "repository": {"full_name": "eval/mock-repo"},
        "pull_request": {
            "number": item_index + 1,
            "title": title,
            "body": body,
            "draft": False,
            "head": {"sha": MOCK_HEAD_SHA, "ref": "feature/eval-branch"},
            "base": {"sha": MOCK_BASE_SHA, "ref": "main"},
        },
    }


async def run_single_item(
    item: dict[str, Any],
    item_index: int,
    *,
    model_client: OpenAICompatibleModelClient,
    settings: Any,
) -> dict[str, Any]:
    """Executa uma run completa do agente para um item do dataset."""

    run_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    # --- Contexto de PR mockado ------------------------------------------
    mock_client = MockGitHubPRClient(item)
    pr_context = PullRequestToolContext(
        owner="eval",
        repo="mock-repo",
        number=item_index + 1,
        client=mock_client,
        head_sha=MOCK_HEAD_SHA,
        base_sha=MOCK_BASE_SHA,
        head_ref="feature/eval-branch",
        base_ref="main",
    )

    # --- Sessão de prompt e notas ----------------------------------------
    pr_payload = _build_pr_payload(item, item_index)
    runtime_context: dict[str, Any] = {
        "pr_number": item_index + 1,
        "repository": "eval/mock-repo",
        "head_sha": MOCK_HEAD_SHA,
        "base_sha": MOCK_BASE_SHA,
        "fake_path": item["fake_path"],
        "item_id": item.get("id", f"item_{item_index}"),
        "item_index": item_index,
        "y_ground_truth": item.get("y"),
        "synthetic": item.get("synthetic", False),
    }
    session = DynamicPromptSession(
        run_id=run_id,
        state=ReviewState.RECEIVED,
        runtime_context=runtime_context,
    )
    notes_writer = ReviewNotesWriter(notes_dir=NOTES_DIR)

    # --- Registry de tools com context mockado ---------------------------
    registry = build_review_tool_registry(
        prompt_session=session,
        notes_writer=notes_writer,
        pull_request_payload=pr_payload,
        pr_context=pr_context,
        run=None,  # sem ReviewRun real no eval
    )

    # --- Loop agêntico ---------------------------------------------------
    loop = AgenticLoop(
        model_client=model_client,
        tool_executor=registry.call,
        max_turns=settings.agent_max_turns,
    )

    user_payload = json.dumps(pr_payload, ensure_ascii=False)

    agent_error: str | None = None
    try:
        agent_result = await loop.run(
            system_prompt=session.render_system_prompt,
            user_payload=user_payload,
        )
        agent_error = agent_result.error
    except Exception as exc:  # noqa: BLE001
        agent_error = f"loop_exception: {exc}"
        # Resultado mínimo para não travar o pipeline
        from app.agent.models import AgentRunResult
        agent_result = AgentRunResult(
            final_payload={},
            error=agent_error,
            turns_used=0,
        )

    # --- Validação do payload pelo backend -------------------------------
    validator_error: str | None = None
    validated = None
    try:
        validated = await validate_agent_review_payload(
            agent_result.final_payload,
            pr_context=pr_context,
        )
    except Exception as exc:  # noqa: BLE001
        validator_error = f"validator_exception: {exc}"

    # --- Escrever nota final ---------------------------------------------
    notes_path = notes_writer.write(session)

    # --- Compor resultado ------------------------------------------------
    if validated is not None:
        decision = validated.decision.value
        publishable = len(validated.publishable_findings)
        summary = len(validated.summary_findings)
        discarded = len(validated.discarded_findings)
        discard_reasons = {}
        for df in validated.discarded_findings:
            reason = df.reason.value
            discard_reasons[reason] = discard_reasons.get(reason, 0) + 1
    else:
        decision = agent_result.final_payload.get("decision", "error")
        publishable = 0
        summary = 0
        discarded = 0
        discard_reasons = {}

    return {
        # Identificação
        "run_id": run_id,
        "item_index": item_index,
        "item_id": str(item.get("id", f"item_{item_index}")),
        "timestamp": timestamp,
        # Ground truth
        "y": item.get("y"),
        "synthetic": item.get("synthetic", False),
        "fake_path": item["fake_path"],
        "original_msg": item.get("msg", ""),
        # Resultado do agente
        "agent_decision": decision,
        "publishable_count": publishable,
        "summary_count": summary,
        "discarded_count": discarded,
        "blocked_by_validator": discarded,  # alias semântico para a Fase 3
        "validator_discard_reasons": discard_reasons,
        # Diagnóstico
        "final_state": session.state.value,
        "turns_used": agent_result.turns_used,
        "agent_error": agent_error,
        "validator_error": validator_error,
        "notes_path": str(notes_path),
    }


async def main(args: argparse.Namespace) -> None:
    print("=" * 60)
    print("FASE 2 -- Motor de Mocking e Execução")
    print("=" * 60)

    # Verificações iniciais
    if not DATASET_PATH.exists():
        print(f"[ERRO] mes_filtered_dataset.json não encontrado em {DATASET_PATH}", file=sys.stderr)
        print("  Gere o dataset primeiro: python eval/build_dataset.py", file=sys.stderr)
        sys.exit(1)

    with DATASET_PATH.open(encoding="utf-8") as fh:
        dataset: list[dict] = json.load(fh)
    print(f"\nDataset carregado: {len(dataset)} itens.")

    # Selecionar subconjunto se solicitado
    if args.item is not None:
        if args.item >= len(dataset):
            print(f"[ERRO] --item {args.item} fora do range (0-{len(dataset)-1})", file=sys.stderr)
            sys.exit(1)
        dataset = [dataset[args.item]]
        start_indices = [args.item]
    elif args.dry_run:
        print("[DRY-RUN] Executando apenas os 3 primeiros itens.")
        dataset = dataset[:3]
        start_indices = list(range(3))
    else:
        start_indices = list(range(len(dataset)))

    # Carregar resultados existentes para --resume
    completed_ids: set[str] = set()
    if args.resume and RESULTS_PATH.exists():
        with RESULTS_PATH.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    completed_ids.add(str(rec.get("item_index")))
                except json.JSONDecodeError:
                    pass
        print(f"[RESUME] {len(completed_ids)} runs já concluídas serão puladas.")

    # Configuração do LLM
    settings = get_settings()
    if not settings.llm_api_key:
        print("[ERRO] LLM_API_KEY não configurada. Defina em .env ou como variável de ambiente.", file=sys.stderr)
        sys.exit(1)

    model_client = OpenAICompatibleModelClient(
        api_key=settings.llm_api_key,
        base_url=settings.llm_api_base_url,
        model=settings.llm_model,
        temperature=0.1,   # baixa temperatura para avaliação reproduzível
        max_tokens=4096,
    )

    # Preparar diretórios de saída
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    NOTES_DIR.mkdir(parents=True, exist_ok=True)

    # Executar
    results: list[dict] = []
    errors = 0

    with RESULTS_PATH.open("a", encoding="utf-8") as results_fh:
        for item, item_index in zip(dataset, start_indices):
            if args.resume and str(item_index) in completed_ids:
                print(f"  [SKIP] item {item_index:3d} (já concluído)")
                continue

            item_id = item.get("id", f"item_{item_index}")
            y = item.get("y")
            synthetic_tag = " [SYNTHETIC]" if item.get("synthetic") else ""
            print(
                f"\n  [{item_index:3d}/{len(start_indices)-1}] id={item_id} "
                f"y={y}{synthetic_tag} path={item['fake_path']}",
                flush=True,
            )

            try:
                result = await run_single_item(
                    item,
                    item_index,
                    model_client=model_client,
                    settings=settings,
                )
                decision = result["agent_decision"]
                pub = result["publishable_count"]
                disc = result["discarded_count"]
                turns = result["turns_used"]
                print(
                    f"    -> decision={decision}  pub={pub}  disc={disc}  "
                    f"turns={turns}  state={result['final_state']}",
                    flush=True,
                )
                if result.get("agent_error"):
                    print(f"    [WARN] agent_error: {result['agent_error']}", flush=True)
                    errors += 1

            except Exception as exc:  # noqa: BLE001
                print(f"    [ERRO] run_single_item exception: {exc}", flush=True)
                result = {
                    "run_id": str(uuid.uuid4()),
                    "item_index": item_index,
                    "item_id": str(item_id),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "y": y,
                    "synthetic": item.get("synthetic", False),
                    "fake_path": item.get("fake_path", ""),
                    "original_msg": item.get("msg", ""),
                    "agent_decision": "error",
                    "publishable_count": 0,
                    "summary_count": 0,
                    "discarded_count": 0,
                    "blocked_by_validator": 0,
                    "validator_discard_reasons": {},
                    "final_state": "ERROR",
                    "turns_used": 0,
                    "agent_error": str(exc),
                    "validator_error": None,
                    "notes_path": "",
                }
                errors += 1

            results.append(result)
            results_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            results_fh.flush()

    print("\n" + "=" * 60)
    print(f"Runs concluídas : {len(results)}")
    print(f"Runs com erro   : {errors}")
    print(f"Resultados em   : {RESULTS_PATH.resolve()}")
    print(f"Notas (Markdown): {NOTES_DIR.resolve()}")
    print("\n[OK] Fase 2 concluída. Execute a Fase 3 para calcular métricas.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fase 2 -- Execução com mock")
    parser.add_argument("--dry-run", action="store_true", help="Executa apenas os 3 primeiros itens")
    parser.add_argument("--resume", action="store_true", help="Pula itens já presentes em run_results.jsonl")
    parser.add_argument("--item", type=int, default=None, metavar="N", help="Executa apenas o item N (0-based)")
    args = parser.parse_args()

    asyncio.run(main(args))

