"""Shared dataframe option builders for secondary tabs."""

from __future__ import annotations

from typing import Any

import pandas as pd


def collect_year_split_league_options(df: pd.DataFrame) -> tuple[list[int], list[str], list[str]]:
    years: list[int] = []
    splits: list[str] = []
    leagues: list[str] = []
    try:
        if df is not None and not df.empty:
            if "year" in df.columns:
                years = sorted([int(x) for x in pd.to_numeric(df["year"], errors="coerce").dropna().unique().tolist()])
            if "split" in df.columns:
                splits = sorted([str(x) for x in df["split"].fillna("").astype(str).unique().tolist() if str(x)])
            if "league" in df.columns:
                leagues = sorted([str(x) for x in df["league"].fillna("").astype(str).unique().tolist() if str(x)])
    except Exception:
        pass
    return years, splits, leagues



def split_options(df: pd.DataFrame) -> list[str]:
    _, splits, _ = collect_year_split_league_options(df)
    return splits


def league_options(df: pd.DataFrame) -> list[str]:
    _, _, leagues = collect_year_split_league_options(df)
    return leagues


def filter_by_league(df: pd.DataFrame, league: Any) -> pd.DataFrame:
    if not league or df is None or df.empty or "league" not in df.columns:
        return df
    return df[df["league"].astype(str) == str(league)].copy()


def filter_by_year(df: pd.DataFrame, year: Any) -> pd.DataFrame:
    if not year or df is None or df.empty or "year" not in df.columns:
        return df
    try:
        return df[pd.to_numeric(df["year"], errors="coerce") == int(year)].copy()
    except Exception:
        return df
