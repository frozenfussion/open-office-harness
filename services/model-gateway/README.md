# QUICK GUIDE

1. Type this in your harness terminal, in the plain shell. This creates the Gateway databases and private settings. No password is needed.

   ```bash
   cd ~/projects/worktrees/stage-2-part-a
   install/64-model-gateway-setup.sh
   ```

   Good result: `DONE`. The test settings are saved outside this repository in `~/.config/ooh/model-gateway-test.env`, mode 600. Claude may run this in the shell tile while Aziz watches.

Setup keeps existing database passwords and refuses a changed sign-in secret. A `STOP:` message explains which platform resource or setting needs attention; fix that cause and run the script again.
