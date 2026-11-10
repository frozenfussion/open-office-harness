# QUICK GUIDE

1. Set up the Harness databases and sign-in secret.

   Type this in your harness terminal, in the plain shell (Claude runs this while Aziz watches). No password is needed.
   This creates the databases and saves private test settings; existing credentials are kept.

   ```bash
   cd ~/projects/worktrees/stage-2-part-b
   bash install/66-harness-api-setup.sh
   ```

   Good result: `DONE`. The test settings are in `~/.config/ooh/harness-api-test.env`, mode 600. Never paste or print that file.

## Setup messages

| STOP message | What to do |
|---|---|
| invalid deployment value | Correct the named setting in deploy/values/do.env. |
| missing tool | Finish server setup. |
| platform/apps namespace missing | Finish platform deployment. |
| PostgreSQL is not Ready / database resources are not ready | Inspect PostgreSQL and DatabaseRole readiness, then run setup again. |
| existing secret has unexpected credentials / unexpected password format | Have the maintainer inspect the Secret privately; do not replace it. |
| PostgreSQL service has no valid ClusterIP | Inspect the ooh-pg-rw Service. |
| could not read Harness client secret | Inspect Keycloak readiness and bootstrap access, then retry. |
| Harness client secret changed | Ask the maintainer before replacing harness-api-oidc. |
| database setup failed | Inspect PostgreSQL readiness and retry. |
| usage | Run the script without arguments. |
