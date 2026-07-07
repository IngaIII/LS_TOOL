"""
Enterprise forecasting workbook sheets.

Builds the upgraded forecasting suite on top of the operational report:
  - Executive Dashboard
  - Revenue Forecast (smart engine + 95% confidence intervals + seasonality)
  - Forecast Accuracy (holdout MAPE / RMSE / MAE / Bias)
  - Revenue Risk (worst / expected / best case)
  - Product Forecasting (demand, growth, confidence, recommended stock)
  - Inventory Planning (safety stock, reorder point, suggested purchase qty)
  - ABC Analysis (Pareto classification)
  - Customer Forecasting (revenue by customer)
  - Delivery Forecasting (deliveries, fuel usage, vehicle utilisation)

Statistical values are produced by `forecasting.smart_forecast` in Python (the
maths cannot be expressed natively in Excel), but every *planning* layer
— safety stock, reorder points, fuel, scenario shocks — is written as live
Excel formulas that reference editable assumption cells, so the workbook stays
dynamic and a planner can change a driver and watch the numbers update.
"""
from collections import defaultdict
from math import sqrt
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from exports.excel import (
    PRIMARY, HEADER2, LIGHT_BLUE, WHITE,
    GREEN_F, GREEN_T, AMBER_F, AMBER_T, RED_F, RED_T, PURPLE_F, PURPLE_T, GRAY_F,
    ZAR_FMT, PCT_FMT, NUM_FMT,
    hdr, section, paint, zar, auto_width, zebra, bold_row,
    MONTH_NAMES, mlabel, add_months, month_range,
)
from exports import forecasting as fc

H = 6                       # forecast horizon (months)
SEASON = 12                 # monthly seasonality
BLUE_INPUT = "0000FF"       # industry convention: hardcoded editable inputs
YELLOW_BG = "FFFF00"        # assumptions needing attention

INPUT_FONT = Font(color=BLUE_INPUT, bold=True)


def _input_cell(ws, row, col, value, fmt=None, note=None):
    """Editable assumption cell: blue text on a yellow background."""
    c = ws.cell(row=row, column=col, value=value)
    c.font = INPUT_FONT
    c.fill = PatternFill("solid", fgColor=YELLOW_BG)
    c.alignment = Alignment(horizontal="center")
    if fmt:
        c.number_format = fmt
    if note:
        from openpyxl.comments import Comment
        c.comment = Comment(note, "Forecast Engine")
    return c


def _title(ws, text, sub=None):
    ws.append([text])
    ws.cell(ws.max_row, 1).font = Font(bold=True, size=15, color=PRIMARY)
    if sub:
        ws.append([sub])
        ws.cell(ws.max_row, 1).font = Font(italic=True, size=9, color="666666")
    ws.append([])


def _series_for_product(ctx, pname, pd):
    """Monthly unit series over the forecast calendar (revenue orders only)."""
    by_month = ctx.get("prod_fc_month", {}).get(pname, pd["by_month"])
    return [by_month.get(k, 0) for k in ctx["months_sorted"]]


def _customer_monthly(orders):
    cm = defaultdict(lambda: defaultdict(float))
    for o in orders:
        cm[o.customer.name][o.order_date.strftime("%Y-%m")] += o.total_zar
    return cm


def _delivery_monthly(deliveries):
    dm = defaultdict(lambda: {"n": 0})
    for d in deliveries:
        dm[d.scheduled_date.strftime("%Y-%m")]["n"] += 1
    return dm


def _conf_fill(conf):
    return {"HIGH": (GREEN_F, GREEN_T), "MEDIUM": (AMBER_F, AMBER_T)}.get(conf, (RED_F, RED_T))


def _future_labels(ly, lm, n):
    return [mlabel(*add_months(ly, lm, i + 1)) for i in range(n)]


