from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.state_machine.states import ReviewState
from app.state_machine.transitions import can_transition


@dataclass(frozen=True)
class StateTransition:
    from_state: ReviewState
    to_state: ReviewState
    reason: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ReviewRun:
    run_id: str
    delivery_id: str
    event: str
    action: str
    repository: str
    pull_request_number: int
    head_sha: str
    installation_id: int
    state: ReviewState = ReviewState.RECEIVED
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    transitions: list[StateTransition] = field(default_factory=list)

    def transition_to(self, target: ReviewState, *, reason: str) -> None:
        if not can_transition(self.state, target):
            raise ValueError(f"Invalid transition from {self.state} to {target}")
        self.transitions.append(
            StateTransition(from_state=self.state, to_state=target, reason=reason)
        )
        self.state = target


class RunStore:
    def __init__(self) -> None:
        self._runs_by_id: dict[str, ReviewRun] = {}
        self._runs_by_delivery: dict[str, str] = {}

    def has_delivery(self, delivery_id: str) -> bool:
        return delivery_id in self._runs_by_delivery

    def get_by_delivery(self, delivery_id: str) -> ReviewRun | None:
        run_id = self._runs_by_delivery.get(delivery_id)
        if run_id is None:
            return None
        return self._runs_by_id[run_id]

    def create_pull_request_run(
        self,
        *,
        delivery_id: str,
        event: str,
        action: str,
        repository: str,
        pull_request_number: int,
        head_sha: str,
        installation_id: int,
    ) -> ReviewRun:
        if self.has_delivery(delivery_id):
            existing = self.get_by_delivery(delivery_id)
            if existing is None:
                raise RuntimeError("delivery index is corrupted")
            return existing

        run = ReviewRun(
            run_id=str(uuid.uuid4()),
            delivery_id=delivery_id,
            event=event,
            action=action,
            repository=repository,
            pull_request_number=pull_request_number,
            head_sha=head_sha,
            installation_id=installation_id,
        )
        self._runs_by_id[run.run_id] = run
        self._runs_by_delivery[delivery_id] = run.run_id
        return run

    def list_runs(self) -> list[ReviewRun]:
        return list(self._runs_by_id.values())
