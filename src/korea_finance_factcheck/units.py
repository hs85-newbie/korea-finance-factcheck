"""본문의 기업 실적 금액을 DART 와 맞춰 10배·100배 단위 오기를 잡는다.

WHY 2026-10-12: 공개 글 8편에서 매출·영업이익이 10배·100배로 틀려 있었다
    (12619 SK가스 '405조' / 4047 카카오뱅크 '3,086억' 등). 원인이던 scraper 단위 꼬리표는
    PR #186 으로 고쳤지만 모델이 숫자를 옮기며 틀리는 경우는 남는다. 사람이 매번 전수
    대조하지 않도록 발행 직전에 기계가 본다. (#187)

판정을 '10^n 배 어긋남'으로 좁힌 이유:
    증권사 분기 전망·잠정치처럼 연간 DART 값과 원래 다른 숫자가 본문에 많다. 그걸 다 걸면
    경고가 매번 떠서 사람이 안 보게 된다. 단위 오기는 자리만 옮긴 모양이라 비율이 10^n 에
    딱 붙는다 — 이 모양만 잡는다. 같은 회사·같은 계정끼리만 비교한다(이익률이 우연히 10%인
    매출↔영업이익 짝은 단위 오기가 아니다).

DART 조회가 안 되면 검사를 생략한다(발행을 막지 않는다). 생략 사유는 결과에 남는다.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_TOL = 0.03
_RATIOS = (10, 100, 1000, 0.1, 0.01, 0.001)
_CONTEXT = 300   # 문장 앞쪽에서 회사를 찾는 범위(자)

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_BLOCK_END_RE = re.compile(r"</(?:p|li|td|th|h\d|div)>|<br\s*/?>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_SENT_RE = re.compile(r"(?:[^.\n]|\.(?=\d))+")   # 소수점(2.6조)에서 자르지 않는다
# WHY: 이름 길이를 막지 않으면 긴 한글 덩어리에서 매 위치마다 끝까지 훑어 느려진다(6천 자에 8초)
_PAIR_RE = re.compile(r"(?<![가-힣A-Za-z0-9&])([가-힣A-Za-z&][가-힣A-Za-z0-9&]{0,29})\s?\((\d{6})\)")
_AMT_RE = re.compile(
    r"(매출(?:액)?|영업이익|당기순이익|순이익)[^.\n]{0,25}?"
    r"(\d[\d,]*(?:\.\d+)?\s?조(?:\s?\d[\d,]*\s?억)?|\d[\d,]*(?:\.\d+)?\s?억)\s?원")
_ACCOUNT = {"매출": "매출액", "매출액": "매출액", "영업이익": "영업이익",
            "순이익": "당기순이익", "당기순이익": "당기순이익"}

Fetcher = Callable[[str], list]   # 종목코드 → [(계정명, 금액원), ...]


def _plain(content: str) -> str:
    text = _BLOCK_END_RE.sub("\n", _COMMENT_RE.sub(" ", content or ""))
    text = _TAG_RE.sub(" ", text)
    return re.sub(r"[ \t]+", " ", text)


def to_won(s: str) -> Optional[float]:
    """'4조 565억' → 4.0565e12. 조·억이 없으면 None."""
    m = re.fullmatch(r"(?:([\d.]+)조)?(?:([\d.]+)억)?", s.replace(",", "").replace(" ", ""))
    if not m or not (m.group(1) or m.group(2)):
        return None
    try:
        return float(m.group(1) or 0) * 1e12 + float(m.group(2) or 0) * 1e8
    except ValueError:
        return None


def extract(content: str) -> list:
    """본문에서 (종목코드, 계정, 원문, 금액원) 목록을 뽑는다. 회사는 문장 직전 문맥의 마지막 언급."""
    text = _plain(content)
    names = {m.group(1): m.group(2) for m in _PAIR_RE.finditer(text)}
    if not names:
        return []
    name_rx = re.compile("|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
                         + r"|\((\d{6})\)")
    out = []
    for sm in _SENT_RE.finditer(text):
        hits = list(name_rx.finditer(text, max(0, sm.start() - _CONTEXT), sm.end()))
        if not hits:
            continue
        code = hits[-1].group(1) or names.get(hits[-1].group(0))
        for am in _AMT_RE.finditer(sm.group(0)):
            won = to_won(am.group(2))
            if code and won and won >= 1e9:
                out.append((code, _ACCOUNT[am.group(1)], am.group(0).strip(), won))
    return out


def _default_fetch(code: str) -> list:
    """최근 2개 사업연도 사업보고서의 매출·영업이익·순이익(연결·별도, 당기·전기)."""
    from . import dart

    corp = dart.corp_code(code)
    if not corp:
        return []
    this_year = _dt.date.today().year
    vals = []
    for yr in (this_year - 1, this_year - 2):
        data = dart.get("fnlttSinglAcnt.json", {"corp_code": corp, "bsns_year": str(yr), "reprt_code": "11011"})
        for row in (data or {}).get("list", []):
            if row.get("account_nm") not in ("매출액", "영업이익", "당기순이익"):
                continue
            for key in ("thstrm_amount", "frmtrm_amount"):
                try:
                    vals.append((row["account_nm"], float(str(row.get(key, "")).replace(",", ""))))
                except ValueError:
                    pass
    return vals


def _unit_ratio(won: float, dart: list) -> Optional[float]:
    """정확히 맞는 값이 있으면 None, 10^n 배로 어긋난 값이 있으면 그 배수."""
    values = [v for v in dart if v]
    if any(abs(won - v) / abs(v) < _TOL for v in values):
        return None
    for v in values:
        for f in _RATIOS:
            if abs(won / v / f - 1) < _TOL:
                return f
    return None


def find_unit_errors(content: str, fetch: Optional[Fetcher] = None) -> dict:
    """단위 오기 후보. {"errors": [{code, account, text, ratio}], "skipped": str}."""
    items = extract(content)
    if not items:
        return {"errors": [], "skipped": ""}
    fetch = fetch or _default_fetch
    cache: dict = {}
    errors = []
    try:
        for code, account, text, won in items:
            if code not in cache:
                cache[code] = fetch(code)
            same = [v for acc, v in cache[code] if acc == account]
            ratio = _unit_ratio(won, same) if same else None
            if ratio:
                errors.append({"code": code, "account": account, "text": text, "ratio": ratio})
    except Exception as e:  # 검사 실패가 발행을 막지 않게 — 사유는 남긴다
        logger.warning(f"[수치대조] DART 대조 생략: {e}")
        return {"errors": errors, "skipped": f"DART 대조 실패: {e}"}
    if not any(cache.values()):
        return {"errors": [], "skipped": "DART 값 없음(키 미설정·조회 실패)"}
    return {"errors": errors, "skipped": ""}


def summary(errors: list) -> str:
    """게이트 사유 한 줄."""
    def _r(f: float) -> str:
        return f"{f:g}배" if f >= 1 else f"1/{1 / f:g}"
    return "DART 대조 단위 오기 의심 %d건: %s" % (
        len(errors), " / ".join(f"{e['code']} '{e['text']}'({_r(e['ratio'])})" for e in errors[:3]))