# ════════════════════════════════════════════════════════════════════════════
# Revenue Forecast
# ════════════════════════════════════════════════════════════════════════════
def build_revenue_forecast(wb, ctx):
    ms = ctx["months_sorted"]
    monthly = ctx["monthly"]
    rev = ctx["rev_series"]
    ly, lm = ctx["ly"], ctx["lm"]
    ws = wb.create_sheet("Revenue Forecast")

    r = fc.smart_forecast(rev, h=H, season_length=SEASON)
    bt = r["backtest"]
    err = bt.get("wape") if bt.get("wape") is not None else bt["mape"]
    err_txt = "n/a" if err is None else f"{err:.1%}"
    _title(ws, "REVENUE FORECAST",
           f"Method: {r['method']} · Confidence: {r['confidence']} · "
           f"Backtest WAPE: {err_txt} · History: {r['n']} months · "
           f"Intervals are 95% confidence. Statistical estimates — review against the sales pipeline.")

    # Recent actuals vs model fit
    section(ws, "RECENT ACTUALS vs MODEL FIT (last 12 months)")
    head = ["Month", "Actual Revenue", "Model Fit", "Error", "Abs % Error"]
    ws.append(head); hdr(ws, ws.max_row, len(head))
    fitted = r["fitted"]
    start = max(0, len(ms) - 12)
    for idx in range(start, len(ms)):
        k = ms[idx]
        m = monthly[k]
        fit = fitted[idx] if idx < len(fitted) else None
        rrow = ws.max_row + 1
        ws.append([mlabel(m["yr"], m["mo"]), m["revenue"],
                   round(fit, 2) if fit is not None else "—"])
        zar(ws, rrow, [2, 3])
        if fit is not None:
            ws.cell(rrow, 4, value=f"=B{rrow}-C{rrow}"); ws.cell(rrow, 4).number_format = ZAR_FMT
            ws.cell(rrow, 5, value=f"=IFERROR(ABS(D{rrow})/B{rrow},\"\")"); ws.cell(rrow, 5).number_format = PCT_FMT
    ws.append([])

    # Forward projection with CI
    section(ws, f"{H}-MONTH FORWARD PROJECTION WITH 95% CONFIDENCE INTERVAL")
    head = ["Period", "Forecast", "Lower 95%", "Upper 95%", "vs Last Actual"]
    ws.append(head); hdr(ws, ws.max_row, len(head), color=HEADER2)
    last_actual = rev[-1] if rev else 0
    labels = _future_labels(ly, lm, H)
    first_fc_row = ws.max_row + 1
    for i in range(H):
        rr = ws.max_row + 1
        ws.append([labels[i], round(r["point"][i], 2), round(r["lower"][i], 2),
                   round(r["upper"][i], 2)])
        zar(ws, rr, [2, 3, 4])
        if last_actual:
            ws.cell(rr, 5, value=f"=IFERROR((B{rr}-{last_actual})/{last_actual},\"\")")
            ws.cell(rr, 5).number_format = PCT_FMT
        for c in range(1, 6):
            ws.cell(rr, c).fill = PatternFill("solid", fgColor="F0F4FF")
    last_fc_row = ws.max_row
    ws.append(["TOTAL (next %d months)" % H,
               f"=SUM(B{first_fc_row}:B{last_fc_row})",
               f"=SUM(C{first_fc_row}:C{last_fc_row})",
               f"=SUM(D{first_fc_row}:D{last_fc_row})"])
    bold_row(ws, ws.max_row, 5); zar(ws, ws.max_row, [2, 3, 4])
    ws.append([])

    # Seasonal calendar index
    if len(ms) >= 6:
        section(ws, "SEASONAL CALENDAR INDEX  (>1.0 = above-average demand month)")
        head = ["Calendar Month", "Avg Revenue", "Seasonal Index", "Months Observed", "Signal"]
        ws.append(head); hdr(ws, ws.max_row, len(head), color=HEADER2)
        overall = fc._mean(rev)
        cal = defaultdict(list)
        for k in ms:
            cal[monthly[k]["mo"]].append(monthly[k]["revenue"])
        for mo in range(1, 13):
            vals = cal.get(mo, [])
            if not vals:
                ws.append([MONTH_NAMES[mo - 1], "No data", "—", 0, "No data yet"]); continue
            avg = fc._mean(vals)
            idx = avg / overall if overall else 1
            if idx >= 1.15:   sig, sf, st = "Peak — stock up", GREEN_F, GREEN_T
            elif idx >= 0.95: sig, sf, st = "Normal", WHITE, "000000"
            elif idx >= 0.80: sig, sf, st = "Below average", AMBER_F, AMBER_T
            else:             sig, sf, st = "Slow — trim costs", RED_F, RED_T
            rr = ws.max_row + 1
            ws.append([MONTH_NAMES[mo - 1], round(avg, 2), round(idx, 2), len(vals), sig])
            ws.cell(rr, 2).number_format = ZAR_FMT
            paint(ws, rr, 5, sf, st)
    auto_width(ws)
    return r


