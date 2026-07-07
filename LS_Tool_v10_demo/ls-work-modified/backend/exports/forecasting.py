"""
Forecasting engine for the logistics workbook.

Pure-Python (stdlib only) so it adds no deployment dependencies. Provides a
"smart" forecaster that selects a method based on how much history exists and
how intermittent the series is:

    < 6 points          -> Linear regression blended with a rolling average
    intermittent        -> Croston's method (SBA variant)
    6 - 11              -> Holt's linear trend (double exponential smoothing)
    12 - 23             -> Holt-Winters additive (triple exponential smoothing)
    24+                 -> Holt-Winters multiplicative

The length ladder decides which methods are *eligible*; the final pick is made
by rolling-origin validation (average miss over several held-out windows), so
one noisy month cannot flip the choice.

It also returns 95% confidence intervals (widened by the ratio of measured
out-of-sample error to in-sample error, so the band reflects real accuracy,
not the optimism of a fitted model), an in-sample fit, an honest backtest
(the method is re-selected on the training split only, so the holdout never
influences the score), WAPE / MAPE / RMSE / MAE / Bias, a confidence rating
and an implied growth rate.

Smoothing parameters (alpha/beta/gamma/phi) are chosen by a small grid search
per series. Fits are memoised, so repeated calls across workbook sheets are
cheap.
"""
from functools import lru_cache
from math import sqrt

# ── basic stats ───────────────────────────────────────────────────────────────
def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def _std(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

def linreg(ys):
    """Ordinary least-squares slope & intercept over index 0..n-1."""
    n = len(ys)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0)
    xm = (n - 1) / 2.0
    ym = _mean(ys)
    num = sum((i - xm) * (v - ym) for i, v in enumerate(ys))
    den = sum((i - xm) ** 2 for i in range(n))
    s = num / den if den else 0.0
    return s, ym - s * xm

def rolling_avg(series, window=3):
    if not series:
        return 0.0
    w = series[-window:]
    return sum(w) / len(w)

# ── guard rails ───────────────────────────────────────────────────────────────
def _runaway_cap(series):
    """A generous ceiling no forecast should exceed, derived from history."""
    if not series:
        return 0.0
    return max(max(series) * 2.5, rolling_avg(series, 3) * 3.0)

def _clean_preds(pred, history):
    """Floor at zero and apply the runaway cap implied by the given history.

    Used on validation/backtest predictions as well as the live forecast, so
    the method contest is scored on exactly what would ship.
    """
    cap = _runaway_cap(history)
    out = [max(p, 0.0) for p in pred]
    if cap > 0:
        out = [min(p, cap) for p in out]
    return out

# ── method 1: linear + rolling blend (short series) ────────────────────────────
def _linear_blend(series, h, weight_linear=0.6):
    slope, intercept = linreg(series)
    ra = rolling_avg(series)
    n = len(series)
    fitted = [None]
    for i in range(1, n):
        fitted.append(intercept + slope * i)        # one-step regression fit
    point = []
    for k in range(h):
        lin = intercept + slope * (n + k)
        point.append(lin * weight_linear + ra * (1 - weight_linear))
    return point, fitted

# ── method 2: Croston's method, SBA variant (intermittent demand) ──────────────
def _croston(series, alpha, h):
    """Croston's method with the Syntetos-Boylan Approximation bias correction.

    Designed for series that are mostly zeros with occasional demand spikes
    (per-product units, per-customer months). Smooths demand *size* and demand
    *interval* separately; the forecast per period is size/interval, scaled by
    (1 - alpha/2) to remove Croston's known positive bias.
    """
    n = len(series)
    fitted = [None] * n
    z = None          # smoothed demand size
    p = None          # smoothed demand interval
    q = 1             # periods since last demand
    fc_val = None
    for t in range(n):
        if fc_val is not None:
            fitted[t] = fc_val
        d = series[t]
        if d > 0:
            z = d if z is None else alpha * d + (1 - alpha) * z
            p = float(q) if p is None else alpha * q + (1 - alpha) * p
            q = 1
            fc_val = (1 - alpha / 2.0) * z / p if p else z
        else:
            q += 1
    point = [fc_val if fc_val is not None else 0.0] * h
    return point, fitted

# ── method 3: Holt linear trend (with optional damping) ────────────────────────
def _holt(series, alpha, beta, h, phi=1.0):
    n = len(series)
    level = series[0]
    if n >= 2:
        # average the first few differences instead of trusting one noisy month
        diffs = [series[i + 1] - series[i] for i in range(min(3, n - 1))]
        trend = _mean(diffs)
    else:
        trend = 0.0
    fitted = [None]
    for t in range(1, n):
        fitted.append(level + phi * trend)          # one-step-ahead forecast
        prev_level = level
        level = alpha * series[t] + (1 - alpha) * (level + phi * trend)
        trend = beta * (level - prev_level) + (1 - beta) * phi * trend
    point = []
    damp = 0.0
    for k in range(1, h + 1):
        damp += phi ** k
        point.append(level + damp * trend)
    return point, fitted, level, trend

