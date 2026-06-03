from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.prompts.default_layers import DEFAULT_PROMPT_LAYERS, PromptLayer
from app.state_machine.states import ReviewState
from app.state_machine.transitions import ALLOWED_TRANSITIONS, can_transition

DEFAULT_STATE_LAYER = """
Estado atual: RECEIVED.

Objetivo imediato:
- Confirmar que o PR deve ser analisado.
- Chamar rewrite_state_prompt antes de mudar de fase.
- Chamar append_review_observation sempre que descobrir fato, risco ou pendencia.
""".strip()


@dataclass
class ReviewObservation:
    category: str
    message: str
    todo: str | None = None
    evidence: list[str] = field(default_factory=list)


@dataclass
class DynamicPromptSession:
    run_id: str
    state: ReviewState
    runtime_context: dict[str, Any]
    state_layer: str = DEFAULT_STATE_LAYER
    observations: list[ReviewObservation] = field(default_factory=list)
    layers: tuple[PromptLayer, ...] = DEFAULT_PROMPT_LAYERS

    def rewrite_state_layer(
        self,
        *,
        target_state: ReviewState,
        state_prompt: str,
        reason: str,
    ) -> str:
        if target_state != self.state and not can_transition(self.state, target_state):
            allowed = ", ".join(state.value for state in ALLOWED_TRANSITIONS[self.state])
            raise ValueError(
                f"Invalid state transition from {self.state.value} to {target_state.value}. "
                f"Allowed: {allowed}"
            )
        previous = self.state
        self.state = target_state
        self.state_layer = (
            f"Estado atual: {target_state.value}.\n\n"
            f"Motivo da atualizacao: {reason}\n\n"
            f"Instrucoes dinamicas desta fase:\n{state_prompt.strip()}"
        )
        return f"state prompt updated: {previous.value} -> {target_state.value}"

    def append_observation(
        self,
        *,
        category: str,
        message: str,
        todo: str | None = None,
        evidence: list[str] | None = None,
    ) -> None:
        self.observations.append(
            ReviewObservation(
                category=category,
                message=message,
                todo=todo,
                evidence=evidence or [],
            )
        )

    def render_system_prompt(self) -> str:
        sections: list[str] = []
        for layer in sorted(self.layers, key=lambda item: item.position):
            sections.append(f"## {layer.key}\n{layer.content.strip()}")
        sections.append("## finite_state_machine\n" + self._state_machine_markdown())
        sections.append("## dynamic_state_layer\n" + self.state_layer)
        sections.append("## runtime_context\n" + repr(self.runtime_context))
        sections.append("## review_observations_markdown\n" + self.observations_markdown())
        sections.append("## available_tools\n" + AVAILABLE_TOOLS_PROMPT)
        sections.append("## output_contract\n" + OUTPUT_CONTRACT_PROMPT)
        return "\n\n".join(sections)

    def observations_markdown(self) -> str:
        if not self.observations:
            return "Nenhuma observacao registrada ainda."
        lines: list[str] = []
        for index, observation in enumerate(self.observations, start=1):
            lines.append(f"### {index}. {observation.category}")
            lines.append("")
            lines.append(observation.message)
            if observation.evidence:
                lines.append("")
                lines.append("Evidencias:")
                for item in observation.evidence:
                    lines.append(f"- {item}")
            if observation.todo:
                lines.append("")
                lines.append(f"Pendencia: {observation.todo}")
            lines.append("")
        return "\n".join(lines).strip()

    def _state_machine_markdown(self) -> str:
        lines = [
            "Use a maquina de estados abaixo para navegar a revisao.",
            "Voce deve chamar rewrite_state_prompt para atualizar a camada dinamica de estado.",
            "",
        ]
        for state, targets in ALLOWED_TRANSITIONS.items():
            if targets:
                target_list = ", ".join(target.value for target in sorted(targets, key=str))
            else:
                target_list = "(terminal)"
            lines.append(f"- {state.value} -> {target_list}")
        return "\n".join(lines)


AVAILABLE_TOOLS_PROMPT = """
Use tools quando precisar agir no ciclo agentico:

1. rewrite_state_prompt
   - Atualiza a camada dinamica do system prompt.
   - Argumentos: state, state_prompt, reason.
   - Use ao mudar de fase da maquina de estados ou quando precisar refocar a investigacao.

2. append_review_observation
   - Escreve uma observacao em Markdown para auditoria da revisao.
   - Argumentos: category, message, todo, evidence.
   - Use para registrar fatos, riscos, hipoteses descartadas e proximas acoes.

3. get_pr_metadata
   - Consulta metadados conhecidos do PR recebidos no webhook.

4. get_state_machine
   - Consulta o estado atual e transicoes permitidas.

5. list_changed_files
   - Lista arquivos alterados do PR via GitHub API.
   - Argumentos opcionais: max_files.
   - Use apenas em COLLECT_CONTEXT ou INVESTIGATE.

6. get_diff_hunks
   - Retorna hunks de diff para todos os arquivos ou um path especifico.
   - Argumentos opcionais: path, max_files, max_patch_chars.
   - Use para coletar evidencia concreta antes de criar findings.

7. read_file_at_ref
   - Le um arquivo no ref `head`, `base` ou SHA/ref explicito.
   - Argumentos: path, ref. Argumento opcional: max_chars.
   - Use em INVESTIGATE para comparar contexto ao redor do diff.

8. read_repo_rules
   - Le README, CONTRIBUTING e arquivos `.github` relevantes.
   - Argumentos opcionais: paths, ref.
   - Use em COLLECT_CONTEXT antes de avaliar regras do repo.

9. get_ci_status
   - Consulta check runs atuais do commit head.
   - Use em COLLECT_CONTEXT, INVESTIGATE ou VALIDATE_FINDINGS.

10. record_finding_candidate
   - Registra um finding candidato em Markdown/runtime context, sem publicar.
   - Argumentos: severity, confidence, category, path, line, side, title, body,
     evidence, suggested_fix.
   - Use em EVALUATE quando houver evidencia concreta.

11. validate_line_mapping
   - Confirma se path/line/side apontam para uma linha realmente alterada no diff.
   - Argumentos: path, line, side.
   - Use em VALIDATE_FINDINGS antes de incluir um finding no JSON final.
""".strip()


OUTPUT_CONTRACT_PROMPT = """
Quando tiver informacao suficiente, responda somente com:

<final>
{
  "decision": "approve|comment|request_changes|skip",
  "summary": "Resumo curto da revisao",
  "findings": [
    {
      "severity": "critical|high|medium|low|nit",
      "confidence": 0.0,
      "category": "bug|security|test|maintainability|style|spec",
      "path": "arquivo",
      "line": 123,
      "side": "RIGHT",
      "title": "Problema em uma frase",
      "body": "Comentario publicavel",
      "evidence": ["evidencia concreta"],
      "suggested_fix": "Opcional"
    }
  ],
  "trace_notes": ["Resumo tecnico sem raciocinio interno"]
}
</final>

O backend validara esse JSON antes de publicar. Findings sem evidencia concreta, linha
alterada valida ou confianca suficiente serao descartados.
""".strip()