# ════════════════════════════════════════════════════════════════════════════
# Forecast Accuracy
# ════════════════════════════════════════════════════════════════════════════
def build_forecast_accuracy(wb, ctx):
    ws = wb.create_sheet("Forecast Accuracy")
    _title(ws, "FORECAST ACCURACY (BACKTEST)",
           "The model is trained on older months and asked to predict the most recent "
           "months it has not seen; predictions are then scored against what actually happened.")

    monthly = ctx["monthly"]; ms = ctx["months_sorted"]
    rev = ctx["rev_series"]
    orders = [monthly[k]["orders"] for k in ms]
    units = [monthly[k]["items"] for k in ms]
    tlb_rev = ctx["tlb_rev_series"]

    series_set = [
        ("Total Revenue", rev, ZAR_FMT),
        ("Order Count", orders, NUM_FMT),
        ("Units Sold", units, NUM_FMT),
        ("TLB Revenue", tlb_rev, ZAR_FMT),
    ]

    head = ["Series", "Method", "Holdout (mo)", "WAPE", "MAPE", "RMSE", "MAE", "Bias", "Rating"]
    ws.append(head); hdr(ws, ws.max_row, len(head))
    for name, s, fmt in series_set:
        if s:
            r = fc.smart_forecast(s, h=H, season_length=SEASON)
            bt = r["backtest"]
            method = r["method"]
            # the honest backtest re-selects on the training split; note when
            # it landed on a different method than the shipped forecast
            if bt.get("method") and bt["method"] != method:
                method = f"{method} (backtest used {bt['method']})"
        else:
            bt = {"wape": None, "mape": None, "rmse": None, "mae": None,
                  "bias": None, "holdout": 0}
            method = "No data"
        rr = ws.max_row + 1
        wape, mape = bt.get("wape"), bt["mape"]
        err = wape if wape is not None else mape      # WAPE rates the model
        if err is None:
            rating, rf, rt = "Insufficient data", GRAY_F, "666666"
        elif err <= 0.10:
            rating, rf, rt = "Excellent", GREEN_F, GREEN_T
        elif err <= 0.20:
            rating, rf, rt = "Good", GREEN_F, GREEN_T
        elif err <= 0.30:
            rating, rf, rt = "Fair", AMBER_F, AMBER_T
        else:
            rating, rf, rt = "Weak — use with care", RED_F, RED_T
        ws.append([name, method, bt.get("holdout", 0),
                   wape if wape is not None else "—",
                   mape if mape is not None else "—",
                   round(bt["rmse"], 2) if bt["rmse"] is not None else "—",
                   round(bt["mae"], 2) if bt["mae"] is not None else "—",
                   round(bt["bias"], 2) if bt["bias"] is not None else "—",
                   rating])
        if wape is not None:
            ws.cell(rr, 4).number_format = PCT_FMT
        if mape is not None:
            ws.cell(rr, 5).number_format = PCT_FMT
        if fmt == ZAR_FMT:
            zar(ws, rr, [6, 7, 8])
        paint(ws, rr, 9, rf, rt, bold=True)
    ws.append([])

    section(ws, "HOW TO READ THESE METRICS")
    legend = [
        ("WAPE", "Weighted Absolute % Error — total miss as a % of total actual. Handles zero months fairly, so it is the score used for the rating. Lower is better; under 10% is excellent."),
        ("MAPE", "Mean Absolute % Error — average size of the miss as a % of actual. Skips zero-actual months, which can flatter sparse series."),
        ("RMSE", "Root Mean Squared Error — like the average miss but punishes big misses more. In the same units as the series."),
        ("MAE", "Mean Absolute Error — average miss, in the same units as the series."),
        ("Bias", "Average signed error. Positive = the model tends to over-forecast; negative = under-forecast; near zero is ideal."),
    ]
    ws.append(["Metric", "Meaning"]); hdr(ws, ws.max_row, 2, color=HEADER2)
    for metric, desc in legend:
        ws.append([metric, desc])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    auto_width(ws)


# ════════════════════════════════════════════════════════════════════════════
# Revenue Risk
# ════════════════════════════════════════════════════════════════════════════
def build_revenue_risk(wb, ctx, rev_result):
    ws = wb.create_sheet("Revenue Risk")
    _title(ws, "REVENUE RISK ANALYSIS",
           f"Scenarios over the next {H} months. Worst/Best use the 95% confidence band of the "
           f"statistical forecast. The shock scenarios let you stress-test against a manual swing.")

    point = rev_result["point"]; lower = rev_result["lower"]; upper = rev_result["upper"]
    exp_total = sum(point)

    # Aggregate confidence band for the H-month TOTAL. Summing the individual
    # (floored) monthly bounds overstates the swing because month-to-month
    # errors partly cancel; the correct total spread adds variances:
    #   total_sd = resid_std * sqrt(1 + 2 + ... + H)  (each month k widens by sqrt(k))
    resid_std = rev_result.get("resid_std", 0.0)
    z = 1.96
    total_spread = z * resid_std * sqrt(H * (H + 1) / 2.0)
    worst_total = max(exp_total - total_spread, 0.0)
    best_total = exp_total + total_spread

    # Assumptions
    section(ws, "STRESS ASSUMPTIONS (edit the yellow cells)")
    ws.append(["Downside shock", None, "applied to Expected for the pessimistic manual scenario"])
    ds_row = ws.max_row
    _input_cell(ws, ds_row, 2, -0.15, PCT_FMT, "Negative = revenue falls. e.g. -0.15 = -15%")
    ws.append(["Upside shock", None, "applied to Expected for the optimistic manual scenario"])
    us_row = ws.max_row
    _input_cell(ws, us_row, 2, 0.15, PCT_FMT, "Positive = revenue rises. e.g. 0.15 = +15%")
    ws.append([])

    section(ws, f"SCENARIO SUMMARY (total over next {H} months)")
    head = ["Scenario", "Total Revenue", "vs Expected", "Basis"]
    ws.append(head); hdr(ws, ws.max_row, len(head), color=HEADER2)
    exp_cell_row = ws.max_row + 2     # Expected row position (Worst, Expected order below)
    rows = [
        ("Worst Case (95% lower)", worst_total, "Statistical 95% confidence floor", RED_F, RED_T),
        ("Expected", exp_total, "Most-likely statistical forecast", LIGHT_BLUE, "000000"),
        ("Best Case (95% upper)", best_total, "Statistical 95% confidence ceiling", GREEN_F, GREEN_T),
        ("Manual Downside", None, "Expected × (1 + downside shock)", AMBER_F, AMBER_T),
        ("Manual Upside", None, "Expected × (1 + upside shock)", GREEN_F, GREEN_T),
    ]
    exp_row = None
    for label, val, basis, ff, ft in rows:
        rr = ws.max_row + 1
        if label == "Expected":
            exp_row = rr
        if val is not None:
            ws.append([label, round(val, 2), None, basis])
        else:
            ws.append([label, None, None, basis])
        zar(ws, rr, [2])
        paint(ws, rr, 1, ff, ft, bold=True)
    # fill manual scenarios as formulas referencing the expected row + shock inputs
    dn_row = exp_row + 2
    up_row = exp_row + 3
    ws.cell(dn_row, 2, value=f"=B{exp_row}*(1+B{ds_row})"); ws.cell(dn_row, 2).number_format = ZAR_FMT
    ws.cell(up_row, 2, value=f"=B{exp_row}*(1+B{us_row})"); ws.cell(up_row, 2).number_format = ZAR_FMT
    # vs Expected column (formulas)
    for rr in range(exp_row - 1, up_row + 1):
        ws.cell(rr, 3, value=f"=IFERROR((B{rr}-B{exp_row})/B{exp_row},\"\")")
        ws.cell(rr, 3).number_format = PCT_FMT
    ws.append([])

    # Per-month band
    section(ws, "MONTH-BY-MONTH BAND")
    head = ["Period", "Worst (Lower 95%)", "Expected", "Best (Upper 95%)", "Band Width"]
    ws.append(head); hdr(ws, ws.max_row, len(head), color=HEADER2)
    labels = _future_labels(ctx["ly"], ctx["lm"], H)
    for i in range(H):
        rr = ws.max_row + 1
        ws.append([labels[i], round(lower[i], 2), round(point[i], 2), round(upper[i], 2)])
        ws.cell(rr, 5, value=f"=D{rr}-B{rr}")
        zar(ws, rr, [2, 3, 4, 5])
    auto_width(ws)


