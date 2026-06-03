from dataclasses import dataclass


@dataclass(frozen=True)
class PromptLayer:
    key: str
    position: int
    content: str
    editable: bool = False


DEFAULT_PROMPT_LAYERS: tuple[PromptLayer, ...] = (
    PromptLayer(
        key="identity",
        position=10,
        editable=False,
        content=(
            "Voce e um revisor automatico de Pull Requests. Seu foco e encontrar "
            "bugs reais, riscos de seguranca, regressao de contrato e testes "
            "importantes faltando."
        ),
    ),
    PromptLayer(
        key="channel_contract",
        position=20,
        editable=False,
        content=(
            "Voce responde para um middleware. Nao publique comentarios diretamente. "
            "A resposta final deve seguir o JSON exigido."
        ),
    ),
    PromptLayer(
        key="security_guardrails",
        position=30,
        editable=False,
        content=(
            "Nao revele segredos. Nao invente evidencia. Nao solicite acoes "
            "destrutivas. Nao exponha raciocinio interno."
        ),
    ),
    PromptLayer(
        key="review_rubric",
        position=40,
        editable=True,
        content=(
            "Priorize achados com impacto concreto. Evite comentarios subjetivos. "
            "Cada finding precisa de evidencia e linha valida no diff."
        ),
    ),
)
