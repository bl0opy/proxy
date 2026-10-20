import threading
from collections import deque

import numpy as np
import sounddevice as sd

from .stt import SAMPLE_RATE

BLOCK = 512
PREROLL_SECONDS = 0.3
MAX_SECONDS = 30


class Recorder:
    """Keeps the mic open and a short pre-roll, so the first syllable after the
    key goes down is never clipped by stream start-up."""

    def __init__(self, device=None):
        self._lock = threading.Lock()
        self._preroll = deque(maxlen=int(PREROLL_SECONDS * SAMPLE_RATE / BLOCK) + 1)
        self._chunks: list[np.ndarray] | None = None
        self.level = 0.0
        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                      blocksize=BLOCK, device=device, callback=self._on_audio)

    def open(self):
        self._stream.start()

    def close(self):
        self._stream.stop()
        self._stream.close()

    def _on_audio(self, data, frames, time_info, status):
        chunk = data[:, 0].copy()
        self.level = float(np.sqrt(np.mean(chunk * chunk)))
        with self._lock:
            if self._chunks is None:
                self._preroll.append(chunk)
            elif len(self._chunks) * BLOCK < MAX_SECONDS * SAMPLE_RATE:
                self._chunks.append(chunk)

    def start(self):
        with self._lock:
            self._chunks = list(self._preroll)

    def stop(self) -> np.ndarray:
        with self._lock:
            chunks, self._chunks = self._chunks or [], None
        return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
