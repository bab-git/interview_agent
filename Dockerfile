FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV APP_DATA_DIR=/app/data
ENV APP_DB_PATH=/app/data/interview_agent.sqlite3
ENV PROMPT_ACTIVE_FILE=/app/prompts/active_prompt.json
ENV PROMPT_VERSIONS_DIR=/app/prompts/versions
ENV LLM_BACKEND=ollama
ENV OLLAMA_HOST=http://ollama:11434
ENV OLLAMA_MODEL=llama3.2:1b

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
