"""Carga de candles diários para backtest, com cache local em CSV (pasta data_cache/, fora do git).

O índice é normalizado para a data do pregão em Nova York, sem fuso.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from agent.config.settings import PROJECT_ROOT

NY = ZoneInfo("America/New_York")
CACHE_DIR = PROJECT_ROOT / "data_cache"


def normalize_daily_index(df: pd.DataFrame) -> pd.DataFrame:
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(NY).tz_localize(None)
    out = df.copy()
    out.index = idx.normalize()
    out.index.name = "date"
    return out[~out.index.duplicated(keep="last")].sort_index()


def load_daily(settings, symbols: list[str], start: date, end: date,
               cache_dir: Path = CACHE_DIR, refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Candles diários ajustados de start a end (inclusive). Usa o cache quando existe."""
    from agent.data import market_data

    cache_dir.mkdir(parents=True, exist_ok=True)
    out, missing = {}, []
    for s in symbols:
        f = cache_dir / f"{s}_{start}_{end}.csv"
        if f.exists() and not refresh:
            out[s] = pd.read_csv(f, index_col="date", parse_dates=["date"])
        else:
            missing.append(s)
    if missing:
        fetched = market_data.daily_bars(settings, missing, start, end, complete_only=False)
        for s in missing:
            if s not in fetched:
                raise RuntimeError(f"sem dados para {s}")
            df = normalize_daily_index(fetched[s])
            df = df[(df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))]
            df.to_csv(cache_dir / f"{s}_{start}_{end}.csv")
            out[s] = df
    return out
