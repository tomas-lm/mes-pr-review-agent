#!/usr/bin/env python3
"""
FASE 3 -- Analisador de Métricas e Output Analysis
===================================================
Lê eval/results/run_results.jsonl, calcula métricas de classificação
(TP/FP/FN/TN, Precision, Recall, F1) e a taxa de bloqueio do Validador.
Gera uma tabela LaTeX pronta para relatório acadêmico e instruções para
extração qualitativa dos logs Markdown.

Uso:
    cd mes-pr-review-agent
    python eval/phase3_metrics.py

    # Para imprimir também a extração qualitativa por run_id:
    python eval/phase3_metrics.py --qualitative

    # Para salvar o relatório em arquivo:
    python eval/phase3_metrics.py --out eval/results/report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------
EVAL_DIR = Path(__file__).parent
RESULTS_PATH = EVAL_DIR / "results" / "run_results.jsonl"
NOTES_DIR = EVAL_DIR / "review_runs"

# ---------------------------------------------------------------------------
# Estruturas de dados
# ---------------------------------------------------------------------------

@dataclass
class RunRecord:
    run_id: str
    item_index: int
    item_id: str
    y: int                         # ground truth: 1=tem bug, 0=limpo
    synthetic: bool
    fake_path: str
    original_msg: str
    agent_decision: str
    publishable_count: int
    summary_count: int
    discarded_count: int
    blocked_by_validator: int
    validator_discard_reasons: dict[str, int]
    final_state: str
    turns_used: int
    agent_error: str | None
    notes_path: str

    @property
    def agent_flagged(self) -> bool:
        """True se o agente publicou pelo menos 1 finding (pub ou summary)."""
        return (self.publishable_count + self.summary_count) > 0

    @property
    def is_tp(self) -> bool:
        return self.y == 1 and self.agent_flagged

    @property
    def is_fp(self) -> bool:
        return self.y == 0 and self.agent_flagged

    @property
    def is_fn(self) -> bool:
        return self.y == 1 and not self.agent_flagged

    @property
    def is_tn(self) -> bool:
        return self.y == 0 and not self.agent_flagged


@dataclass
class MetricsReport:
    # Classificação binária
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0

    # Validador
    total_attempted: int = 0       # findings enviados pelo agente no payload
    total_publishable: int = 0     # passaram no validador
    total_discarded: int = 0       # bloqueados pelo validador

    # FP específicos por camada
    fp_caught_by_validator: int = 0  # y=0, discarded>0, publishable==0
    fp_escaped_validator: int = 0    # y=0, publishable>0

    # Razões de descarte (aggregado)
    discard_reasons: dict[str, int] = field(default_factory=dict)

    # Turn distribution
    turn_counts: list[int] = field(default_factory=list)

    # Erros de execução
    execution_errors: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        denom = p + r
        return 2 * p * r / denom if denom > 0 else 0.0

    @property
    def accuracy(self) -> float:
        denom = self.tp + self.fp + self.fn + self.tn
        return (self.tp + self.tn) / denom if denom > 0 else 0.0

    @property
    def validator_blocking_rate(self) -> float:
        denom = self.total_discarded + self.total_publishable
        return self.total_discarded / denom if denom > 0 else 0.0

    @property
    def avg_turns(self) -> float:
        return sum(self.turn_counts) / len(self.turn_counts) if self.turn_counts else 0.0

    @property
    def total_runs(self) -> int:
        return self.tp + self.fp + self.fn + self.tn + self.execution_errors


# ---------------------------------------------------------------------------
# Carregamento
# ---------------------------------------------------------------------------

def load_results(path: Path) -> list[RunRecord]:
    if not path.exists():
        print(f"[ERRO] Arquivo de resultados não encontrado: {path}", file=sys.stderr)
        print("  Execute a Fase 2 primeiro: python eval/phase2_mock_runner.py", file=sys.stderr)
        sys.exit(1)

    records: list[RunRecord] = []
    parse_errors = 0

    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                records.append(RunRecord(
                    run_id=d.get("run_id", ""),
                    item_index=d.get("item_index", i),
                    item_id=str(d.get("item_id", "")),
                    y=int(d.get("y", 1)),
                    synthetic=bool(d.get("synthetic", False)),
                    fake_path=d.get("fake_path", ""),
                    original_msg=d.get("original_msg", ""),
                    agent_decision=d.get("agent_decision", ""),
                    publishable_count=int(d.get("publishable_count", 0)),
                    summary_count=int(d.get("summary_count", 0)),
                    discarded_count=int(d.get("discarded_count", 0)),
                    blocked_by_validator=int(d.get("blocked_by_validator", 0)),
                    validator_discard_reasons=d.get("validator_discard_reasons") or {},
                    final_state=d.get("final_state", ""),
                    turns_used=int(d.get("turns_used", 0)),
                    agent_error=d.get("agent_error"),
                    notes_path=d.get("notes_path", ""),
                ))
            except (KeyError, ValueError, TypeError) as exc:
                parse_errors += 1
                print(f"  [AVISO] Linha {i+1} inválida: {exc}", file=sys.stderr)

    print(f"Carregados {len(records)} registros ({parse_errors} com erro de parse).")
    return records


# ---------------------------------------------------------------------------
# Cálculo de métricas
# ---------------------------------------------------------------------------

def compute_metrics(records: list[RunRecord]) -> MetricsReport:
    m = MetricsReport()

    for r in records:
        if r.agent_error and r.agent_decision == "error":
            m.execution_errors += 1
            continue

        # Classificação binária
        if r.is_tp:
            m.tp += 1
        elif r.is_fp:
            m.fp += 1
        elif r.is_fn:
            m.fn += 1
        else:
            m.tn += 1

        # Validador
        attempted = r.publishable_count + r.summary_count + r.discarded_count
        m.total_attempted += attempted
        m.total_publishable += r.publishable_count + r.summary_count
        m.total_discarded += r.discarded_count

        # FP por camada
        if r.y == 0:
            if r.discarded_count > 0 and (r.publishable_count + r.summary_count) == 0:
                m.fp_caught_by_validator += 1
            if (r.publishable_count + r.summary_count) > 0:
                m.fp_escaped_validator += 1

        # Razões de descarte
        for reason, count in r.validator_discard_reasons.items():
            m.discard_reasons[reason] = m.discard_reasons.get(reason, 0) + count

        if r.turns_used > 0:
            m.turn_counts.append(r.turns_used)

    return m


# ---------------------------------------------------------------------------
# Geração de tabela LaTeX
# ---------------------------------------------------------------------------

def _pct(value: float) -> str:
    return f"{value * 100:.1f}\\%"


def _fmt(n: int) -> str:
    return str(n)


def generate_latex_table(m: MetricsReport, records: list[RunRecord]) -> str:
    n_real = sum(1 for r in records if not r.synthetic)
    n_synth = sum(1 for r in records if r.synthetic)
    n_y1 = sum(1 for r in records if r.y == 1)
    n_y0 = sum(1 for r in records if r.y == 0)

    # Tabela 1: Configuração do experimento
    tab_config = r"""
