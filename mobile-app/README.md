# RelayDesk Mobile

Expo React Native mobile client for RelayDesk. This app reuses the existing `api/`
backend and the existing `voice-agent/` phone workflow instead of rebuilding the
voice runtime inside the app.

## Features

- Cognito or local-dev sign-in
- Client-scoped dashboard
- Consumers management
- Campaign trigger and schedule management
- Voice-agent settings
- Knowledge-base upload and document management
- Call history
- Profile management
- Admin tools for client approval, search, and collections

## Environment

Update `app.json` or use Expo config overrides for:

- `apiBaseUrl`
- `cognitoIssuer`
- `cognitoClientId`
- `cognitoScope`
- `authDisableSso`

## Run

1. Start the API so phones on your Wi‑Fi can reach it (from `api/`):

```powershell
uv sync --reinstall-package relaydesk-api
$env:PORT='8090'
uv run python -m app.main
```

2. Start the mobile app (from `mobile-app/`):

```powershell
npm install
npm run start
```

Then open in Expo Go on the same Wi‑Fi network.

`apiBaseUrl` may stay as `http://127.0.0.1:8090` in `app.json`. On a physical device the app automatically rewrites that host to your PC’s LAN IP (the same host Metro uses, e.g. `192.168.1.7`). Web / desktop keep `127.0.0.1`.

If auto-rewrite fails, set `extra.apiBaseUrl` explicitly, for example `http://192.168.1.7:8090`.

The shared `LIVEKIT_SIP_OUTBOUND_TRUNK_ID` is only a fallback. After a user buys a number, campaigns dial from that user's Plivo-backed LiveKit outbound trunk.

Apply the phone-line table once:

```powershell
python infra/scripts/apply_schema.py
```
