# Outside-user trial: git-quint-diff `158ec18`

Can a Quint user install the candidate, review an upstream model change, and replay a witness without help from the authors? This is a private source trial, not a release. You don't need to share any of your own models.

## For the participant

Start a timer before checking prerequisites. Use a machine you would normally use to review Quint and a POSIX-compatible shell (for example, Bash or Zsh). The guide as written needs Git 2.43+, Nix 2.30+ (`nix profile add`), and network access. Follow the instructions without maintainer help; stop at the first step you can't complete from the instructions alone. Don't clear your Nix store or change your usual cache settings just for this trial.

1. Check the attached `git-quint-diff-158ec18-source.tar` with `sha256sum` (or `shasum -a 256` on macOS). It should match:

   ```text
   b0bfd6b4799ea38e2e9a108657c5e501d815ee7c41082b3c6a80062813035aa7
   ```

2. From the directory containing the attachment, unpack it into a fresh directory. The independent replay needs a temporary directory path without spaces. If your `TMPDIR` contains spaces, first run `export TMPDIR=/tmp` in this shell.

   ```sh
   trial_dir=$(mktemp -d)
   tar -xf git-quint-diff-158ec18-source.tar -C "$trial_dir"
   cd "$trial_dir/git-quint-diff-158ec18"
   ```

3. Follow **`docs/source-trial.md` inside the archive**. It covers installing via Nix, comparing two upstream commits, and replaying against the original Quint model. Don't clone `git-quint-diff` instead: its public default branch may not contain this candidate. If your Nix does not already enable `nix-command` and `flakes`, add them for this shell only before running the guide:

   ```sh
   export NIX_CONFIG="${NIX_CONFIG-}
   extra-experimental-features = nix-command flakes"
   ```

Reply privately to the person who sent you the archive:

```text
OS / architecture:
Git / Nix versions (or missing):
Nix store before the trial (already used, fresh, or unknown):
Elapsed time from start to first successful replay or blocker:
Outcome: first `Replayed …` line OR the first blocked step, command, exit status (if known), and relevant error:
Any deviations or help:
If you reached the report: what would you tell the model author changed, and what did the report not tell you?
```

Report what you actually saw, not the expected output printed in the guide. Include only the relevant diagnostic, with private paths, tokens, and unrelated data removed. A blocker is a useful result; you don't need to work around it for the trial.

## For the maintainer

Send this file and the exact archive of `158ec18df0242c68995975fde4f06f8361060df5` to one Quint user who did not develop or dry-run the candidate. If rebuilding the attachment, use:

```sh
rev=158ec18df0242c68995975fde4f06f8361060df5
git archive --format=tar --prefix=git-quint-diff-158ec18/ \
  --output=/tmp/git-quint-diff-158ec18-source.tar "$rev"
```

Verify the digest above before sending. Keep the protocol out of the candidate tar; a later commit containing this file is not the tested source. Record the user's elapsed time and either first replay or first blocker, with their permission and without identifying details. A fresh profile is not evidence of a cold store. Another author or collaborator run is not an outside trial.

If they reach replay, the next question is whether they can map a review onto a change in their **own** model. If they are blocked, fix or clarify the first blocker and repeat the source-first trial before expanding scope. Public binaries stay on hold either way.
