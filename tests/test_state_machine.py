import pytest

from app.state_machine.states import ReviewState
from app.storage.runs import ReviewRun


def make_run() -> ReviewRun:
    return ReviewRun(
        run_id="run-1",
        delivery_id="delivery-1",
        event="pull_request",
        action="opened",
        repository="tomas-lm/mes-pr-review-agent",
        pull_request_number=1,
        head_sha="abc123",
        installation_id=123,
    )


def test_valid_transition_records_history() -> None:
    run = make_run()

    run.transition_to(ReviewState.TRIAGE, reason="start triage")

    assert run.state == ReviewState.TRIAGE
    assert len(run.transitions) == 1
    assert run.transitions[0].from_state == ReviewState.RECEIVED
    assert run.transitions[0].to_state == ReviewState.TRIAGE


def test_cannot_publish_before_validation() -> None:
    run = make_run()

    with pytest.raises(ValueError):
        run.transition_to(ReviewState.PUBLISH, reason="invalid jump")
