import os
from pathlib import Path
from dotenv import load_dotenv
from itertools import cycle

class KeyManager:
    def __init__(self, env_path: str):
        env_file = Path(env_path).resolve()
        load_dotenv(dotenv_path=env_file, override=True)

        keys_raw = os.getenv("GEMINI_KEYS", "").strip()

        # fallback a key única
        if not keys_raw:
            single = os.getenv("GEMINI_API_KEY", "").strip()
            if single:
                keys_raw = single
            else:
                raise ValueError("No GEMINI_KEYS ni GEMINI_API_KEY en .env")

        self.keys = [k.strip() for k in keys_raw.split(",") if k.strip()]
        self._cycle = cycle(self.keys)

    def next_key(self):
        return next(self._cycle)