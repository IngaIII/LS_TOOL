"""Tests for the forecasting engine (run from the backend folder).

    python test_forecasting.py      # plain runner
    pytest test_forecasting.py      # or under pytest

The engine is pure and deterministic, so every test is exact/seedless.
"""
from math import sin, pi

from exports import forecasting as fc


def test_linear_trend_recovered():
    series = [100.0 + 10.0 * i for i in range(20)]
    r = fc.smart_forecast(series, h=3)
    # forecast must keep climbing and land near the true continuation (300, 310, 320)
    assert r["point"][0] > series[-1], "forecast should continue an obvious uptrend"
    for k, true_val in enumerate([300.0, 310.0, 320.0]):
        assert abs(r["point"][k] - true_val) / true_val < 0.15, \
            f"period {k}: {r['point'][k]:.1f} too far from {true_val}"
    assert r["lower"][0] <= r["point"][0] <= r["upper"][0]


def test_seasonal_series_scores_well():
    # 3 years of trend + strong 12-month cycle: engine should model it usefully
    series = [200.0 + 2.0 * t + 60.0 * sin(2 * pi * t / 12) for t in range(36)]
    r = fc.smart_forecast(series, h=6)
    bt = r["backtest"]
    assert bt["wape"] is not None and bt["wape"] < 0.25, \
        f"seasonal series should backtest decently, got WAPE {bt['wape']}"
    assert len(r["point"]) == 6 and all(p >= 0 for p in r["point"])


def test_all_zeros_is_safe():
    r = fc.smart_forecast([0.0] * 12, h=6)
    assert r["point"] == [0.0] * 6
    assert r["upper"] == [0.0] * 6 and r["lower"] == [0.0] * 6
    assert r["confidence"] in ("HIGH", "MEDIUM", "LOW")
    r0 = fc.smart_forecast([], h=4)
    assert r0["method"] == "No data" and r0["point"] == [0.0] * 4
    assert r0["confidence"] == "LOW"


def test_intermittent_uses_croston_family():
    # mostly zeros with occasional demand: classic intermittent series
    series = [0, 0, 40, 0, 0, 0, 55, 0, 0, 35, 0, 0, 0, 60, 0, 0, 45, 0]
    cands = fc._candidates([float(x) for x in series], 12)
    assert "Croston (SBA)" in cands
    r = fc.smart_forecast(series, h=3)
    assert r["method"] in ("Croston (SBA)", "Linear + Rolling Avg")
    # a sensible per-period rate: positive, nowhere near the spike sizes
    assert 0.0 <= r["point"][0] <= max(series)


def test_croston_rate_is_reasonable():
    # demand of ~30 every 3rd month -> per-month rate should be near 10
    series = [0.0, 0.0, 30.0] * 6
    pt, _ = fc._croston(series, alpha=0.1, h=1)
    assert 5.0 <= pt[0] <= 15.0, f"expected ~10/period, got {pt[0]:.2f}"


def test_runaway_cap_and_floor():
    series = [10.0, 12.0, 9.0, 11.0, 10.0, 500.0, 11.0, 10.0, 12.0, 9.0, 11.0, 10.0]
    cap = fc._runaway_cap(series)
    r = fc.smart_forecast(series, h=6)
    assert all(0.0 <= p <= cap for p in r["point"])
    assert all(u <= cap * 1.5 + 1e-9 for u in r["upper"])
    assert all(l >= 0.0 for l in r["lower"])
    assert fc._clean_preds([-5.0, 1e9], series) == [0.0, cap]


def test_wape_metric():
    m = fc._metrics([100.0, 0.0, 50.0], [110.0, 5.0, 45.0])
    # WAPE = (10+5+5)/150; MAPE skips the zero-actual month
    assert abs(m["wape"] - 20.0 / 150.0) < 1e-9
    assert abs(m["mape"] - ((10 / 100 + 5 / 50) / 2)) < 1e-9
    assert fc._metrics([0.0, 0.0], [1.0, 2.0])["wape"] is None


def test_backtest_is_nested_and_labelled():
    series = [100.0 + 10.0 * i for i in range(20)]
    bt = fc.backtest(series)
    assert bt["holdout"] > 0 and "method" in bt and bt["wape"] is not None
    # too short to hold anything out -> metrics are None, not garbage
    short = fc.backtest([5.0, 6.0, 7.0])
    assert short["holdout"] == 0 and short["wape"] is None


def test_band_widens_with_horizon_and_backtest_error():
    series = [100.0, 130.0, 90.0, 140.0, 110.0, 95.0, 150.0, 105.0, 120.0,
              85.0, 135.0, 100.0, 145.0, 90.0, 125.0]
    r = fc.smart_forecast(series, h=6)
    w = [r["upper"][k] - r["lower"][k] for k in range(6)]
    assert w[-1] >= w[0], "interval should not shrink with horizon"
    # band std must be at least the raw in-sample residual std (never narrower)
    resid = [series[t] - r["fitted"][t] for t in range(len(series))
             if r["fitted"][t] is not None]
    assert r["resid_std"] >= fc._std(resid) - 1e-9


def test_repeat_calls_identical():
    # memoised fits must never leak mutated state between calls
    series = [50.0, 60.0, 55.0, 70.0, 65.0, 80.0, 75.0, 90.0, 85.0, 100.0]
    a = fc.smart_forecast(series, h=4)
    b = fc.smart_forecast(series, h=4)
    assert a["point"] == b["point"] and a["lower"] == b["lower"] \
        and a["upper"] == b["upper"] and a["method"] == b["method"]


def test_month_range_contiguous():
    from exports.excel import month_range
    assert month_range("2025-11", "2026-02") == ["2025-11", "2025-12", "2026-01", "2026-02"]
    assert month_range("2026-03", "2026-03") == ["2026-03"]
    assert month_range("2026-05", "2026-04") == []
    assert month_range(None, "2026-04") == []


if __name__ == "__main__":
    import sys, traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print()
    print("ALL PASSED" if not failed else f"{failed} FAILURES")
    sys.exit(1 if failed else 0)
