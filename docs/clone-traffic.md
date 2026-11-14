# Clone traffic archive

The `Archive clone traffic` workflow collects daily clone counts for `Dingent/Dingent` at 03:23 UTC every day (11:23 China Standard Time). It can also be run manually from the Actions tab. GitHub may delay scheduled runs.

## One-time setup

1. Create a fine-grained personal access token under GitHub **Settings → Developer settings → Personal access tokens**. Select the resource owner `Dingent`, grant access only to `Dingent/Dingent`, and set repository permission **Administration: Read-only**. If the organization requires approval, have the token approved first. Set an expiry date and renew it before expiry.
2. Add it under repository **Settings → Secrets and variables → Actions → New repository secret**, named `TRAFFIC_TOKEN`.
3. On the default branch, open **Actions → Archive clone traffic → Run workflow**. Confirm that the `traffic` branch contains `clones.json`, `clones.csv`, `clones.svg`, and `README.md`.

The PAT only reads traffic. The workflow uses its own `GITHUB_TOKEN` with `contents: write` to commit the archive. Never put a token in source files, command history, or issue comments. If branch rules restrict writes to `traffic`, allow this workflow to update that branch.

## Data and limitations

- GitHub's API exposes only the latest 14 days. The first collection can recover that window; older unrecorded data cannot be recovered.
- The archive merges by UTC date and preserves the highest observed clone count and daily unique count for each date. Repeated and overlapping API windows do not add the same day's count twice. Partial boundary days cannot lower an archived count. Downward corrections by GitHub are consequently not applied.
- The badge shows the sum of archived daily clone counts, **not lifetime clones**. The archive README states the first and latest recorded dates. The newest date may still be incomplete; missing dates are unknown, not zero.
- `uniques` is a daily metric. Summing it does **not** give distinct users across the archive period. A clone is also not a download count or a count of human users.
- Collection runs before archive checkout, so this workflow's own checkout of `traffic` cannot be included in that run's initial snapshot. GitHub does not provide attribution to reliably remove CI or other automated clones from the source statistics.
- Scheduled workflows run from the default branch and can be delayed. In public repositories, GitHub may disable them after 60 days without repository activity. Check Actions periodically, enable a disabled workflow if needed, and address token expiry or failed runs before the 14-day window passes.

## Local verification

The merger uses the Python standard library and accepts a saved API response:

```bash
gh api --method GET repos/Dingent/Dingent/traffic/clones -f per=day > /tmp/clones.json
python3 .github/scripts/archive_clones.py --snapshot /tmp/clones.json --output /tmp/dingent-traffic
```

API reference: https://docs.github.com/en/rest/metrics/traffic#get-repository-clones
Schedule reference: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
