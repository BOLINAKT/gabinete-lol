from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from shutil import copy2


FILES_TO_SNAPSHOT = [
    "ml_artifact.json",
    "players_artifact.json",
    "params_fitted.json",
    "mlcore/tests/fixtures/odds_regression.json",
    "mlcore/tests/fixtures/odds_regression_40.json",
    "mlcore/tests/fixtures/interleague_matchups_regression.json",
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description="Create versioned baseline snapshot.")
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--root", default=".")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d")
    out_dir = root / "ops" / "baselines" / f"{stamp}_{args.tag}"
    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for rel in FILES_TO_SNAPSHOT:
        src = root / rel
        if not src.exists():
            continue
        dst = out_dir / Path(rel).name
        copy2(src, dst)
        entries.append(
            {
                "file": Path(rel).as_posix(),
                "snapshot_file": dst.name,
                "size_bytes": dst.stat().st_size,
                "sha256": sha256_of(dst),
            }
        )

    manifest = {
        "created_at_utc": now.isoformat(),
        "tag": args.tag,
        "entries": entries,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[ok] baseline snapshot: {out_dir}")
    print(f"[ok] files: {len(entries)}")


if __name__ == "__main__":
    main()
