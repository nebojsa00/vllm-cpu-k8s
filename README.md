# vLLM на CPU в Kubernetes

Локальное развертывание `HuggingFaceTB/SmolLM2-135M-Instruct` через vLLM `0.28.0+cpu` в кластере k3d/K3s. Проект рассчитан на запуск без GPU, в том числе на ноутбуке с 8 ГБ RAM.

Для сервера и загрузчика модели используются отдельные Docker-образы без root (UID 10001). Веса хранятся на PVC, настройки — в ConfigMap, токены — в Kubernetes Secret. Логирование запросов реализовано собственным middleware: записываются маршрут, HTTP-статус и время обработки, но не тексты промптов и ответов.

## Состав проекта

- `Dockerfile`, `requirements.txt` — образ vLLM и зафиксированные версии зависимостей.
- `Dockerfile.init`, `requirements-downloader.txt` — отдельный образ загрузчика.
- `scripts/download_model.py` — загрузка модели и проверка ревизии в кэше.
- `scripts/request_logging.py` — логирование метаданных запросов.
- `scripts/create-secret.ps1` — создание Secret без сохранения ключа в репозитории.
- `k8s/` — Namespace, PVC, ConfigMap, Deployment, Service и Kustomize.
- `benchmarks/` — тестовый скрипт и результаты измерений.

## Запуск

Проверялось на Windows 10, Docker Desktop (WSL2), k3d 5.9.0 и K3s `v1.34.3-k3s1`. Для запуска необходимы Docker, `kubectl`, `k3d` и PowerShell. В кластере должен быть StorageClass `local-path` (либо нужно изменить `k8s/pvc.yaml`).

Создание кластера:

```powershell
k3d cluster create llm-local --image rancher/k3s:v1.34.3-k3s1 --servers 1 --agents 0 --no-lb --k3s-arg "--disable=traefik@server:*" --k3s-arg "--disable=servicelb@server:*"
```

Сборка образов:

```powershell
docker build -t vllm-cpu-custom:0.4 .
docker build -f Dockerfile.init -t vllm-model-downloader:0.3 .
k3d image import vllm-cpu-custom:0.4 -c llm-local
k3d image import vllm-model-downloader:0.3 -c llm-local
```

Создание пространства имен и Secret, затем развертывание:

```powershell
kubectl apply -f k8s/namespace.yaml
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\create-secret.ps1
kubectl apply -k k8s
kubectl rollout status deployment/vllm-server -n vllm --timeout=600s
kubectl get pods -n vllm
```

Для публичной SmolLM2 токен Hugging Face не требуется. При первом запуске `initContainer` скачивает модель на PVC, при следующих — использует сохраненные файлы. Ревизия модели зафиксирована в `k8s/configmap.yaml` (`12fd25f77366fa6b3b4b768ec3050bf629380bac`).

## Запрос к API

В одном окне PowerShell:

```powershell
kubectl port-forward -n vllm --address 127.0.0.1 service/vllm-service 8000:8000
```

В другом окне:

```powershell
$encoded = kubectl get secret vllm-secrets -n vllm -o jsonpath="{.data.VLLM_API_KEY}"
$apiKey = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
Remove-Variable encoded
$headers = @{ Authorization = "Bearer $apiKey" }

$body = @{
    model = 'HuggingFaceTB/SmolLM2-135M-Instruct'
    messages = @(@{ role = 'user'; content = 'What is the capital of Russia?' })
    max_tokens = 32
} | ConvertTo-Json -Depth 5

$response = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/v1/chat/completions' -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$response.choices[0].message.content
```

Без Bearer-токена проверенные маршруты `/v1/models`, `/v1/chat/completions`, `/v1/completions` и `/v1/responses` возвращают HTTP 401. Сервис имеет тип `ClusterIP`; наружу API не публикуется. Защита всех возможных служебных маршрутов отдельно не проверялась.

## Нагрузочное тестирование

Тесты проводились на Ryzen 5 5500U с последовательными запросами. Параметры: `max_model_len=512`, `max_num_seqs=1`, KV-cache 128 MiB. Для повторения нужен локальный Python 3 и открытый `port-forward`:

```powershell
python benchmarks/benchmark.py --api-key $apiKey --runs 10 --output benchmarks/results_warm.csv
```

Результаты после прогрева (по 10 запросов):

| Метрика | Короткий промпт | Длинный промпт |
|---|---:|---:|
| TTFT P50 | 0,687 с | 1,164 с |
| TTFT P95 | 0,710 с | 1,388 с |
| Latency P50 | 1,054 с | 4,534 с |
| Latency P95 | 1,106 с | 4,855 с |
| Средняя скорость генерации | 22,34 ток/с | 19,10 ток/с |

Скрипт использует потоковый ответ: TTFT измеряется до первого непустого фрагмента, скорость — по числу выходных токенов и времени после первого фрагмента. Это не тест максимального RPS при параллельной нагрузке. Исходные данные есть в `benchmarks/results_initial.csv` и `benchmarks/results_warm.csv`.

**Что можно оптимизировать:**

- При большом числе коротких запросов — постепенно повышать `max_num_seqs`, подбирать `max_num_batched_tokens` и размер KV-cache; prefix caching полезен при общих началах промптов.
- Для длинного контекста — увеличить `max_model_len` и память KV-cache, подобрать бюджет токенов для chunked prefill. На ограниченной RAM эти настройки нужно менять осторожно.

Это направления дальнейшей оптимизации, а не результаты отдельных сравнительных экспериментов.

## Примечания

При запуске контейнер vLLM использовал около 2,3 GiB RAM. Параметры выбраны под ограниченные ресурсы ноутбука; увеличение контекста и числа параллельных запросов может привести к OOM (и уже много раз приводило). Образы импортируются в k3d локально (`imagePullPolicy: Never`), поэтому для обычного удаленного Kubernetes их потребуется опубликовать в registry и поправить манифесты.

Для остановки без удаления данных:

```powershell
kubectl scale deployment vllm-server -n vllm --replicas=0
k3d cluster stop llm-local
```

PVC удалять не нужно: на нем находятся веса модели.
