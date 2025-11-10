FROM python:3.13-slim
WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn httpx
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
