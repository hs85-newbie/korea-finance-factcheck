"""market_fact_check 회귀 — 공식 데이터 대조 게이트.

WHY 2026-09-30: 쿡 논평(13178)이 재무부 표 칸을 잘못 읽어 2개월물을 '2년물', 7년물을 '10년물'로
    썼다. 여기 테스트는 **그 실제 원고 모양이 막히는지**를 지킨다. 통과만 보는 테스트는 검증이 아니다.
    네트워크는 모두 가짜 데이터로 바꾼다(재무부 CSV 실측 값 그대로).
"""
from __future__ import annotations

import ast
import csv
import io
from datetime import date
from pathlib import Path

import pytest

from korea_finance_factcheck import market as mfc

REF = date(2026, 9, 30)

# 재무부 CSV 실측(2026-09-30 조회). 열 순서가 곧 사고 원인이었다 — 열 이름으로만 읽어야 한다.
_CSV = """Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
09/29/2026,4.04,4.14,4.18,4.25,4.30,4.36,4.58,4.89,4.98,5.06,5.16,5.26,5.64,5.59
09/28/2026,4.04,4.14,4.20,4.28,4.33,4.41,4.59,4.92,5.01,5.06,5.15,5.24,5.60,5.56
09/25/2026,4.04,4.14,4.20,4.24,4.32,4.33,4.50,4.81,4.94,4.98,5.06,5.17,5.54,5.49
"""


def _ust_from(text: str):
    def fetch(year):
        out = {}
        for r in csv.DictReader(io.StringIO(text)):
            m, d, y = (int(x) for x in r["Date"].split("/"))
            out[date(y, m, d)] = {n: float(r[f"{n} Yr"]) for n in (2, 5, 10, 30)}
        return out
    return fetch


_ECOS = {
    "kospi": {date(2026, 9, 28): 6889.74, date(2026, 9, 29): 6870.81},
    "bok": {date(2026, 7, 16): 2.75, date(2026, 8, 28): 3.00},
    "fx": {date(2026, 9, 29): 1360.0},
}


def _eco(kind, start, end):
    return _ECOS[kind]


def _check(md: str):
    return mfc.check(md, REF, fetch_ust=_ust_from(_CSV), fetch_eco=_eco)


# 2026-09-30 실제로 올라온 틀린 원고의 표 (git 5063599)
WRONG = """
| 항목 | 값 |
|---|---|
| 미국 10년 국채금리 (9월 29일) | 5.16% (재무부 일별 수익률) |
| 코스피 (9월 29일 종가) | 6,870.81 |

| 만기 | 9월 25일 | 9월 28일 | 9월 29일 |
|---|---|---|---|
| 2년물 | 4.20% | 4.20% | 4.18% |
| 10년물 | 5.06% | 5.15% | 5.16% |
| 30년물 | 5.49% | 5.56% | 5.59% |
"""


class TestTheIncident:
    def test_wrong_manuscript_is_blocked(self):
        rep = _check(WRONG)
        assert not rep.ok
        joined = " ".join(rep.blocks)
        for bad in ("5.16", "4.2", "4.18", "5.06", "5.15"):
            assert bad in joined
        assert not any("30년물" in b for b in rep.blocks)   # 30년물은 맞았다

    def test_corrected_manuscript_passes(self):
        fixed = (WRONG.replace("| 5.16% (재무부", "| 5.26% (재무부")
                 .replace("| 2년물 | 4.20% | 4.20% | 4.18% |", "| 2년물 | 4.81% | 4.92% | 4.89% |")
                 .replace("| 10년물 | 5.06% | 5.15% | 5.16% |", "| 10년물 | 5.17% | 5.24% | 5.26% |"))
        rep = _check(fixed)
        assert rep.ok, rep.blocks
        assert rep.checked >= 10

    def test_columns_are_read_by_name_not_position(self):
        # 열 순서를 뒤섞어도 같은 값을 읽어야 한다 — 위치로 읽는 코드가 사고를 냈다
        rows = list(csv.reader(io.StringIO(_CSV)))
        order = [0] + list(range(len(rows[0]) - 1, 0, -1))
        shuffled = "\n".join(",".join(r[i] for i in order) for r in rows)
        rep = mfc.check(WRONG, REF, fetch_ust=_ust_from(shuffled), fetch_eco=_eco)
        assert any("5.16" in b and "5.26" in b for b in rep.blocks)


