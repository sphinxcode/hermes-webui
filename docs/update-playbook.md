# Update Playbook

This repo is an integration layer around two vendored upstream projects:
- `vendor/hermes-agent` from `https://github.com/NousResearch/hermes-agent.git`
- `vendor/hermes-webui` from `https://github.com/sphinxcode/hermes-webui.git`

Custom control-plane logic lives at repo root under `control_plane/`.

## Operating principles

- Keep custom logic outside `vendor/` whenever possible.
- Keep one canonical Hermes runtime/state boundary.
- Keep Hermes WebUI at `/` and the control plane at `/admin`.
- Prefer boring deployment behavior over clever runtime tricks.
- Treat OAuth-style hosted provider login as advanced/manual unless proven robust.

## Current runtime decisions

Public surface:
- `/` → Hermes WebUI through the wrapper
- `/admin` → control-plane UI/API
- `/health` → wrapper health endpoint for Railway

Shared state:
- `HERMES_HOME=/data/.hermes`
- `HERMES_CONFIG_PATH=/data/.hermes/config.yaml`
- `HERMES_WEBUI_STATE_DIR=/data/webui`
- `HERMES_WORKSPACE_DIR=/data/workspace`

Process model:
- one public wrapper process
- one internal WebUI process on loopback
- one optional gateway process for Telegram/messaging

Auth model:
- WebUI auth remains native to WebUI (`HERMES_WEBUI_PASSWORD`)
- admin auth is separate (`HERMES_ADMIN_PASSWORD`)
- no shared SSO in the first pass

Gateway policy:
- `HERMES_GATEWAY_AUTOSTART=auto` by default
- autostart only when both provider + channel config are present
- manual start/stop/restart remains available in `/admin`

## Version pinning policy

This repo should avoid “latest” semantics in operator-facing docs and release handling.

Pinning model:
- vendor imports are the pinned source of truth
- image builds should reflect the exact vendored contents in git
- update notes should mention the vendored upstream commit or release being adopted

Practical rule:
- treat each subtree update as an explicit version bump
- document what changed before redeploying

## Bootstrap / re-import commands

Fresh clone import commands:

```bash
git remote add hermes-agent-upstream https://github.com/NousResearch/hermes-agent.git
git remote add hermes-webui-upstream https://github.com/sphinxcode/hermes-webui.git

git fetch hermes-agent-upstream main
git fetch hermes-webui-upstream master

git subtree add --prefix=vendor/hermes-agent hermes-agent-upstream main --squash
git subtree add --prefix=vendor/hermes-webui hermes-webui-upstream master --squash
```

## Normal refresh workflow

1. Confirm the working tree is clean.
2. Run:

```bash
./scripts/sync-upstreams.sh
```

3. Inspect changes:

```bash
git diff --stat
```

4. Run:

```bash
./scripts/smoke.sh
```

5. If smoke passes, redeploy Railway.
6. If any vendored edit was required, record it in `docs/vendor-patches.md`.

## Deployment contract

Railway requirements:
- one persistent volume mounted at `/data`
- public health check path `/health`
- wrapper process launched via `/app/start.sh`

Required secrets before public exposure:
- `HERMES_WEBUI_PASSWORD`
- `HERMES_ADMIN_PASSWORD` (recommended, otherwise wrapper falls back to WebUI password)

Optional secrets/config:
- provider API keys
- messaging channel credentials

## Smoke validation checklist

`./scripts/smoke.sh` is the deployment gate.

It should verify:
- image builds successfully
- wrapper binds to the injected Railway `PORT`
- `/health` responds through the wrapper
- `/` remains the WebUI surface
- `/admin/login` is reachable
- `/admin` requires admin auth
- WebUI auth still protects the user-facing app when passworded
- config paths resolve to `/data/.hermes` and `/data/webui`
- state survives restart with the same `/data` volume
- gateway manual control endpoints work once authenticated
- autostart policy behaves predictably when provider + channel config are present

If Docker is unavailable locally, treat smoke as blocked and do not claim the deployment is fully verified.

## Migration steps

From the old WebUI-first topology to the control-plane topology:

1. Keep the existing `/data` volume.
2. Deploy the wrapper-enabled image.
3. Verify `/health` first.
4. Verify `/` still reaches WebUI.
5. Verify `/admin` login works.
6. Verify the shared Hermes config and `.env` are still read from `/data/.hermes`.
7. Verify WebUI state resolves under `/data/webui`.
8. Verify gateway status and manual lifecycle controls from `/admin`.
9. Verify Telegram/WebUI still behave as one shared agent identity.

## Rollback plan

If the wrapper introduces instability:

1. Revert `Dockerfile`, `start.sh`, and `railway.toml` to the previous direct-WebUI topology.
2. Remove wrapper-specific files from the image build.
3. Redeploy against the same `/data` volume.
4. Re-validate:
   - `/health`
   - WebUI login
   - state persistence
   - gateway optional boot path

The shared `/data` contract is intentionally kept stable so rollback does not require state migration.

## Vendor patch policy

Preferred state:
- no vendored changes

If unavoidable:
- patch the smallest possible vendor surface
- log the patch in `docs/vendor-patches.md`
- include reason, scope, and upstream status
- revisit removal on the next upstream sync
