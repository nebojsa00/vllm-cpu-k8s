import logging
import os
from pathlib import Path

from huggingface_hub import snapshot_download


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger("model_downloader")

MODEL_ID = os.getenv(
    "MODEL_ID",
    "HuggingFaceTB/SmolLM2-135M-Instruct",
)

MODEL_DIR = Path(
    os.getenv("MODEL_DIR", "/models/smollm2-135m")
)

MODEL_REVISION = os.getenv(
    "MODEL_REVISION",
    "12fd25f77366fa6b3b4b768ec3050bf629380bac",
)

HF_TOKEN = os.getenv("HF_TOKEN") or None

READY_FILE = MODEL_DIR / ".download_complete"

METADATA_DIR = (
    MODEL_DIR / ".cache" / "huggingface" / "download"
)


def get_file_revision(filename: str):
    metadata_file = METADATA_DIR / f"{filename}.metadata"

    if not metadata_file.is_file():
        return None

    try:
        with metadata_file.open(
            "r", encoding="utf-8"
        ) as file:
            return file.readline().strip()
    except OSError:
        return None


def model_files_valid():
    required_files = [
        "config.json",
        "tokenizer_config.json",
        "tokenizer.json",
    ]

    for filename in required_files:
        path = MODEL_DIR / filename

        if not path.is_file() or path.stat().st_size == 0:
            logger.warning("Missing or empty file: %s", path)
            return False

    weights = sorted(MODEL_DIR.glob("*.safetensors"))

    if not weights:
        logger.warning("Model weights are missing")
        return False

    files_to_verify = required_files + [
        path.name for path in weights
    ]

    for filename in files_to_verify:
        revision = get_file_revision(filename)

        if revision != MODEL_REVISION:
            logger.warning(
                "Revision mismatch for %s: expected %s, got %s",
                filename,
                MODEL_REVISION,
                revision,
            )
            return False

    return True


def ready_marker_valid():
    if not READY_FILE.is_file():
        return False

    try:
        lines = READY_FILE.read_text(
            encoding="utf-8"
        ).splitlines()

        return lines == [
            MODEL_ID,
            MODEL_REVISION,
        ]
    except OSError:
        return False


def write_ready_marker():
    READY_FILE.write_text(
        f"{MODEL_ID}\n{MODEL_REVISION}\n",
        encoding="utf-8",
    )


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    if model_files_valid():
        if not ready_marker_valid():
            logger.info(
                "Model files verified. Updating ready marker."
            )
            write_ready_marker()

        logger.info(
            "Model already cached at %s. "
            "Revision %s verified. Skipping download.",
            MODEL_DIR,
            MODEL_REVISION,
        )
        return

    logger.info(
        "Downloading model %s at revision %s into %s",
        MODEL_ID,
        MODEL_REVISION,
        MODEL_DIR,
    )

    READY_FILE.unlink(missing_ok=True)

    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=str(MODEL_DIR),
        token=HF_TOKEN,
        ignore_patterns=[
            "*.bin",
            "*.h5",
            "*.msgpack",
            "*.onnx",
            "*.tflite",
        ],
    )

    if not model_files_valid():
        raise RuntimeError(
            "Downloaded model files failed validation"
        )

    write_ready_marker()

    logger.info(
        "Model download completed successfully. "
        "Revision: %s",
        MODEL_REVISION,
    )


if __name__ == "__main__":
    main()
