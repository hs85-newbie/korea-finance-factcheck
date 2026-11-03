"""MCP 서버 — 검사 세 가지와 그 묶음을 도구로 내놓는다. 판정은 각 모듈이 하고 여기선 결과만 모양을 맞춘다."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from mcp.server.mcpserver import MCPServer

from . import market, ratio, units

mcp = MCPServer("korea-finance-factcheck")


@mcp.tool()
def check_unit_errors(text: str) -> dict:
    """본문에 '회사명(종목코드)'와 함께 적힌 매출·영업이익·순이익이 DART 사업보고서 값과 10배·100배 어긋나는지 본다.

    DART_API_KEY 가 필요하다. 조회가 안 되면 skipped 에 이유를 남긴다.
    """
    return units.find_unit_errors(text)


@mcp.tool()
def check_ratio_direction(text: str) -> dict:
    """'X 1주당 Y n주' 문장이 공시 원문(본문의 접수번호로 조회)이나 본문 안의 'A : B = 1 : x' 표기와 반대로 적혔는지 본다."""
    return ratio.check(text)


@mcp.tool()
def check_market_numbers(text: str, as_of: Optional[str] = None) -> dict:
    """미국 국채금리(재무부)와 코스피 종가·한국 기준금리·환율(한국은행 ECOS)을 그날 공식값과 대조한다.

    as_of 는 글을 쓴 날(YYYY-MM-DD). 없으면 본문의 '**작성**: 날짜' 줄, 그것도 없으면 오늘.
    ECOS 항목은 ECOS_API_KEY 가 필요하다.
    """
    ref = dt.date.fromisoformat(as_of) if as_of else market.written_date(text)
    rep = market.check(text, ref)
    return {"ok": rep.ok, "checked": rep.checked, "errors": rep.blocks, "warnings": rep.warns,
            "unverified": rep.unverified}


@mcp.tool()
def check_all(text: str, as_of: Optional[str] = None) -> dict:
    """위 세 검사를 한 번에 돌린다. 하나가 실패해도 나머지 결과는 돌려준다."""
    out = {}
    for name, fn in (("unit_errors", lambda: check_unit_errors(text)),
                     ("ratio_direction", lambda: check_ratio_direction(text)),
                     ("market_numbers", lambda: check_market_numbers(text, as_of))):
        try:
            out[name] = fn()
        except Exception as e:  # noqa: BLE001 — 한 검사의 실패가 다른 검사 결과를 지우지 않게
            out[name] = {"error": f"{type(e).__name__}: {e}"}
    return out


def main() -> None:
    mcp.run()
