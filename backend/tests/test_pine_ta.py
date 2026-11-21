import math
import numpy as np
import pandas as pd
import pytest

from app.services import pine_ta as pine


def test_highest_and_lowest():
    s = pd.Series([1.0, 5.0, 3.0, 7.0, 2.0])
    h = pine.highest(s, 3)
    l = pine.lowest(s, 3)
    assert np.isnan(h.iloc[1])
    assert h.iloc[2] == 5.0
    assert h.iloc[3] == 7.0
    assert h.iloc[4] == 7.0
    assert l.iloc[2] == 1.0
    assert l.iloc[3] == 3.0
    assert l.iloc[4] == 2.0


def test_sma_length_validation_and_values():
    with pytest.raises(ValueError, match="length must be >= 1"):
        pine.sma(pd.Series([1.0]), 0)

    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    res = pine.sma(s, 2)
    assert np.isnan(res.iloc[0])
    assert res.iloc[1] == 15.0
    assert res.iloc[2] == 25.0
    assert res.iloc[3] == 35.0


def test_ema_seeded_by_first_full_sma():
    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    res = pine.ema(s, 3)
    # length=3: seed at index 2 is SMA(10, 20, 30) = 20.0
    assert np.isnan(res.iloc[0])
    assert np.isnan(res.iloc[1])
    assert res.iloc[2] == pytest.approx(20.0)
    # alpha = 2 / (3 + 1) = 0.5
    # index 3: 0.5 * 40 + 0.5 * 20 = 30.0
    assert res.iloc[3] == pytest.approx(30.0)


def test_rma_wilder_smoothing():
    s = pd.Series([10.0, 20.0, 30.0, 40.0])
    res = pine.rma(s, 3)
    # seed at index 2 is 20.0
    assert res.iloc[2] == pytest.approx(20.0)
    # alpha = 1 / 3
    # index 3: (1/3)*40 + (2/3)*20 = 40/3 + 40/3 = 80/3 = 26.6667
    assert res.iloc[3] == pytest.approx(80.0 / 3.0)


def test_wma_linear_weights():
    s = pd.Series([1.0, 2.0, 3.0])
    res = pine.wma(s, 3)
    # weights: 1, 2, 3 -> sum=6. (1*1 + 2*2 + 3*3)/6 = (1 + 4 + 9)/6 = 14/6 = 7/3
    assert res.iloc[2] == pytest.approx(14.0 / 6.0)


def test_hma_computation():
    s = pd.Series(range(30), dtype=float)
    res = pine.hma(s, 9)
    assert pd.notna(res.iloc[-1])


def test_vwma_volume_weighting():
    close = pd.Series([10.0, 20.0, 30.0])
    volume = pd.Series([100.0, 200.0, 300.0])
    res = pine.vwma(close, volume, 2)
    # index 1: (10*100 + 20*200) / (100 + 200) = (1000 + 4000) / 300 = 5000 / 300 = 16.6667
    assert res.iloc[1] == pytest.approx(5000.0 / 300.0)
    # index 2: (20*200 + 30*300) / (200 + 300) = (4000 + 9000) / 500 = 13000 / 500 = 26.0
    assert res.iloc[2] == pytest.approx(26.0)


def test_dev_and_cci_pine_mad():
    s = pd.Series([10.0] * 19 + [20.0])
    # For length 20: 19 tens and one 20. Mean = (190 + 20) / 20 = 10.5
    # Abs diffs: 19 * |10 - 10.5| + 1 * |20 - 10.5| = 19 * 0.5 + 9.5 = 9.5 + 9.5 = 19.0
    # Mean dev = 19.0 / 20 = 0.95
    d = pine.dev(s, 20)
    assert d.iloc[-1] == pytest.approx(0.95)
    c = pine.cci(s, 20)
    expected_cci = (20.0 - 10.5) / (0.015 * 0.95)
    assert c.iloc[-1] == pytest.approx(expected_cci)


