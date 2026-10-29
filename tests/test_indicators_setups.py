"""Os valores esperados foram calculados com o código original do day-trader-skill
(trader-scanner/scan.py, funções rsi e find_setups) em 28 out 2026."""
import pandas as pd
import pytest

from agent.quant.indicators import atr, ewma_volatility, rsi_wilder, sma
from agent.quant.setups import find_setups

SERIES = [100.0, 99.49, 100.51, 100.06, 99.43, 97.58, 97.16, 99.32, 100.16, 102.24, 102.75, 103.56,
          103.94, 100.48, 102.2, 103.24, 104.27, 100.74, 97.23, 95.5, 94.61, 95.19, 95.1, 96.09, 94.86,
          95.45, 96.2, 94.93, 98.19, 99.28, 101.66, 100.4, 98.92, 98.24, 98.03, 99.27, 99.76, 98.87,
          96.98, 95.97, 98.31, 96.72, 97.19, 98.02, 95.1, 95.19, 97.68, 93.74, 93.14, 92.94, 91.42,
          92.33, 92.21, 89.51, 90.99, 92.21, 93.95, 96.66, 97.36, 97.59]


def test_rsi_matches_reference():
    assert rsi_wilder(SERIES) == pytest.approx(56.55379797669632, abs=1e-12)
    assert rsi_wilder(SERIES[:-1]) == pytest.approx(56.016204647190214, abs=1e-12)


def test_rsi_needs_enough_data_and_handles_no_losses():
    assert rsi_wilder([1.0] * 14) is None
    assert rsi_wilder([float(i) for i in range(1, 20)]) == 100.0


def test_setups_match_reference_no_signal():
    tags, nums = find_setups(SERIES)
    assert tags == []
    assert nums["high20"] == 98.31
    assert nums["ma20"] == pytest.approx(94.613)
    assert nums["run_pct"] == pytest.approx(-4.321766561514195)
    assert nums["range5_pct"] == pytest.approx(5.512859924172568)


def test_setups_match_reference_oversold_bounce():
    closes = [100 - i * 0.8 for i in range(40)] + [69.5]
    tags, nums = find_setups(closes)
    assert tags == ["oversold", "oversold_bounce"]
    assert nums["rsi"] == pytest.approx(6.306306306306325)


def test_setup_breakout_20d():
    closes = [50.0] * 35 + [55.0]
    tags, _ = find_setups(closes)
    assert tags == ["breakout_20d"]  # c[-2] == média anterior, então reclaim_ma20 não dispara


def test_setup_reclaim_ma20():
    closes = [50.0] * 34 + [49.0, 51.0]
    tags, _ = find_setups(closes)
    assert "reclaim_ma20" in tags


def test_setups_reject_short_history():
    with pytest.raises(ValueError):
        find_setups([1.0] * 29)


def test_sma_ewma_atr_shapes():
    s = pd.Series(SERIES)
    assert sma(s, 20).isna().sum() == 19
    assert sma(s, 20).iloc[-1] == pytest.approx(sum(SERIES[-20:]) / 20)
    vol = ewma_volatility(s)
    assert vol.iloc[-1] > 0
    df = pd.DataFrame({"high": s * 1.01, "low": s * 0.99, "close": s})
    assert atr(df).iloc[-1] > 0
