import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]


def test_release_repository_push_uses_scoped_http_auth_header():
    workflow_path = ROOT / ".github" / "workflows" / "release.yml"
    # The published distribution is the target of the source repository's
    # publishing workflow, not its owner. Never copy publisher credentials
    # or its workflow into the distribution just to satisfy this test.
    if os.environ.get("GITHUB_REPOSITORY") == "libing28390-sketch/Release-netops":
        assert not workflow_path.exists(), "Publisher workflow must not ship in the release tree"
        return
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["release-ubuntu"]["steps"]
    publish_step = next(step for step in steps if step.get("name") == "Commit sanitized Ubuntu release tree")

    assert publish_step["env"]["RELEASE_REPO_TOKEN"] == "${{ secrets.RELEASE_REPO_TOKEN }}"
    script = publish_step["run"]
    assert "https://github.com/libing28390-sketch/Release-netops.git" in script
    assert "${{ secrets.RELEASE_REPO_TOKEN }}@github.com" not in script
    assert "printf 'x-access-token:%s' \"$RELEASE_REPO_TOKEN\"" in script
    assert "::add-mask::$auth_header" in script

    push_commands = [line.strip() for line in script.splitlines() if " push " in line and line.strip().startswith("git -c ")]
    assert len(push_commands) == 2  # main plus an optional version tag
    assert all(line.startswith('git -c "http.https://github.com/.extraheader=') for line in push_commands)

    missing_secret_check = script.index('[[ -z "${RELEASE_REPO_TOKEN:-}" ]]')
    credential_setup = script.index("git remote add origin")
    assert missing_secret_check < credential_setup
