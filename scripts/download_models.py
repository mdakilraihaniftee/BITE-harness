"""Cache the README's pinned local checkpoints and model-ID tokenizer references."""
import argparse
import os
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import snapshot_download

MODELS = {
    "qwen": ("Qwen/Qwen3-VL-8B-Instruct", "0c351dd01ed87e9c1b53cbc748cba10e6187ff3b"),
    "ocr": ("PaddlePaddle/PaddleOCR-VL-1.5", "2a4195faa5e7914c12f2fc601d72c81caf8d2da5"),
    "depth": ("depth-anything/DA3NESTED-GIANT-LARGE", "8615eefb62f2db4f8d6ebaa59160086981672829"),
    "sam3": ("facebook/sam3", "3c879f39826c281e95690f02c7821c4de09afae7"),
}


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    load_dotenv(root / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", choices=MODELS)
    args = parser.parse_args()
    cache = Path(os.getenv("HF_HOME", root / ".cache/huggingface")) / "hub"

    def download(name):
        repo, revision = MODELS[name]
        try:
            # Explicit cache_dir is needed because huggingface_hub was imported
            # before dotenv could establish HF_HOME.
            path = Path(snapshot_download(repo, revision=revision, cache_dir=str(cache), max_workers=6))
            ref = path.parent.parent / "refs/main"
            ref.parent.mkdir(parents=True, exist_ok=True)
            ref.write_text(revision)
            print(f"READY {name}: {path}", flush=True)
            return True
        except Exception as exc:
            print(f"FAILED {name}: {type(exc).__name__}; check checkpoint access and connectivity", flush=True)
            return False

    # Each snapshot already downloads files concurrently. Concurrent snapshots
    # can race over tqdm's process-wide lock during progress-bar teardown.
    results = [download(name) for name in args.models]
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