\begin{table}[ht]
\centering
\caption{Configuração do Dataset de Avaliação}
\label{tab:eval-config}
\begin{tabular}{lc}
\hline
\textbf{Parâmetro} & \textbf{Valor} \\
\hline
""" + (
        f"Total de runs              & {m.total_runs} \\\\\n"
        f"Exemplos reais (y=1)       & {n_y1} \\\\\n"
        f"Exemplos sintéticos (y=0)  & {n_y0} \\\\\n"
        f"Erros de execução          & {m.execution_errors} \\\\\n"
        f"Média de turns por run     & {m.avg_turns:.1f} \\\\\n"
    ) + r"""\hline
\end{tabular}
\end{table}
"""

    # Tabela 2: Matriz de Confusão
    total_classified = m.tp + m.fp + m.fn + m.tn
    tab_confusion = r"""
\begin{table}[ht]
\centering
\caption{Matriz de Confusão -- MES PR Review Agent}
\label{tab:confusion}
\begin{tabular}{lcc}
\hline
 & \textbf{Predito: Bug} & \textbf{Predito: Limpo} \\
\hline
\textbf{Real: Bug (y=1)}   & """ + (
        f"TP = {m.tp}  & FN = {m.fn} \\\\\n"
        r"\textbf{Real: Limpo (y=0)} & "
        f"FP = {m.fp}  & TN = {m.tn} \\\\\n"
    ) + r"""\hline
\end{tabular}
\end{table}
"""

    # Tabela 3: Métricas de Classificação
    tab_metrics = r"""
