"""Money-model tests (doc 2 §6, doc 3 step 6, doc 4 testing checklist).

The load-bearing suite alongside the cost math: these four figures are the dashboard, and
conflating any two of them is the failure mode doc 2 §6 exists to prevent. Pure — the
functions take `MeetingRead`, so no database is involved.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.enums import Status, Tier, Verdict
from app.schemas.api import MeetingRead
from app.services.money import (
    avoidable_spend,
    budget_comparison,
    necessary_spend,
    reclaimed_savings,
    spend_over_time,
    total_spend,
)

JAN = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

_next_id = iter(range(1, 10_000))


def meeting(cost, verdict, status, *, reclaimed="0.00", created_at=JAN) -> MeetingRead:
    """A ledger row with only the fields the money model reads varying."""
    return MeetingRead(
        id=next(_next_id),
        title="Meeting",
        description="",
        start=None,
        duration_minutes=60,
        attendee_count=1,
        attendee_tiers=[Tier.IC],
        organizer_email="o@x.com",
        is_recurring=False,
        recurrence_freq=None,
        cost=Decimal(cost),
        annualized_cost=None,
        score=5,
        verdict=verdict,
        reasoning="—",
        alternative_email="Subject: x" if verdict is Verdict.EMAIL else None,
        status=status,
        reclaimed_savings=Decimal(reclaimed),
        created_at=created_at,
    )


# A hand-built ledger covering every verdict x status combination.
KEEP_ANALYZED = meeting("100.00", Verdict.KEEP, Status.ANALYZED)
KEEP_HELD = meeting("200.00", Verdict.KEEP, Status.HELD)
KEEP_CONVERTED = meeting("300.00", Verdict.KEEP, Status.CONVERTED, reclaimed="300.00")
EMAIL_ANALYZED = meeting("400.00", Verdict.EMAIL, Status.ANALYZED)
EMAIL_HELD = meeting("500.00", Verdict.EMAIL, Status.HELD)
EMAIL_CONVERTED = meeting("600.00", Verdict.EMAIL, Status.CONVERTED, reclaimed="600.00")

EVERY_COMBO = [
    KEEP_ANALYZED, KEEP_HELD, KEEP_CONVERTED,
    EMAIL_ANALYZED, EMAIL_HELD, EMAIL_CONVERTED,
]


# ------------------------------------------------------- the four dollar concepts


def test_total_spend_counts_every_meeting_that_happened():
    # 100 + 200 + 400 + 500. The two converted meetings never happened.
    assert total_spend(EVERY_COMBO) == Decimal("1200.00")


def test_necessary_spend_is_kept_meetings_only():
    assert necessary_spend(EVERY_COMBO) == Decimal("300.00")  # 100 + 200


def test_avoidable_spend_is_flagged_meetings_held_anyway():
    assert avoidable_spend(EVERY_COMBO) == Decimal("900.00")  # 400 + 500


def test_reclaimed_savings_is_converted_meetings_only():
    assert reclaimed_savings(EVERY_COMBO) == Decimal("900.00")  # 300 + 600


def test_spend_splits_exactly_into_necessary_and_avoidable():
    # The invariant the dashboard depends on: no dollar is in both or neither.
    assert necessary_spend(EVERY_COMBO) + avoidable_spend(EVERY_COMBO) == total_spend(EVERY_COMBO)


def test_a_converted_meeting_is_never_both_spend_and_savings():
    # Doc 2 §6's central warning: spend happened, savings did not.
    ledger = [EMAIL_CONVERTED]

    assert total_spend(ledger) == Decimal("0.00")
    assert avoidable_spend(ledger) == Decimal("0.00")
    assert reclaimed_savings(ledger) == Decimal("600.00")


def test_converting_moves_money_from_avoidable_to_reclaimed():
    # The step-10 transition, asserted on the derivations that render it.
    before = [EMAIL_HELD]
    after = [meeting("500.00", Verdict.EMAIL, Status.CONVERTED, reclaimed="500.00")]

    assert avoidable_spend(before) == Decimal("500.00")
    assert reclaimed_savings(before) == Decimal("0.00")

    assert avoidable_spend(after) == Decimal("0.00")
    assert reclaimed_savings(after) == Decimal("500.00")
    assert total_spend(after) == Decimal("0.00")


def test_a_held_flagged_meeting_stays_on_the_books_as_spend():
    # "Flagged, but still real spend on the books."
    assert avoidable_spend([EMAIL_HELD]) == Decimal("500.00")
    assert total_spend([EMAIL_HELD]) == Decimal("500.00")
    assert reclaimed_savings([EMAIL_HELD]) == Decimal("0.00")


@pytest.mark.parametrize(
    "derivation", [total_spend, necessary_spend, avoidable_spend, reclaimed_savings]
)
def test_an_empty_ledger_is_zero_not_an_error(derivation):
    assert derivation([]) == Decimal("0.00")


def test_zero_cost_meetings_do_not_upset_the_figures():
    ledger = [meeting("0.00", Verdict.EMAIL, Status.ANALYZED), EMAIL_HELD]

    assert total_spend(ledger) == Decimal("500.00")
    assert avoidable_spend(ledger) == Decimal("500.00")


def test_cents_survive_summation():
    ledger = [
        meeting("0.01", Verdict.KEEP, Status.ANALYZED),
        meeting("0.02", Verdict.KEEP, Status.ANALYZED),
        meeting("12.83", Verdict.KEEP, Status.ANALYZED),
    ]

    assert total_spend(ledger) == Decimal("12.86")


def test_reclaimed_savings_reads_the_field_not_the_cost():
    # Step 10 sets reclaimed_savings = cost, but the derivation must not assume it.
    partial = meeting("600.00", Verdict.EMAIL, Status.CONVERTED, reclaimed="450.00")

    assert reclaimed_savings([partial]) == Decimal("450.00")


def test_reclaimed_savings_ignores_a_stray_value_on_an_unconverted_meeting():
    stray = meeting("600.00", Verdict.EMAIL, Status.HELD, reclaimed="600.00")

    assert reclaimed_savings([stray]) == Decimal("0.00")


# ------------------------------------------------------------- burn-rate buckets


def test_spend_buckets_by_day_oldest_first():
    day1, day2 = JAN, JAN + timedelta(days=2)
    ledger = [
        meeting("100.00", Verdict.KEEP, Status.ANALYZED, created_at=day2),
        meeting("50.00", Verdict.KEEP, Status.ANALYZED, created_at=day1),
        meeting("25.00", Verdict.EMAIL, Status.HELD, created_at=day1),
    ]

    buckets = spend_over_time(ledger, "day")

    assert [(b.period, b.amount) for b in buckets] == [
        (day1.date(), Decimal("75.00")),
        (day2.date(), Decimal("100.00")),
    ]


def test_weekly_buckets_start_on_monday():
    # 2026-01-15 is a Thursday; 2026-01-17 a Saturday. Same week.
    thursday = datetime(2026, 1, 15, tzinfo=timezone.utc)
    saturday = datetime(2026, 1, 17, tzinfo=timezone.utc)
    ledger = [
        meeting("100.00", Verdict.KEEP, Status.ANALYZED, created_at=thursday),
        meeting("100.00", Verdict.KEEP, Status.ANALYZED, created_at=saturday),
    ]

    buckets = spend_over_time(ledger, "week")

    assert len(buckets) == 1
    assert buckets[0].period == datetime(2026, 1, 12, tzinfo=timezone.utc).date()  # Monday
    assert buckets[0].amount == Decimal("200.00")


def test_converted_meetings_do_not_appear_in_the_burn_rate():
    ledger = [EMAIL_CONVERTED, meeting("100.00", Verdict.KEEP, Status.ANALYZED)]

    assert [b.amount for b in spend_over_time(ledger)] == [Decimal("100.00")]


def test_an_empty_ledger_has_no_buckets():
    assert spend_over_time([]) == []


def test_an_unknown_bucket_size_is_rejected():
    with pytest.raises(ValueError, match="day.*week"):
        spend_over_time([], "fortnight")


# ---------------------------------------------------------- budget comparison


def test_over_budget_reports_the_headline_percentage():
    # Doc 1's demo: $8,400 spent against a $6,268.66 budget is ~34% over.
    ledger = [meeting("8400.00", Verdict.KEEP, Status.ANALYZED)]

    result = budget_comparison(ledger, Decimal("6268.66"), now=JAN)

    assert result.month_spend == Decimal("8400.00")
    assert result.is_over_budget is True
    assert result.difference == Decimal("2131.34")
    assert round(result.percent_over) == 34


def test_under_budget_reports_a_negative_difference():
    ledger = [meeting("400.00", Verdict.KEEP, Status.ANALYZED)]

    result = budget_comparison(ledger, Decimal("1000.00"), now=JAN)

    assert result.is_over_budget is False
    assert result.difference == Decimal("-600.00")
    assert round(result.percent_over) == -60


def test_only_the_current_month_counts_toward_the_budget():
    ledger = [
        meeting("100.00", Verdict.KEEP, Status.ANALYZED, created_at=JAN),
        meeting("999.00", Verdict.KEEP, Status.ANALYZED, created_at=JAN - timedelta(days=40)),
        meeting("888.00", Verdict.KEEP, Status.ANALYZED, created_at=JAN + timedelta(days=40)),
    ]

    assert budget_comparison(ledger, Decimal("500.00"), now=JAN).month_spend == Decimal("100.00")


def test_converting_a_meeting_pulls_the_month_back_under_budget():
    # The demo beat: convert the worst offender, watch the headline move.
    over = [meeting("1200.00", Verdict.EMAIL, Status.HELD)]
    converted = [meeting("1200.00", Verdict.EMAIL, Status.CONVERTED, reclaimed="1200.00")]

    assert budget_comparison(over, Decimal("1000.00"), now=JAN).is_over_budget is True
    assert budget_comparison(converted, Decimal("1000.00"), now=JAN).is_over_budget is False


def test_no_budget_set_reports_spend_without_a_percentage():
    ledger = [meeting("400.00", Verdict.KEEP, Status.ANALYZED)]

    result = budget_comparison(ledger, None, now=JAN)

    assert result.monthly_amount is None
    assert result.month_spend == Decimal("400.00")
    assert result.difference is None
    assert result.percent_over is None
    assert result.is_over_budget is False


def test_a_zero_budget_reports_dollars_rather_than_dividing_by_zero():
    ledger = [meeting("400.00", Verdict.KEEP, Status.ANALYZED)]

    result = budget_comparison(ledger, Decimal("0"), now=JAN)

    assert result.percent_over is None
    assert result.difference == Decimal("400.00")
    assert result.is_over_budget is True


def test_an_empty_month_is_not_over_budget():
    result = budget_comparison([], Decimal("1000.00"), now=JAN)

    assert result.month_spend == Decimal("0.00")
    assert result.is_over_budget is False
    assert round(result.percent_over) == -100
