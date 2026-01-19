"""Google Ads MCP server - READ-ONLY tools for agentic analysis.

This server exposes Google Ads data for analysis by AI agents.
All tools are read-only - no mutations allowed.

Required environment variables:
  GOOGLE_ADS_DEVELOPER_TOKEN
  GOOGLE_ADS_CLIENT_ID
  GOOGLE_ADS_CLIENT_SECRET
  GOOGLE_ADS_REFRESH_TOKEN
  GOOGLE_ADS_LOGIN_CUSTOMER_ID (optional, defaults to 3766923372)
"""

import asyncio
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP

# Configuration
CUSTOMER_ID = os.getenv("GOOGLE_ADS_CUSTOMER_ID", "2318854468")
LOGIN_CUSTOMER_ID = os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", "3766923372")

# Promo tracking
PROMO_TARGET = 500.0
PROMO_DEADLINE = datetime(2026, 2, 5, tzinfo=UTC)

# Quality geo targets
QUALITY_GEO_IDS = {2840, 2826, 2124, 2036}  # US, UK, CA, AU
COUNTRY_NAMES = {
    2840: "United States",
    2826: "United Kingdom",
    2124: "Canada",
    2036: "Australia",
    2356: "India",
    2608: "Philippines",
    2566: "Nigeria",
    2586: "Pakistan",
    2050: "Bangladesh",
    2704: "Vietnam",
    2360: "Indonesia",
    2076: "Brazil",
    2484: "Mexico",
}

# Create MCP server
mcp = FastMCP(
    name="google-ads-hub",
    instructions="""Read-only Google Ads data for analysis.

Available tools query campaign performance, geo breakdown, and promo progress.
All data is read-only - no campaign mutations possible.

Quality traffic = US, UK, Canada, Australia (geo IDs: 2840, 2826, 2124, 2036).
Low-value traffic = India, SEA countries.
""",
)


def _create_config() -> str:
    """Create temporary google-ads.yaml from env vars."""
    config = f"""developer_token: "{os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN")}"
client_id: "{os.getenv("GOOGLE_ADS_CLIENT_ID")}"
client_secret: "{os.getenv("GOOGLE_ADS_CLIENT_SECRET")}"
refresh_token: "{os.getenv("GOOGLE_ADS_REFRESH_TOKEN")}"
client_customer_id: "{CUSTOMER_ID}"
login-customer-id: "{LOGIN_CUSTOMER_ID}"
use_proto_plus: True
"""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(config)
    return path


def _get_client():
    """Get Google Ads client."""
    from google.ads.googleads.client import GoogleAdsClient

    config_path = _create_config()
    os.environ["GOOGLE_ADS_CONFIGURATION_FILE_PATH"] = config_path
    try:
        return GoogleAdsClient.load_from_storage(config_path)
    finally:
        try:
            os.unlink(config_path)
        except OSError:
            pass


def _query(gaql: str) -> list[Any]:
    """Execute a GAQL query."""
    client = _get_client()
    ga_service = client.get_service("GoogleAdsService")
    response = ga_service.search(customer_id=CUSTOMER_ID, query=gaql)
    return list(response)


@mcp.tool()
def query_campaigns(
    period_days: Annotated[int, "Number of days to look back (7, 14, 30, etc.)"] = 30,
) -> str:
    """Query campaign performance metrics.

    Returns: JSON with campaign name, status, budget, spend, clicks, conversions, CTR, CPC.
    """
    query = f"""
        SELECT
            campaign.id,
            campaign.name,
            campaign.status,
            campaign_budget.amount_micros,
            metrics.impressions,
            metrics.clicks,
            metrics.cost_micros,
            metrics.conversions,
            metrics.ctr,
            metrics.average_cpc
        FROM campaign
        WHERE segments.date DURING LAST_{period_days}_DAYS
    """
    results = _query(query)

    campaigns = []
    for r in results:
        campaigns.append({
            "id": str(r.campaign.id),
            "name": r.campaign.name,
            "status": r.campaign.status.name,
            "daily_budget_usd": r.campaign_budget.amount_micros / 1_000_000,
            "impressions": r.metrics.impressions,
            "clicks": r.metrics.clicks,
            "spend_usd": r.metrics.cost_micros / 1_000_000,
            "conversions": r.metrics.conversions,
            "ctr_pct": r.metrics.ctr * 100,
            "cpc_usd": r.metrics.average_cpc / 1_000_000,
        })

    return json.dumps({
        "period_days": period_days,
        "campaigns": sorted(campaigns, key=lambda x: -x["spend_usd"]),
        "totals": {
            "spend_usd": sum(c["spend_usd"] for c in campaigns),
            "clicks": sum(c["clicks"] for c in campaigns),
            "conversions": sum(c["conversions"] for c in campaigns),
        },
    }, indent=2)


