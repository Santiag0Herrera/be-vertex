import datetime
import os

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql://vertex_test:vertex_test@localhost/vertex_test",
)

from app.jobs import validate_trx

# Valid CUITs (check digit verified) used as Banelco voucher numbers.
CUIT_A = "20417869612"
CUIT_B = "20434854378"
CUIT_C = "23434892759"
TRX_DATE = datetime.datetime(2026, 11, 16, 12, 0)


def _trx(trx_id, cuit=None, amount=17000):
    return {
        "trx_id": trx_id,
        "trx_amount": amount,
        "trx_date": TRX_DATE,
        "trx_emisor_cuit": cuit,
    }


def _banelco(cuit, correlative, amount=17000):
    return {
        "amount": amount,
        "movement_date": "2026-11-16T00:00:00",
        "debit_credit_type": "C",
        "voucher_number": cuit,
        "correlative_number": str(correlative),
        "operation_code_bank": "34136",
        "operation_code_ib": "119",
        "branch_office_activity": "733",
        "customer_cuit": "",
        "account_cbu": "",
    }


def _coelsa(correlative, amount=17000):
    return {
        "amount": amount,
        "movement_date": "2026-11-16T00:00:00",
        "debit_credit_type": "C",
        "voucher_number": "11110008",
        "correlative_number": str(correlative),
        "operation_code_bank": "34129",
        "operation_code_ib": "697",
        "branch_office_activity": "100",
        "customer_cuit": "",
        "account_cbu": "",
    }


def _match(trx, movements, used=None, allow_unidentified=True):
    return validate_trx.match_trx_with_ib(
        trx,
        movements,
        bank_number="017",
        account_number="0430509162",
        used_fingerprints={} if used is None else used,
        allow_unidentified=allow_unidentified,
    )


def _fingerprint(movement):
    return validate_trx.build_interbanking_fingerprint(
        movement, bank_number="017", account_number="0430509162"
    )


@pytest.mark.parametrize(
    "voucher,expected",
    [
        (CUIT_A, CUIT_A),
        ("20-41786961-2", CUIT_A),
        ("20417869613", None),  # wrong check digit
        ("11110008", None),  # COELSA constant voucher
        ("0", None),
        ("", None),
        (None, None),
        ("99417869612", None),  # not a CUIT prefix
    ],
)
def test_movement_sender_cuit_only_accepts_valid_cuits(voucher, expected):
    assert validate_trx.movement_sender_cuit({"voucher_number": voucher}) == expected


def test_identified_movement_is_not_taken_by_another_sender():
    result = _match(_trx("LUCAS", cuit=CUIT_A), [_banelco(CUIT_C, 175)])

    assert result is None


def test_receipt_without_cuit_cannot_take_an_identified_movement():
    result = _match(_trx("NO-CUIT", cuit=None), [_banelco(CUIT_C, 175)])

    assert result is None


def test_identified_movement_is_preferred_over_unidentified_pool():
    own = _banelco(CUIT_A, 155)
    result = _match(_trx("TALAVERA", cuit=CUIT_A), [_coelsa(130), own])

    assert result["duplicated_trx"] is None
    assert result["matched_by"] == "sender_cuit"
    assert result["document_fingerprint"] == _fingerprint(own)


def test_receipt_falls_back_to_unidentified_movement():
    pool = _coelsa(130)
    result = _match(_trx("COELSA-SENDER", cuit=CUIT_A), [_banelco(CUIT_C, 175), pool])

    assert result["matched_by"] == "amount_date"
    assert result["document_fingerprint"] == _fingerprint(pool)


def test_first_pass_ignores_unidentified_pool():
    result = _match(
        _trx("COELSA-SENDER", cuit=CUIT_A),
        [_coelsa(130)],
        allow_unidentified=False,
    )

    assert result is None


def test_used_own_movement_is_reported_as_duplicate():
    own = _banelco(CUIT_A, 155)
    used = {_fingerprint(own): {"trx_id": "FIRST", "status": "conciliado"}}

    result = _match(_trx("SECOND", cuit=CUIT_A), [own], used=used)

    assert result["duplicated_trx"]["trx_id"] == "FIRST"
    assert result["matched_by"] == "sender_cuit"


