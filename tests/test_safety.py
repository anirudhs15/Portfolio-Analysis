"""Guards that keep this project read-only and free of secrets."""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
REPO = SRC.parent

FORBIDDEN_CALLS = ["place_order", "modify_order", "cancel_order", "create_smart_order",
                   "modify_smart_order", "cancel_smart_order"]


def test_no_order_placement_anywhere_in_source():
    for f in SRC.rglob("*.py"):
        text = f.read_text()
        for call in FORBIDDEN_CALLS:
            assert call not in text, f"{call} found in {f} - this project must stay read-only"


def test_no_hardcoded_credentials():
    pattern = re.compile(r"(GROWW_TOTP_(TOKEN|SECRET)|CAS_PASSWORD)\s*=\s*['\"][^'\"]+['\"]")
    for f in list(REPO.rglob("*.py")) + list(REPO.rglob("*.yml")) + list(REPO.rglob("*.yaml")):
        if ".git" in f.parts:
            continue
        assert not pattern.search(f.read_text()), f"Possible hard-coded credential in {f}"
