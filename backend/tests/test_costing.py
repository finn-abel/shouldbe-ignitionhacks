"""Cost math tests. Pure — no DB, no network, no app."""

from decimal import Decimal

import pytest

from app.enums import Tier
from app.services.costing import (
    DEFAULT_TIER_RATES,
    OCCURRENCES_PER_YEAR,
    annualized_cost,
    meeting_cost,
)


# --------------------------------------------------------------------------- cost


def test_multi_tier_hour_hits_an_exact_figure():
    # IT-02 + IT-03 + IT-04 + EX-03/DG federal references, for one hour.
    cost = meeting_cost([Tier.IC, Tier.SENIOR, Tier.MANAGER, Tier.EXEC], 60)

    assert cost == Decimal("270.29")


def test_one_hour_ten_people_costs_hundreds():
    # Framing case: six ICs, two seniors, a manager and an exec for an hour.
    attendees = [Tier.IC] * 6 + [Tier.SENIOR] * 2 + [Tier.MANAGER, Tier.EXEC]

    cost = meeting_cost(attendees, 60)

    assert cost == Decimal("573.36")


def test_half_hour_bills_half_the_hourly_total():
    cost = meeting_cost([Tier.IC, Tier.SENIOR, Tier.MANAGER], 30)

    assert cost == Decimal("87.01")


def test_zero_attendees_costs_nothing():
    assert meeting_cost([], 60) == Decimal("0.00")


def test_zero_attendees_costs_nothing_even_for_a_long_meeting():
    assert meeting_cost([], 480) == Decimal("0.00")


def test_single_attendee_is_just_that_tier_rate():
    assert meeting_cost([Tier.EXEC], 60) == Decimal("96.27")


def test_zero_duration_costs_nothing():
    assert meeting_cost([Tier.EXEC] * 10, 0) == Decimal("0.00")


def test_fractional_hour_rounds_to_cents():
    # Senior 58.27/hr for 7 minutes = 6.7981...
    assert meeting_cost([Tier.SENIOR], 7) == Decimal("6.80")


def test_rounding_is_half_up_not_bankers():
    # 100.01/hr for 30 minutes = 50.005 exactly. Half-up gives 50.01; banker's would
    # round to even and give 50.00.
    cost = meeting_cost([Tier.IC], 30, tier_rates={Tier.IC: Decimal("100.01")})

    assert cost == Decimal("50.01")


def test_tier_rates_are_overridable_per_user():
    rates = {Tier.IC: Decimal("90"), Tier.SENIOR: Decimal("200")}

    cost = meeting_cost([Tier.IC, Tier.SENIOR], 60, tier_rates=rates)

    assert cost == Decimal("290.00")
    assert meeting_cost([Tier.IC, Tier.SENIOR], 60) == Decimal("107.23")  # defaults intact


def test_accepts_the_stored_string_form_of_a_tier():
    # Meeting.attendee_tiers persists as JSON strings, so both forms must work.
    assert meeting_cost(["ic", "senior"], 60) == meeting_cost([Tier.IC, Tier.SENIOR], 60)


def test_unknown_tier_is_rejected():
    with pytest.raises(ValueError, match="Unknown role tier"):
        meeting_cost(["intern"], 60)


def test_tier_with_no_configured_rate_is_rejected():
    with pytest.raises(ValueError, match="No hourly rate configured"):
        meeting_cost([Tier.EXEC], 60, tier_rates={Tier.IC: Decimal("75")})


def test_negative_duration_is_rejected():
    with pytest.raises(ValueError, match="must not be negative"):
        meeting_cost([Tier.IC], -30)


def test_returns_one_aggregate_figure_never_a_breakdown():
    # The privacy rule, asserted structurally.
    assert isinstance(meeting_cost([Tier.IC, Tier.EXEC], 60), Decimal)


# --------------------------------------------------------------- annualized cost


def test_non_recurring_meeting_has_no_annualized_cost():
    assert annualized_cost(Decimal("800.00"), is_recurring=False) is None


def test_non_recurring_ignores_a_stray_frequency():
    assert annualized_cost(Decimal("800.00"), False, "WEEKLY") is None


@pytest.mark.parametrize(
    ("freq", "expected"),
    [
        ("DAILY", Decimal("208000.00")),    # 260 workdays
        ("WEEKLY", Decimal("41600.00")),    # 52
        ("BIWEEKLY", Decimal("20800.00")),  # 26
        ("MONTHLY", Decimal("9600.00")),    # 12
        ("YEARLY", Decimal("800.00")),      # 1
    ],
)
def test_each_recurrence_frequency_annualizes(freq, expected):
    assert annualized_cost(Decimal("800.00"), True, freq) == expected


