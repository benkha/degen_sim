# degen_sim

This repo is for running Monte Carlo simulations to measure accuracy in picking winning bets.

Results are published as a website: https://benkha.github.io/degen_sim/

## Generate the Report

Run the following command

```shell
uv run jupyter nbconvert --to HTML --execute notebooks/degen_sim.ipynb --output-dir=reports/ --output="degen_sim_20251007"
```

## Update the Website

After generating a new weekly report, rebuild `data.json` (parsed from `reports/*.md`) so the site picks up the new week:

```shell
uv run python scripts/build_site_data.py
```

Commit the new report, along with the regenerated `data.json`. The site itself (`index.html`) reads `data.json` directly — no build step needed. It's served via GitHub Pages from the `main` branch root.

## Reports

- [20251007](reports/degen_sim_20251007.md)
- [20251014](reports/degen_sim_20251014.md)
- [20251021](reports/degen_sim_20251021.md)
- [20251028](reports/degen_sim_20251028.md)
- [20251104](reports/degen_sim_20251104.md)
- [20251111](reports/degen_sim_20251111.md)
- [20251118](reports/degen_sim_20251118.md)
- [20251125](reports/degen_sim_20251125.md)
- [20251202](reports/degen_sim_20251202.md)
- [20251209](reports/degen_sim_20251209.md)
- [20251216](reports/degen_sim_20251216.md)
