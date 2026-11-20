FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# App Runner routes to port 8080 by default.
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK CMD curl --fail http://localhost:8080/_stcore/health || exit 1

CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
