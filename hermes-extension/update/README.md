# Hermes daily auto-update (Kiri OS)

Runtime mirror of the Hermes self-update that runs on the dev box. The live
copies are `~/.hermes/scripts/hermes-update.sh` and the systemd user units
`~/.config/systemd/user/hermes-update.{service,timer}`; this directory keeps
them version-controlled (working agreement: mirror durable `~/.hermes` changes
into the repo). Mirrors the sibling `hermes-extension/mempalace/` update setup.

## What it does
`hermes-update.sh apply` (run daily by `hermes-update.timer`) fetches
`upstream/main`, and if it merges cleanly into `kiri-customizations` it records
status to `~/.hermes/update_status.json` (the dashboard UpdateBanner polls it).
Restart is **not** automatic — the user clicks "Restart" in the dashboard so
Kiri can run a drainage check first. On merge conflict it aborts and flags for a
manual merge.

## Kiri customization — base-image freshness
After a **clean** merge it also does a best-effort
`git push origin kiri-customizations`. That push triggers the `hermes-agent`
`build-base-image.yml` workflow, which rebuilds the private base image
`ghcr.io/dakotasb/hermes-agent:prod` consumed by the kiri-os Fly backend.

This refreshes the base **image** only — it does **not** redeploy production.
Prod redeploys are a deliberate `kiri-os` push (or manual `workflow_dispatch`),
so nightly upstream merges never reach prod on their own.
