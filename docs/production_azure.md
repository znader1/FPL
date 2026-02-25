# Azure Production Runbook (FastAPI + Lovable frontend)

## 1) Target architecture

- **Frontend**: Lovable-hosted website
- **Backend**: this repo (`FastAPI`) on Azure (always-on)
- **Scheduler**: GitHub Action every 6h calling `POST /admin/refresh`

This gives:
- stable URL for Lovable
- auto refresh of FPL cache/snapshots
- no dependency on your local terminal

## 2) Required backend env vars

Set these in Azure app settings:

- `FPL_ENTRY_ID` (your team id)
- `FPL_API_KEY` (public API protection key)
- `FPL_ADMIN_KEY` (admin-only key, different from API key)
- `FPL_API_CORS_ORIGINS` (your Lovable domains, comma-separated)
- `BOOTSTRAP_TTL=300`
- `FIXTURES_TTL=300`
- `FPL_SNAPSHOT_OUT_BASE=data/processed`

## 3) Deploy with Docker

From repo root:

```bash
docker build -t fpl-assistant-api .
docker run -p 8000:8000 --env-file .env fpl-assistant-api
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## 4) GitHub Actions secrets

In GitHub repo settings, add:

- `FPL_API_BASE_URL` (for example `https://your-api.azurewebsites.net`)
- `FPL_ADMIN_KEY` (must match backend setting)
- `AZURE_CREDENTIALS` (service principal JSON for `azure/login`)
- `AZURE_RESOURCE_GROUP`
- `AZURE_LOCATION` (for example `francecentral`)
- `AZURE_CONTAINERAPP_NAME`
- `AZURE_CONTAINERAPP_ENVIRONMENT`
- `AZURE_ACR_NAME` (globally unique, lowercase)
- `FPL_ENTRY_ID` (optional but recommended)
- `FPL_API_KEY` (optional but recommended)
- `FPL_API_CORS_ORIGINS` (optional but recommended)

Then enable workflow:
- `.github/workflows/refresh-backend.yml`
- `.github/workflows/deploy-azure-containerapp.yml`

It runs every 6 hours and calls:
- `POST /admin/refresh`
- `GET /events/next`

## 5) Lovable connection

In Lovable env/config, set:

- `VITE_FPL_TEAM_RECOMMENDATION_URL=https://your-api.azurewebsites.net/recommendations?entry_id={entry_id}&event_id={event_id}&horizon_gws={horizon_gws}&api_key=YOUR_PUBLIC_KEY`

If you want to avoid query `api_key`, pass `X-API-Key` from your frontend proxy layer.

## 6) Useful endpoints for your product

- `GET /health`
- `GET /events/next` (deadline + first fixture time)
- `GET /squad`
- `GET /recommendations`
- `POST /admin/refresh` (admin key required)

## 7) Product defaults to keep UX stable

- Default `event_id` to next GW (already in backend logic)
- Show `notes[]` from API to explain fallback behavior
- Show `position_panels.not_owned` for transfer ideas by position
- Call `/events/next` to render deadline timer in UI
