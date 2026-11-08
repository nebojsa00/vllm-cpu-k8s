
import argparse
import csv
import json
import statistics
import time
import urllib.request
from pathlib import Path

MODEL = "HuggingFaceTB/SmolLM2-135M-Instruct"

SHORT_PROMPT = "What is the capital of Russia?"

LONG_PROMPT = (
    "Explain the main differences between relational "
    "databases and NoSQL databases. Discuss consistency, "
    "scalability, transactions, indexing, data models, "
    "and typical use cases. Provide practical examples. "
) * 5


def percentile(values, p):
    values = sorted(values)
    if len(values) == 1:
        return values[0]

    position = (len(values) - 1) * p / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower

    return values[lower] * (1 - fraction) + values[upper] * fraction


def benchmark_request(url, api_key, prompt, max_tokens):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
    }

    request = urllib.request.Request(
        url=url + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    started = time.perf_counter()
    first_token_time = None
    completion_tokens = None
    observed_chunks = 0

    with urllib.request.urlopen(request, timeout=180) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()

            if not line.startswith("data: "):
                continue

            data = line[6:]

            if data == "[DONE]":
                break

            event = json.loads(data)

            usage = event.get("usage")
            if usage and usage.get("completion_tokens") is not None:
                completion_tokens = usage["completion_tokens"]

            for choice in event.get("choices", []):
                delta = choice.get("delta", {})
                content = delta.get("content")

                if content:
                    observed_chunks += 1

                    if first_token_time is None:
                        first_token_time = time.perf_counter()

    finished = time.perf_counter()

    latency = finished - started

    ttft = (
        first_token_time - started
        if first_token_time is not None
        else None
    )

    if completion_tokens is None:
        raise RuntimeError(
            "API did not return completion_tokens in streaming usage"
        )

    generation_duration = (
        finished - first_token_time
        if first_token_time is not None
        else None
    )

    throughput = (
        completion_tokens / generation_duration
        if generation_duration and generation_duration > 0
        else None
    )

    return {
        "ttft_seconds": ttft,
        "latency_seconds": latency,
        "completion_tokens": completion_tokens,
        "throughput_tokens_per_second": throughput,
        "observed_content_chunks": observed_chunks,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", default="benchmarks/results.csv")
    args = parser.parse_args()

    if args.runs < 1:
        parser.error("--runs must be >= 1")

    cases = [
        ("short", SHORT_PROMPT, 32),
        ("long", LONG_PROMPT, 64),
    ]

    rows = []

    for name, prompt, max_tokens in cases:
        print(f"\nRunning benchmark: {name}")

        for index in range(args.runs):
            result = benchmark_request(
                args.url,
                args.api_key,
                prompt,
                max_tokens,
            )

            row = {
                "case": name,
                "run": index + 1,
                **result,
            }

            rows.append(row)

            print(
                f"Run {index + 1}: "
                f"latency={result['latency_seconds']:.3f}s, "
                f"TTFT={result['ttft_seconds']}, "
                f"tokens={result['completion_tokens']}, "
                f"throughput={result['throughput_tokens_per_second']}"
            )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nSaved results to: {output}")

    for name, _, _ in cases:
        selected = [r for r in rows if r["case"] == name]

        latencies = [r["latency_seconds"] for r in selected]
        ttfts = [
            r["ttft_seconds"]
            for r in selected
            if r["ttft_seconds"] is not None
        ]
        throughputs = [
            r["throughput_tokens_per_second"]
            for r in selected
            if r["throughput_tokens_per_second"] is not None
        ]

        print(f"\n{name.upper()} summary")
        print(f"Latency P50: {statistics.median(latencies):.3f}s")
        print(f"Latency P95: {percentile(latencies, 95):.3f}s")

        if ttfts:
            print(f"TTFT P50: {statistics.median(ttfts):.3f}s")
            print(f"TTFT P95: {percentile(ttfts, 95):.3f}s")

        if throughputs:
            print(
                f"Throughput mean: "
                f"{statistics.mean(throughputs):.2f} tokens/s"
            )


if __name__ == "__main__":
    main()
