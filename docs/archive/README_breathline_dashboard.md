README_breathline_dashboard.md
# Synthesizer — Breathline Dashboard Layer (copy/paste kit)

## Files
1) `01_schema_breath_dashboard.sql`
2) `02_load_and_build_2025_2026.sql`
3) `03_migration_bimonthly_anchors.sql` (optional)
4) `README_breathline_dashboard.md`

## Prereqs
- MariaDB 10.2+ (window functions used)
- `LOAD DATA LOCAL INFILE` enabled if you want to load CSVs directly.
  - Otherwise use Python ETL or INSERT batches.

## Run order
1) Run `01_schema_breath_dashboard.sql`
2) Place CSVs next to your DB client (or change paths in SQL):
   - `astro_events_utc_eclipses_plus_vedic_jupiter_saturn_rahu_ketu.csv`
   - `xrp_breath_daily_2025.csv`
3) Run `02_load_and_build_2025_2026.sql`
4) Optional: run `03_migration_bimonthly_anchors.sql` if you move to anchor-based sampling.
