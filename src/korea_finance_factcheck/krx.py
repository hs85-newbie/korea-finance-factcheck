"""종목 종가를 한국거래소(KRX) 공식 종가와 맞춰 본다.

본문에 '삼성전자(005930)'처럼 이름과 종목코드가 한 번 나온 종목만 본다. 같은 문장에 '종가·마감'이 있는
'○○원'만 종가 주장으로 친다(목표주가·매수가 같은 다른 원 단위 숫자를 잡지 않으려고).
등락률은 보지 않는다. 기간 수익률('9월 30일 이후 18.8%')을 하루 등락으로 오인한 일이 있었다.

날짜는 숫자 앞에 마지막으로 나온 'M월 D일'로 본다. 날짜가 없으면 기준일 이전 닷새 거래일 가운데
하나와 맞으면 통과시킨다. KRX Open API 약관상 비상업 목적에만 쓸 수 있고 결과에 'KRX 통계정보'를
밝혀야 한다. 키는 사용자 것(KRX_API_KEY)을 쓴다.
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Callable, Optional

import requests

_URL = "http://data-dbg.krx.co.kr/svc/apis/sto/{market}?basDd={d}"
_MARKETS = ("stk_bydd_trd", "ksq_bydd_trd")   # 유가증권·코스닥
_PAIR = re.compile(r"(?<![가-힣A-Za-z0-9&])([가-힣A-Za-z&][가-힣A-Za-z0-9&]{0,29})\s?\((\d{6})\)")
_PRICE = re.compile(r"(?<![\d,.])(\d+)만\s*(\d{1,3}(?:,\d{3})?|\d{1,4})?\s*원|"
                    r"(?<![\d,.만조억])(\d{1,3}(?:,\d{3})+|\d+)\s*원")
_DATE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일")
_CLOSE = re.compile(r"종가|마감|장을 마쳤|거래를 마쳤")
_LOOKBACK = 5

Fetcher = Callable[[str, str], list]   # (시장, YYYYMMDD) → 그날 행 목록


def _won(m: re.Match) -> int:
    if m.group(1):
        return int(m.group(1)) * 10_000 + int((m.group(2) or "0").replace(",", ""))
    return int(m.group(3).replace(",", ""))


def _plain(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "\n", text or ""))


def claims(text: str, ref: dt.date) -> list:
    """[(코드, 이름, 원, 날짜 또는 None, 문장)] — 이름이나 코드가 있고 '종가·마감'이 함께 있는 문장만."""
    plain = _plain(text)
    names = {code: name for name, code in _PAIR.findall(plain)}
    out = []
    for sent in re.split(r"(?<=[.!?。])\s+|\n", plain):
        if not _CLOSE.search(sent):
            continue
        for code, name in names.items():
            if name not in sent and code not in sent:
                continue
            for m in _PRICE.finditer(sent):
                dm = [d for d in _DATE.finditer(sent) if d.start() < m.start()]
                when = None
                if dm:
                    mo, dd = int(dm[-1].group(1)), int(dm[-1].group(2))
                    when = dt.date(ref.year - (mo > ref.month), mo, dd)
                out.append((code, name, _won(m), when, sent.strip()[:80]))
    return out


def _default_fetch(market: str, d: str) -> list:
    key = os.getenv("KRX_API_KEY", "").strip()
    if not key:
        raise RuntimeError("KRX_API_KEY 없음")
    r = requests.get(_URL.format(market=market, d=d), timeout=20,
                     headers={"AUTH_KEY": key, "User-Agent": "korea-finance-factcheck"})
    r.raise_for_status()
    return r.json().get("OutBlock_1", []) or []


def _close(code: str, day: dt.date, fetch: Fetcher, cache: dict) -> Optional[int]:
    k = day.strftime("%Y%m%d")
    if k not in cache:
        cache[k] = {r["ISU_CD"]: int(str(r["TDD_CLSPRC"]).replace(",", ""))
                    for m in _MARKETS for r in fetch(m, k) if r.get("TDD_CLSPRC")}
    return cache[k].get(code)


def check(text: str, ref: dt.date, fetch: Optional[Fetcher] = None) -> dict:
    """{"errors": [...], "unverified": [...], "skipped": 사유}. 주말·휴장일은 행이 없어 건너뛴다."""
    found = claims(text, ref)
    if not found:
        return {"errors": [], "unverified": [], "skipped": "종가 문장 없음"}
    fetch, cache = fetch or _default_fetch, {}
    errors, unverified = [], []
    try:
        for code, name, won, when, sent in found:
            days = [when] if when else [ref - dt.timedelta(days=i) for i in range(1, _LOOKBACK + 3)]
            actual = {d: _close(code, d, fetch, cache) for d in days}
            actual = {d: v for d, v in actual.items() if v is not None}
            if not actual:
                unverified.append(f"{name}({code}) {won:,}원 — {when or '기간 내'} KRX 종가 없음(휴장일·상장 여부 확인)")
            elif won not in actual.values():
                shown = ", ".join(f"{d:%m/%d} {v:,}원" for d, v in sorted(actual.items()))
                errors.append({"claim": sent, "stock": f"{name}({code})", "written": won, "krx": shown})
    except Exception as e:  # noqa: BLE001 — 조회 실패는 막지 않고 사유를 남긴다
        return {"errors": errors, "unverified": unverified, "skipped": f"KRX 조회 실패: {type(e).__name__}: {e}"}
    return {"errors": errors, "unverified": unverified, "skipped": "", "source": "KRX 통계정보"}