# ── method 4/5: Holt-Winters (additive / multiplicative) ───────────────────────
def _init_season(series, m, mult):
    """Initial seasonal factors averaged over ALL complete seasons, normalised.

    Using only the first year makes the factors hostage to one season's noise;
    averaging across seasons and renormalising (multiplicative factors mean 1,
    additive factors sum 0) is the classical initialisation.
    """
    k = max(1, len(series) // m)
    season = []
    for i in range(m):
        vals = []
        for s in range(k):
            seg = series[s * m:(s + 1) * m]
            if len(seg) < m:
                break
            seg_mean = _mean(seg)
            if mult:
                if seg_mean > 1e-9:
                    vals.append(seg[i] / seg_mean)
            else:
                vals.append(seg[i] - seg_mean)
        season.append(_mean(vals) if vals else (1.0 if mult else 0.0))
    if mult:
        savg = _mean(season)
        if savg > 1e-9:
            season = [s_ / savg for s_ in season]
    else:
        adj = _mean(season)
        season = [s_ - adj for s_ in season]
    return season

def _holt_winters(series, m, alpha, beta, gamma, h, mult, phi=1.0):
    n = len(series)
    level = _mean(series[:m])
    if n >= 2 * m:
        trend = (_mean(series[m:2 * m]) - level) / m
    else:
        trend = linreg(series)[0]
    season = _init_season(series, m, mult)

    fitted = [None] * m
    L, T, S = level, trend, list(season)
    for t in range(m, n):
        si = S[t % m]
        f = (L + phi * T) * si if mult else (L + phi * T + si)
        fitted.append(f)
        prev_L = L
        if mult:
            L = alpha * (series[t] / si if si else series[t]) + (1 - alpha) * (L + phi * T)
            T = beta * (L - prev_L) + (1 - beta) * phi * T
            S[t % m] = gamma * (series[t] / L if L else 1.0) + (1 - gamma) * si
        else:
            L = alpha * (series[t] - si) + (1 - alpha) * (L + phi * T)
            T = beta * (L - prev_L) + (1 - beta) * phi * T
            S[t % m] = gamma * (series[t] - L) + (1 - gamma) * si

    point = []
    damp = 0.0
    for k in range(1, h + 1):
        damp += phi ** k
        si = S[(n - 1 + k) % m]
        point.append((L + T * damp) * si if mult else (L + T * damp + si))
    return point, fitted

# ── parameter optimisation (small grid search on in-sample SSE) ────────────────
_ALPHAS = [0.1, 0.3, 0.5, 0.7, 0.9]
_BETAS = [0.05, 0.15, 0.3, 0.5]
_GAMMAS = [0.1, 0.3, 0.5]
_PHIS = [0.85, 0.95, 1.0]
_CROSTON_ALPHAS = [0.05, 0.1, 0.2, 0.3]

def _sse(series, fitted):
    return sum((series[t] - fitted[t]) ** 2 for t in range(len(series)) if fitted[t] is not None)

def _best_holt(series, h):
    best = None
    for a in _ALPHAS:
        for b in _BETAS:
            for p in _PHIS:
                pt, fit, _, _ = _holt(series, a, b, h, phi=p)
                e = _sse(series, fit)
                if best is None or e < best[0]:
                    best = (e, pt, fit)
    return best[1], best[2]

def _best_croston(series, h):
    best = None
    for a in _CROSTON_ALPHAS:
        pt, fit = _croston(series, a, h)
        e = _sse(series, fit)
        if best is None or e < best[0]:
            best = (e, pt, fit)
    return best[1], best[2]

def _best_hw(series, m, h, mult):
    best = None
    for a in _ALPHAS:
        for b in _BETAS:
            for g in _GAMMAS:
                for p in _PHIS:
                    pt, fit = _holt_winters(series, m, a, b, g, h, mult, phi=p)
                    # reject unstable fits (NaN / inf)
                    if any((f != f) or (f in (float("inf"), float("-inf")))
                           for f in fit if f is not None):
                        continue
                    e = _sse(series, fit)
                    if best is None or e < best[0]:
                        best = (e, pt, fit)
    if best is None:                                   # fallback
        return _best_holt(series, h)
    return best[1], best[2]

# ── method selection ───────────────────────────────────────────────────────────
def _candidates(series, m):
    """Methods that are *eligible* for this series, richest first.

    The spec's length ladder decides eligibility; intermittent series get
    Croston's (SBA) with the linear blend as a challenger. The final pick
    among eligible methods is made by rolling-origin validation (``_choose``),
    so we never commit to a model the data does not actually support well.
    """
    n = len(series)
    nonzero = sum(1 for x in series if x > 0)
    zero_frac = (n - nonzero) / n if n else 1.0

    if n < 6:
        return ["Linear + Rolling Avg"]
    if zero_frac >= 0.35 or nonzero < 6:
        if nonzero >= 3:
            return ["Croston (SBA)", "Linear + Rolling Avg"]
        return ["Linear + Rolling Avg"]
    if n < m:
        return ["Holt Linear Trend", "Linear + Rolling Avg"]
    if n < 2 * m or min(series) <= 0:
        return ["Holt-Winters (Additive)", "Holt Linear Trend"]
    return ["Holt-Winters (Multiplicative)", "Holt-Winters (Additive)", "Holt Linear Trend"]

def _select_method(series, m):
    """The spec's default ladder choice (richest eligible method)."""
    return _candidates(series, m)[0]

@lru_cache(maxsize=2048)
def _fit_cached(tseries, m, h, method):
    series = list(tseries)
    if method == "Linear + Rolling Avg":
        pt, ft = _linear_blend(series, h)
    elif method == "Croston (SBA)":
        pt, ft = _best_croston(series, h)
    elif method == "Holt Linear Trend":
        pt, ft = _best_holt(series, h)
    elif len(series) < m:
        # defensive: a forced Holt-Winters on too-short history degrades to Holt
        pt, ft = _best_holt(series, h)
    elif method == "Holt-Winters (Additive)":
        pt, ft = _best_hw(series, m, h, mult=False)
    else:
        pt, ft = _best_hw(series, m, h, mult=True)
    return tuple(pt), tuple(ft)

def _fit(series, m, h, method):
    """Memoised fit. Returns fresh lists so callers may mutate them safely."""
    pt, ft = _fit_cached(tuple(series), m, h, method)
    return list(pt), list(ft)

def _validation_score(series, m, method):
    """Score a method by rolling-origin validation.

    Up to three held-out windows, each ``vh`` months long, with origins
    stepping back two months at a time; the score is the average absolute
    miss across folds. A single split lets one odd month decide the contest;
    averaging origins makes the choice stable. Predictions are floored and
    capped exactly as the live forecast would be.

    Falls back to in-sample mean squared error when the series is too short
    to hold out any window for this method.
    """
    n = len(series)
    vh = min(6, max(2, n // 5))      # same horizon the accuracy backtest reports
    need = m if method.startswith("Holt-Winters") else 4
    folds = []
    for k in range(3):
        cut = n - vh - 2 * k
        if cut < max(4, need):
            break
        train, val = series[:cut], series[cut:cut + vh]
        pred, _ = _fit(train, m, vh, method)
        pred = _clean_preds(pred, train)
        folds.append(_mean([abs(pred[i] - val[i]) for i in range(len(val))]))
    if folds:
        return _mean(folds)
    _, fit = _fit(series, m, 1, method)
    cnt = sum(1 for f in fit if f is not None)
    return (_sse(series, fit) / cnt) if cnt else float("inf")

def _choose(series, m, h):
    """Pick the eligible method with the best validation score, then fit it.

    Ties break toward the spec-preferred (richer) method via ladder order.
    Returns ``(method_name, point, fitted)``.
    """
    cands = _candidates(series, m)
    scored = sorted((( _validation_score(series, m, meth), i, meth)
                     for i, meth in enumerate(cands)))
    method = scored[0][2]
    point, fitted = _fit(series, m, h, method)
    return method, point, fitted

# ── accuracy metrics ───────────────────────────────────────────────────────────
_EMPTY_METRICS = {"wape": None, "mape": None, "rmse": None, "mae": None, "bias": None}

def _metrics(actual, pred):
    pairs = list(zip(actual, pred))
    if not pairs:
        return dict(_EMPTY_METRICS)
    errs = [p - a for a, p in pairs]
    mae = _mean([abs(e) for e in errs])
    rmse = sqrt(_mean([e ** 2 for e in errs]))
    bias = _mean(errs)
    # WAPE (weighted absolute % error) handles zero months naturally and is the
    # preferred score for sparse series; MAPE (which must skip zero-actual
    # months, flattering the result) is kept for familiarity.
    denom = sum(abs(a) for a, _ in pairs)
    wape = (sum(abs(e) for e in errs) / denom) if denom else None
    nz = [(a, p) for a, p in pairs if a != 0]
    mape = _mean([abs(p - a) / abs(a) for a, p in nz]) if nz else None
    return {"wape": wape, "mape": mape, "rmse": rmse, "mae": mae, "bias": bias}

# ── public API ─────────────────────────────────────────────────────────────────
def smart_forecast(series, h=6, season_length=12, floor_zero=True, z=1.96):
    """
    Forecast `h` periods ahead.

    Returns a dict:
        method      str
        point       [float] * h
        lower/upper [float] * h        95% confidence interval
        fitted      [float|None] * n   one-step in-sample fit
        resid_std   float              band std (in-sample, inflated by the
                                       backtest/in-sample error ratio)
        confidence  'HIGH'|'MEDIUM'|'LOW'
        growth      float              implied growth (forecast vs recent actuals)
        backtest    {wape,mape,rmse,mae,bias,holdout,method}
                                       honest holdout: the engine re-selects on
                                       the training split only, so the holdout
                                       months never influence their own score
        n           int
    """
    series = [float(x) for x in series]
    n = len(series)
    m = season_length

    if n == 0:
        zero = [0.0] * h
        return {"method": "No data", "point": zero, "lower": zero, "upper": list(zero),
                "fitted": [], "resid_std": 0.0, "confidence": "LOW", "growth": 0.0,
                "backtest": dict(_EMPTY_METRICS, holdout=0, method="No data"), "n": 0}

    method, point, fitted = _choose(series, m, h)

    # Guard against runaway extrapolation (same guard the validation applied).
    cap = _runaway_cap(series)
    if cap > 0:
        point = [min(p, cap) for p in point]

    # residual std from in-sample one-step fit
    resid = [series[t] - fitted[t] for t in range(n) if fitted[t] is not None]
    resid_std = _std(resid) if len(resid) >= 2 else (abs(_mean(resid)) if resid else 0.0)

    # Honest backtest: self-selects on the training split (nested validation),
    # so the reported accuracy is what the engine would genuinely have achieved.
    bt = backtest(series, season_length)

    # In-sample residuals understate real error (the model was fitted to them).
    # Widen the band by the measured out-of-sample/in-sample error ratio,
    # clamped so a tiny holdout can't blow the interval up absurdly.
    insample_rmse = sqrt(_mean([r * r for r in resid])) if resid else 0.0
    if bt["rmse"] and insample_rmse > 1e-9:
        band_std = resid_std * min(max(bt["rmse"] / insample_rmse, 1.0), 3.0)
    else:
        band_std = resid_std

    # confidence interval widens with horizon
    lower, upper = [], []
    for k in range(h):
        spread = z * band_std * sqrt(k + 1)
        lo, hi = point[k] - spread, point[k] + spread
        if floor_zero:
            lo = max(lo, 0.0)
            point[k] = max(point[k], 0.0)
        if cap > 0:
            hi = min(hi, cap * 1.5)
        lower.append(lo)
        upper.append(hi)

    err = bt["wape"] if bt.get("wape") is not None else bt["mape"]
    confidence = confidence_label(n, m, err)

    recent = rolling_avg(series, 3)
    growth = (_mean(point) - recent) / recent if recent else 0.0

    return {"method": method, "point": point, "lower": lower, "upper": upper,
            "fitted": fitted, "resid_std": band_std, "confidence": confidence,
            "growth": growth, "backtest": bt, "n": n}

def backtest(series, season_length=12, min_train=4, method=None):
    """Hold out the tail of the series, forecast it from the head, and score.

    By default the engine re-selects the method on the training split only
    (nested validation) — the holdout months never influence which model is
    scored on them, so the metrics are honest out-of-sample numbers. Passing
    ``method`` forces a specific method instead (legacy behaviour).
    """
    series = [float(x) for x in series]
    n = len(series)
    test_h = min(6, max(1, n // 5))
    if n - test_h < min_train:
        return dict(_EMPTY_METRICS, holdout=0,
                    method=method or _select_method(series, season_length))
    train, actual = series[:-test_h], series[-test_h:]
    if method:
        pred, _ = _fit(train, season_length, test_h, method)
        used = method
    else:
        used, pred, _ = _choose(train, season_length, test_h)
    out = _metrics(actual, _clean_preds(pred, train))
    out["holdout"] = test_h
    out["method"] = used
    return out

def confidence_label(n, m, err):
    """Combine data sufficiency with measured accuracy (WAPE preferred)."""
    if err is not None:
        if n >= m and err <= 0.15:
            return "HIGH"
        if n >= 6 and err <= 0.30:
            return "MEDIUM"
        if err <= 0.20 and n >= 4:
            return "MEDIUM"
        return "LOW"
    # no holdout possible -> fall back to length only
    if n >= m:
        return "HIGH"
    if n >= 6:
        return "MEDIUM"
    return "LOW"

# legacy-compatible helper (drop-in for the old excel.forecast)
def forecast(series, n=3, weight_linear=0.6):
    if not series:
        return [0.0] * n
    return smart_forecast(series, h=n)["point"]
