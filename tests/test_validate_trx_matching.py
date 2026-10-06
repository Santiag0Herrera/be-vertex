import datetime
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://vertex_test:vertex_test@localhost/vertex_test",
)

from app.jobs import validate_trx
from app.db.database import Base
from app.models import Trx


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


def test_only_one_conciliated_transaction_can_claim_a_fingerprint():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    def transaction(trx_id, status):
        return Trx(
            document_fingerprint="SAME-FINGERPRINT",
            document_name=f"{trx_id}.pdf",
            trx_id=trx_id,
            emisor_name="Sender",
            emisor_cuit="1",
            receptor_cbu="000123",
            amount=100,
            date=datetime.datetime(2026, 9, 29, 12, 0),
            received_date=datetime.date(2026, 9, 29),
            status=status,
            account_id=1,
        )

    try:
        session.add(transaction("CONCILIATED-1", "conciliado"))
        session.add(transaction("REPEATED-1", "repetido"))
        session.commit()

        session.add(transaction("CONCILIATED-2", "conciliado"))
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()
        engine.dispose()


def test_reconciliation_accounts_are_limited_to_owned_accounts():
    accounts = [
        {
            "account_number": "111",
            "bank_number": "015",
            "account_cbu": "000-123",
        },
        {
            "account_number": "222",
            "bank_number": "072",
            "account_cbu": "000-999",
        },
        {"account_number": "333"},
    ]

    result = validate_trx.filter_reconciliation_accounts(
        accounts,
        owned_account_identifiers={"111"},
    )

    assert result == [accounts[0]]


def test_reconciliation_account_ownership_does_not_match_account_cbu():
    account = {
        "account_number": "111",
        "bank_number": "015",
        "account_cbu": "000-123",
    }

    result = validate_trx.filter_reconciliation_accounts(
        [account],
        owned_account_identifiers={"000123"},
    )

    assert result == []


def test_account_matching_tolerates_formatting_and_missing_leading_zero():
    account = {
        "account_number": "9170/210248397",
        "bank_number": "015",
        "account_cbu": "015-0001-2345-6789-0123-45",
    }
    account_index, ambiguous = validate_trx.build_account_index([account])

    resolved, reason = validate_trx.resolve_reconciliation_account(
        "09170210248397",
        account_index,
        ambiguous,
    )

    assert resolved == account
    assert reason is None


def test_lookup_normalization_does_not_change_legacy_fingerprint_normalization():
    value = " 0917-0210/248.397 "

    assert validate_trx.normalize_account(value) == "09170210/248.397"
    assert validate_trx.normalize_account_identifier(value) == "09170210248397"


def test_account_matching_does_not_guess_when_zero_less_alias_is_ambiguous():
    accounts = [
        {
            "account_number": "00123",
            "bank_number": "015",
            "account_cbu": "0150000000000000000001",
        },
        {
            "account_number": "123",
            "bank_number": "072",
            "account_cbu": "0720000000000000000002",
        },
    ]
    account_index, ambiguous = validate_trx.build_account_index(accounts)

    resolved, reason = validate_trx.resolve_reconciliation_account(
        "000123",
        account_index,
        ambiguous,
    )

    assert resolved is None
    assert reason == "ambiguous_destination_account"


def test_entity_account_filter_normalizes_account_number():
    account = {
        "account_number": "123",
        "bank_number": "015",
        "cbu": {"nro": "000-123"},
    }

    result = validate_trx.filter_reconciliation_accounts(
        [account],
        owned_account_identifiers=validate_trx.account_identifier_aliases(
            "000123"
        ),
    )

    assert result == [account]


def test_credit_movement_index_ignores_unrelated_and_invalid_movements():
    selected_movement = _movement()
    movements = [
        selected_movement,
        _movement(amount=999),
        _movement(debit_credit_type="D"),
        {"amount": 1500, "movement_date": None, "debit_credit_type": "C"},
    ]

    movement_index = validate_trx.build_credit_movement_index(movements)
    selected = validate_trx.select_credit_movements(
        movement_index,
        amount=1500,
        valid_dates={datetime.date(2026, 9, 29)},
    )

    assert selected == [selected_movement]


def _full_pending_trx(trx_id, trx_date):
    return {
        "trx_id": trx_id,
        "trx_amount": 1500,
        "trx_date": trx_date,
        "trx_receptor_cbu": "000123",
        "currency_name": "ARS",
        "customer_balance_id": 1,
        "fee_percentage": 0,
    }


class FakeBusinessCalendar:
    async def get_settlement_date(self, transaction_date):
        return transaction_date


class FakeInterbanking:
    MOVEMENT_RESULT_LIMIT = 1000

    def __init__(self, movements):
        self.movements = movements
        self.movement_calls = []

    async def get_reconciliation_accounts(self):
        return [
            {
                "account_number": "123456",
                "bank_number": "015",
                "account_cbu": "000123",
                "bank_name": "Test Bank",
            }
        ]

    async def get_movement(
        self,
        account_number,
        bank_number,
        date_since,
        date_until,
    ):
        self.movement_calls.append(
            (account_number, bank_number, date_since, date_until)
        )
        return {"movements_detail": self.movements}


