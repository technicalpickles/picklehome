# Redeploying Woodpecker without losing events

For any `just deploy-woodpecker`: a secret rotation, an image bump, a config change.
Woodpecker is the CI for the repos that use it, and a restart drops things on the
floor in ways that are easy to miss.

## What a restart does

The server and the agent share the Tailscale sidecar's network (`network_mode:
service:ts-woodpecker`), so the deploy recreates all three together.

| Effect | Why it matters |
|---|---|
| Pipelines in flight die | They show as failed or errored, not as "interrupted" |
| Webhooks arriving during the gap fail | GitHub does not retry them, so a push or PR event in that window never reaches Woodpecker |
| The Funnel URL is briefly unreachable | The Funnel is how GitHub's webhooks get in at all |
| Anything waiting on a pipeline stalls | For example a PR with auto-merge, which waits for a check that never starts |

The gap is usually under a minute, longer if the deploy has to pull images.

## Before

You can deploy at any time, but a quiet moment means there is less to recover.

1. Look for running work. On picklelab, the agent logs show workflow lines while
   something runs: `ssh picklelab 'docker logs --since 30m woodpecker-woodpecker-agent-1'`.
   Nothing after its startup line means idle.
2. Look for pending checks on open PRs in repos that use Woodpecker:
   `gh pr list -R <owner>/<repo> --json number,statusCheckRollup`.
3. If something is running and you can wait, wait. If it is not worth waiting, go
   ahead and use the recovery steps below.

## After

1. **Stack health.** `just woodpecker-status`. All three containers should end up
   healthy, though the server and agent report `health: starting` for a short while.
2. **Tailnet and Funnel.** On picklelab, `docker exec woodpecker-ts-woodpecker-1
   tailscale status --self` should show the node online with `tag:ci`, and
   `tailscale funnel status` should show the Funnel on.
3. **Find webhooks that failed in the gap.** For each repo that uses Woodpecker,
   list the deliveries and pick out the ones that did not return a 2xx:

   ```bash
   gh api repos/<owner>/<repo>/hooks --jq '.[] | select(.config.url | test("woodpecker")) | .id'
   gh api repos/<owner>/<repo>/hooks/<hook-id>/deliveries \
     --jq '.[] | select(.status_code < 200 or .status_code >= 300) | {id, delivered_at, event, status_code}'
   ```

   Redeliver each one inside the window:

   ```bash
   gh api -X POST repos/<owner>/<repo>/hooks/<hook-id>/deliveries/<delivery-id>/attempts
   ```

   The same list is in the repo's Settings, Webhooks, Recent deliveries, with a
   Redeliver button. **Verify** how a timeout shows up in the status code the first
   time you see one.
4. **Restart pipelines the restart killed.** In the Woodpecker UI open the failed
   pipeline and restart it. If the failure was only because of the deploy, nothing
   else needs to change.
5. **Find PRs with no pipeline.** A PR whose checks list has no Woodpecker entry
   missed its webhook: `gh pr checks <number> -R <owner>/<repo>`. Redeliver the
   `pull_request` event, or push an empty commit as the fallback.
6. **Prove a new event works.** Trigger one pipeline from a real push and watch it
   start. This is the check that the whole path (GitHub, Funnel, server, agent)
   works after the restart.

## If a webhook times out outside a deploy

GitHub gives a webhook receiver 10 seconds and does not retry. A slow Woodpecker
(busy server, a cold Funnel path) can miss that window with no restart involved.
The symptom is the same, a PR with no pipeline, and so is the fix: redeliver. If
it keeps happening, the cause is the slow response, not the delivery.