\begin{table}[ht]
\centering
\caption{Métricas de Classificação do Agente}
\label{tab:metrics}
\begin{tabular}{lcc}
\hline
\textbf{Métrica} & \textbf{Valor} & \textbf{Fórmula} \\
\hline
""" + (
        f"Precision               & {_pct(m.precision)}  & $TP / (TP + FP)$ \\\\\n"
        f"Recall                  & {_pct(m.recall)}     & $TP / (TP + FN)$ \\\\\n"
        f"F1-Score                & {_pct(m.f1)}         & $2 \\cdot P \\cdot R / (P + R)$ \\\\\n"
        f"Accuracy                & {_pct(m.accuracy)}   & $(TP + TN) / N$ \\\\\n"
        r"\hline" + "\n"
        f"FP vazados do validador & {m.fp_escaped_validator} / {sum(1 for r in records if r.y==0)} "
        f"& y=0 com pub$>$0 \\\\\n"
        f"FP barrados pelo validador & {m.fp_caught_by_validator} / {sum(1 for r in records if r.y==0)} "
        f"& y=0 com disc$>$0, pub=0 \\\\\n"
    ) + r"""\hline
\end{tabular}
\end{table}
"""

    # Tabela 4: Análise do Validador
    reason_rows = ""
    for reason, count in sorted(m.discard_reasons.items(), key=lambda x: -x[1]):
        escaped = reason.replace("_", r"\_")
        reason_rows += f"\\texttt{{{escaped}}} & {count} \\\\\n"
    if not reason_rows:
        reason_rows = "\\textit{(nenhum finding descartado)} & --- \\\\\n"

    tab_validator = r"""
\begin{table}[ht]
\centering
\caption{Análise do Validador de Findings}
\label{tab:validator}
\begin{tabular}{lc}
\hline
\textbf{Razão de Descarte} & \textbf{Ocorrências} \\
\hline
""" + reason_rows + (
        r"\hline" + "\n"
        f"\\textbf{{Total descartados}}   & \\textbf{{{m.total_discarded}}} \\\\\n"
        f"\\textbf{{Total publicados}}    & \\textbf{{{m.total_publishable}}} \\\\\n"
        f"\\textbf{{Taxa de bloqueio}}    & \\textbf{{{_pct(m.validator_blocking_rate)}}} \\\\\n"
    ) + r"""\hline
\end{tabular}
\end{table}
"""

    return "\n".join([tab_config, tab_confusion, tab_metrics, tab_validator])


# ---------------------------------------------------------------------------
# Análise qualitativa
# ---------------------------------------------------------------------------

def qualitative_instructions() -> str:
    return """
=============================================================
  GUIA PARA EXTRAÇÃO QUALITATIVA DOS LOGS MARKDOWN
=============================================================

Os logs estão em eval/review_runs/<run_id>.md.
Cada arquivo contém:
  - Estado atual e camada dinâmica de estado
  - Todas as observações registradas pelo agente
  - (se habilitado no serviço) trace das chamadas de tool

--- COMO IDENTIFICAR CADA CATEGORIA ---

[OK] SUCESSO (Verdadeiro Positivo -- TP):
   Critérios obrigatórios:
     1. y=1 no item do dataset (há bug real)
     2. agent_decision = "request_changes" ou "comment"
     3. publishable_count >= 1
     4. O finding publicado deve mencionar o mesmo tipo de problema
        que o comentário humano original (campo "original_msg").
   Como verificar no log:
     - Procure "finding_candidate" nas observações
     - Verifique que o campo "evidence" não está vazio
     - Compare o "title" / "body" do finding com original_msg

[TN] RESILIÊNCIA (Verdadeiro Negativo -- TN):
   Critérios obrigatórios:
     1. y=0 (código limpo ou sintético)
     2. publishable_count = 0 E summary_count = 0
   Casos especiais de resiliência elevada:
     - discarded_count > 0: o agente tentou criar findings, mas o
       VALIDADOR bloqueou todos -> o sistema funcionou como esperado.
     - discarded_count = 0: o agente reconheceu o código como limpo
       sem nem tentar registrar findings -> comportamento ideal.
   Como verificar no log:
     - Procure pela ausência de "finding_candidate" nas observações
     - Se houver "finding_candidate", verifique por qual razão foi
       descartado em validator_discard_reasons

