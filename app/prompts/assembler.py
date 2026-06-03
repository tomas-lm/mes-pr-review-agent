from __future__ import annotations

from app.prompts.default_layers import DEFAULT_PROMPT_LAYERS, PromptLayer
from app.prompts.session import DynamicPromptSession
from app.state_machine.states import ReviewState


def assemble_prompt(
    *,
    state: ReviewState,
    runtime_context: dict[str, object],
    layers: tuple[PromptLayer, ...] = DEFAULT_PROMPT_LAYERS,
) -> str:
    sections: list[str] = []
    for layer in sorted(layers, key=lambda item: item.position):
        sections.append(f"## {layer.key}\n{layer.content.strip()}")

    sections.append(f"## current_state\nEstado atual: {state.value}")
    sections.append("## runtime_context\n" + repr(runtime_context))
    sections.append(
        "## output_contract\n"
        "Responda no final apenas com JSON valido contendo decision, summary e findings."
    )
    return "\n\n".join(sections)


def assemble_dynamic_prompt(session: DynamicPromptSession) -> str:
    return session.render_system_prompt()
