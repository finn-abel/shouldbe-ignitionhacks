"""Money-model tests.

The load-bearing suite alongside the cost math: these four figures are the dashboard, and
conflating any two of them is the failure mode these tests prevent. Pure — the functions
take `MeetingRead`, so no database is involved.
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal

import pytest

from app.enums import BudgetScope, Status, Tier, Verdict
from app.schemas.api import MeetingRead
from app.services.money import (
    avoidable_spend,
    budget_guardrail,
    within_period,
    within_budget_scope,
    budget_comparison,
    necessary_spend,
    reclaimed_savings,
    spend_over_time,
    total_spend,
)

JAN = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)

_next_id = iter(range(1, 10_000))


def meeting(
    cost,
    verdict,
    status,
    *,
    reclaimed="0.00",
    created_at=JAN,
    budget_scope_type=BudgetScope.USER,
    budget_scope_name="Personal",
) -> MeetingRead:
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
        budget_scope_type=budget_scope_type,
        budget_scope_name=budget_scope_name,
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
    # The conversion transition, asserted on the derivations that render it.
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
    # Conversion sets reclaimed_savings = cost, but the derivation must not assume it.
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
    assert result.remaining_amount == Decimal("600.00")
    assert round(result.usage_percent) == 40
    assert result.threshold is None


def test_budget_soft_thresholds_are_reported():
    ledger = [meeting("820.00", Verdict.KEEP, Status.ANALYZED)]

    result = budget_comparison(ledger, Decimal("1000.00"), now=JAN)

    assert result.remaining_amount == Decimal("180.00")
    assert round(result.usage_percent) == 82
    assert result.threshold == 80


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
    assert result.usage_percent is None
    assert result.difference == Decimal("400.00")
    assert result.is_over_budget is True


def test_an_empty_month_is_not_over_budget():
    result = budget_comparison([], Decimal("1000.00"), now=JAN)

    assert result.month_spend == Decimal("0.00")
    assert result.remaining_amount == Decimal("1000.00")
    assert result.is_over_budget is False
    assert round(result.percent_over) == -100


def test_budget_scope_filters_team_and_department_spend():
    ledger = [
        meeting("100.00", Verdict.KEEP, Status.ANALYZED),
        meeting(
            "200.00",
            Verdict.KEEP,
            Status.ANALYZED,
            budget_scope_type=BudgetScope.TEAM,
            budget_scope_name="Platform",
        ),
        meeting(
            "300.00",
            Verdict.KEEP,
            Status.ANALYZED,
            budget_scope_type=BudgetScope.DEPARTMENT,
            budget_scope_name="Digital",
        ),
    ]

    assert total_spend(within_budget_scope(ledger, BudgetScope.USER, "Personal")) == Decimal("100.00")
    assert total_spend(within_budget_scope(ledger, BudgetScope.TEAM, "Platform")) == Decimal("200.00")
    assert total_spend(within_budget_scope(ledger, BudgetScope.DEPARTMENT, "Digital")) == Decimal("300.00")


def test_guardrail_warns_before_a_meeting_crosses_the_budget():
    ledger = [
        meeting(
            "900.00",
            Verdict.KEEP,
            Status.ANALYZED,
            budget_scope_type=BudgetScope.TEAM,
            budget_scope_name="Platform",
        )
    ]

    result = budget_guardrail(
        ledger,
        Decimal("1000.00"),
        Decimal("150.00"),
        scope_type=BudgetScope.TEAM,
        scope_name="Platform",
        now=JAN,
    )

    assert result.exceeds_budget is True
    assert result.threshold_crossed == 100
    assert result.projected_spend == Decimal("1050.00")
    assert result.projected_remaining_amount == Decimal("-50.00")
    assert "exceed" in result.warning


# --------------------------------------------------------- the convert transition


def test_converting_reclaims_the_whole_cost():
    from app.services.money import reclaimed_by_converting

    assert reclaimed_by_converting(Decimal("450.00")) == Decimal("450.00")


def test_reclaimed_amount_is_quantised_to_cents():
    from app.services.money import reclaimed_by_converting

    assert reclaimed_by_converting(Decimal("12.834")) == Decimal("12.83")


def test_converting_twice_cannot_inflate_savings():
    # The rule is assignment, not accumulation, so a double click is a no-op.
    from app.services.money import reclaimed_by_converting

    once = reclaimed_by_converting(Decimal("450.00"))
    twice = reclaimed_by_converting(Decimal("450.00"))

    assert once == twice == Decimal("450.00")
    assert reclaimed_savings([
        meeting("450.00", Verdict.EMAIL, Status.CONVERTED, reclaimed=str(twice))
    ]) == Decimal("450.00")


# ------------------------------------------- the calendar the team actually lives in

TORONTO = ZoneInfo("America/Toronto")


def test_this_month_follows_the_team_not_the_server():
    # 9pm on Aug 31 in Toronto is already Sep 1 in UTC. Reporting in UTC rolls the
    # headline over mid-demo and August's spend vanishes.
    evening_of_the_31st = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)
    ledger = [
        meeting("500.00", Verdict.KEEP, Status.ANALYZED,
                created_at=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)),
        meeting("400.00", Verdict.KEEP, Status.ANALYZED, created_at=evening_of_the_31st),
    ]

    result = budget_comparison(ledger, Decimal("1000.00"), now=evening_of_the_31st, tz=TORONTO)

    assert result.month_spend == Decimal("900.00")  # both, because it is still August
    assert result.is_over_budget is False


def test_an_evening_meeting_lands_on_the_day_it_was_held():
    # 7pm and 9pm the same Toronto evening straddle midnight UTC.
    ledger = [
        meeting("100.00", Verdict.KEEP, Status.ANALYZED,
                created_at=datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc)),
        meeting("100.00", Verdict.KEEP, Status.ANALYZED,
                created_at=datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)),
    ]

    buckets = spend_over_time(ledger, "day", tz=TORONTO)

    assert len(buckets) == 1
    assert buckets[0].period == date(2026, 8, 21)
    assert buckets[0].amount == Decimal("200.00")


def test_the_timezone_is_configurable():
    from app.services import money

    evening = datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc)
    ledger = [meeting("400.00", Verdict.KEEP, Status.ANALYZED, created_at=evening)]

    # In UTC that timestamp is September; in Toronto it is still August.
    assert budget_comparison(ledger, Decimal("1000"), now=evening,
                             tz=ZoneInfo("UTC")).month_spend == Decimal("400.00")
    august = budget_comparison(
        ledger, Decimal("1000"), now=datetime(2026, 8, 31, 20, 0, tzinfo=timezone.utc), tz=TORONTO
    )
    assert august.month_spend == Decimal("400.00")
    assert money.business_timezone() is not None


def test_an_unknown_timezone_falls_back_rather_than_crashing(monkeypatch):
    from app.services import money

    monkeypatch.setenv("SHOULDBE_TIMEZONE", "Mars/Olympus_Mons")

    assert money.business_timezone() == ZoneInfo(money.DEFAULT_TIMEZONE)


# ------------------------------------------------------------ period scoping


def test_the_month_period_keeps_only_this_month():
    now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    ledger = [
        meeting("100.00", Verdict.KEEP, Status.ANALYZED, created_at=now),
        meeting("900.00", Verdict.KEEP, Status.ANALYZED,
                created_at=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)),
    ]

    assert total_spend(within_period(ledger, "month", now, TORONTO)) == Decimal("100.00")
    assert total_spend(within_period(ledger, "all", now, TORONTO)) == Decimal("1000.00")


def test_the_month_period_matches_the_budget_headline():
    # The two must never disagree, or the tiles contradict the headline above them.
    now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
    ledger = [
        meeting("100.00", Verdict.KEEP, Status.ANALYZED, created_at=now),
        meeting("900.00", Verdict.EMAIL, Status.HELD,
                created_at=datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)),
    ]

    scoped = total_spend(within_period(ledger, "month", now, TORONTO))
    headline = budget_comparison(ledger, Decimal("500"), now=now, tz=TORONTO).month_spend

    assert scoped == headline == Decimal("100.00")


def test_an_unknown_period_is_rejected():
    with pytest.raises(ValueError, match="month.*all"):
        within_period([], "quarter")
