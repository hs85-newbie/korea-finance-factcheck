"""원고의 시장 수치를 공식 데이터와 대조한다. 틀리면 업로드를 막는다.

WHY 2026-09-30: 쿡 이사 논평(13178)에 미국 국채금리가 틀리게 들어갔다.
    자동 집필이 재무부 표를 요약 도구로 읽다가 칸이 밀려, '2년물' 자리에 2개월물,
    '10년물' 자리에 7년물이 들어갔다(5.16% → 실제 5.26%). 그 숫자 위에 쓴 해석도 무너졌다.
    지시문에는 '원문으로 확인하라'가 이미 있었다. 모델은 확인했다고 믿었지만
    확인한 대상(요약)이 틀려 있었다. **지시가 아니라 검사로 받는다.**

무엇을 보나 — 공식 원본이 있는 것만 판정한다. 틀리면 차단(환율만 15원 넘게 다를 때 경고).
    미국 국채 2·5·10·30년 = 재무부 par yield CSV / 코스피 종가·한국 기준금리·환율 = 한국은행 ECOS
    ★ 환율은 기사(주간 종가)와 ECOS(매매기준율)가 원래 다른 숫자다(9/29 1,356.7 vs 1,360).

★ 데이터를 못 받으면 **막는다**(fail-closed). 확인 못 한 숫자를 내보내지 않는다.
  사용자 결정(2026-09-30): "허수는 위험하다."


"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from .official import fetch_ecos, fetch_treasury


_TOL = {"ust": 0.005, "kospi": 0.005, "bok": 0.001}
_FX_WARN = 15.0
_FOREIGN = re.compile(r"독일|영국|일본|분트|길트|유로|중국|JGB")
# 공식 값이 아닌 걸 알고 인용하는 문장의 표지. 2026-09-18 논평이 "매체마다 4.83%·4.867%…로
#   제각각 보도됐는데 원문 대조 결과 4.95%" 라고 썼다 — 이걸 막으면 정직한 서술을 벌한다.
_REPORTED = re.compile(r"보도|매체|스니펫|호가|표시했|전했")
_DATE = re.compile(r"(\d{1,2})월\s*(\d{1,2})일|(?<![\d.])(\d{1,2})/(\d{1,2})(?![\d/])")


@dataclass
class Report:
    blocks: list = field(default_factory=list)      # 틀림·검증불가 — 업로드 차단
    warns: list = field(default_factory=list)       # 환율 차이 — 알림만
    unverified: list = field(default_factory=list)  # 공식 원본이 없는 숫자 — 사람 몫
    checked: int = 0

    @property
    def ok(self) -> bool:
        return not self.blocks


# ── 원고에서 주장 뽑기 ───────────────────────────────────────────────────────

@dataclass
class Claim:
    kind: str                 # ust | kospi | bok | fx
    value: float
    when: Optional[date]      # None 이면 날짜 없는 본문 서술 — 기간 안 값 중 하나와 맞아야 한다
    tenor: tuple = ()         # ust 만기(들)
    text: str = ""
    reported: bool = False    # "매체마다 ~로 보도됐다" 처럼 남의 수치를 옮긴 문장 — 막지 않고 사람에게


def _dates(s: str, year: int, ref: date) -> list:
    out = []
    for m in _DATE.finditer(s):
        mo, dd = int(m.group(1) or m.group(3)), int(m.group(2) or m.group(4))
        if 1 <= mo <= 12 and 1 <= dd <= 31:
            out.append(date(year - 1 if mo > ref.month else year, mo, dd))
    return out


def _kind_of(label: str) -> Optional[str]:
    if _FOREIGN.search(label):
        return None
    if re.search(r"\d+년\s*물|\d+년\s*국채", label):
        return "ust"
    if "코스피" in label and "코스닥" not in label:
        return "kospi"
    if re.search(r"(한국|한국은행)\s*기준금리", label):
        return "bok"
    if "환율" in label and re.search(r"원\s*[/·]\s*달러|달러", label):
        return "fx"
    return None


# "%p"·"%포인트" 는 변동폭이지 수준이 아니다 — 금리 값으로 읽으면 멀쩡한 원고를 막는다
_VAL = {"ust": r"(?<![\d.~])(\d{1,2}\.\d{2,3})%(?!p|포인트)", "bok": r"(\d\.\d{2})%(?!p|포인트)",
        "kospi": r"(\d{1,2},\d{3}\.\d{2})", "fx": r"(\d,\d{3}(?:\.\d+)?)\s*원"}


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def _table_claims(md: str, year: int, ref: date) -> list:
    claims, header = [], []
    for line in md.splitlines():
        if not line.strip().startswith("|"):
            header = []
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if re.fullmatch(r"[\s:|-]+", line.strip().replace("|", "")):
            continue
        if not header:
            header = cells
            continue
        claims += _row_claims(cells, header, year, ref)
    return claims


def _row_claims(cells: list, header: list, year: int, ref: date) -> list:
    label, out = cells[0], []
    kind = _kind_of(label)
    if not kind:
        return out
    tenor = tuple(int(t) for t in re.findall(r"(\d+)년", label))
    for i, cell in enumerate(cells[1:], start=1):
        head = header[i] if i < len(header) else ""
        for m in re.finditer(_VAL[kind], cell):
            own = _dates(cell[m.end():m.end() + 14], year, ref)   # "1,350.36원(9/23)" 꼴
            d = (own or _dates(head, year, ref) or _dates(cell, year, ref)
                 or _dates(label, year, ref) or [None])[0]
            out.append(Claim(kind, _num(m.group(1)), d, tenor, f"표 「{label}」 {cell[:40]}"))
    return out


def _prose_claims(md: str) -> list:
    """표 밖 문장. 날짜를 문장에서 짝지을 수 없으니 '기간 안 실제 값 중 하나'와 맞는지만 본다."""
    out = []
    body = "\n".join(l for l in md.splitlines() if not l.strip().startswith("|"))
    prev: tuple = ()
    for sent in re.split(r"(?<=[.다])\s+", body):
        if _FOREIGN.search(sent):
            prev = ()
            continue
        # "미국 10년물과 30년물이다. 재무부 종가로 각각 5.16%와 5.59%다." — 만기와 값이 두 문장에
        #   나뉜 모양이 2026-09-30 원고에 실제로 있었다. 값만 있는 문장은 앞 문장의 만기를 잇는다.
        own = tuple(int(t) for t in re.findall(r"(\d+)년물", sent))
        tenors, prev = own or prev, own
        if tenors:
            for m in re.finditer(_VAL["ust"], sent):
                if not re.search(r"범위|기준금리|상단|하단|중립|목표|~", sent[max(0, m.start() - 12):m.start()]):
                    out.append(Claim("ust", _num(m.group(1)), None, tenors, sent.strip()[:60],
                                     bool(_REPORTED.search(sent))))
        for m in re.finditer(r"코스피.{0,40}?(\d{1,2},\d{3}\.\d{2})\s*(?:으로|로|에)\s*(?:마감|장을 마쳤|거래를 마쳤)", sent):
            out.append(Claim("kospi", _num(m.group(1)), None, (), sent.strip()[:60]))
    return out


def extract(md: str, ref: date) -> list:
    return _table_claims(md, ref.year, ref) + _prose_claims(md)


# ── 대조 ────────────────────────────────────────────────────────────────────

_TENORS = (1, 2, 3, 5, 7, 10, 20, 30)


def _as_of(series: dict, d: date) -> Optional[float]:
    """d 당일 또는 그 이전 가장 가까운 관측값(기준금리처럼 계단형 시계열용)."""
    past = [k for k in series if k <= d]
    return series[max(past)] if past else None


def _judge(c: Claim, data: dict, window: list, rep: Report) -> None:
    rep.checked += 1
    tag = f"{c.text} → {c.value}"
    if c.kind == "fx":
        act = data["fx"].get(c.when) if c.when else None
        if act is None:
            rep.unverified.append(f"{tag} (환율 — 날짜 대응 없음)")
        elif abs(act - c.value) > _FX_WARN:
            rep.warns.append(f"{tag} · 한국은행 매매기준율 {act} (차이 {abs(act - c.value):.1f}원)")
        return
    if c.kind == "bok":
        # ★ 괄호 속 날짜는 대개 "8월 27일 인상" 같은 결정일이다. ECOS 일별값은 시행일부터 바뀌어
        #   결정 당일엔 옛 금리가 찍힌다. 그래서 원고 작성일 기준 "현재 금리"로 본다.
        act = _as_of(data["bok"], window[-1])
        cands = [act] if act is not None else []
    elif c.kind == "kospi":
        cands = [data["kospi"][c.when]] if c.when in data["kospi"] else (
            [] if c.when else [data["kospi"][d] for d in window if d in data["kospi"]])
    else:
        tenors = [t for t in c.tenor if t in _TENORS]
        if not tenors:
            rep.unverified.append(f"{tag} (만기 불명)")
            return
        days = [c.when] if c.when else window
        cands = [data["ust"][d][t] for d in days for t in tenors
                 if d in data["ust"] and t in data["ust"][d]]
    if c.reported and not any(abs(round(c.value, 2) - a) <= _TOL[c.kind] for a in cands):
        rep.unverified.append(f"{tag} (인용 보도 수치 — 공식 값과 다름, 사람 확인)")
        return
    if not cands:
        rep.blocks.append(f"{tag} · 공식 값 없음({c.when or '기간 내'}) — 날짜·종목을 확인하라")
    elif not any(abs(round(c.value, 2) - a) <= _TOL[c.kind] for a in cands):
        shown = cands[0] if c.when else sorted(set(cands))[:6]
        rep.blocks.append(f"{tag} · 공식 값 {shown}")


def _load(claims: list, ref: date, fetch_ust: Callable, fetch_eco: Callable, rep: Report) -> dict:
    start = min([c.when for c in claims if c.when] + [ref - timedelta(days=30)])
    kinds = {c.kind for c in claims}
    data = {"ust": {}, "kospi": {}, "bok": {}, "fx": {}}
    try:
        if "ust" in kinds:
            for y in range(start.year, ref.year + 1):
                data["ust"].update(fetch_ust(y))
        for k in ("kospi", "bok", "fx"):
            if k in kinds:
                # 기준금리는 계단형이라 마지막 변경일까지 거슬러 올라가야 한다
                back = start - timedelta(days=400) if k == "bok" else start
                data[k] = fetch_eco(k, back, ref)
    except Exception as e:  # noqa: BLE001 — 못 받으면 막는다(fail-closed)
        rep.blocks.append(f"공식 데이터 조회 실패 — 검증 불가라 막는다: {e}")
    return data


def check(md: str, ref: date, fetch_ust: Callable = fetch_treasury,
          fetch_eco: Callable = fetch_ecos) -> Report:
    rep = Report()
    claims = extract(md, ref)
    if not claims:
        return rep
    data = _load(claims, ref, fetch_ust, fetch_eco, rep)
    if rep.blocks:
        return rep
    window = sorted(d for d in {ref - timedelta(days=i) for i in range(31)})
    for c in claims:
        _judge(c, data, window, rep)
    return rep


def written_date(md: str) -> date:
    m = re.search(r"\*\*작성\*\*\s*:\s*(\d{4})-(\d{2})-(\d{2})", md)
    return date(*map(int, m.groups())) if m else date.today()


def format_report(rep: Report) -> str:
    lines = [f"시장 수치 대조 {rep.checked}건 — " + ("통과" if rep.ok else f"❌ 틀림 {len(rep.blocks)}건")]
    lines += [f"  ✗ {b}" for b in rep.blocks]
    lines += [f"  △ {w}" for w in rep.warns]
    lines += [f"  ? {u}" for u in rep.unverified]
    return "\n".join(lines)