[X] FALHA -- Falso Negativo (FN):
   Critérios:
     1. y=1 (há bug)
     2. publishable_count = 0 E summary_count = 0
   Como investigar a causa no log:
     a) O agente chegou ao estado EVALUATE?
        - Não: problema na TRIAGE ou COLLECT_CONTEXT -> o agente
          pulou (skipped) o PR ou parou prematuramente.
        - Sim: leia as observações do INVESTIGATE para ver se o agente
          identificou o arquivo correto.
     b) O agente registrou algum finding_candidate?
        - Não: FN puro -- agente não detectou o problema.
        - Sim: o finding foi descartado pelo validador (FN induzido
          por linha errada ou baixa confiança) -> veja discard_reasons.
     c) Compare o "original_msg" com o que o agente observou.

[FP!] FALHA -- Falso Positivo (FP Vazado):
   Critérios:
     1. y=0 (código limpo)
     2. publishable_count >= 1
   Como investigar no log:
     - Leia o "body" do finding publicado
     - Verifique se o código referenciado no "evidence" realmente
       contém um problema (pode ser um falso positivo legítimo ou
       um misreading do contexto)
     - Verifique se o agente alucionou um path/linha inexistente
       (validator_discard_reasons: path_not_in_pr)

--- TEMPLATE PARA REGISTRO QUALITATIVO ---

| run_id (primeiros 8 chars) | item_id | y | synthetic | Categoria     | Nota |
|----------------------------|---------|---|-----------|---------------|------|
| abc12345                   | 1234    | 1 | False     | TP/SUCESSO    | Finding menciona "null check" -- alinha com original_msg |
| def67890                   | synth3  | 0 | True      | TN/RESILIÊNCIA| Agente não gerou findings em código limpo |
| ...                        | ...     | . | ...       | FN/FALHA      | Chegou a EVALUATE mas não registrou finding para o bug |

--- COMO ABRIR UM LOG ESPECÍFICO ---

  Windows (PowerShell):
    notepad eval\\review_runs\\<run_id>.md

  macOS/Linux:
    cat eval/review_runs/<run_id>.md | less

  VS Code:
    code eval/review_runs/<run_id>.md

--- SINAL DE QUALIDADE DO SISTEMA ---
  Uma boa run mostra:
  1. Progressão de estados: RECEIVED->TRIAGE->COLLECT_CONTEXT->INVESTIGATE->EVALUATE->VALIDATE_FINDINGS
  2. Pelo menos 2-3 observações registradas via append_review_observation
  3. Evidence não vazia nos findings_candidates
  4. validate_line_mapping chamado antes do payload final