def test_rsi_matches_wilder_bounds():
    s = pd.Series(range(50), dtype=float)
    r = pine.rsi(s, 14)
    assert r.iloc[-1] == pytest.approx(100.0)

    s_down = pd.Series(range(50, 0, -1), dtype=float)
    r_down = pine.rsi(s_down, 14)
    assert r_down.iloc[-1] == pytest.approx(0.0)

    s_flat = pd.Series([50.0] * 50)
    r_flat = pine.rsi(s_flat, 14)
    assert r_flat.iloc[-1] == pytest.approx(50.0)


def test_stoch_and_stoch_full():
    high = pd.Series([10.0, 12.0, 15.0, 14.0, 16.0, 13.0])
    low = pd.Series([8.0, 9.0, 11.0, 10.0, 12.0, 11.0])
    close = pd.Series([9.0, 11.0, 14.0, 12.0, 15.0, 12.0])
    k, d = pine.stoch_full(high, low, close, 3, 2, 2)
    assert pd.notna(k.iloc[-1])
    assert pd.notna(d.iloc[-1])


def test_dmi_directional_movement():
    high = pd.Series(np.linspace(10, 50, 40))
    low = high - 2.0
    close = high - 1.0
    pdi, ndi, adx = pine.dmi(high, low, close, 14, 14)
    assert pd.notna(adx.iloc[-1])
    assert pdi.iloc[-1] > ndi.iloc[-1]


def test_macd_values():
    close = pd.Series(np.linspace(100, 200, 60))
    m, s, h = pine.macd(close, 12, 26, 9)
    assert pd.notna(m.iloc[-1])
    assert pd.notna(s.iloc[-1])
    assert h.iloc[-1] == pytest.approx(m.iloc[-1] - s.iloc[-1])


def test_awesome_oscillator():
    high = pd.Series(np.linspace(10, 50, 50))
    low = high - 2.0
    ao = pine.awesome_oscillator(high, low)
    assert pd.notna(ao.iloc[-1])


def test_williams_r_range():
    high = pd.Series([10.0, 12.0, 15.0, 14.0])
    low = pd.Series([8.0, 9.0, 11.0, 10.0])
    close = pd.Series([9.0, 11.0, 14.0, 12.0])
    wr = pine.williams_r(high, low, close, 3)
    # highest high in last 3: max(12, 15, 14) = 15
    # lowest low in last 3: min(9, 11, 10) = 9
    # close: 12.0 -> 100 * (12 - 15) / (15 - 9) = 100 * (-3) / 6 = -50.0
    assert wr.iloc[-1] == pytest.approx(-50.0)


def test_ultimate_oscillator():
    high = pd.Series(np.linspace(10, 50, 60))
    low = high - 2.0
    close = high - 1.0
    uo = pine.ultimate_oscillator(high, low, close, 7, 14, 28)
    assert 0.0 <= uo.iloc[-1] <= 100.0


def test_ichimoku_components():
    high = pd.Series(np.linspace(10, 100, 80))
    low = high - 5.0
    close = high - 2.5
    tenkan, kijun, span1, span2, chikou = pine.ichimoku(high, low, close)
    assert pd.notna(tenkan.iloc[-1])
    assert pd.notna(kijun.iloc[-1])
    assert pd.notna(span1.iloc[-1])
    assert pd.notna(span2.iloc[-1])
    assert chikou.iloc[-1] == close.iloc[-1]


def test_crossover_and_crossunder():
    a = pd.Series([1.0, 2.0, 4.0, 3.0])
    b = pd.Series([2.0, 2.0, 3.0, 5.0])
    co = pine.crossover(a, b)
    cu = pine.crossunder(a, b)
    # index 0: shift(1) is NaN -> False
    assert not co.iloc[0]
    # index 1: a=2, b=2 -> a > b is False -> False
    assert not co.iloc[1]
    # index 2: a=4 > b=3, a[1] <= b[1] (2 <= 2 is True) -> True!
    assert co.iloc[2]
    # index 3: a=3 < b=5, a[2] >= b[2] (4 >= 3 is True) -> True!
    assert cu.iloc[3]


def test_sign():
    s = pd.Series([-5.0, 0.0, 10.0, np.nan])
    res = pine.sign(s)
    assert res.iloc[0] == -1.0
    assert res.iloc[1] == 0.0
    assert res.iloc[2] == 1.0
    assert np.isnan(res.iloc[3])
