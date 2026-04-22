import asyncio
from pathlib import Path

from ruamel.yaml import YAML

from server.config_store import ConfigStore


SAMPLE = """\
server:
  host: 0.0.0.0
  port: 8080
  log_level: INFO

# API keys for clients calling this gateway
api_keys:
  - sk-test

gemini:
  secure_1psid: "psid-value"
  # the program will rewrite this field
  secure_1psidts: "original-ts"
  proxy: null
  refresh_interval: 600
  timeout: 450
"""


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(SAMPLE, encoding="utf-8")
    return p


def test_load_parses_sample(tmp_path):
    path = _write(tmp_path)
    store = ConfigStore(path)
    cfg = store.load()
    assert cfg.gemini.secure_1psid == "psid-value"
    assert cfg.gemini.secure_1psidts == "original-ts"
    assert cfg.api_keys == ["sk-test"]
    assert cfg.server.port == 8080


def test_current_requires_load(tmp_path):
    import pytest
    path = _write(tmp_path)
    store = ConfigStore(path)
    with pytest.raises(RuntimeError):
        _ = store.current


async def test_update_psidts_persists_and_preserves_comments(tmp_path):
    path = _write(tmp_path)
    store = ConfigStore(path)
    store.load()

    await store.update_psidts("new-ts-1")
    content = path.read_text(encoding="utf-8")
    assert "new-ts-1" in content
    assert "original-ts" not in content
    # comment preserved
    assert "# the program will rewrite this field" in content
    # re-parsable
    yaml = YAML()
    data = yaml.load(content)
    assert data["gemini"]["secure_1psidts"] == "new-ts-1"
    assert store.current.gemini.secure_1psidts == "new-ts-1"


async def test_update_psidts_concurrent(tmp_path):
    path = _write(tmp_path)
    store = ConfigStore(path)
    store.load()

    values = [f"v{i}" for i in range(20)]
    await asyncio.gather(*(store.update_psidts(v) for v in values))

    yaml = YAML()
    data = yaml.load(path.read_text(encoding="utf-8"))
    final = data["gemini"]["secure_1psidts"]
    assert final in values
    assert store.current.gemini.secure_1psidts == final


async def test_update_psidts_empty_is_noop(tmp_path):
    path = _write(tmp_path)
    store = ConfigStore(path)
    store.load()
    before = path.read_text(encoding="utf-8")
    await store.update_psidts("")
    after = path.read_text(encoding="utf-8")
    assert before == after


async def test_update_psidts_leaves_no_temp_files(tmp_path):
    path = _write(tmp_path)
    store = ConfigStore(path)
    store.load()
    await store.update_psidts("fresh-ts")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != path.name and not p.name.endswith(".lock")]
    assert leftovers == []
