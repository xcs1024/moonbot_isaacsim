from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pi05_remote_scripts_default_to_a800_alias():
    for script in [
        "scripts/bootstrap_pi05_remote.sh",
        "scripts/sync_pi05_dataset_to_remote.sh",
        "scripts/remote_pi05_train.sh",
        "scripts/fetch_pi05_checkpoint.sh",
    ]:
        text = _read(script)
        assert 'REMOTE_ALIAS="${XROBOT_PI05_REMOTE:-A800}"' in text
        assert "hdssh01.casdao.com" not in text
        assert 'REMOTE_ROOT="${XROBOT_PI05_REMOTE_ROOT:-/local/zqm/zxd}"' in text
        assert "/local/zqm/zxd|/local/zqm/zxd/*" in text
        assert "/home/zqm/zxd|/home/zqm/zxd/*" not in text


def test_pi05_remote_scripts_keep_legacy_host_override():
    for script in [
        "scripts/bootstrap_pi05_remote.sh",
        "scripts/sync_pi05_dataset_to_remote.sh",
        "scripts/remote_pi05_train.sh",
        "scripts/fetch_pi05_checkpoint.sh",
    ]:
        text = _read(script)
        assert 'if [ -n "${XROBOT_PI05_REMOTE_HOST:-}" ]; then' in text
        assert 'REMOTE_PORT="${XROBOT_PI05_REMOTE_PORT:-63125}"' in text
        assert 'REMOTE_USER="${XROBOT_PI05_REMOTE_USER:-zqm}"' in text


def test_pi05_remote_bootstrap_pins_openpi_and_checks_space():
    text = _read("tools/openpi_nero/remote_bootstrap.sh")

    assert "c23745b5ad24e98f66967ea795a07b2588ed6c79" in text
    assert "BOOTSTRAP_MIN_FREE_GB" in text
    assert 'git -C "$REMOTE_ROOT/openpi" checkout --detach "$OPENPI_COMMIT"' in text


def test_pi05_remote_train_can_skip_existing_norm_stats():
    text = _read("scripts/remote_pi05_train.sh")

    assert 'SKIP_NORM_STATS="${XROBOT_PI05_SKIP_NORM_STATS:-0}"' in text
    assert 'export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.75}"' in text
    assert 'STATS_DIR="$REMOTE_ROOT/cache/openpi/assets/nero_pi05/$REPO_ID"' in text
    assert "Refusing to skip norm stats" in text
