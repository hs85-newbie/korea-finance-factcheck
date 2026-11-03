"""교환·합병 비율의 방향이 공시 원문과 거꾸로 적혔는지 본다.

WHY 2026-11-03: 공시의 "A : B = 1 : x" 를 "A 1주당 B x주" 로 거꾸로 푼 문장이 두 번 나왔다
    (딥다이브 2242 우리금융↔동양생명은 4월부터 공개 상태, 개념 010 이마트↔신세계푸드는 발행 전 정정).
    맞는 뜻은 "B 1주당 A x주" 다. 공시 본문에는 "B 보통주식 1주당 A 보통주식 x주를 교부" 문장이
    따로 있으니, 본문의 '1주당' 문장을 그 문장과 회사 순서까지 대조한다.

판정은 '같은 숫자 x 를 두고 주는 쪽·받는 쪽이 뒤바뀐 경우'만 잡는다. 숫자가 다르거나 회사를 못 찾으면
말하지 않는다. DART 조회가 안 되면 검사를 생략한다(발행을 막지 않는다). 생략 사유는 결과에 남는다.
"""
from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

# "동양생명보험(주) 보통주식 1주당 (주)우리금융지주 보통주식 0.2521056주" / "신세계푸드 1주당 이마트 0.5031313주"
_CLAIM_RE = re.compile(
    r"([^\s\d,.:·→]{2,})\s*(?:보통주식?|주식)?\s*1주당\s*([^\s\d,.:·]{2,})[^\d\n]{0,25}?(\d+\.\d{2,})\s*주")
# "(주)우리금융지주 : 동양생명보험(주) = 1 : 0.2521056" — 뒤 회사 1주당 앞 회사 x주라는 뜻
_NOTATION_RE = re.compile(r"([^\s\d,.:=]{2,})\s*:\s*([^\s\d,.:=]{2,})\s*=\s*1\s*:\s*(\d+\.\d+)")
_RCEPT_RE = re.compile(r"\b(20\d{12})\b")
_CORP_RE = re.compile(r"\(주\)|㈜|주식회사|\s")

Fetcher = Callable[[str], Optional[str]]


def _norm(name: str) -> str:
    """회사 이름 앞 두 글자. '(주)우리금융지주가' 와 '우리금융' 을 같은 회사로 본다."""
    return _CORP_RE.sub("", name)[:2]


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))


def claims(text: str) -> list:
    """(주는 쪽, 받는 쪽, 비율 문자열) 목록."""
    return [(m.group(1), m.group(2), m.group(3)) for m in _CLAIM_RE.finditer(_plain(text))]


def truths(text: str) -> list:
    """(주는 쪽, 받는 쪽, 비율) — '1주당' 문장과 'A : B = 1 : x' 표기(= B 1주당 A x주) 양쪽에서."""
    out = [(_norm(g), _norm(r), float(x)) for g, r, x in claims(text)]
    out += [(_norm(b), _norm(a), float(x)) for a, b, x in _NOTATION_RE.findall(_plain(text))]
    return out


def _same(x: str, y: float) -> bool:
    """본문 자릿수만큼 반올림해 같은가. '6.08' 과 '6.0800000' 은 같다."""
    d = len(x.split(".")[1])
    return abs(float(x) - y) <= 0.5 * 10 ** -d + 1e-12


def find_reversed(article: str, filing: str) -> list:
    """본문 주장 중 공시(또는 본문 안의 공시 표기)와 주는 쪽·받는 쪽이 뒤바뀐 것."""
    truth = truths(filing) + truths(article)
    out = []
    for g, r, x in claims(article):
        for tg, tr, tx in truth:
            if _same(x, tx) and tg != tr and (_norm(g), _norm(r)) == (tr, tg):
                out.append({"claim": f"{g} 1주당 {r} {x}주", "filing": f"{tg}… 1주당 {tr}… {x}주"})
                break
    return out


def _default_fetch(rcept_no: str) -> Optional[str]:
    key = os.getenv("DART_API_KEY", "")
    if not key:
        return None
    r = requests.get("https://opendart.fss.or.kr/api/document.xml", timeout=30,
                     params={"crtfc_key": key, "rcept_no": rcept_no})
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    return z.read(z.namelist()[0]).decode("utf-8", "ignore")


def check(text: str, fetch: Optional[Fetcher] = None) -> dict:
    """본문에 적힌 접수번호의 공시와 대조한다. {"errors": [...], "skipped": 사유 또는 ""}"""
    if not claims(text):
        return {"errors": [], "skipped": "비율 문장 없음"}
    rcepts = list(dict.fromkeys(_RCEPT_RE.findall(_plain(text))))
    if not rcepts:
        # 공시 조회는 못 해도 본문 안의 'A : B = 1 : x' 표기와는 대조한다
        errors = find_reversed(text, "")
        return {"errors": errors, "skipped": "" if errors else "접수번호 없음"}
    fetch = fetch or _default_fetch
    errors, failed = [], []
    for rc in rcepts[:5]:
        try:
            filing = fetch(rc)
        except Exception as e:  # noqa: BLE001 — 조회 실패는 검사 생략으로 남긴다
            logger.warning(f"[비율 방향] DART {rc} 조회 실패: {e}")
            filing = None
        if filing is None:
            failed.append(rc)
            continue
        errors += find_reversed(text, _plain(filing))
    skipped = f"DART 조회 실패 {len(failed)}건" if failed and not errors else ""
    return {"errors": errors, "skipped": skipped}


def summary(errors: list) -> str:
    e = errors[0]
    return (f"비율 방향 역전 {len(errors)}건 — 본문 '{e['claim']}' 은 공시와 주는 쪽·받는 쪽이 반대"
            f"(공시: {e['filing']})")