class TestProse:
    def test_undated_wrong_yield_in_prose_is_blocked(self):
        rep = _check("둘째, 미국 10년물과 30년물이다. 재무부 종가로 각각 5.16%와 5.59%다.")
        assert not rep.ok and any("5.16" in b for b in rep.blocks)

    def test_basis_point_change_is_not_a_level(self):
        rep = _check("2년물이 하루에 0.14%포인트 뛰었다. 10년물은 0.06%p 올랐다.")
        assert rep.ok and rep.checked == 0

    def test_policy_rate_in_yield_sentence_is_ignored(self):
        rep = _check("인상 전 2년물이 이미 4.89%로, 새 목표범위 상단인 4.00%보다 높다.")
        assert rep.ok, rep.blocks

    def test_foreign_bond_sentence_is_skipped(self):
        rep = _check("독일 10년물 분트는 3.451%까지 올랐다.")
        assert rep.ok and rep.checked == 0

    def test_reported_figures_go_to_human_not_block(self):
        rep = _check("10년물 금리가 매체마다 4.83%·4.867%로 제각각 보도됐는데 원문 대조 결과 5.26%였다.")
        assert rep.ok and rep.unverified

    def test_treasury_claim_is_not_excused_as_report(self):
        # 2026-09-30 원고의 이 문장은 '재무부 고시치'라고 단언했다 — 보도 인용이 아니다
        rep = _check("10년물 기준으로 재무부 고시치 5.15%와 0.11%p 차이가 난다.")
        assert not rep.ok

    def test_kospi_close_in_prose(self):
        assert _check("코스피는 18.93포인트 내린 6,870.81로 마감했다.").ok
        assert not _check("코스피는 18.93포인트 내린 6,724.34로 마감했다.").ok


class TestOtherSeries:
    def test_kospi_table_mismatch_blocked(self):
        rep = _check("| 항목 | 값 |\n|---|---|\n| 코스피 (9월 29일 종가) | 6,724.34 (+0.09%) |\n")
        assert not rep.ok and "6870.81" in rep.blocks[0]

    def test_bok_rate_uses_current_rate_not_decision_day(self):
        # "8월 27일 인상" 은 결정일. ECOS 는 시행일(8/28)부터 3.00 — 결정일로 보면 멀쩡한 원고를 막는다
        ok = _check("| 항목 | 값 |\n|---|---|\n| 한국 기준금리 | 3.00% (8월 27일 인상) |\n")
        bad = _check("| 항목 | 값 |\n|---|---|\n| 한국 기준금리 | 2.75% (8월 27일 인상) |\n")
        assert ok.ok and not bad.ok

    def test_fx_only_warns(self):
        # 기사 주간 종가와 ECOS 매매기준율은 원래 다른 숫자다 — 막지 않는다
        near = _check("| 항목 | 값 |\n|---|---|\n| 원·달러 환율 (9월 29일 주간 종가) | 1,356.7원 |\n")
        far = _check("| 항목 | 값 |\n|---|---|\n| 원·달러 환율 (9월 29일) | 1,300.0원 |\n")
        assert near.ok and not near.warns
        assert far.ok and far.warns

    def test_missing_date_in_official_data_blocks(self):
        rep = _check("| 항목 | 값 |\n|---|---|\n| 미국 10년물 (9월 27일) | 5.20% |\n")  # 일요일
        assert not rep.ok and "공식 값 없음" in rep.blocks[0]


class TestFailClosed:
    def test_fetch_failure_blocks(self):
        def boom(_):
            raise RuntimeError("조회 실패: HTTP 503")
        rep = mfc.check(WRONG, REF, fetch_ust=boom, fetch_eco=_eco)
        assert not rep.ok and "검증 불가" in rep.blocks[0]

    def test_no_market_numbers_passes_without_fetching(self):
        def boom(*_):
            raise AssertionError("수치가 없으면 조회하지 않는다")
        assert mfc.check("본문에 시장 수치가 없다.", REF, fetch_ust=boom, fetch_eco=boom).ok


class TestParsing:
    @pytest.mark.parametrize("text,expected", [
        ("9월 29일", date(2026, 9, 29)),
        ("(9/23)", date(2026, 9, 23)),
        ("12월 30일", date(2025, 12, 30)),   # 작성월보다 뒤 → 전년
    ])
    def test_dates(self, text, expected):
        assert mfc._dates(text, 2026, REF) == [expected]

    def test_written_date_from_footer(self):
        assert mfc.written_date("**작성**: 2026-09-17\n") == date(2026, 9, 17)






