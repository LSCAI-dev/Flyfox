# SGX Swing Screener

Daily automated stock screener for SGX-listed swing trades, combining
fundamental filters (P/E vs sector, revenue growth, debt/equity,
dividend consistency) with technical entry signals (MA cross, RSI turn,
MACD cross, volume surge), with entry/stop/target at a minimum 2:1
reward-to-risk.

## How the automation works
`.github/workflows/daily-report.yml` runs every weekday morning
(before SGX market open), regenerates `docs/index.html`, and commits
it back to the repo. With GitHub Pages enabled on the `docs/` folder,
that becomes a stable URL you can bookmark and open from your phone.

## One-time setup
1. Create a new **public** GitHub repo (private repos need a paid plan
   for Pages, on some account tiers).
2. Upload these files, preserving the folder structure:
   - `sgx_screener.py`
   - `report_generator.py`
   - `chart_generator.py`
   - `.github/workflows/daily-report.yml`
3. Go to **Settings -> Pages**. Under "Build and deployment", set
   Source = "Deploy from a branch", Branch = `main`, Folder = `/docs`.
   Save.
4. Go to the **Actions** tab, select "Daily SGX Watchlist", click
   "Run workflow" to trigger it manually the first time.
5. Wait ~1-2 minutes, then refresh the Pages URL shown in
   Settings -> Pages (looks like
   `https://<username>.github.io/<repo-name>/`). Bookmark it on your
   phone -- that's your daily report from now on, no local Python
   needed.

## Editing the universe or thresholds
Open `sgx_screener.py` and edit `SGX_UNIVERSE` (the ticker list) or the
parameters near the top (`MIN_RR`, `RSI_OVERSOLD`, etc.), commit the
change, and the next scheduled run will pick it up.
