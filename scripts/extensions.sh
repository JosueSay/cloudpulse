
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTENSIONS_FILE="$ROOT_DIR/.vscode/extensions.json"

usage() {
    echo "Usage: $0 {install|list}"
    exit 1
}

if [[ ! -f "$EXTENSIONS_FILE" ]]; then
    echo "Error: $EXTENSIONS_FILE not found." >&2
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required." >&2
    exit 1
fi

# VS Code extensions.json allows JSONC comments.
# Extract extension IDs from the recommendations array.
read_extensions() {
    python3 - "$EXTENSIONS_FILE" <<'PY'
import json
import re
import sys
from pathlib import Path

content = Path(sys.argv[1]).read_text(encoding="utf-8")

# Remove full-line JSONC comments.
content = re.sub(r"(?m)^\s*//.*$", "", content)
# Remove trailing commas.
content = re.sub(r",\s*([}\]])", r"\1", content)

config = json.loads(content)

for extension in config.get("recommendations", []):
    print(extension)
PY
}

case "${1:-}" in
    list)
        echo "Recommended VS Code extensions:"
        read_extensions
        ;;

    install)
        if ! command -v code >/dev/null 2>&1; then
            echo "Error: VS Code CLI 'code' not found." >&2
            echo "Open this project in VS Code WSL and retry." >&2
            exit 1
        fi

        echo "Installing recommended VS Code extensions..."

        while IFS= read -r extension; do
            [[ -z "$extension" ]] && continue

            echo "Installing: $extension"
            code --install-extension "$extension"
        done < <(read_extensions)

        echo "Extension installation completed."
        ;;

    *)
        usage
        ;;
esac
