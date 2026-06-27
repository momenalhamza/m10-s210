FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy coordinator files into a coordinator/ subdirectory so relative
# imports (from .models, from .upstream) resolve correctly when uvicorn
# loads the app as coordinator.main:app.
COPY . coordinator/
RUN touch __init__.py coordinator/__init__.py
EXPOSE 8000
CMD ["uvicorn", "coordinator.main:app", "--host", "0.0.0.0", "--port", "8000"]
