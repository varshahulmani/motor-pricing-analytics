# Building the Tableau Public dashboard

Everything comes from the CSVs in `tableau/data/` (written by `src/export_tableau.py` and reconciled by `src/validate.py`). Build time is about an hour. Tableau Public (free desktop app) saves straight to your public profile.

## 1. Connect

Open Tableau Public → **Text file** → `tableau/data/heatmap_age_region.csv`. Then add the other files as separate data sources (Data → New Data Source): `segments.csv`, `lift_chart.csv`, `double_lift.csv`, `lorenz_frequency.csv`, `oneway.csv`, `kpis.csv`. Keep them separate; there is nothing to join.

## 2. Sheet "Loss ratio heatmap" (heatmap_age_region)

1. Columns: `Region`. Rows: `Driv Age Band`; right-click it → Sort → by field `Age Order`, ascending.
2. Calculated field **LR** = `SUM([Losses]) / SUM([Premium])`. Format as percentage, 0 decimals.
3. Marks: Square. Drag **LR** to Color and to Label.
4. Color → Edit Colors → Red-Green Diverging, **Reversed**, tick *Use Full Color Range*, Center = **0.70** (the target loss ratio, so green is profitable and red is losing money).
5. Calculated field **Thin cell** = `SUM([Exposure]) < 200`. Drag to Detail, then to Filter and keep *False*, so noisy cells are blank.
6. Tooltip: Exposure, Claims, Losses, Premium, LR, and `SUM([Claims]) / SUM([Exposure])` as frequency.
7. Title: *Loss ratio by driver age × region (target 70%)*.

## 3. Sheet "Model lift" (lift_chart)

1. Columns: `Decile` (as dimension, discrete). Rows: `Loss Cost`.
2. Color: `Series`. Marks: Line, with markers on (Color → Markers → all).
3. Filter `Series` to *Actual (capped + loading)*, *Model expected cost*, *Tariff risk premium* (leave *Actual (total)* out, or show it as a faint line).
4. Colours: actual = dark grey, model = blue, tariff = orange.
5. Title: *Lift chart (test set): the model separates cheap and expensive risks; the tariff is flatter*.

Optional second view from `double_lift.csv`: Columns `Decile`, Rows `Model Vs Tariff` and `Actual Smoothed Vs Tariff` (dual axis, synchronised), reference line at 1.

## 4. Sheet "Mispriced segments" (segments)

1. Filter: `Credible` = True, `Status` in *under-priced*, *over-priced*.
2. Rows: `Segment`. Columns: `Premium Gap` (SUM). Sort descending.
3. Color: `Status` (under-priced = red, over-priced = blue).
4. Label: `Model Vs Tariff` formatted `0.00"×"`.
5. Tooltip: Policies, Exposure, Claims, Loss Ratio, Actual Vs Tariff, Model Closer On Test.
6. Title: *Mispriced segments: where the model's expected cost and the tariff differ by more than 10%*.

Alternative layout: a text table with `Segment`, `Policies`, `Exposure`, `Model Vs Tariff`, `Loss Ratio`, `Premium Gap`, coloured by `Status`.

## 5. KPI tiles (kpis)

One sheet per number, Marks: Text, large font: Policies, Policy-years, Claims, Loss ratio, **% of policies mispriced** (`Mispriced Policy Share`, percentage). Or one sheet with Measure Names on Columns and Measure Values on Text.

## 6. Dashboard

Size: Automatic (or 1400 × 900). Layout:

```
┌─────────────────────────── KPI tiles ───────────────────────────┐
├──────────────── Loss ratio heatmap (full width) ────────────────┤
├────────── Model lift ─────────┬──────── Mispriced segments ─────┤
└─── note: data, tariff assumption, link to GitHub repo ──────────┘
```

Add a text box stating the tariff assumption: *"The dataset has no premiums. Loss ratios use an assumed 3-factor tariff (bonus-malus, driver age, area; one-way relativities, 70% target loss ratio)."*
Use the heatmap as a filter (Dashboard → Actions → Filter, source heatmap, target segments) if you want click-through.

## 7. Publish

File → Save to Tableau Public. Put the link in the README Results table and on your resume.
