"""OpenDART 최소 클라이언트. 키는 사용자 것(DART_API_KEY)을 쓴다 — 약관상 키를 남과 나눠 쓸 수 없다."""
from __future__ import annotations

import io
import json
import os
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Optional

import requests

BASE = "https://opendart.fss.or.kr/api"
CACHE = Path(os.getenv("KFF_CACHE_DIR", Path.home() / ".cache" / "korea-finance-factcheck"))
_MAP_TTL = 7 * 24 * 3600


def key() -> str:
    return os.getenv("DART_API_KEY", "")


def get(endpoint: str, params: dict) -> Optional[dict]:
    """JSON 엔드포인트. 정상(status 000)이 아니면 None — 호출부가 '검사 생략'으로 남긴다."""
    if not key():
        return None
    r = requests.get(f"{BASE}/{endpoint}", params={"crtfc_key": key(), **params}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j if j.get("status") == "000" else None


def _load_map() -> dict:
    p = CACHE / "corpcode.json"
    if p.exists() and time.time() - p.stat().st_mtime < _MAP_TTL:
        return json.loads(p.read_text(encoding="utf-8"))
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": key()}, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {el.findtext("stock_code").strip(): el.findtext("corp_code")
         for el in root.iter("list") if (el.findtext("stock_code") or "").strip()}
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(m), encoding="utf-8")
    return m


def corp_code(stock_code: str) -> Optional[str]:
    """6자리 종목코드 → DART 고유번호. 첫 호출에 전체 목록을 받아 일주일 캐시한다."""
    if not key():
        return None
    return _load_map().get(stock_code)
