import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine_yir import Engine, InputFile  # noqa: E402
from engine_yir.catalog import load_catalog  # noqa: E402
from engine_yir.payloads import build_input  # noqa: E402
from engine_yir.transport import ProviderError  # noqa: E402

MP4 = b"\x00\x00\x00\x18ftypmp42clip"
PNG = b"\x89PNG\r\n\x1a\nimage"
SLOTS = {"reference_images": ["i.png"], "reference_videos": ["v.mp4"], "reference_audios": ["s.mp3"]}


class Fake:
    """Stands in for transport.Client: records every call, never touches the network."""

    def __init__(self, status="succeeded", submit_errors=()):
        self.posts, self.gets, self.status = [], [], status
        self.submit_errors = list(submit_errors)

    def request_json(self, method, path, payload=None, *, headers=None, params=None):
        if method == "POST":
            self.posts.append({"path": path, "body": payload, "headers": dict(headers or {})})
            if self.submit_errors:
                raise self.submit_errors.pop(0)
            return {"id": "job_1", "object": "job", "status": "queued"}
        self.gets.append((path, params))
        if path == "v1/jobs/job_1/status":
            error = {"code": "YIR_CONTENT_REJECTED", "message": "rejected by moderation"}
            return {"id": "job_1", "status": self.status,
                    "error": error if self.status != "succeeded" else None}
        assert path == "v1/jobs/job_1"
        return {"id": "job_1", "status": "succeeded",
                "result": {"files": [{"url": "https://cdn.invalid/out"}]}}

    def download(self, url):
        return PNG if "image" in self.posts[-1]["path"] else MP4


def run(model, params, item, tmp_path, monkeypatch, fake=None):
    fake = fake or Fake()
    monkeypatch.setattr(Engine, "_client", lambda _self: fake)
    profile = {"platform": "yir", "endpoint": model, "parameters": params,
               "poll_interval": 0, "retry_base_delay": 0}
    return Engine(profile, tmp_path / "out", api_key="k").run([item]), fake


def item(tmp_path, **kw):
    return InputFile(path=tmp_path / "s.md", prompt=kw.pop("prompt", "a fox"), **kw)


def body(model, params, it):
    spec = load_catalog().get(model)
    return build_input({}, spec, params, it.prompt, it)


def test_a_prompt_runs_as_text_and_the_file_is_saved(tmp_path, monkeypatch):
    out, fake = run("minimax/minimax-h3-max", {"aspect_ratio": "9:16", "duration": 5},
                    item(tmp_path), tmp_path, monkeypatch)
    assert out[0].status == "ok" and out[0].path.read_bytes() == MP4
    post = fake.posts[0]
    assert post["path"] == "v1/videos/generations"
    assert post["body"] == {"model": "minimax/minimax-h3-max",
                            "input": {"type": "text", "prompt": "a fox"},
                            "parameters": {"aspect_ratio": "9:16", "duration": 5}}
    assert post["headers"]["Idempotency-Key"]
    assert fake.gets[0] == ("v1/jobs/job_1/status", {"wait": "20"})


def test_an_image_model_posts_to_images(tmp_path, monkeypatch):
    out, fake = run("minimax/minimax-h3-image", {"resolution": "2K"}, item(tmp_path),
                    tmp_path, monkeypatch)
    assert out[0].status == "ok" and out[0].path.suffix == ".png"
    assert fake.posts[0]["path"] == "v1/images/generations"


def test_start_and_end_frames_drop_an_aspect_the_image_input_does_not_take(tmp_path):
    payload, warnings = body("minimax/minimax-h3-max", {"aspect_ratio": "16:9", "resolution": "768P"},
                             item(tmp_path, reference_urls=["a.png", "b.png"]))
    assert payload["input"]["type"] == "image"
    assert payload["input"]["references"] == [{"role": "first_frame", "url": "a.png"},
                                              {"role": "last_frame", "url": "b.png"}]
    assert payload["parameters"] == {"resolution": "768P"}
    assert any("aspect_ratio" in w for w in warnings)


def test_a_picture_is_a_reference_image_where_the_model_takes_no_first_frame(tmp_path):
    for model, kind in (("minimax/minimax-h3-lite", "reference"),
                        ("minimax/minimax-h3-highspeed", "reference"),
                        ("minimax/minimax-h3-image-highspeed", "image")):
        payload, _ = body(model, {}, item(tmp_path, reference_urls=["a.png"]))
        assert payload["input"] == {"type": kind, "prompt": "a fox",
                                    "references": [{"role": "reference_image", "url": "a.png"}]}


def test_declared_slots_become_references(tmp_path):
    payload, _ = body("minimax/minimax-h3-max", {}, item(tmp_path, references=SLOTS))
    assert payload["input"]["type"] == "reference"
    assert payload["input"]["references"] == [{"role": "reference_image", "url": "i.png"},
                                              {"role": "reference_video", "url": "v.mp4"},
                                              {"role": "reference_audio", "url": "s.mp3"}]


@pytest.mark.parametrize("kw", [{}, {"reference_urls": ["a.png"]}, {"references": SLOTS}])
def test_slot_keys_in_the_profile_never_reach_parameters(tmp_path, kw):
    params = {key: ["x.png"] for key in SLOTS} | {"seed": 3, "duration": 5}
    payload, _ = body("minimax/minimax-h3-max", params, item(tmp_path, **kw))
    assert payload["parameters"] == {"duration": 5}


def test_only_the_chosen_input_types_parameters_go_out(tmp_path):
    payload, _ = body("minimax/minimax-h3-image-highspeed",
                      {"resolution": "2K", "aspect_ratio": "1:1", "duration": 5},
                      item(tmp_path, reference_urls=["a.png"]))
    assert payload["parameters"] == {"aspect_ratio": "1:1"}


def test_a_duration_outside_the_contract_refuses_the_item(tmp_path, monkeypatch):
    out, fake = run("minimax/minimax-h3-max", {"duration": 3}, item(tmp_path), tmp_path, monkeypatch)
    assert out[0].status == "error" and "duration" in out[0].error_msg
    assert fake.posts == []


def test_a_model_without_text_input_refuses_a_prompt_alone(tmp_path, monkeypatch):
    out, fake = run("minimax/minimax-h3-lite", {}, item(tmp_path), tmp_path, monkeypatch)
    assert out[0].status == "error" and fake.posts == []


def test_a_retried_submit_keeps_its_idempotency_key(tmp_path, monkeypatch):
    fake = Fake(submit_errors=[ProviderError(503, "temporarily unavailable")])
    out, _ = run("minimax/minimax-h3", {}, item(tmp_path), tmp_path, monkeypatch, fake)
    assert out[0].status == "ok" and len(fake.posts) == 2
    assert fake.posts[0]["headers"] == fake.posts[1]["headers"]
    _, other = run("minimax/minimax-h3", {}, item(tmp_path), tmp_path, monkeypatch)
    assert other.posts[0]["headers"] != fake.posts[0]["headers"]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_a_failed_job_and_a_refused_request_name_yirs_reason(tmp_path, monkeypatch, status):
    out, _ = run("minimax/minimax-h3-max", {}, item(tmp_path), tmp_path, monkeypatch, Fake(status))
    assert out[0].status == "error" and "rejected by moderation" in out[0].error_msg
    refused = ProviderError(400, "aspect_ratio='5:4' is not allowed")
    out, _ = run("minimax/minimax-h3-max", {}, item(tmp_path), tmp_path, monkeypatch,
                 Fake(submit_errors=[refused]))
    assert out[0].status == "error" and "5:4" in out[0].error_msg
