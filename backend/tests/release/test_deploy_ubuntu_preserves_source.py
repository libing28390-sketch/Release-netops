from pathlib import Path


def test_ubuntu_deploy_does_not_delete_checked_out_source_tree():
    script = (Path(__file__).resolve().parents[3] / "deploy-ubuntu.sh").read_text(encoding="utf-8")

    assert 'rm -rf "$PROJECT_DIR/backend/tests"' not in script
    assert 'rm -rf "$PROJECT_DIR/docs"' not in script
    assert 'find "$PROJECT_DIR" -maxdepth 2 -type f -name "*.md"' not in script
    assert "不执行目录清理" in script
