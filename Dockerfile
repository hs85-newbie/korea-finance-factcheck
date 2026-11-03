# Glama 등 MCP 목록 사이트가 서버를 띄워 점검할 때 쓰는 이미지. 키는 실행할 때 환경변수로 넣는다.
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
ENTRYPOINT ["korea-finance-factcheck"]
