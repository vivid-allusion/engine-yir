import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine_yir import list_standby_profiles, metadata  # noqa: E402
from engine_yir.catalog import load_catalog  # noqa: E402

VIDEO = {"minimax/minimax-h3-max", "minimax/h3-max-turbo", "minimax/minimax-h3",
         "minimax/minimax-h3-highspeed", "minimax/minimax-h3-lite"}
IMAGE = {"minimax/minimax-h3-image", "minimax/minimax-h3-image-highspeed"}


def test_the_seven_h3_models_are_async_with_a_standby_profile_each():
    specs = {s.model: s for s in load_catalog().specs()}
    assert set(specs) == VIDEO | IMAGE
    for model, spec in specs.items():
        assert spec.mode == "async" and spec.label.endswith("(Yir)")
        assert spec.category == ("VID" if model in VIDEO else "IMG")
    standby = {p.stem for p in list_standby_profiles()}
    assert standby == {m.split("/")[1] for m in specs}


def test_slots_only_where_the_contract_takes_references_beside_a_first_frame():
    specs = {s.model: s for s in load_catalog().specs()}
    with_slots = {m for m, s in specs.items() if s.slots}
    assert with_slots == {"minimax/minimax-h3-max", "minimax/minimax-h3"}


def test_identity():
    assert (metadata.PROVIDER_NAME, metadata.PLATFORM, metadata.API_KEY_ENV_VAR) == (
        "Yir", "yir", "YIR_API_KEY")