def test_exhausted_unidentified_pool_leaves_receipt_pending():
    pool = _coelsa(130)
    used = {_fingerprint(pool): {"trx_id": "OTHER", "status": "conciliado"}}

    result = _match(_trx("LATE", cuit=CUIT_A), [pool], used=used)

    assert result is None


class FakeBusinessCalendar:
    async def get_settlement_date(self, transaction_date):
        return transaction_date


class FakeInterbanking:
    MOVEMENT_RESULT_LIMIT = 1000

    def __init__(self, movements):
        self.movements = movements

    async def get_reconciliation_accounts(self):
        return [{"account_number": "0430509162", "bank_number": "017"}]

    async def get_movement(self, account_number, bank_number, date_since, date_until):
        return {"movements_detail": self.movements}


def _pending(trx_id, cuit):
    return {
        "trx_id": trx_id,
        "trx_amount": 17000,
        "trx_date": datetime.datetime.now().replace(hour=12, minute=0, second=0, microsecond=0),
        "trx_emisor_cuit": cuit,
        "trx_receptor_cbu": "0430509162",
        "currency_name": "ARS",
        "customer_balance_id": 1,
        "fee_percentage": 0,
    }


async def _run(monkeypatch, pending, movements):
    today = pending[0]["trx_date"].date().isoformat()
    for movement in movements:
        movement["movement_date"] = f"{today}T00:00:00"

    conciliated = {}
    repeated = []

    def update_trx_status(**kwargs):
        conciliated[kwargs["trx_id"]] = kwargs["document_fingerprint"]
        return True

    def mark_trx_as_repeated(trx_id, document_fingerprint):
        repeated.append(trx_id)
        return True

    monkeypatch.setattr(validate_trx, "get_pending_trx", lambda entity_id: pending)
    monkeypatch.setattr(
        validate_trx,
        "get_entity_account_identifiers",
        lambda entity_id: validate_trx.account_identifier_aliases("0430509162"),
    )
    monkeypatch.setattr(validate_trx, "get_used_fingerprints", lambda entity_id=None: {})
    monkeypatch.setattr(validate_trx, "expire_old_pending_trx", lambda *a, **k: 0)
    monkeypatch.setattr(validate_trx, "InterBankingService", lambda: FakeInterbanking(movements))
    monkeypatch.setattr(validate_trx, "BusinessCalendarService", FakeBusinessCalendar)
    monkeypatch.setattr(validate_trx, "update_trx_status", update_trx_status)
    monkeypatch.setattr(validate_trx, "mark_trx_as_repeated", mark_trx_as_repeated)

    await validate_trx._run_reconciliation(entity_id=1)
    return conciliated, repeated


@pytest.mark.asyncio
async def test_earlier_receipt_does_not_steal_the_owner_movement(monkeypatch):
    # The 17/11 Sileo case: a receipt whose transfer has not arrived yet was
    # processed first and took Zabaleta's movement, leaving Zabaleta repetido.
    pending = [_pending("LUCAS", CUIT_A), _pending("ZABALETA", CUIT_C)]
    movements = [_banelco(CUIT_C, 175)]

    conciliated, repeated = await _run(monkeypatch, pending, movements)

    assert list(conciliated) == ["ZABALETA"]
    assert repeated == []


@pytest.mark.asyncio
async def test_unidentified_pool_waits_until_identified_movements_are_claimed(monkeypatch):
    # A sends via COELSA (no CUIT on the movement), B via Banelco. B must get
    # its own movement and A the COELSA one, whatever the processing order.
    pending = [_pending("B-FIRST", CUIT_B), _pending("A-COELSA", CUIT_A)]
    own_b = _banelco(CUIT_B, 153)
    pool = _coelsa(130)

    conciliated, repeated = await _run(monkeypatch, pending, [pool, own_b])

    assert conciliated["B-FIRST"] == _fingerprint(own_b)
    assert conciliated["A-COELSA"] == _fingerprint(pool)
    assert repeated == []