def test_frequency_is_case_and_whitespace_insensitive():
    # .ics RRULEs are uppercase, hand-typed form input may not be.
    assert annualized_cost(Decimal("100"), True, " weekly ") == Decimal("5200.00")


def test_weekly_amount_annualizes_to_fifty_two_occurrences():
    # A recurring weekly amount must annualize through the same 52x rule the UI explains.
    assert annualized_cost(Decimal("800.00"), True, "WEEKLY") == Decimal("41600.00")


def test_zero_cost_meeting_annualizes_to_zero_not_null():
    # Null means "does not recur"; a free recurring meeting is still recurring.
    assert annualized_cost(Decimal("0.00"), True, "WEEKLY") == Decimal("0.00")


def test_annualized_rounds_to_cents():
    assert annualized_cost(Decimal("12.83"), True, "DAILY") == Decimal("3335.80")


def test_recurring_without_a_frequency_is_rejected():
    with pytest.raises(ValueError, match="needs a recurrence_freq"):
        annualized_cost(Decimal("800.00"), True, None)


def test_unreadable_frequency_is_rejected_rather_than_nulled():
    with pytest.raises(ValueError, match="Unknown recurrence frequency"):
        annualized_cost(Decimal("800.00"), True, "FORTNIGHTLY")


# ------------------------------------------------------------- the two composed


def test_cost_then_annualize_for_a_recurring_standup():
    attendees = [Tier.IC] * 8 + [Tier.MANAGER]

    per_occurrence = meeting_cost(attendees, 30)
    yearly = annualized_cost(per_occurrence, True, "WEEKLY")

    assert per_occurrence == Decimal("229.24")
    assert yearly == Decimal("11920.48")


def test_doc_defaults_are_the_documented_rates():
    assert DEFAULT_TIER_RATES == {
        Tier.IC: Decimal("48.96"),
        Tier.SENIOR: Decimal("58.27"),
        Tier.MANAGER: Decimal("66.79"),
        Tier.EXEC: Decimal("96.27"),
    }
    assert set(OCCURRENCES_PER_YEAR) == {"DAILY", "WEEKLY", "BIWEEKLY", "MONTHLY", "YEARLY"}


# ----------------------------------------- a calendar is not only meetings (clamping)


def test_an_all_day_event_bills_a_working_day_not_a_calendar_day():
    # An .ics all-day event reads as 1440 minutes. Costing that literally puts a
    # $21,600 "meeting" on the books for twelve people.
    cost = meeting_cost([Tier.IC] * 12, 1440)

    assert cost == Decimal("4700.16")  # 12 x 48.96 x 8h, not x 24h


def test_a_multi_day_event_bills_a_working_day_too():
    conference = meeting_cost([Tier.IC] * 12, 6240)  # a 5-day conference

    assert conference == Decimal("4700.16")


def test_ordinary_meetings_are_untouched_by_the_cap():
    assert meeting_cost([Tier.IC] * 8 + [Tier.MANAGER], 30) == Decimal("229.24")
    assert meeting_cost([Tier.IC], 480) == Decimal("391.68")  # exactly at the cap


@pytest.mark.parametrize(
    ("minutes", "expected", "clamped"),
    [(30, 30, False), (480, 480, False), (481, 480, True), (1440, 480, True), (6240, 480, True)],
)
def test_billable_minutes_reports_what_is_charged_for(minutes, expected, clamped):
    from app.services.costing import billable_minutes, is_clamped

    assert billable_minutes(minutes) == expected
    assert is_clamped(minutes) is clamped


def test_the_cap_is_configurable(monkeypatch):
    from app.services.costing import billable_minutes

    monkeypatch.setenv("SHOULDBE_MAX_BILLABLE_MINUTES", "120")

    assert billable_minutes(1440) == 120
    assert meeting_cost([Tier.IC], 1440) == Decimal("97.92")


def test_a_nonsense_cap_falls_back_to_the_default(monkeypatch):
    from app.services.costing import DEFAULT_MAX_BILLABLE_MINUTES, billable_minutes

    monkeypatch.setenv("SHOULDBE_MAX_BILLABLE_MINUTES", "not-a-number")

    assert billable_minutes(9999) == DEFAULT_MAX_BILLABLE_MINUTES


def test_the_cap_flows_through_to_the_annualized_figure():
    # A weekly all-day event must not annualize off an uncapped occurrence.
    per_occurrence = meeting_cost([Tier.IC] * 12, 1440)

    assert annualized_cost(per_occurrence, True, "WEEKLY") == Decimal("244408.32")
