from app.state_machine.states import ReviewState

ALLOWED_TRANSITIONS: dict[ReviewState, set[ReviewState]] = {
    ReviewState.RECEIVED: {
        ReviewState.TRIAGE,
        ReviewState.SKIPPED,
        ReviewState.NEEDS_HUMAN,
        ReviewState.ERROR,
    },
    ReviewState.TRIAGE: {
        ReviewState.COLLECT_CONTEXT,
        ReviewState.SKIPPED,
        ReviewState.NEEDS_HUMAN,
        ReviewState.ERROR,
    },
    ReviewState.COLLECT_CONTEXT: {
        ReviewState.INVESTIGATE,
        ReviewState.NEEDS_HUMAN,
        ReviewState.ERROR,
    },
    ReviewState.INVESTIGATE: {
        ReviewState.EVALUATE,
        ReviewState.NEEDS_HUMAN,
        ReviewState.ERROR,
    },
    ReviewState.EVALUATE: {
        ReviewState.VALIDATE_FINDINGS,
        ReviewState.NEEDS_HUMAN,
        ReviewState.ERROR,
    },
    ReviewState.VALIDATE_FINDINGS: {
        ReviewState.COMMENT_PLAN,
        ReviewState.NEEDS_HUMAN,
        ReviewState.ERROR,
    },
    ReviewState.COMMENT_PLAN: {
        ReviewState.PUBLISH,
        ReviewState.NEEDS_HUMAN,
        ReviewState.ERROR,
    },
    ReviewState.PUBLISH: {ReviewState.DONE, ReviewState.NEEDS_HUMAN, ReviewState.ERROR},
    ReviewState.DONE: set(),
    ReviewState.SKIPPED: set(),
    ReviewState.NEEDS_HUMAN: set(),
    ReviewState.ERROR: set(),
}


def can_transition(current: ReviewState, target: ReviewState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]