# ════════════════════════════════════════════════════════════════════════════
# Product Forecasting
# ════════════════════════════════════════════════════════════════════════════
def build_product_forecasting(wb, ctx, top=25):
    ws = wb.create_sheet("Product Forecasting")
    _title(ws, "PRODUCT DEMAND FORECAST",
           "Per-product unit demand for the next 3 months using the smart engine. "
           "Recommended stock = next-month forecast plus a safety buffer (editable below).")

    ms = ctx["months_sorted"]; n_months = ctx["n_months"]
    ly, lm = ctx["ly"], ctx["lm"]
    prod_sorted = ctx["prod_sorted"]

    section(ws, "ASSUMPTION")
    ws.append(["Safety buffer on recommended stock", None,
               "extra cover above the next-month forecast"])
    buf_row = ws.max_row
    _input_cell(ws, buf_row, 2, 0.20, PCT_FMT, "e.g. 0.20 = keep 20% above forecast")
    ws.append([])

    f1, f2, f3 = _future_labels(ly, lm, 3)
    head = ["Product", "Category", "Avg Units/Mo", f"Fc {f1}", f"Fc {f2}", f"Fc {f3}",
            "Growth", "Confidence", "Method", "Recommended Stock"]
    ws.append(head); hdr(ws, ws.max_row, len(head), color=HEADER2)

    results = {}
    for pname, pd in prod_sorted[:top]:
        series = _series_for_product(ctx, pname, pd)
        r = fc.smart_forecast(series, h=3, season_length=SEASON)
        results[pname] = r
        avg = sum(series) / n_months if n_months else 0
        rr = ws.max_row + 1
        ws.append([pname, pd["cat"], round(avg, 1),
                   round(r["point"][0], 1), round(r["point"][1], 1), round(r["point"][2], 1),
                   None, r["confidence"], r["method"], None])
        # growth & recommended stock as formulas
        ws.cell(rr, 7, value=f"=IFERROR((AVERAGE(D{rr}:F{rr})-C{rr})/C{rr},\"\")")
        ws.cell(rr, 7).number_format = PCT_FMT
        ws.cell(rr, 10, value=f"=ROUNDUP(D{rr}*(1+$B${buf_row}),0)")
        cf, ct = _conf_fill(r["confidence"])
        paint(ws, rr, 8, cf, ct, bold=True)
        # growth colour
        g = r["growth"]
        if g > 0.05:   paint(ws, rr, 7, GREEN_F, GREEN_T)
        elif g < -0.05: paint(ws, rr, 7, RED_F, RED_T)
    zebra(ws, ws.max_row - len(results) + 1, ws.max_row, len(head))
    auto_width(ws)
    ctx["product_results"] = results
    return results