def _on(movement, day):
    return {**movement, "movement_date": f"{day.isoformat()}T00:00:00"}


def test_late_booked_identified_movement_matches_on_next_business_day():
    monday = datetime.date(2026, 11, 16)
    own = _on(_banelco(CUIT_A, 155), monday)
    trx = {**_trx("FRIDAY-NIGHT", cuit=CUIT_A), "trx_date": datetime.datetime(2026, 11, 13, 18, 1)}

    result = validate_trx.match_trx_with_ib(
        trx,
        [own],
        bank_number="017",
        account_number="0430509162",
        valid_movement_dates={datetime.date(2026, 11, 13)},
        used_fingerprints={},
        identified_movement_dates={monday},
    )

    assert result["matched_by"] == "sender_cuit"
    assert result["document_fingerprint"] == _fingerprint(own)


def test_late_booking_date_is_not_searched_for_unidentified_movements():
    monday = datetime.date(2026, 11, 16)
    trx = {**_trx("FRIDAY-NIGHT", cuit=CUIT_A), "trx_date": datetime.datetime(2026, 11, 13, 18, 1)}

    result = validate_trx.match_trx_with_ib(
        trx,
        [_on(_coelsa(130), monday)],
        bank_number="017",
        account_number="0430509162",
        valid_movement_dates={datetime.date(2026, 11, 13)},
        used_fingerprints={},
        identified_movement_dates={monday},
    )

    assert result is None


class WeekdayCalendar:
    async def get_settlement_date(self, transaction_date):
        while transaction_date.weekday() >= 5:
            transaction_date += datetime.timedelta(days=1)
        return transaction_date


@pytest.mark.asyncio
async def test_resolve_movement_dates_returns_next_business_day():
    cache = {}
    friday = datetime.date(2026, 11, 13)
    saturday = datetime.date(2026, 11, 14)

    assert await validate_trx.resolve_movement_dates(WeekdayCalendar(), friday, cache) == (
        friday,
        datetime.date(2026, 11, 16),
    )
    assert await validate_trx.resolve_movement_dates(WeekdayCalendar(), saturday, cache) == (
        datetime.date(2026, 11, 16),
        datetime.date(2026, 11, 17),
    )


@pytest.mark.asyncio
async def test_job_fetches_and_matches_the_late_booking_day(monkeypatch):
    # Receipt from today; its transfer is booked tomorrow (after the cutoff).
    pending = [_pending("LATE", CUIT_A)]
    trx_date = pending[0]["trx_date"].date()
    tomorrow = trx_date + datetime.timedelta(days=1)
    movement = _banelco(CUIT_A, 155)
    calls = []

    class LateInterbanking(FakeInterbanking):
        async def get_movement(self, account_number, bank_number, date_since, date_until):
            calls.append((date_since, date_until))
            return {"movements_detail": [_on(movement, tomorrow)]}

    conciliated = {}
    monkeypatch.setattr(validate_trx, "get_pending_trx", lambda entity_id: pending)
    monkeypatch.setattr(
        validate_trx,
        "get_entity_account_identifiers",
        lambda entity_id: validate_trx.account_identifier_aliases("0430509162"),
    )
    monkeypatch.setattr(validate_trx, "get_used_fingerprints", lambda entity_id=None: {})
    monkeypatch.setattr(validate_trx, "expire_old_pending_trx", lambda *a, **k: 0)
    monkeypatch.setattr(validate_trx, "InterBankingService", lambda: LateInterbanking([]))
    monkeypatch.setattr(validate_trx, "BusinessCalendarService", FakeBusinessCalendar)
    monkeypatch.setattr(
        validate_trx,
        "update_trx_status",
        lambda **kwargs: conciliated.setdefault(kwargs["trx_id"], kwargs["document_fingerprint"]) or True,
    )

    await validate_trx._run_reconciliation(entity_id=1)

    assert calls == [(trx_date.isoformat(), (tomorrow + datetime.timedelta(days=1)).isoformat())]
    assert conciliated["LATE"] == _fingerprint(_on(movement, tomorrow))
