"""Lazy, optional frozen LAION-CLAP encoder."""

from __future__ import annotations

from pathlib import Path


class ClapUnavailable(RuntimeError):
    pass


class ClapEmbedder:
    def __init__(self, checkpoint: Path | str, *, device: str = "cpu"):
        try:
            import laion_clap
            import torch
        except ImportError as error:
            raise ClapUnavailable(
                "Install requirements-recommendation-ai.txt to enable CLAP embeddings"
            ) from error
        self.torch = torch
        self.model = laion_clap.CLAP_Module(enable_fusion=False, device=device)
        self.model.load_ckpt(str(Path(checkpoint).expanduser()))
        for parameter in self.model.model.parameters():
            parameter.requires_grad_(False)
        self.model.model.eval()

    def audio(self, paths: list[Path | str]) -> list[list[float]]:
        with self.torch.inference_mode():
            values = self.model.get_audio_embedding_from_filelist(
                x=[str(Path(path)) for path in paths], use_tensor=True
            )
        return values.detach().cpu().tolist()

    def text(self, values: list[str]) -> list[list[float]]:
        with self.torch.inference_mode():
            embeddings = self.model.get_text_embedding(values, use_tensor=True)
        return embeddings.detach().cpu().tolist()
