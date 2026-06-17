# Enterprise Forecasting Upgrade

This adds a forecasting suite to the Excel report produced by
`GET /api/v1/export/full-report.xlsx`. The workbook now opens with an
**Executive Dashboard** followed by nine forecasting sheets, then all the
existing operational sheets.

## What was added

| Sheet | Contents |
|-------|----------|
| Executive Dashboard | Forward KPIs (revenue, deliveries, TLB), current-state metrics, top growing / declining products |
| Revenue Forecast | 6-month revenue forecast with 95% confidence band + recent actual-vs-fit |
| Forecast Accuracy | Out-of-sample backtest (MAPE / RMSE / MAE / Bias) per series, with a plain-language rating |
| Revenue Risk | Worst / Expected / Best totals + editable manual shock scenarios |
| Product Forecasting | Per-product demand, growth, confidence and recommended stock |
| Inventory Planning | Safety stock, reorder point and suggested purchase qty (live formulas) |
| ABC Analysis | Pareto classification of products by revenue (A/B/C) |
| Customer Forecasting | Projected revenue for top customers |
| Delivery Forecasting | Projected deliveries, fuel usage and fleet utilisation |

## The engine — `backend/exports/forecasting.py` (new, stdlib-only)

A "smart" forecaster that follows the spec's method ladder by data length
(linear+rolling < 6 mo, Holt 6–11, Holt-Winters additive 12–23,
multiplicative 24+) and returns point forecasts, 95% intervals, in-sample fit,
an accuracy backtest, a confidence rating and an implied growth rate.
Smoothing parameters are chosen per-series by a small grid search.

### Improvements beyond the spec

- **Validation-based model selection.** The length ladder decides which methods
  are *eligible*; the engine then picks the one that actually validates best on
  a held-out tail (ties favour the richer seasonal model). This stops it from
  committing to a seasonal model the data doesn't support.
- **Damped trend + runaway cap + intermittent-demand guard.** Prevents the
  multiplicative model from compounding into implausible numbers on sparse or
  intermittent series (e.g. per-customer monthly revenue), which previously
  produced multi-million-rand blow-ups.
- **Partial-month hygiene.** The current, still-incomplete calendar month is
  excluded from forecast inputs (it was dragging every trend down and inflating
  error); operational sheets still show it.
- **Correct aggregate confidence band.** Multi-month worst/best totals add
  variances instead of summing floored monthly bounds, so the "worst case" is
  realistic rather than near-zero.
- **Consistent reporting.** Every sheet names the same method and accuracy for a
  given series.

## Planning layer uses live Excel formulas

Safety stock, reorder points, purchase quantities, fuel cost, fleet
utilisation, ABC cumulative %, and the risk shock scenarios are **live Excel
formulas** that reference editable blue-on-yellow assumption cells, so a planner
can change a driver (lead time, service level, km/delivery, diesel price, …) and
watch the numbers update.

Because the data model has no on-hand stock, delivery distance or fuel fields,
those drivers are exposed as clearly-labelled editable assumptions (sensible
defaults) rather than invented.

## Other fix

Corrected a pre-existing latent bug where a "= Stable" trend label was parsed by
Excel as a formula (producing a `#NAME?` error); it is now "→ Stable".

## Notes

- No new dependencies — the engine is pure Python (stdlib only).
- Verified with LibreOffice recalculation: **0 formula errors across 214 formulas.**
