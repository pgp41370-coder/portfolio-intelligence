"""Price moves large enough to distrust: detection, disclosure, and never adjustment.

The point of this feature is what it refuses to do. It must flag a move that looks like a
corporate action, say exactly which figures become unreliable, and leave every number alone.
A test therefore checks that the reported return is *still wrong* in the presence of a split,
because silently correcting it would need data the application does not have.
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.performance.corporate_actions import (
    DEFAULT_THRESHOLD,
    detect_anomalies,
    describe,
)
from test_performance_api import MakeClient, SessionFactory, seed  # noqa: F401
from test_transaction_performance import add_transactions, buy  # noqa: F401
from test_valuation_api import add_listing, add_price, create_portfolio, make_client  # noqa: F401

MON, TUE, WED, THU, FRI = (date(2026, 9, day) for day in (14, 15, 16, 17, 18))
WEDNESDAY_EVENING = datetime(2026, 9, 16, 13, 0, tzinfo=UTC)
FRIDAY_EVENING = datetime(2026, 9, 18, 13, 0, tzinfo=UTC)
NSE = "NSE"


def series(*prices: str, start: date = MON) -> dict[date, Decimal]:
    days = [MON, TUE, WED, THU, FRI]
    return {day: Decimal(value) for day, value in zip(days, prices, strict=False)}


def get(client: TestClient, portfolio_id: str, view: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/api/v1/portfolios/{portfolio_id}/{view}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# --- The detector ---------------------------------------------------------------------------


def test_a_halving_is_flagged_and_named() -> None:
    found = detect_anomalies({("RELIANCE", NSE): series("1200", "600")})

    assert len(found) == 1
    anomaly = found[0]
    assert anomaly.change == Decimal("-0.5")
    assert anomaly.consistent_with == "a 1-for-2 split, or a 1:1 bonus issue"
    assert "fell 50.00%" in describe(anomaly)
    assert "1-for-2 split" in describe(anomaly)


def test_an_ordinary_fall_is_not_flagged() -> None:
    assert detect_anomalies({("TCS", NSE): series("3000", "2900", "2750")}) == []


def test_a_large_move_that_matches_no_ratio_is_flagged_without_a_hypothesis() -> None:
    """A 40% fall is worth distrusting but is not the arithmetic of a common action."""
    found = detect_anomalies({("SMALLCO", NSE): series("100", "60")})

    assert len(found) == 1
    assert found[0].consistent_with is None
    assert "would produce" not in describe(found[0])


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        ("1200", "600", "a 1-for-2 split, or a 1:1 bonus issue"),
        ("900", "300", "a 1-for-3 split, or a 2:1 bonus issue"),
        ("800", "200", "a 1-for-4 split, or a 3:1 bonus issue"),
        ("500", "100", "a 1-for-5 split"),
        ("1000", "100", "a 1-for-10 split"),
        ("900", "600", "a 1:2 bonus issue"),
        ("600", "1200", "a 2-for-1 consolidation"),
        ("100", "1000", "a 10-for-1 consolidation"),
    ],
)
def test_common_corporate_action_ratios_are_recognised(before: str, after: str, expected: str) -> None:
    found = detect_anomalies({("X", NSE): series(before, after)})

    assert found and found[0].consistent_with == expected


def test_a_ratio_slightly_off_is_still_recognised_but_a_distant_one_is_not() -> None:
    """Prices move on the day of an action too, so the match has a tolerance - a small one."""
    near = detect_anomalies({("X", NSE): series("1000", "505")})  # 1% off a halving
    far = detect_anomalies({("X", NSE): series("1000", "560")})  # 12% off

    assert near[0].consistent_with == "a 1-for-2 split, or a 1:1 bonus issue"
    assert far[0].consistent_with is None


def test_exactly_at_the_threshold_is_flagged() -> None:
    boundary = Decimal(1) - DEFAULT_THRESHOLD  # a fall of exactly the threshold
    found = detect_anomalies({("X", NSE): {MON: Decimal(100), TUE: Decimal(100) * boundary}})

    assert len(found) == 1


def test_just_inside_the_threshold_is_not_flagged() -> None:
    found = detect_anomalies({("X", NSE): {MON: Decimal(100), TUE: Decimal("65.1")}})  # -34.9%

    assert found == []


def test_several_moves_are_ordered_by_size() -> None:
    found = detect_anomalies({
        ("SMALL", NSE): series("100", "60"),  # -40%
        ("BIG", NSE): series("100", "10"),  # -90%
        ("MID", NSE): series("100", "50"),  # -50%
    })

    assert [item.symbol for item in found] == ["BIG", "MID", "SMALL"]


def test_only_the_requested_window_is_scanned() -> None:
    prices = {MON: Decimal(1200), TUE: Decimal(600), WED: Decimal(610), THU: Decimal(620)}

    inside = detect_anomalies({("X", NSE): prices}, window=[MON, TUE, WED, THU])
    outside = detect_anomalies({("X", NSE): prices}, window=[WED, THU])

    assert len(inside) == 1
    assert outside == [], "a move before the window is not this window's problem"


def test_a_non_positive_previous_close_is_skipped_not_divided_by() -> None:
    assert detect_anomalies({("X", NSE): {MON: Decimal(0), TUE: Decimal(100)}}) == []


def test_an_empty_series_detects_nothing() -> None:
    assert detect_anomalies({}) == []
    assert detect_anomalies({("X", NSE): {}}) == []


# --- Through the API ------------------------------------------------------------------------------


def test_a_split_shaped_move_is_disclosed_on_the_performance_response(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1200", "1210", "600", "610", "620"))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))

    body = get(client, portfolio_id, "performance")

    anomalies = body["price_anomalies"]
    assert anomalies["detected"] == 1
    assert anomalies["threshold_pct"] == "35.00"
    row = anomalies["anomalies"][0]
    assert row["symbol"] == "RELIANCE"
    assert row["previous_date"] == "2026-09-15" and row["trade_date"] == "2026-09-16"
    assert row["previous_close"] == "1210.00" and row["close"] == "600.00"
    assert row["change_pct"] == "-50.41"
    assert row["consistent_with"] == "a 1-for-2 split, or a 1:1 bonus issue"
    assert "corporate-action data" in anomalies["note"]


def test_the_figures_are_left_wrong_rather_than_silently_corrected(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """The heart of the feature: disclosure, not adjustment.

    A 1-for-2 split shows as a 50% loss. Correcting it needs the ratio and effective date from a
    corporate-action feed; guessing them would rewrite the user's history. So the return stays as
    measured and the response says loudly why it may be wrong.
    """
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1000", "500"))
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))

    body = get(client, portfolio_id, "performance")

    assert body["summary"]["cumulative_return_pct"] == "-50.00", "the number is not adjusted"
    assert body["price_anomalies"]["detected"] == 1
    assert body["price_anomalies"]["anomalies"][0]["consistent_with"] is not None


def test_a_clean_history_reports_no_anomalies(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1000", "1050", "1010", "1080", "1100"))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))

    anomalies = get(client, portfolio_id, "performance")["price_anomalies"]

    assert anomalies["detected"] == 0
    assert anomalies["anomalies"] == [] and anomalies["note"] is None


def test_the_transaction_basis_discloses_them_too(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1200", "1210", "600"))
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))
    add_transactions(client, portfolio_id, buy("RELIANCE", MON, 10, "1200"))

    body = get(client, portfolio_id, "performance")

    assert body["basis"] == "TRANSACTIONS"
    assert body["price_anomalies"]["detected"] == 1


def test_the_intelligence_layer_leads_with_the_anomaly(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1200", "1210", "600", "610", "620"))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))

    body = get(client, portfolio_id, "intelligence")

    quality = body["data_quality"]
    assert quality["price_anomalies"]["detected"] == 1
    assert any("corporate-action data" in item for item in quality["limitations"])
    assert any("RELIANCE fell" in item for item in quality["limitations"])
    # An explanation resting on a suspect price is never reported as fully available.
    assert body["status"] == "limited"
    assert any("RELIANCE fell" in finding for finding in body["findings"])


def test_a_clean_portfolio_is_not_qualified_by_this_check(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1000", "1050", "1010", "1080", "1100"))
    client = make_client(now=FRIDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))

    body = get(client, portfolio_id, "intelligence")

    assert body["data_quality"]["price_anomalies"]["detected"] == 0
    assert not any("corporate-action" in item for item in body["data_quality"]["limitations"])


def test_the_disclosure_never_asserts_that_an_action_happened(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """It reports arithmetic and names the limit of its knowledge; it does not conclude."""
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1200", "600"))
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))

    body = get(client, portfolio_id, "intelligence")
    text = " ".join([*body["findings"], body["data_quality"]["price_anomalies"]["note"] or ""]).lower()

    for phrase in ("a split occurred", "was split", "has been adjusted", "we adjusted", "corrected"):
        assert phrase not in text
    assert "cannot tell" in text and "would produce" in text


def test_detection_adds_no_query_and_no_valuation_pass(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    """It reads the closes the valuation already loaded."""
    import app.performance.ledger_analysis as ledger_analysis

    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("1200", "600", "610"))
    client = make_client(now=WEDNESDAY_EVENING)
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "1000"))

    calls = {"count": 0}
    original = ledger_analysis.value_holdings

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls["count"] += 1
        return original(*args, **kwargs)

    ledger_analysis.value_holdings = counted
    try:
        body = get(client, portfolio_id, "performance")
    finally:
        ledger_analysis.value_holdings = original

    assert body["price_anomalies"]["detected"] == 1
    assert calls["count"] == 1, "one valuation pass, as before"


# --- Ratio-triggered detection below the generic threshold ---------------------------------


def test_a_bonus_issue_below_the_generic_threshold_is_still_caught() -> None:
    """A 1:2 bonus issue moves the price by a third: under 35%, and still a corporate action."""
    found = detect_anomalies({("X", NSE): series("900", "600")})  # -33.33%

    assert len(found) == 1
    assert found[0].trigger == "corporate_action_ratio"
    assert found[0].consistent_with == "a 1:2 bonus issue"


def test_a_one_in_three_bonus_issue_is_caught() -> None:
    found = detect_anomalies({("X", NSE): series("800", "600")})  # -25%, a 0.75 multiplier

    assert len(found) == 1 and found[0].consistent_with == "a 1:3 bonus issue"


def test_a_large_arbitrary_move_is_triggered_by_size_not_by_ratio() -> None:
    found = detect_anomalies({("X", NSE): series("100", "60")})  # -40%, matches no ratio

    assert found[0].trigger == "large_move" and found[0].consistent_with is None


def test_an_ordinary_move_that_happens_to_match_a_ratio_is_ignored() -> None:
    """Below the ratio floor, a coincidence is just a coincidence."""
    # A 0.85 multiplier is not near any listed ratio; a 19% fall is below the floor anyway.
    assert detect_anomalies({("X", NSE): series("100", "81")}) == []


def test_the_ratio_floor_is_applied_exactly() -> None:
    at_floor = detect_anomalies({("X", NSE): {MON: Decimal(100), TUE: Decimal(80)}})  # -20%, 0.8
    assert at_floor == [], "0.8 is not a listed corporate-action ratio"

    ratio_at_floor = detect_anomalies({("X", NSE): {MON: Decimal(100), TUE: Decimal(75)}})  # 0.75
    assert len(ratio_at_floor) == 1 and ratio_at_floor[0].trigger == "corporate_action_ratio"


def test_the_trigger_reaches_the_api(
    make_client: MakeClient, db_session_factory: SessionFactory
) -> None:
    seed(db_session_factory, "S1", "Reliance", "RELIANCE", series("900", "600"))
    client = make_client(now=datetime(2026, 9, 15, 13, 0, tzinfo=UTC))
    portfolio_id = create_portfolio(client, ("NSE", "RELIANCE", 10, "900"))

    anomalies = get(client, portfolio_id, "performance")["price_anomalies"]

    assert anomalies["detected"] == 1
    row = anomalies["anomalies"][0]
    assert row["trigger"] == "corporate_action_ratio"
    assert row["change_pct"] == "-33.33"
