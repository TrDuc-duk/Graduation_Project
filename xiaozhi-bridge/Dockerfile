# Cầu nối Xiaozhi: mcp_pipe.py nối MCP endpoint, nạp các hàm trong aqi_tools.py (09-xiaozhi-mcp).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /bridge

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN useradd --uid 1000 --no-create-home bridge
USER bridge

CMD ["python", "mcp_pipe.py", "aqi_tools.py"]
