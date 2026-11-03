"""KRX 종가 검사 — 실제 KRX data-dbg 응답(2026-10-22~24 조회분)으로 확인한다."""
import datetime as dt
import json
from pathlib import Path

from korea_finance_factcheck import krx

FIX = json.loads((Path(__file__).parent / "fixtures/krx_stk_bydd_trd_20261022-24.json").read_text(encoding="utf-8"))
REF = dt.date(2026, 10, 24)


def fetch(market, d):
    return FIX.get(d, []) if market == "stk_bydd_trd" else []


def test_맞는_종가는_통과한다():
    text = "삼성전자(005930)는 10월 22일 214,500원에 장을 마쳤다."
    assert krx.check(text, REF, fetch)["errors"] == []


def test_다른_날_종가를_적으면_잡는다():
    # 10/23 종가 215,500원을 10/22 종가라고 쓴 경우
    res = krx.check("삼성전자(005930)는 10월 22일 종가 215,500원을 기록했다.", REF, fetch)
    assert res["errors"] and res["errors"][0]["krx"] == "10/22 214,500원"


def test_한글_만_단위도_읽는다():
    assert krx.check("SK하이닉스(000660) 10월 23일 종가 127만7,000원.", REF, fetch)["errors"] == []
    assert krx.check("SK하이닉스(000660) 10월 23일 종가 127만원.", REF, fetch)["errors"]


def test_날짜가_없으면_최근_거래일_중_하나와_맞으면_통과():
    assert krx.check("삼성전자(005930)는 215,500원으로 마감했다.", REF, fetch)["errors"] == []


def test_종가_마감이_없는_원_숫자는_보지_않는다():
    res = krx.check("삼성전자(005930) 목표주가는 300,000원이다.", REF, fetch)
    assert res["skipped"] == "종가 문장 없음"


def test_등락률은_보지_않는다():
    res = krx.check("삼성전자(005930)는 9월 30일 이후 18.8% 하락했다.", REF, fetch)
    assert res["skipped"] == "종가 문장 없음"


def test_조회_실패는_막지_않고_사유를_남긴다():
    def boom(m, d):
        raise RuntimeError("KRX_API_KEY 없음")
    res = krx.check("삼성전자(005930) 10월 22일 종가 214,500원.", REF, boom)
    assert res["errors"] == [] and "KRX_API_KEY 없음" in res["skipped"]
