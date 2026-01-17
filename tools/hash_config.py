import argparse
import hashlib
from pathlib import Path


def compute_hash(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Compute config hash.")
    parser.add_argument("--config", required=True, help="Path to settings.yaml")
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    print(compute_hash(config_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
