"""비율 방향 역전 검사 — 공시 원문 문장(DART document.xml, 2026-11-03 조회)과 실제로 틀렸던 본문 문장으로 확인한다.

2242(우리금융↔동양생명)와 개념 010(이마트↔신세계푸드)에서 'A : B = 1 : x' 를 'A 1주당 B x주' 로 거꾸로 풀었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from korea_finance_factcheck import ratio as rc  # noqa: E402

# DART 20260424000498 (우리금융지주 주식교환) 본문 그대로
WOORI = ("3. 교환ㆍ이전 비율 (주)우리금융지주 : 동양생명보험(주) = 1 : 0.2521056 ... 그 대가로 주식교환 대상주주에게 "
         "동양생명보험(주) 보통주식 1주당 (주)우리금융지주 보통주식 0.2521056주를 교환하여 지급합니다.")
# DART 20260716000543 (이마트 주식교환) 본문 그대로
EMART = ("(주)이마트 : (주)신세계푸드 = 1:0.5031313 ... 그 대가로 주식교환 대상주주에게 (주)신세계푸드 보통주식 1주당 "
         "(주)이마트가 보유한 보통주 자기주식 0.5031313주를 교환하여 지급합니다.")


def test_2242_의_틀렸던_문장을_잡는다():
    errs = rc.find_reversed("교환 비율은 우리금융 1주당 동양생명 0.2521056주이고, 신주는 869만 주입니다.", WOORI)
    assert errs and errs[0]["claim"].startswith("우리금융 1주당 동양생명")


def test_2242_의_고친_문장은_통과한다():
    assert rc.find_reversed("교환 비율은 동양생명 1주당 우리금융 0.2521056주이고", WOORI) == []


def test_010_의_틀렸던_문장을_잡는다():
    assert rc.find_reversed("교환비율은 이마트 1주당 신세계푸드 0.5031313주였다.", EMART)
    assert rc.find_reversed("교환비율은 신세계푸드 1주당 이마트 0.5031313주였다.", EMART) == []


def test_본문_안의_공시_표기와도_대조한다_자릿수가_달라도():
    # 9814: 본문 표에 'HD현대케미칼 : 롯데대산석화 = 1 : 6.08' 이 있고 공시는 6.0800000 이다
    art = "합병비율 HD현대케미칼 : 롯데대산석화 = 1 : 6.08 … 롯데대산석화 1주당 HD현대케미칼 6.08주가 배정된다."
    assert rc.find_reversed(art, "") == []
    assert rc.find_reversed(art.replace("롯데대산석화 1주당 HD현대케미칼", "HD현대케미칼 1주당 롯데대산석화"), "")


def test_접수번호가_있으면_공시를_불러_대조한다():
    calls = []
    text = "우리금융 1주당 동양생명 0.2521056주. 접수번호 20260424000498"
    res = rc.check(text, fetch=lambda r: calls.append(r) or WOORI)
    assert calls == ["20260424000498"] and res["errors"]


def test_공시_조회가_실패하면_막지_않고_생략_사유를_남긴다():
    def boom(_):
        raise OSError("timeout")
    res = rc.check("우리금융 1주당 동양생명 0.2521056주. 접수번호 20260424000498", fetch=boom)
    assert res == {"errors": [], "skipped": "DART 조회 실패 1건"}


def test_비율_문장이_없으면_조회하지_않는다():
    res = rc.check("1주당 0.3주를 받는다. 20260424000498", fetch=lambda r: (_ for _ in ()).throw(AssertionError))
    assert res["skipped"] == "비율 문장 없음"


