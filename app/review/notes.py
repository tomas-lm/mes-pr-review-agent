from __future__ import annotations

from pathlib import Path

from app.prompts.session import DynamicPromptSession


class ReviewNotesWriter:
    def __init__(self, *, notes_dir: str | Path) -> None:
        self.notes_dir = Path(notes_dir)

    def write(self, session: DynamicPromptSession, *, trace_markdown: str | None = None) -> Path:
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        path = self.notes_dir / f"{session.run_id}.md"
        path.write_text(self._render(session, trace_markdown=trace_markdown), encoding="utf-8")
        return path

    def _render(self, session: DynamicPromptSession, *, trace_markdown: str | None) -> str:
        sections = [
            f"# Review run {session.run_id}",
            f"## Estado atual\n\n{session.state.value}",
            f"## Camada dinamica de estado\n\n{session.state_layer}",
            f"## Observacoes e pendencias\n\n{session.observations_markdown()}",
        ]
        if trace_markdown:
            sections.append(trace_markdown)
        return "\n\n".join(sections).strip() + "\n"
