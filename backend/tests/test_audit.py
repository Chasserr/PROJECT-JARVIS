from __future__ import annotations

from jarvis.container import Container


def test_audit_chain_detects_tampering(container: Container) -> None:
    container.audit.record(actor="test", action="one", outcome="ok", detail={"a": 1})
    container.audit.record(actor="test", action="two", outcome="ok", detail={"b": 2})
    assert container.audit.verify().ok is True

    with container.db.connection() as conn:
        conn.execute("UPDATE audit SET action = 'tampered' WHERE seq = 1")

    result = container.audit.verify()
    assert result.ok is False
    assert result.first_bad_seq == 1


def test_audit_detail_is_encrypted(container: Container) -> None:
    container.audit.record(actor="test", action="secret", detail={"token": "hunter2"})
    with container.db.connection() as conn:
        blob = conn.execute("SELECT detail FROM audit").fetchone()["detail"]
    assert b"hunter2" not in blob
    assert container.audit.tail(1)[0].detail == {"token": "hunter2"}
