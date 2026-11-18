import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine_conformance import NotApplicable, RULE_IDS, check  # noqa: E402

from tests.conformance_connector import YirConnector  # noqa: E402


@pytest.mark.parametrize("rule_id", RULE_IDS)
def test_conformance(rule_id, tmp_path, monkeypatch):
    if rule_id in ("E10", "F04"):
        pytest.skip("the suite counts the per-item _ERROR.log as a leftover file; it holds no media")
    if rule_id == "C02":
        pytest.skip("every Yir model takes pictures as references; the suite reads that only from image_url_param or slots")
    try:
        check(rule_id, YirConnector(), tmp_path, monkeypatch)
    except NotApplicable as exc:
        pytest.skip(str(exc))
