#!/usr/bin/env python3
"""Export BAAI/bge-m3 to an offline ONNX int8 model directory.

Run on a CONNECTED build host (it downloads the model once), then copy the
output directory to the offline image build context:

    pip install "optimum[onnxruntime]>=1.21" "transformers>=4.44" onnx onnxruntime
    python sidecars/embedding/export_model.py --output sidecars/embedding/models/bge-m3

Result::

    models/bge-m3/
        model.onnx        dynamic int8 (about 570 MB)
        tokenizer.json
        manifest.json     model_id / dimensions / version / sha256 of each file

A pinned revision keeps the vector contract reproducible: vectors built from
different revisions must not be mixed, so changing --revision means a new
``version`` and a full re-embedding.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

MODEL_ID = "BAAI/bge-m3"
DIMENSIONS = 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--revision", default="main", help="HuggingFace revision (pin a commit hash for releases)")
    parser.add_argument("--version", default="bge-m3-int8-v1", help="vector contract version stored with every vector")
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--no-quantize", action="store_true", help="keep fp32 (about 2.2 GB, more memory)")
    args = parser.parse_args()

    from optimum.onnxruntime import ORTModelForFeatureExtraction
    from transformers import AutoTokenizer

    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bge_m3_export_") as tmp:
        tmp_dir = Path(tmp)
        model = ORTModelForFeatureExtraction.from_pretrained(MODEL_ID, revision=args.revision, export=True)
        model.save_pretrained(tmp_dir)
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=args.revision)
        tokenizer.save_pretrained(tmp_dir)

        source = tmp_dir / "model.onnx"
        target = args.output / "model.onnx"
        if args.no_quantize:
            shutil.copyfile(source, target)
            # Large fp32 exports keep weights in an external data file.
            for extra in tmp_dir.glob("model.onnx_data*"):
                shutil.copyfile(extra, args.output / extra.name)
        else:
            from onnxruntime.quantization import QuantType, quantize_dynamic

            quantize_dynamic(str(source), str(target), weight_type=QuantType.QInt8, use_external_data_format=False)
        shutil.copyfile(tmp_dir / "tokenizer.json", args.output / "tokenizer.json")

    files = {path.name: _sha256(path) for path in sorted(args.output.iterdir()) if path.name != "manifest.json"}
    manifest = {
        "model_id": "bge-m3",
        "source": MODEL_ID,
        "revision": args.revision,
        "dimensions": DIMENSIONS,
        "version": args.version,
        "max_length": args.max_length,
        "pooling": "cls_l2_normalized",
        "quantization": "none" if args.no_quantize else "dynamic_int8",
        "files": files,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
