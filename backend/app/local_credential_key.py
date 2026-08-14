from __future__ import annotations

import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet


def ensure_local_credential_key(path: Path) -> str:
    """Create the persistent local Fernet key used by the Windows launcher."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        key = path.read_text(encoding="ascii").strip()
        Fernet(key.encode("ascii"))
        return key

    key = Fernet.generate_key().decode("ascii")
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(key, encoding="ascii")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return key


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data") / "credential.key"
    print(ensure_local_credential_key(path.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
