"""MCP 도구 목록과 묶음 검사의 실패 격리."""
import asyncio

import korea_finance_factcheck.server as s


def test_도구가_모두_노출된다():
    names = {t.name for t in asyncio.run(s.mcp.list_tools())}
    assert names == {"check_unit_errors", "check_ratio_direction", "check_market_numbers", "check_stock_closes", "check_all"}


def test_묶음_검사는_하나가_터져도_나머지_결과를_돌려준다(monkeypatch):
    monkeypatch.setattr(s.units, "find_unit_errors", lambda t: (_ for _ in ()).throw(RuntimeError("DART 장애")))
    monkeypatch.setattr(s.market, "check", lambda t, ref: s.market.Report())
    monkeypatch.setattr(s.krx, "check", lambda t, ref: {"errors": [], "skipped": "종가 문장 없음"})
    out = s.check_all("우리금융 : 동양생명 = 1 : 0.2521056. 우리금융 1주당 동양생명 0.2521056주.", "2026-04-24")
    assert out["unit_errors"] == {"error": "RuntimeError: DART 장애"}
    assert out["ratio_direction"]["errors"]
    assert out["market_numbers"]["ok"] is True