# ════════════════════════════════════════════════════════════════════════════
# Inventory Planning
# ════════════════════════════════════════════════════════════════════════════
def build_inventory_planning(wb, ctx, top=25):
    ws = wb.create_sheet("Inventory Planning")
    _title(ws, "INVENTORY PLANNING",
           "Safety stock, reorder point and suggested purchase quantity per product. "
           "All planning numbers are live Excel formulas driven by the yellow assumption cells.")

    ms = ctx["months_sorted"]; n_months = ctx["n_months"]
    prod_sorted = ctx["prod_sorted"]
    product_results = ctx.get("product_results", {})

    # ── assumptions block ──
    section(ws, "PLANNING ASSUMPTIONS (edit the yellow cells)")
    a = {}
    def add_assum(label, value, fmt, note):
        ws.append([label]); rr = ws.max_row
        _input_cell(ws, rr, 2, value, fmt, note)
        return rr
    a["z"] = add_assum("Service level Z-score", 1.65, "0.00",
                       "1.65 = 95% service level, 2.05 = 98%, 1.28 = 90%")
    a["lead"] = add_assum("Lead time (days)", 7, "0", "Days from order to delivery of stock")
    a["review"] = add_assum("Review / cover period (days)", 30, "0", "How many days of demand a purchase should cover")
    a["dpm"] = add_assum("Days per month", 30, "0", "Used to convert monthly demand to daily")
    ws.append([])

    z_ref = f"$B${a['z']}"; lead_ref = f"$B${a['lead']}"
    review_ref = f"$B${a['review']}"; dpm_ref = f"$B${a['dpm']}"

    head = ["Product", "Avg Monthly Demand", "Avg Daily Demand", "Monthly Demand Std",
            "Lead-Time Demand", "Safety Stock", "Reorder Point",
            "On Hand", "Fc Next Month", "Suggested Purchase Qty"]
    ws.append(head); hdr(ws, ws.max_row, len(head), color=HEADER2)
    note_row = ws.max_row
    data_start = note_row + 1

    for pname, pd in prod_sorted[:top]:
        series = _series_for_product(ctx, pname, pd)
        avg_m = sum(series) / n_months if n_months else 0
        std_m = fc._std(series)
        r = product_results.get(pname) or fc.smart_forecast(series, h=1, season_length=SEASON)
        fc_next = r["point"][0] if r["point"] else avg_m
        rr = ws.max_row + 1
        ws.append([pname, round(avg_m, 2), None, round(std_m, 2),
                   None, None, None, 0, round(fc_next, 1), None])
        # Avg daily demand = monthly / days-per-month
        ws.cell(rr, 3, value=f"=IFERROR(B{rr}/{dpm_ref},0)"); ws.cell(rr, 3).number_format = NUM_FMT
        # Lead-time demand = avg daily * lead time
        ws.cell(rr, 5, value=f"=C{rr}*{lead_ref}"); ws.cell(rr, 5).number_format = NUM_FMT
        # Safety stock = Z * daily-std * sqrt(lead);  daily std ≈ monthly std / sqrt(days)
        ws.cell(rr, 6, value=f"=ROUNDUP({z_ref}*(D{rr}/SQRT({dpm_ref}))*SQRT({lead_ref}),0)")
        # Reorder point = lead-time demand + safety stock
        ws.cell(rr, 7, value=f"=ROUNDUP(E{rr}+F{rr},0)")
        # On hand is an editable input
        _input_cell(ws, rr, 8, 0, "0", "Enter current stock on hand")
        # Suggested purchase = cover (review-period demand) + safety stock − on hand, floored at 0
        ws.cell(rr, 10, value=f"=MAX(0,ROUNDUP(C{rr}*{review_ref}+F{rr}-H{rr},0))")
        for c in (3, 5):
            ws.cell(rr, c).number_format = NUM_FMT
    zebra(ws, data_start, ws.max_row, len(head))
    auto_width(ws)


# ════════════════════════════════════════════════════════════════════════════
# ABC Analysis
# ════════════════════════════════════════════════════════════════════════════
def build_abc_analysis(wb, ctx):
    ws = wb.create_sheet("ABC Analysis")
    _title(ws, "ABC ANALYSIS (PARETO)",
           "Products ranked by revenue contribution. A = top ~80% of revenue (your vital few), "
           "B = next ~15%, C = the long tail. Focus stock & service on A items.")

    prod_sorted = ctx["prod_sorted"]
    total = sum(pd["revenue"] for _, pd in prod_sorted) or 1

    # total cell to reference
    section(ws, "CLASSIFICATION")
    head = ["Rank", "Product", "Category", "Revenue", "Revenue %", "Cumulative %", "Class"]
    ws.append(head); hdr(ws, ws.max_row, len(head))
    data_start = ws.max_row + 1
    cumulative = 0.0
    counts = {"A": 0, "B": 0, "C": 0}
    rev_by_class = {"A": 0.0, "B": 0.0, "C": 0.0}
    n = len(prod_sorted)
    for i, (pname, pd) in enumerate(prod_sorted, 1):
        cumulative += pd["revenue"]
        cum_pct = cumulative / total
        cls = "A" if cum_pct <= 0.80 else ("B" if cum_pct <= 0.95 else "C")
        counts[cls] += 1
        rev_by_class[cls] += pd["revenue"]
        rr = ws.max_row + 1
        ws.append([i, pname, pd["cat"], round(pd["revenue"], 2), None, None, cls])
        ws.cell(rr, 5, value=f"=IFERROR(D{rr}/$D${data_start + n + 1},\"\")")
        ws.cell(rr, 5).number_format = PCT_FMT
        # cumulative % formula references all revenue cells above (inclusive)
        ws.cell(rr, 6, value=f"=IFERROR(SUM($D${data_start}:D{rr})/$D${data_start + n + 1},\"\")")
        ws.cell(rr, 6).number_format = PCT_FMT
        zar(ws, rr, [4])
        cf = {"A": GREEN_F, "B": AMBER_F, "C": GRAY_F}[cls]
        ct = {"A": GREEN_T, "B": AMBER_T, "C": "666666"}[cls]
        paint(ws, rr, 7, cf, ct, bold=True)
    # total row (referenced by % formulas above via absolute address D{data_start+n+1})
    ws.append(["", "TOTAL", "", f"=SUM(D{data_start}:D{ws.max_row})"])
    bold_row(ws, ws.max_row, len(head)); zar(ws, ws.max_row, [4])
    zebra(ws, data_start, data_start + n - 1, len(head))
    ws.append([])

    section(ws, "CLASS SUMMARY")
    ws.append(["Class", "# Products", "% of Products", "Revenue", "Revenue Share"])
    hdr(ws, ws.max_row, 5, color=HEADER2)
    for cls in ("A", "B", "C"):
        rr = ws.max_row + 1
        ws.append([cls, counts[cls],
                   counts[cls] / n if n else 0,
                   round(rev_by_class[cls], 2),
                   rev_by_class[cls] / total])
        ws.cell(rr, 3).number_format = PCT_FMT
        ws.cell(rr, 5).number_format = PCT_FMT
        zar(ws, rr, [4])
        cf = {"A": GREEN_F, "B": AMBER_F, "C": GRAY_F}[cls]
        ct = {"A": GREEN_T, "B": AMBER_T, "C": "666666"}[cls]
        paint(ws, rr, 1, cf, ct, bold=True)
    auto_width(ws)


