import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FakeOutput:
    def __init__(self, text: str, images: list | None = None, **usage) -> None:
        self.text = text
        self.images = images or []
        for k, v in usage.items():
            setattr(self, k, v)


@pytest.fixture
def fake_output_cls():
    return FakeOutput