@pytest.mark.asyncio
async def test_reconciliation_reuses_one_movement_request_for_same_account_and_date(
    monkeypatch,
    caplog,
):
    caplog.set_level("INFO", logger="validate_trx_job")
    trx_date = datetime.datetime.now().replace(hour=12, minute=0, second=0)
    movements = [
        _movement(movement_date=trx_date.isoformat()),
        _movement(movement_date=trx_date.isoformat()),
    ]
    fake_interbanking = FakeInterbanking(movements)
    pending = [
        _full_pending_trx("PENDING-1", trx_date),
        _full_pending_trx("PENDING-2", trx_date),
    ]

    monkeypatch.setattr(validate_trx, "get_pending_trx", lambda entity_id: pending)
    monkeypatch.setattr(
        validate_trx,
        "get_entity_account_identifiers",
        lambda entity_id: validate_trx.account_identifier_aliases("123456"),
    )
    monkeypatch.setattr(
        validate_trx,
        "get_used_fingerprints",
        lambda entity_id=None: {},
    )
    monkeypatch.setattr(validate_trx, "expire_old_pending_trx", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        validate_trx,
        "InterBankingService",
        lambda: fake_interbanking,
    )
    monkeypatch.setattr(
        validate_trx,
        "BusinessCalendarService",
        FakeBusinessCalendar,
    )
    monkeypatch.setattr(validate_trx, "update_trx_status", lambda **kwargs: True)

    result = await validate_trx._run_reconciliation(entity_id=1)

    assert result["conciliated"] == 2
    assert result["movement_requests"] == 1
    assert result["movement_cache_hits"] == 1
    assert len(fake_interbanking.movement_calls) == 1
    completed_log = next(
        record
        for record in caplog.records
        if getattr(record, "event", None) == "reconciliation_completed"
    )
    assert completed_log.checked == 2
    assert completed_log.conciliated == 2
    assert completed_log.skipped_by_reason == {}


@pytest.mark.asyncio
async def test_unavailable_destination_is_reported_by_reason(monkeypatch):
    trx_date = datetime.datetime.now().replace(hour=12, minute=0, second=0)
    pending = [_full_pending_trx("PENDING-1", trx_date)]
    pending[0]["trx_receptor_cbu"] = "999999"
    fake_interbanking = FakeInterbanking([])

    monkeypatch.setattr(validate_trx, "get_pending_trx", lambda entity_id: pending)
    monkeypatch.setattr(
        validate_trx,
        "get_entity_account_identifiers",
        lambda entity_id: validate_trx.account_identifier_aliases("123456"),
    )
    monkeypatch.setattr(
        validate_trx,
        "get_used_fingerprints",
        lambda entity_id=None: {},
    )
    monkeypatch.setattr(validate_trx, "expire_old_pending_trx", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        validate_trx,
        "InterBankingService",
        lambda: fake_interbanking,
    )
    monkeypatch.setattr(
        validate_trx,
        "BusinessCalendarService",
        FakeBusinessCalendar,
    )

    result = await validate_trx._run_reconciliation(entity_id=1)

    assert result["checked"] == 0
    assert result["skipped"] == 1
    assert result["skipped_by_reason"] == {
        "destination_account_not_available": 1,
    }
    assert result["movement_requests"] == 0


@pytest.mark.asyncio
async def test_truncated_movement_response_leaves_batch_pending(monkeypatch):
    trx_date = datetime.datetime.now().replace(hour=12, minute=0, second=0)
    fake_interbanking = FakeInterbanking(
        [_movement(movement_date=trx_date.isoformat())] * 1000
    )
    pending = [_full_pending_trx("PENDING-1", trx_date)]
    update_calls = []

    monkeypatch.setattr(validate_trx, "get_pending_trx", lambda entity_id: pending)
    monkeypatch.setattr(
        validate_trx,
        "get_entity_account_identifiers",
        lambda entity_id: validate_trx.account_identifier_aliases("123456"),
    )
    monkeypatch.setattr(
        validate_trx,
        "get_used_fingerprints",
        lambda entity_id=None: {},
    )
    monkeypatch.setattr(validate_trx, "expire_old_pending_trx", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        validate_trx,
        "InterBankingService",
        lambda: fake_interbanking,
    )
    monkeypatch.setattr(
        validate_trx,
        "BusinessCalendarService",
        FakeBusinessCalendar,
    )
    monkeypatch.setattr(
        validate_trx,
        "update_trx_status",
        lambda **kwargs: update_calls.append(kwargs),
    )

    result = await validate_trx._run_reconciliation(entity_id=1)

    assert result["conciliated"] == 0
    assert result["skipped"] == 1
    assert result["still_pending"] == 1
    assert update_calls == []


@pytest.mark.asyncio
async def test_expired_transactions_do_not_call_interbanking(monkeypatch):
    pending = [
        _full_pending_trx(
            "EXPIRED-1",
            datetime.datetime(2020, 1, 1, 12, 0),
        )
    ]

    monkeypatch.setattr(validate_trx, "get_pending_trx", lambda entity_id: pending)
    monkeypatch.setattr(
        validate_trx,
        "expire_old_pending_trx",
        lambda trx_ids, reference_time: len(trx_ids),
    )

    class UnexpectedInterbankingCall:
        def __init__(self):
            raise AssertionError("Interbanking must not be called for expired receipts")

    monkeypatch.setattr(
        validate_trx,
        "InterBankingService",
        UnexpectedInterbankingCall,
    )

    result = await validate_trx._run_reconciliation(entity_id=1)

    assert result["expired"] == 1
    assert result["movement_requests"] == 0
    assert result["still_pending"] == 0