# ════════════════════════════════════════════════════════════════════════════
# Customer Forecasting
# ════════════════════════════════════════════════════════════════════════════
def build_customer_forecasting(wb, ctx, top=20):
    ws = wb.create_sheet("Customer Forecasting")
    _title(ws, "CUSTOMER REVENUE FORECAST",
           "Projected revenue for the top customers over the next 3 months, "
           "based on each customer's own monthly order history.")

    ms = ctx["months_sorted"]; ly, lm = ctx["ly"], ctx["lm"]
    cm = _customer_monthly(ctx.get("fc_orders", ctx["active_orders"]))
    cust_sorted = ctx["cust_sorted"]

    f1, f2, f3 = _future_labels(ly, lm, 3)
    head = ["Customer", "Lifetime Revenue", "Avg Rev/Mo", f"Fc {f1}", f"Fc {f2}", f"Fc {f3}",
            "3-Mo Forecast", "Growth", "Confidence"]
    ws.append(head); hdr(ws, ws.max_row, len(head))
    rows = 0
    for cname, cd in cust_sorted[:top]:
        series = [cm[cname].get(k, 0.0) for k in ms]
        r = fc.smart_forecast(series, h=3, season_length=SEASON)
        nz = [v for v in series if v > 0]
        avg = sum(series) / len(series) if series else 0
        rr = ws.max_row + 1
        ws.append([cname, round(cd["revenue"], 2), round(avg, 2),
                   round(r["point"][0], 2), round(r["point"][1], 2), round(r["point"][2], 2),
                   None, None, r["confidence"]])
        ws.cell(rr, 7, value=f"=SUM(D{rr}:F{rr})"); ws.cell(rr, 7).number_format = ZAR_FMT
        ws.cell(rr, 8, value=f"=IFERROR((AVERAGE(D{rr}:F{rr})-C{rr})/C{rr},\"\")")
        ws.cell(rr, 8).number_format = PCT_FMT
        zar(ws, rr, [2, 3, 4, 5, 6])
        cf, ct = _conf_fill(r["confidence"])
        paint(ws, rr, 9, cf, ct, bold=True)
        if r["growth"] > 0.05:   paint(ws, rr, 8, GREEN_F, GREEN_T)
        elif r["growth"] < -0.05: paint(ws, rr, 8, RED_F, RED_T)
        rows += 1
    zebra(ws, ws.max_row - rows + 1, ws.max_row, len(head))
    auto_width(ws)


