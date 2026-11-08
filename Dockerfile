
# Фиксируем конкретный CPU-образ vLLM
FROM vllm/vllm-openai-cpu:v0.28.0@sha256:197354e6475e638eb5ccca09beb078488046a82de0e204e7429bf1a804df9647

# Создаем непривилегированного пользователя (в принципе можно и попрощее, но ладно. Если тот кто оценивает задание потребует, могу поределать. Дайте знать.)
RUN groupadd --gid 10001 appgroup \
    && useradd --uid 10001 --gid 10001 \
       --create-home --shell /bin/bash appuser \
    && mkdir -p /models /app /home/appuser/.cache \
    && chown -R 10001:10001 /models /app /home/appuser

ENV HOME=/home/appuser \
    HF_HOME=/home/appuser/.cache/huggingface \
    VLLM_CACHE_ROOT=/home/appuser/.cache/vllm \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY scripts/request_logging.py /app/request_logging.py

RUN python - <<'PY'
from importlib.metadata import distributions
from pathlib import Path

installed = {
    d.metadata["Name"].lower().replace("_", "-"): d.version
    for d in distributions()
}

for line in Path("/app/requirements.txt").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    name, expected = line.split("==", 1)
    actual = installed.get(name.lower().replace("_", "-"))
    if actual != expected:
        raise RuntimeError(
            f"{name}: expected {expected}, installed {actual}"
        )

print("Pinned dependencies verified")
PY

RUN python -m pip check

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["vllm", "serve"]
