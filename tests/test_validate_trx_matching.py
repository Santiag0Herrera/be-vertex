import datetime
import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://vertex_test:vertex_test@localhost/vertex_test",
)

from app.jobs import validate_trx


def _pending_trx(trx_id):
    return {
        "trx_id": trx_id,
        "trx_amount": 1500,
        "trx_date": datetime.datetime(2026, 9, 29, 12, 0),
    }


def _movement(**overrides):
    movement = {
        "amount": 1500,
        "movement_date": "2026-09-29T10:00:00",
        "debit_credit_type": "C",
        "voucher_number": None,
        "correlative_number": None,
        "operation_code_bank": "TRANSFER",
        "operation_code_ib": "CREDIT",
        "branch_office_activity": None,
        "customer_cuit": None,
        "account_cbu": None,
    }
    movement.update(overrides)
    return movement


def _match(trx_id, movements):
    return validate_trx.match_trx_with_ib(
        _pending_trx(trx_id),
        movements,
        bank_number="015",
        account_number="123456",
    )


def test_indistinguishable_movements_provide_one_stable_slot_each(monkeypatch):
    movements = [_movement() for _ in range(10)]
    occupied = {}

    def find_occupied(document_fingerprint, current_trx_id):
        return occupied.get(document_fingerprint)

    monkeypatch.setattr(
        validate_trx,
        "find_trx_by_fingerprint",
        find_occupied,
    )

    allocated_fingerprints = []
    for index in range(10):
        result = _match(f"PENDING-{index + 1}", movements)

        assert result["duplicated_trx"] is None
        assert result["fingerprint_slot"] == index + 1
        assert result["fingerprint_total_slots"] == 10

        fingerprint = result["document_fingerprint"]
        allocated_fingerprints.append(fingerprint)
        occupied[fingerprint] = {
            "trx_id": f"CONCILIATED-{index + 1}",
            "status": "conciliado",
        }

    assert len(set(allocated_fingerprints)) == 10
    assert allocated_fingerprints[0] == validate_trx.build_interbanking_fingerprint(
        movements[0],
        bank_number="015",
        account_number="123456",
    )

    excess_result = _match("PENDING-11", movements)

    assert excess_result["duplicated_trx"] is not None
    assert excess_result["fingerprint_slot"] == 10
    assert excess_result["fingerprint_total_slots"] == 10
    assert excess_result["document_fingerprint"] == allocated_fingerprints[-1]


def test_repeated_api_row_with_bank_reference_does_not_add_capacity(monkeypatch):
    movement = _movement(voucher_number="VOUCHER-123")
    movements = [movement, dict(movement)]
    occupied = {}
    lookup_calls = []

    def find_occupied(document_fingerprint, current_trx_id):
        lookup_calls.append(document_fingerprint)
        return occupied.get(document_fingerprint)

    monkeypatch.setattr(
        validate_trx,
        "find_trx_by_fingerprint",
        find_occupied,
    )

    first_result = _match("PENDING-1", movements)
    occupied[first_result["document_fingerprint"]] = {
        "trx_id": "CONCILIATED-1",
        "status": "conciliado",
    }

    lookup_calls.clear()
    second_result = _match("PENDING-2", movements)

    assert second_result["duplicated_trx"] is not None
    assert second_result["fingerprint_slot"] == 1
    assert second_result["fingerprint_total_slots"] == 1
    assert len(lookup_calls) == 1


def test_placeholder_bank_references_still_allow_multiple_slots(monkeypatch):
    movements = [
        _movement(voucher_number="0", correlative_number="000000"),
        _movement(voucher_number="0", correlative_number="000000"),
    ]
    occupied = {}

    monkeypatch.setattr(
        validate_trx,
        "find_trx_by_fingerprint",
        lambda document_fingerprint, current_trx_id: occupied.get(
            document_fingerprint
        ),
    )

    first_result = _match("PENDING-1", movements)
    occupied[first_result["document_fingerprint"]] = {
        "trx_id": "CONCILIATED-1",
        "status": "conciliado",
    }
    second_result = _match("PENDING-2", movements)

    assert first_result["fingerprint_slot"] == 1
    assert second_result["fingerprint_slot"] == 2
    assert second_result["fingerprint_total_slots"] == 2
    assert second_result["duplicated_trx"] is None


def test_used_identified_movement_does_not_block_another_reference(monkeypatch):
    movements = [
        _movement(voucher_number="VOUCHER-1"),
        _movement(voucher_number="VOUCHER-2"),
    ]
    first_fingerprint = validate_trx.build_interbanking_fingerprint(
        movements[0],
        bank_number="015",
        account_number="123456",
    )

    def find_occupied(document_fingerprint, current_trx_id):
        if document_fingerprint == first_fingerprint:
            return {"trx_id": "CONCILIATED-1", "status": "conciliado"}
        return None

    monkeypatch.setattr(
        validate_trx,
        "find_trx_by_fingerprint",
        find_occupied,
    )

    result = _match("PENDING-2", movements)

    assert result["duplicated_trx"] is None
    assert result["movement"]["voucher_number"] == "VOUCHER-2"
    assert result["document_fingerprint"] != first_fingerprint


def test_pending_transactions_are_processed_oldest_first():
    assert "ORDER BY trx.creation_date ASC, trx.id ASC" in validate_trx.SQL
