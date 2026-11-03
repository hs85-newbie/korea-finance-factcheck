# korea-finance-factcheck

한국 금융 글에 적힌 숫자를 공식 원본과 맞춰 보는 MCP 서버입니다. 글을 쓰는 사람이 Claude에게 "이 글 숫자 맞는지 봐 줘"라고 하면, 서버가 DART 공시와 한국은행 ECOS, 미국 재무부 자료를 직접 불러와 틀린 곳을 짚습니다.

## 왜 만들었나

저는 공시 해설과 시장 브리핑을 쓰는 사이트 [macromalt.com](https://macromalt.com)을 운영합니다. AI와 함께 글을 쓰다 보니 숫자가 틀린 채 공개된 일이 여러 번 있었습니다. 문장은 매끄러운데 숫자만 틀려서 읽는 사람도 쓴 사람도 알아채지 못했습니다. 실제로 겪은 일은 이렇습니다.

- 4월에 쓴 글에서 우리금융지주와 동양생명의 주식 교환 비율을 거꾸로 적었습니다. 공시에는 "동양생명 1주당 우리금융 0.2521056주"라고 되어 있는데 글에는 "우리금융 1주당 동양생명 0.2521056주"라고 썼습니다. 공시의 `우리금융 : 동양생명 = 1 : 0.2521056` 표기를 반대로 읽은 탓입니다.
- 10월에는 원 단위 금액에 '백만원' 꼬리표가 붙어 매출과 영업이익이 열 배, 백 배로 부풀었습니다. 공개 글 여덟 편에 그대로 실렸습니다.
- 9월에는 미국 재무부 금리표를 읽다가 칸이 밀려, 10년물 자리에 7년물 금리를 적었습니다.

세 번 모두 모델은 받은 대로 썼습니다. 그래서 글을 쓴 뒤 기계가 원본과 다시 맞춰 보게 했고 그 검사를 따로 떼어 이 저장소에 담았습니다.

## 할 수 있는 일

`check_ratio_direction`은 합병·주식교환 비율 문장을 봅니다. 본문의 "X 1주당 Y n주"를 공시 원문과 비교하고 주는 회사와 받는 회사가 뒤바뀐 문장을 짚습니다. 본문에 접수번호가 있으면 DART에서 공시를 불러오고 없으면 본문 안에 옮겨 적은 공시 표기와 비교합니다.

`check_unit_errors`는 "삼성전자(005930)"처럼 종목코드와 함께 적힌 매출, 영업이익, 순이익을 DART 사업보고서와 대조합니다. 열 배, 백 배, 천 배로 어긋난 숫자만 잡습니다. 증권사 전망치처럼 원래 공시와 다른 숫자까지 잡으면 경고가 너무 많아져서 일부러 좁혔습니다.

`check_market_numbers`는 미국 국채 2·5·10·30년물 금리를 재무부 자료와, 코스피 종가와 한국 기준금리와 원·달러 환율을 한국은행 ECOS와 비교합니다. 글 끝에 `**작성**: 2026-10-30` 같은 줄이 있으면 그날을 기준으로 봅니다. 환율은 기사에 흔히 쓰는 주간 종가와 ECOS의 매매기준율이 원래 다른 숫자라서 15원 넘게 차이 날 때만 알립니다.

`check_all`은 셋을 한꺼번에 돌립니다. 하나가 실패해도 나머지 결과는 그대로 돌려줍니다.

검사를 하지 못했을 때도 조용히 넘어가지 않습니다. 키가 없거나 조회가 실패하면 `skipped`에 이유를 적습니다.

## 설치

[uv](https://docs.astral.sh/uv/)가 있으면 설치 없이 바로 실행합니다. Claude Code에서는 이렇게 등록합니다.

```bash
claude mcp add korea-finance-factcheck \
  -e DART_API_KEY=발급받은_키 -e ECOS_API_KEY=발급받은_키 \
  -- uvx korea-finance-factcheck
```

Claude Desktop에서는 설정 파일(`claude_desktop_config.json`)에 아래를 넣습니다.

```json
{
  "mcpServers": {
    "korea-finance-factcheck": {
      "command": "uvx",
      "args": ["korea-finance-factcheck"],
      "env": { "DART_API_KEY": "발급받은_키", "ECOS_API_KEY": "발급받은_키" }
    }
  }
}
```

## 키 발급

키는 직접 발급받아 넣습니다. 두 기관 약관상 인증키는 남과 나눠 쓸 수 없어서 이 서버는 누구의 키도 대신 맡아 두지 않습니다.

DART 키는 [OpenDART](https://opendart.fss.or.kr)에서 회원가입 뒤 인증키 신청 메뉴에서 받습니다. 비율 검사와 단위 검사에 씁니다.

ECOS 키는 [한국은행 ECOS](https://ecos.bok.or.kr/api/)에서 받습니다. 신청할 때 이용 형태를 고르게 되어 있으니 쓰임에 맞게 고르세요. 코스피와 기준금리, 환율 검사에 씁니다. 미국 국채 금리는 키 없이 볼 수 있습니다.

## 쓰는 예

Claude에게 글을 붙여 넣고 이렇게 말하면 됩니다.

> 이 원고 숫자를 korea-finance-factcheck로 확인해 줘.

우리금융 문장을 넣으면 이런 결과가 돌아옵니다.

```json
{
  "ratio_direction": {
    "errors": [{"claim": "우리금융 1주당 동양생명 0.2521056주",
                "filing": "동양… 1주당 우리… 0.2521056주"}]
  }
}
```

## 하지 않는 일

이 서버는 숫자가 원본과 맞는지만 봅니다. 어떤 종목을 사라거나 팔라고 하지 않고 주가 전망도 내놓지 않습니다. 결과를 투자 판단의 근거로 쓰지 마세요.

공시나 공식 통계에 없는 숫자는 판정하지 못합니다. 증권사 추정치, 장중 시세, 기사에만 나온 숫자가 그렇습니다. 이런 숫자는 `unverified`로 돌려주니 사람이 확인해 주세요.

한국거래소(KRX) 시세와 네이버 데이터는 넣지 않았습니다. 두 곳 약관을 더 확인한 뒤에 다룰 생각입니다.

## 출처

이 서버가 불러오는 자료의 저작권은 각 기관에 있습니다. 공시는 금융감독원 전자공시시스템(DART), 국내 지표는 한국은행 경제통계시스템(ECOS), 미국 국채 금리는 미국 재무부(U.S. Department of the Treasury)의 자료입니다. 결과를 글에 옮길 때는 출처를 함께 적어 주세요.

## 개발

```bash
uv venv && uv pip install -e ".[test]"
.venv/bin/python -m pytest
```

테스트에는 실제 공시 원문과 실제로 틀렸던 문장을 그대로 넣었습니다. 손으로 지어낸 숫자만 보는 테스트는 실제 실수를 잡지 못했기 때문입니다.

## English

An MCP server that checks numbers in Korean finance writing against official sources: DART filings (merger and share-exchange ratio direction, 10x/100x unit errors in revenue and profit), Bank of Korea ECOS (KOSPI close, base rate, KRW/USD) and US Treasury par yields. Bring your own `DART_API_KEY` and `ECOS_API_KEY`. It reports mismatches and never gives investment advice.

## 라이선스

MIT
