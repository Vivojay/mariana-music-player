import sys
from types import SimpleNamespace

import pytest

from recommendation_engine.embeddings import ClapEmbedder, ClapUnavailable


def test_clap_unavailable_message(monkeypatch):
    monkeypatch.setitem(sys.modules, "laion_clap", None)
    with pytest.raises(ClapUnavailable, match="requirements-recommendation-ai"):
        ClapEmbedder("missing.pt")


def test_clap_encoder_is_frozen_and_normalizes_outputs(monkeypatch, tmp_path):
    class Tensor:
        def detach(self):
            return self

        def cpu(self):
            return self

        def tolist(self):
            return [[0.1, 0.2]]

    class Parameter:
        def __init__(self):
            self.frozen = False

        def requires_grad_(self, value):
            self.frozen = not value

    parameter = Parameter()

    class Module:
        def __init__(self, **_kwargs):
            self.model = SimpleNamespace(parameters=lambda: [parameter], eval=lambda: None)

        def load_ckpt(self, value):
            self.checkpoint = value

        def get_audio_embedding_from_filelist(self, **_kwargs):
            return Tensor()

        def get_text_embedding(self, *_args, **_kwargs):
            return Tensor()

    class Inference:
        def __enter__(self):
            pass

        def __exit__(self, *_args):
            pass

    monkeypatch.setitem(sys.modules, "laion_clap", SimpleNamespace(CLAP_Module=Module))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=lambda: Inference()))
    embedder = ClapEmbedder(tmp_path / "model.pt")
    assert parameter.frozen
    assert embedder.audio([tmp_path / "song.wav"]) == [[0.1, 0.2]]
    assert embedder.text(["ambient"]) == [[0.1, 0.2]]