@mcp.tool()
def query_geo_breakdown(
    period_days: Annotated[int, "Number of days to look back"] = 30,
) -> str:
    """Query geographic breakdown of traffic.

    Returns: JSON with clicks/spend by country, quality traffic percentage.
    Quality = US, UK, Canada, Australia.
    """
    query = f"""
        SELECT
            geographic_view.country_criterion_id,
            campaign.name,
            metrics.clicks,
            metrics.cost_micros
        FROM geographic_view
        WHERE segments.date DURING LAST_{period_days}_DAYS
            AND metrics.clicks > 0
        ORDER BY metrics.clicks DESC
        LIMIT 50
    """
    results = _query(query)

    # Aggregate by country
    by_country: dict[int, dict] = {}
    for r in results:
        cid = r.geographic_view.country_criterion_id
        if cid not in by_country:
            by_country[cid] = {
                "country_id": cid,
                "country_name": COUNTRY_NAMES.get(cid, f"Unknown ({cid})"),
                "is_quality": cid in QUALITY_GEO_IDS,
                "clicks": 0,
                "spend_usd": 0,
            }
        by_country[cid]["clicks"] += r.metrics.clicks
        by_country[cid]["spend_usd"] += r.metrics.cost_micros / 1_000_000

    countries = sorted(by_country.values(), key=lambda x: -x["clicks"])

    total_clicks = sum(c["clicks"] for c in countries)
    quality_clicks = sum(c["clicks"] for c in countries if c["is_quality"])
    quality_pct = (quality_clicks / total_clicks * 100) if total_clicks > 0 else 0

    return json.dumps({
        "period_days": period_days,
        "countries": countries[:15],  # Top 15
        "quality_summary": {
            "total_clicks": total_clicks,
            "quality_clicks": quality_clicks,
            "quality_percentage": round(quality_pct, 1),
            "quality_countries": ["United States", "United Kingdom", "Canada", "Australia"],
        },
    }, indent=2)


@mcp.tool()
def get_total_spend() -> str:
    """Get all-time total spend across all campaigns.

    Returns: Total spend in USD (useful for promo tracking).
    """
    query = """
        SELECT metrics.cost_micros
        FROM customer
        WHERE segments.date BETWEEN "2020-01-01" AND "2030-12-31"
    """
    results = _query(query)
    total = sum(r.metrics.cost_micros for r in results) / 1_000_000

    return json.dumps({
        "total_spend_usd": round(total, 2),
        "as_of": datetime.now(UTC).isoformat(),
    }, indent=2)


@mcp.tool()
def get_promo_status() -> str:
    """Get progress toward the $500 promotional credit.

    Promo: Spend $500 by Feb 5, 2026 to get $500 credit.
    Returns: Current spend, target, remaining, days left, daily spend needed.
    """
    # Get total spend
    query = """
        SELECT metrics.cost_micros
        FROM customer
        WHERE segments.date BETWEEN "2020-01-01" AND "2030-12-31"
    """
    results = _query(query)
    spent = sum(r.metrics.cost_micros for r in results) / 1_000_000

    remaining = max(0, PROMO_TARGET - spent)
    progress_pct = min(100, spent / PROMO_TARGET * 100)
    now = datetime.now(UTC)
    days_left = max(0, (PROMO_DEADLINE - now).days)
    daily_needed = remaining / days_left if days_left > 0 else 0

    return json.dumps({
        "spent_usd": round(spent, 2),
        "target_usd": PROMO_TARGET,
        "remaining_usd": round(remaining, 2),
        "progress_pct": round(progress_pct, 1),
        "deadline": PROMO_DEADLINE.strftime("%Y-%m-%d"),
        "days_left": days_left,
        "daily_spend_needed_usd": round(daily_needed, 2),
        "on_track": remaining == 0 or daily_needed < 15,
        "achieved": remaining == 0,
    }, indent=2)


@mcp.tool()
def query_daily_spend(
    days: Annotated[int, "Number of recent days to show"] = 7,
) -> str:
    """Query daily spend breakdown for recent days.

    Useful for spotting trends and anomalies.
    """
    query = f"""
        SELECT
            segments.date,
            metrics.cost_micros,
            metrics.clicks,
            metrics.conversions
        FROM customer
        WHERE segments.date DURING LAST_{days}_DAYS
        ORDER BY segments.date DESC
    """
    results = _query(query)

    daily = []
    for r in results:
        daily.append({
            "date": r.segments.date,
            "spend_usd": r.metrics.cost_micros / 1_000_000,
            "clicks": r.metrics.clicks,
            "conversions": r.metrics.conversions,
        })

    return json.dumps({
        "days": days,
        "daily": daily,
        "avg_daily_spend": sum(d["spend_usd"] for d in daily) / len(daily) if daily else 0,
    }, indent=2)


def main():
    """Run the MCP server on stdio."""
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    # Validate required env vars
    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
    ]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        logging.error(f"Missing required env vars: {missing}")
        sys.exit(1)

    asyncio.run(mcp.run_stdio_async())


if __name__ == "__main__":
    main()
