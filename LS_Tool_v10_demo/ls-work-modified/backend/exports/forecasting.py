"""
Forecasting engine for the logistics workbook.

Pure-Python (stdlib only) so it adds no deployment dependencies. Provides a
"smart" forecaster that selects a method based on how much history exists:

    < 6 points   -> Linear regression blended with a rolling average
    6 - 11       -> Holt's linear trend (double exponential smoothing)
    12 - 23      -> Holt-Winters additive (triple exponential smoothing)
    24+          -> Holt-Winters multiplicative

It also returns 95% confidence intervals, in-sample fitted values, an
out-of-sample (holdout) accuracy backtest (MAPE / RMSE / MAE / Bias), a
confidence rating and an implied growth rate.

Smoothing parameters (alpha/beta/gamma) are chosen by a small grid search that
minimises in-sample squared error, so the model adapts to each series instead
of using fixed guesses.
"""
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

# ── method 2: Holt linear trend (with optional damping) ────────────────────────
def _holt(series, alpha, beta, h, phi=1.0):
    n = len(series)
    level = series[0]
    trend = (series[1] - series[0]) if n >= 2 else 0.0
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

# ── method 3/4: Holt-Winters (additive / multiplicative) ───────────────────────
def _holt_winters(series, m, alpha, beta, gamma, h, mult, phi=1.0):
    n = len(series)
    level = _mean(series[:m])
    if n >= 2 * m:
        trend = (_mean(series[m:2 * m]) - level) / m
    else:
        trend = linreg(series)[0]
    if mult:
        # guard against a zero/near-zero level producing exploding seasonal factors
        base = level if level > 1e-9 else 1.0
        season = [(series[i] / base if base else 1.0) for i in range(m)]
    else:
        season = [series[i] - level for i in range(m)]

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

    The spec's length ladder decides eligibility; sparse / intermittent series
    are pinned to the robust linear blend. The final pick among eligible
    methods is made by out-of-sample validation (see ``_choose``), so we never
    commit to a seasonal model that the data does not actually support well.
    """
    n = len(series)
    nonzero = sum(1 for x in series if x > 0)
    zero_frac = (n - nonzero) / n if n else 1.0

    if n < 6 or zero_frac >= 0.35 or nonzero < 6:
        return ["Linear + Rolling Avg"]
    if n < m:
        return ["Holt Linear Trend", "Linear + Rolling Avg"]
    if n < 2 * m or min(series) <= 0:
        return ["Holt-Winters (Additive)", "Holt Linear Trend"]
    return ["Holt-Winters (Multiplicative)", "Holt-Winters (Additive)", "Holt Linear Trend"]

def _select_method(series, m):
    """The spec's default ladder choice (richest eligible method)."""
    return _candidates(series, m)[0]

def _fit(series, m, h, method):
    if method == "Linear + Rolling Avg":
        return _linear_blend(series, h)
    if method == "Holt Linear Trend":
        return _best_holt(series, h)
    if method == "Holt-Winters (Additive)":
        return _best_hw(series, m, h, mult=False)
    return _best_hw(series, m, h, mult=True)

