import os

import numpy as np

SAMPLE_RATE = 16000
MODEL = os.environ.get("PARAKEET_MODEL", "mlx-community/parakeet-tdt-0.6b-v3")


class Transcriber:
    """Not thread-safe: MLX streams belong to the thread that loaded the model,
    so load() and transcribe() must run on the same thread."""

    def __init__(self, model: str = MODEL):
        self._name = model
        self._model = None

    def load(self):
        from parakeet_mlx import from_pretrained
        self._model = from_pretrained(self._name)
        self.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))

    def transcribe(self, samples: np.ndarray) -> str:
        import mlx.core as mx
        from parakeet_mlx.audio import get_logmel

        if samples.size == 0:
            return ""
        mel = get_logmel(mx.array(samples.astype(np.float32)), self._model.preprocessor_config)
        result = self._model.generate(mel)
        if isinstance(result, list):
            result = result[0] if result else None
        return (result.text if result else "").strip()