# ════════════════════════════════════════════════════════════════════════════
# Delivery Forecasting
# ════════════════════════════════════════════════════════════════════════════
def build_delivery_forecasting(wb, ctx):
    ws = wb.create_sheet("Delivery Forecasting")
    _title(ws, "DELIVERY FORECASTING",
           "Projected delivery volume, fuel usage and fleet load. Fuel and fleet figures are "
           "estimates driven by the yellow assumption cells — adjust them to your fleet's reality.")

    deliveries = ctx["deliveries"]; ly, lm = ctx["ly"], ctx["lm"]
    dm = _delivery_monthly(deliveries)
    # Contiguous calendar, partial current month excluded (same hygiene as revenue)
    current_key = ctx["today"].strftime("%Y-%m")
    done = sorted(k for k in dm.keys() if k < current_key)
    dkeys = month_range(done[0], done[-1]) if done else []
    series = [dm[k]["n"] if k in dm else 0 for k in dkeys]
    r = fc.smart_forecast(series, h=H, season_length=SEASON)

    # fleet snapshot
    vehicles = sorted({d.vehicle_reg for d in deliveries if d.vehicle_reg})
    n_veh = len(vehicles)

    section(ws, "FLEET & FUEL ASSUMPTIONS (edit the yellow cells)")
    def add_assum(label, value, fmt, note):
        ws.append([label]); rr = ws.max_row
        _input_cell(ws, rr, 2, value, fmt, note); return rr
    km_row = add_assum("Avg km per delivery (round trip)", 40, "0", "Average distance covered per delivery")
    eff_row = add_assum("Fuel consumption (L/100km)", 28, "0", "Typical for a loaded delivery truck")
    price_row = add_assum("Diesel price (R/litre)", 23.5, ZAR_FMT, "Current pump price")
    cap_row = add_assum("Deliveries per vehicle per day", 3, "0", "Realistic daily capacity per truck")
    wd_row = add_assum("Working days per month", 22, "0", "Operating days in a month")
    veh_row = add_assum("Vehicles available", max(n_veh, 1), "0",
                        f"Auto-filled from {n_veh} distinct vehicle(s) seen in deliveries")
    ws.append([])

    km_ref = f"$B${km_row}"; eff_ref = f"$B${eff_row}"; price_ref = f"$B${price_row}"
    cap_ref = f"$B${cap_row}"; wd_ref = f"$B${wd_row}"; veh_ref = f"$B${veh_row}"

    section(ws, f"{H}-MONTH DELIVERY & FUEL FORECAST")
    head = ["Period", "Forecast Deliveries", "Lower 95%", "Upper 95%",
            "Est. Distance (km)", "Est. Fuel (L)", "Est. Fuel Cost",
            "Vehicle-Days Needed", "Fleet Utilisation"]
    ws.append(head); hdr(ws, ws.max_row, len(head), color=HEADER2)
    labels = _future_labels(ly, lm, H)
    for i in range(H):
        rr = ws.max_row + 1
        ws.append([labels[i], round(r["point"][i]), round(r["lower"][i]), round(r["upper"][i])])
        ws.cell(rr, 5, value=f"=B{rr}*{km_ref}")
        ws.cell(rr, 6, value=f"=E{rr}*{eff_ref}/100")
        ws.cell(rr, 7, value=f"=F{rr}*{price_ref}"); ws.cell(rr, 7).number_format = ZAR_FMT
        ws.cell(rr, 8, value=f"=IFERROR(ROUNDUP(B{rr}/{cap_ref},0),0)")
        ws.cell(rr, 9, value=f"=IFERROR(B{rr}/({cap_ref}*{wd_ref}*{veh_ref}),\"\")")
        ws.cell(rr, 9).number_format = PCT_FMT
        for c in (5, 6):
            ws.cell(rr, c).number_format = NUM_FMT
    ws.append([])

    section(ws, "CURRENT FLEET UTILISATION")
    ws.append(["Metric", "Value"]); hdr(ws, ws.max_row, 2, color=HEADER2)
    completed = [d for d in deliveries if d.status == "completed"]
    rows = [
        ("Distinct vehicles in use", n_veh),
        ("Total deliveries on record", len(deliveries)),
        ("Completed deliveries", len(completed)),
        ("Avg deliveries per vehicle", round(len(deliveries) / n_veh, 1) if n_veh else 0),
        ("Months of delivery history", len(dkeys)),
    ]
    for label, val in rows:
        ws.append([label, val])
    zebra(ws, ws.max_row - len(rows) + 1, ws.max_row, 2)
    if vehicles:
        ws.append([])
        section(ws, "DELIVERIES BY VEHICLE")
        ws.append(["Vehicle", "Total Deliveries", "Completed", "Share of Deliveries"])
        hdr(ws, ws.max_row, 4, color=HEADER2)
        per_veh = defaultdict(lambda: {"n": 0, "done": 0})
        for d in deliveries:
            if d.vehicle_reg:
                per_veh[d.vehicle_reg]["n"] += 1
                if d.status == "completed":
                    per_veh[d.vehicle_reg]["done"] += 1
        tot = len(deliveries) or 1
        for reg, vd in sorted(per_veh.items(), key=lambda x: x[1]["n"], reverse=True):
            rr = ws.max_row + 1
            ws.append([reg, vd["n"], vd["done"], vd["n"] / tot])
            ws.cell(rr, 4).number_format = PCT_FMT
    auto_width(ws)
    return r