def _validation_score(series, m, method):
    """Score a method by holding out a small tail and measuring the miss.

    Falls back to in-sample mean squared error when the series is too short to
    hold out a validation window for this method.
    """
    n = len(series)
    vh = min(6, max(2, n // 5))      # same horizon the accuracy backtest reports
    need = m if method.startswith("Holt-Winters") else 4
    if n - vh < max(4, need):
        _, fit = _fit(series, m, 1, method)
        cnt = sum(1 for f in fit if f is not None)
        return (_sse(series, fit) / cnt) if cnt else float("inf")
    train, val = series[:-vh], series[-vh:]
    pred, _ = _fit(train, m, vh, method)
    pred = [max(p, 0.0) for p in pred]
    return _mean([abs(pred[i] - val[i]) for i in range(vh)])

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
def _metrics(actual, pred):
    pairs = list(zip(actual, pred))
    if not pairs:
        return {"mape": None, "rmse": None, "mae": None, "bias": None}
    errs = [p - a for a, p in pairs]
    mae = _mean([abs(e) for e in errs])
    rmse = sqrt(_mean([e ** 2 for e in errs]))
    bias = _mean(errs)
    nz = [(a, p) for a, p in pairs if a != 0]
    mape = _mean([abs(p - a) / abs(a) for a, p in nz]) if nz else None
    return {"mape": mape, "rmse": rmse, "mae": mae, "bias": bias}

# ── public API ─────────────────────────────────────────────────────────────────
def smart_forecast(series, h=6, season_length=12, floor_zero=True, z=1.96):
    """
    Forecast `h` periods ahead.

    Returns a dict:
        method      str
        point       [float] * h
        lower/upper [float] * h        95% confidence interval
        fitted      [float|None] * n   one-step in-sample fit
        resid_std   float
        confidence  'HIGH'|'MEDIUM'|'LOW'
        growth      float              implied growth (forecast vs recent actuals)
        backtest    {mape,rmse,mae,bias}  out-of-sample holdout (may be None values)
        n           int
    """
    series = [float(x) for x in series]
    n = len(series)
    m = season_length

    if n == 0:
        zero = [0.0] * h
        return {"method": "No data", "point": zero, "lower": zero, "upper": list(zero),
                "fitted": [], "resid_std": 0.0, "confidence": "LOW", "growth": 0.0,
                "backtest": {"mape": None, "rmse": None, "mae": None, "bias": None}, "n": 0}

    method, point, fitted = _choose(series, m, h)

    # Guard against runaway extrapolation. No forecast period should exceed a
    # generous multiple of what the series has actually shown; this keeps a
    # multiplicative model from compounding into implausible numbers on noisy
    # or near-intermittent data while leaving healthy trends untouched.
    hist_max = max(series) if series else 0.0
    recent_mean = rolling_avg(series, 3)
    cap = max(hist_max * 2.5, recent_mean * 3.0)
    if cap > 0:
        point = [min(p, cap) for p in point]

    # residual std from in-sample one-step fit
    resid = [series[t] - fitted[t] for t in range(n) if fitted[t] is not None]
    resid_std = _std(resid) if len(resid) >= 2 else (abs(_mean(resid)) if resid else 0.0)

    # confidence interval widens with horizon
    lower, upper = [], []
    for k in range(h):
        spread = z * resid_std * sqrt(k + 1)
        lo, hi = point[k] - spread, point[k] + spread
        if floor_zero:
            lo = max(lo, 0.0)
            point[k] = max(point[k], 0.0)
        if cap > 0:
            hi = min(hi, cap * 1.5)
        lower.append(lo)
        upper.append(hi)

    bt = backtest(series, season_length, method=method)
    confidence = confidence_label(n, m, bt["mape"])

    recent = rolling_avg(series, 3)
    growth = (_mean(point) - recent) / recent if recent else 0.0

    return {"method": method, "point": point, "lower": lower, "upper": upper,
            "fitted": fitted, "resid_std": resid_std, "confidence": confidence,
            "growth": growth, "backtest": bt, "n": n}

def backtest(series, season_length=12, min_train=4, method=None):
    """Hold out the tail of the series, forecast it from the head, and score.

    If ``method`` is given, that method is forced (so the reported accuracy
    matches the method actually shipped in the live forecast); otherwise the
    engine self-selects on the training split.
    """
    series = [float(x) for x in series]
    n = len(series)
    test_h = min(6, max(1, n // 5))
    if n - test_h < min_train:
        return {"mape": None, "rmse": None, "mae": None, "bias": None,
                "holdout": 0, "method": method or _select_method(series, season_length)}
    train, actual = series[:-test_h], series[-test_h:]
    if method:
        pred, _ = _fit(train, season_length, test_h, method)
        used = method
    else:
        used, pred, _ = _choose(train, season_length, test_h)
    out = _metrics(actual, [max(p, 0.0) for p in pred])
    out["holdout"] = test_h
    out["method"] = used
    return out

def confidence_label(n, m, mape):
    """Combine data sufficiency with measured accuracy."""
    if mape is not None:
        if n >= m and mape <= 0.15:
            return "HIGH"
        if n >= 6 and mape <= 0.30:
            return "MEDIUM"
        if mape <= 0.20 and n >= 4:
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
