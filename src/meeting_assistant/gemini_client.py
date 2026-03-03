import os
from google import genai
from meeting_assistant.key_manager import KeyManager

def make_client(env_path: str):
    km = KeyManager(env_path)
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    client = genai.Client(api_key=km.next_key())
    return client, model, km