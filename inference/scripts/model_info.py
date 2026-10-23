#!/usr/bin/env python3
"""读取 inference/models.yaml，供 shell 脚本使用。

用法：
  model_info.py list                 # 每行一个模型 key
  model_info.py env <key>            # 输出可 eval 的 MODEL_* 变量
"""

import shlex
import sys
from pathlib import Path

import yaml

REGISTRY = Path(__file__).resolve().parents[1] / "models.yaml"


def load() -> dict:
    with REGISTRY.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["models"]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    models = load()
    command = sys.argv[1]

    if command == "list":
        print("\n".join(models))
        return 0

    if command == "env" and len(sys.argv) == 3:
        key = sys.argv[2]
        if key not in models:
            print(f"unknown model: {key}; see {REGISTRY}", file=sys.stderr)
            return 1
        model = models[key]
        values = {
            "MODEL_KEY": key,
            "MODEL_MODELSCOPE_ID": model["modelscope_id"],
            "MODEL_DIR": model["dir"],
            "MODEL_DTYPE": model.get("dtype") or "auto",
            "MODEL_QUANTIZATION": model.get("quantization") or "",
            "MODEL_TP": " ".join(str(tp) for tp in model.get("tp", [])),
        }
        for name, value in values.items():
            print(f"{name}={shlex.quote(str(value))}")
        return 0

    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