=============================================================
"""


# ---------------------------------------------------------------------------
# Formatação de sumário em texto
# ---------------------------------------------------------------------------

def format_text_summary(m: MetricsReport, records: list[RunRecord]) -> str:
    n_y1 = sum(1 for r in records if r.y == 1 and not (r.agent_error and r.agent_decision == "error"))
    n_y0 = sum(1 for r in records if r.y == 0 and not (r.agent_error and r.agent_decision == "error"))
    n_synth_y0 = sum(1 for r in records if r.y == 0 and r.synthetic)
    n_real_y1 = sum(1 for r in records if r.y == 1 and not r.synthetic)

    lines = [
        "",
        "=" * 60,
        "  SUMÁRIO DE MÉTRICAS -- MES PR Review Agent Eval",
        "=" * 60,
        "",
        f"  Dataset          : {m.total_runs} runs totais",
        f"    Exemplos reais (y=1)        : {n_real_y1}",
        f"    Exemplos sintéticos (y=0)   : {n_synth_y0}",
        f"    Erros de execução           : {m.execution_errors}",
        "",
        "  --- Matriz de Confusão ---",
        f"    TP (detectou bug)           : {m.tp}",
        f"    FP (falso alarme)           : {m.fp}",
        f"    FN (perdeu bug)             : {m.fn}",
        f"    TN (código limpo correto)   : {m.tn}",
        "",
        "  --- Métricas de Classificação ---",
        f"    Precision    : {m.precision:.3f}  ({m.tp}/{m.tp+m.fp})",
        f"    Recall       : {m.recall:.3f}  ({m.tp}/{m.tp+m.fn})",
        f"    F1-Score     : {m.f1:.3f}",
        f"    Accuracy     : {m.accuracy:.3f}",
        "",
        "  --- Análise do Validador ---",
        f"    Findings tentados           : {m.total_attempted}",
        f"    Findings publicados         : {m.total_publishable}",
        f"    Findings bloqueados         : {m.total_discarded}",
        f"    Taxa de bloqueio            : {m.validator_blocking_rate:.3f} "
        f"({m.total_discarded}/{m.total_discarded+m.total_publishable})",
        "",
        f"    FP barrados pelo validador  : {m.fp_caught_by_validator} / {n_y0}  (y=0 que não vazaram)",
        f"    FP que vazaram o validador  : {m.fp_escaped_validator} / {n_y0}  (y=0 com pub>0)",
        "",
    ]

    if m.discard_reasons:
        lines.append("  --- Top razões de descarte ---")
        for reason, count in sorted(m.discard_reasons.items(), key=lambda x: -x[1]):
            lines.append(f"    {reason:<35}: {count}")
        lines.append("")

    if m.turn_counts:
        lines.append(f"  Avg turns / run   : {m.avg_turns:.1f}")
        lines.append(f"  Max turns / run   : {max(m.turn_counts)}")
        lines.append(f"  Min turns / run   : {min(m.turn_counts)}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Listagem por item (modo qualitativo)
# ---------------------------------------------------------------------------

def format_qualitative_listing(records: list[RunRecord]) -> str:
    header = (
        "\n  --- Listagem por item (para análise qualitativa) ---\n"
        f"  {'idx':>4}  {'item_id':<16}  {'y':>2}  {'synth':>5}  "
        f"{'decision':<18}  {'pub':>3}  {'disc':>4}  {'state':<20}  "
        f"{'turns':>5}  run_id\n"
        + "  " + "-" * 120
    )
    rows = [header]
    for r in sorted(records, key=lambda x: x.item_index):
        cat = ""
        if r.agent_error and r.agent_decision == "error":
            cat = "ERROR"
        elif r.is_tp:
            cat = "TP"
        elif r.is_fp:
            cat = "FP"
        elif r.is_fn:
            cat = "FN"
        else:
            cat = "TN"
        rows.append(
            f"  {r.item_index:>4}  {r.item_id:<16}  {r.y:>2}  "
            f"{'Y' if r.synthetic else 'N':>5}  "
            f"{r.agent_decision:<18}  {r.publishable_count:>3}  "
            f"{r.discarded_count:>4}  {r.final_state:<20}  "
            f"{r.turns_used:>5}  {r.run_id[:8]}  [{cat}]"
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fase 3 -- Analisador de Métricas")
    parser.add_argument(
        "--qualitative",
        action="store_true",
        help="Imprime listagem por item para análise qualitativa",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="PATH",
        help="Salva o relatório em arquivo (Markdown + LaTeX)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("FASE 3 -- Analisador de Métricas")
    print("=" * 60)

    records = load_results(RESULTS_PATH)
    if not records:
        print("[ERRO] Nenhum registro encontrado.", file=sys.stderr)
        sys.exit(1)

    metrics = compute_metrics(records)

    # Sumário em texto
    summary = format_text_summary(metrics, records)
    print(summary)

    # Listagem qualitativa (opcional)
    if args.qualitative:
        listing = format_qualitative_listing(records)
        print(listing)

    # Tabela LaTeX
    print("\n" + "=" * 60)
    print("  TABELAS LaTeX")
    print("=" * 60)
    latex = generate_latex_table(metrics, records)
    print(latex)

    # Instruções qualitativas
    print(qualitative_instructions())

    # Salvar em arquivo se pedido
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        output_text = (
            f"# Relatório de Avaliação -- MES PR Review Agent\n\n"
            f"```\n{summary}\n```\n\n"
            f"## Tabelas LaTeX\n\n```latex\n{latex}\n```\n\n"
            f"## Guia Qualitativo\n\n```\n{qualitative_instructions()}\n```\n"
        )
        if args.qualitative:
            output_text += f"\n## Listagem por Item\n\n```\n{format_qualitative_listing(records)}\n```\n"
        args.out.write_text(output_text, encoding="utf-8")
        print(f"\nRelatório salvo em: {args.out.resolve()}")

    print("\n[OK] Fase 3 concluída.")


if __name__ == "__main__":
    main()

