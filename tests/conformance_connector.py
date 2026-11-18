"""What the conformance suite needs from Yir: its Job envelopes, faked."""

from __future__ import annotations

from engine_conformance import Behaviours, Call, Connector, Provider


class YirConnector(Connector):
    package = "engine_yir"

    #: Yir needs a prompt on every model, so there is no prompt_optional or prompt_none entry.
    entries = {
        "text_to_image": "IMG-Models/minimax-h3-image.toml",
        "image_to_video": "VID-Models/h3-max-turbo.toml",
    }

    provider_modules = ()
    supports_polling = True
    #: Yir nests the prompt and references under ``input``.
    flat_payload = False

    def install(self, monkeypatch, behaviours: Behaviours) -> Provider:
        provider = Provider()
        state = {"submit": list(behaviours.submit_errors)}

        class FakeClient:
            def request_json(self, method, path, payload=None, *, headers=None, params=None):
                if method == "GET" and not path.endswith("/status"):
                    return {"id": "job-1", "status": "succeeded",
                            "result": {"files": [{"url": u} for u in behaviours.result_urls[:1]]}}
                if method == "GET":
                    provider.calls.append(Call(kind="poll", path=path))
                    if behaviours.poll_error is not None:
                        raise behaviours.poll_error
                    statuses = behaviours.poll_statuses
                    index = min(state.get("polls", 0), len(statuses) - 1)
                    state["polls"] = state.get("polls", 0) + 1
                    status = {"completed": "succeeded"}.get(statuses[index], statuses[index])
                    return {"id": "job-1", "status": status}

                # The suite reads prompt and parameters at the top level.
                flat = {**payload.get("input", {}), **payload.get("parameters", {}),
                        "model": payload.get("model")}
                provider.calls.append(Call(kind="submit", payload=flat, path=path))
                if behaviours.submit_error is not None:
                    raise behaviours.submit_error
                if state["submit"]:
                    raise state["submit"].pop(0)
                return {"id": "job-1", "status": "queued"}

            def download(self, url):
                provider.downloads.append(url)
                provider.calls.append(Call(kind="download", url=url))
                if behaviours.download_error is not None:
                    raise behaviours.download_error
                return behaviours.result_bytes

        fake = FakeClient()
        monkeypatch.setattr(self.engine_class(), "_client", lambda _self: fake)
        return provider
