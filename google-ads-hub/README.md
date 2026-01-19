# Google Ads Hub

Read-only MCP server for Google Ads data.

## Tools

- `query_campaigns(period_days)` - Campaign performance metrics
- `query_geo_breakdown(period_days)` - Geographic traffic breakdown
- `get_total_spend()` - All-time spend
- `get_promo_status()` - Progress toward promotional credit
- `query_daily_spend(days)` - Daily spend breakdown

All tools are **read-only** - no mutations allowed.

## Environment Variables

```bash
GOOGLE_ADS_DEVELOPER_TOKEN=...
GOOGLE_ADS_CLIENT_ID=...
GOOGLE_ADS_CLIENT_SECRET=...
GOOGLE_ADS_REFRESH_TOKEN=...
GOOGLE_ADS_LOGIN_CUSTOMER_ID=3766923372  # Optional, MCC account
GOOGLE_ADS_CUSTOMER_ID=2318854468        # Optional, ad account
```

## Usage

```bash
uv run google-ads-hub
```