# ════════════════════════════════════════════════════════════════════════════
# Executive Dashboard
# ════════════════════════════════════════════════════════════════════════════
def build_executive_dashboard(wb, ctx, rev_result, delivery_result):
    ws = wb.create_sheet("Executive Dashboard")
    today = ctx["today"]
    _title(ws, "EXECUTIVE DASHBOARD",
           f"Generated {today.strftime('%d %B %Y')} · Forward view: next {H} months · "
           f"Forecast engine: {rev_result['method']} ({rev_result['confidence']} confidence)")

    # ── headline KPIs ──
    section(ws, "FORWARD KPIs (NEXT 3 MONTHS)")
    head = ["KPI", "Expected", "Range (95%)", "Confidence"]
    ws.append(head); hdr(ws, ws.max_row, len(head))

    def band(res, n=3, money=True):
        # Aggregate band over n months adds variances (errors partly cancel),
        # matching the Revenue Risk sheet rather than summing monthly bounds.
        exp = sum(res["point"][:n])
        spread = 1.96 * res.get("resid_std", 0.0) * sqrt(n * (n + 1) / 2.0)
        lo = max(exp - spread, 0.0)
        hi = exp + spread
        fmtv = (lambda v: f"R{v:,.0f}") if money else (lambda v: f"{v:,.0f}")
        return exp, f"{fmtv(lo)} – {fmtv(hi)}"

    rev_exp, rev_band = band(rev_result, 3, True)
    del_exp, del_band = band(delivery_result, 3, False)
    tlb_res = ctx.get("tlb_result")
    rows = [("Revenue Forecast", rev_exp, rev_band, rev_result["confidence"], True),
            ("Delivery Forecast (count)", del_exp, del_band, delivery_result["confidence"], False)]
    if tlb_res:
        tlb_exp, tlb_band = band(tlb_res, 3, True)
        rows.append(("TLB Revenue Forecast", tlb_exp, tlb_band, tlb_res["confidence"], True))
    for label, exp, rng, conf, money in rows:
        rr = ws.max_row + 1
        ws.append([label, round(exp, 2), rng, conf])
        if money:
            ws.cell(rr, 2).number_format = ZAR_FMT
        else:
            ws.cell(rr, 2).number_format = NUM_FMT
        cf, ct = _conf_fill(conf)
        paint(ws, rr, 4, cf, ct, bold=True)
    ws.append([])

    # ── current-state KPIs ──
    section(ws, "CURRENT STATE")
    ws.append(["Metric", "Value"]); hdr(ws, ws.max_row, 2, color=HEADER2)
    cur = [
        ("Revenue (active orders, to date)", ctx["total_rev"], True),
        ("Outstanding receivables", ctx["outstanding"], True),
        ("Active customers", len(ctx["cust_sorted"]), False),
        ("Products in catalogue", len(ctx["prod_sorted"]), False),
        ("Months of history", ctx["n_months"], False),
    ]
    for label, val, money in cur:
        rr = ws.max_row + 1
        ws.append([label, round(val, 2) if money else val])
        if money:
            ws.cell(rr, 2).number_format = ZAR_FMT
    zebra(ws, ws.max_row - len(cur) + 1, ws.max_row, 2)
    ws.append([])

    # ── growing / declining products ──
    pr = ctx.get("product_results", {})
    ranked = sorted(pr.items(), key=lambda x: x[1]["growth"], reverse=True)
    growing = [(n, r) for n, r in ranked if r["growth"] > 0.02][:5]
    declining = [(n, r) for n, r in sorted(pr.items(), key=lambda x: x[1]["growth"]) if r["growth"] < -0.02][:5]

    section(ws, "TOP GROWING PRODUCTS")
    ws.append(["Product", "Forecast Growth", "Next-Month Forecast (units)", "Confidence"])
    hdr(ws, ws.max_row, 4, color=HEADER2)
    if growing:
        for n, r in growing:
            rr = ws.max_row + 1
            ws.append([n, r["growth"], round(r["point"][0], 1), r["confidence"]])
            ws.cell(rr, 2).number_format = PCT_FMT
            paint(ws, rr, 2, GREEN_F, GREEN_T, bold=True)
    else:
        ws.append(["No products with a clear upward trend yet", "", "", ""])
    ws.append([])

    section(ws, "DECLINING PRODUCTS — REVIEW")
    ws.append(["Product", "Forecast Growth", "Next-Month Forecast (units)", "Confidence"])
    hdr(ws, ws.max_row, 4, color=HEADER2)
    if declining:
        for n, r in declining:
            rr = ws.max_row + 1
            ws.append([n, r["growth"], round(r["point"][0], 1), r["confidence"]])
            ws.cell(rr, 2).number_format = PCT_FMT
            paint(ws, rr, 2, RED_F, RED_T, bold=True)
    else:
        ws.append(["No products in clear decline", "", "", ""])
    ws.append([])

    # ── inventory risk ──
    section(ws, "INVENTORY RISK")
    a_class = [n for n, r in pr.items()]  # placeholder; refine via revenue rank below
    # flag products whose next-month forecast notably exceeds their recent average (stock-out risk)
    flags = []
    for n, r in pr.items():
        if r["point"] and r["growth"] > 0.10:
            flags.append((n, r["growth"]))
    ws.append(["High-demand-growth products needing stock attention", len(flags)])
    ws.cell(ws.max_row, 1).font = Font(bold=True)
    if flags:
        ws.append(["Product", "Forecast Growth"]); hdr(ws, ws.max_row, 2, color=HEADER2)
        for n, g in sorted(flags, key=lambda x: x[1], reverse=True)[:8]:
            rr = ws.max_row + 1
            ws.append([n, g]); ws.cell(rr, 2).number_format = PCT_FMT
            paint(ws, rr, 2, AMBER_F, AMBER_T)
    ws.append([])
    ws.append(["See the Inventory Planning sheet for reorder points and suggested purchase quantities."])
    ws.cell(ws.max_row, 1).font = Font(italic=True, color="666666")
    auto_width(ws)


# ════════════════════════════════════════════════════════════════════════════
# Orchestration
# ════════════════════════════════════════════════════════════════════════════
def build_enterprise_forecasting(wb, ctx):
    """Build the full enterprise forecasting suite and order the sheets sensibly."""
    rev_result = build_revenue_forecast(wb, ctx)
    build_forecast_accuracy(wb, ctx)
    build_revenue_risk(wb, ctx, rev_result)
    build_product_forecasting(wb, ctx)
    build_inventory_planning(wb, ctx)
    build_abc_analysis(wb, ctx)
    build_customer_forecasting(wb, ctx)
    delivery_result = build_delivery_forecasting(wb, ctx)
    build_executive_dashboard(wb, ctx, rev_result, delivery_result)

    # Order: Summary, Executive Dashboard, then forecasting suite, then the rest.
    preferred = [
        "Summary", "Executive Dashboard", "Revenue Forecast", "Forecast Accuracy",
        "Revenue Risk", "Product Forecasting", "Inventory Planning", "ABC Analysis",
        "Customer Forecasting", "Delivery Forecasting",
    ]
    order = [s for s in preferred if s in wb.sheetnames]
    order += [s for s in wb.sheetnames if s not in order]
    wb._sheets.sort(key=lambda s: order.index(s.title))
