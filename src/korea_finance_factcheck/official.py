"""시장 수치 대조용 공식 데이터 조회 — 미 재무부 CSV · 한국은행 ECOS.

market_fact_check 가 쓴다. 조회만 한다. 판정은 거기서 한다.
"""
from __future__ import annotations

import csv
import io
import os
import time
from datetime import date

import requests

_UA = {"User-Agent": "Mozilla/5.0 korea-finance-factcheck"}
_TREASURY = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
             "daily-treasury-rates.csv/{y}/all?type=daily_treasury_yield_curve"
             "&field_tdr_date_value={y}&page&_format=csv")
_ECOS = "https://ecos.bok.or.kr/api/StatisticSearch/{key}/json/kr/1/1000/{stat}/D/{s}/{e}/{item}"
_SERIES = {"kospi": ("802Y001", "0001000"), "fx": ("731Y001", "0000001"),
           "bok": ("722Y001", "0101000")}

def _get(url: str) -> requests.Response:
    """GET. 네트워크 오류·5xx 만 재시도한다(1s→2s→4s)."""
    err = ""
    for i in range(3):
        try:
            r = requests.get(url, headers=_UA, timeout=20)
            if r.status_code < 500:
                r.raise_for_status()
                return r
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = type(e).__name__
        time.sleep(2 ** i)
    raise RuntimeError(f"조회 실패: {err}")


def fetch_treasury(year: int) -> dict:
    """{date: {2: 4.89, 5: .., 10: .., 30: ..}}. 열 이름으로 찾는다 — 위치로 찾으면 오늘 사고가 난다."""
    rows = csv.DictReader(io.StringIO(_get(_TREASURY.format(y=year)).text))
    out = {}
    for r in rows:
        m, d, y = (int(x) for x in r["Date"].split("/"))
        out[date(y, m, d)] = {n: float(r[f"{n} Yr"]) for n in (2, 5, 10, 30) if r.get(f"{n} Yr")}
    return out


def fetch_ecos(kind: str, start: date, end: date) -> dict:
    key = (os.getenv("ECOS_API_KEY") or os.getenv("BOK_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("ECOS_API_KEY 없음")
    stat, item = _SERIES[kind]
    url = _ECOS.format(key=key, stat=stat, item=item,
                       s=start.strftime("%Y%m%d"), e=end.strftime("%Y%m%d"))
    rows = _get(url).json().get("StatisticSearch", {}).get("row", [])
    return {date(int(r["TIME"][:4]), int(r["TIME"][4:6]), int(r["TIME"][6:])): float(r["DATA_VALUE"])
            for r in rows}
