import time
import re
from google import genai


class DailyQuotaExceeded(RuntimeError):
    pass


def _is_daily_quota_error(msg: str) -> bool:
    """Detecta errores de cuota diaria agotada (Free Tier)."""
    return bool(re.search(r"FreeTier|RESOURCE_EXHAUSTED|Quota exceeded", msg, re.I))


def _is_rate_limit_error(msg: str) -> bool:
    """Detecta errores de rate limit temporal (429 / too many requests)."""
    return bool(re.search(r"429|Too Many Requests|RATE_LIMIT", msg, re.I))


def _call_with_retry(fn, retries: int = 3, base_wait: int = 30):
    """
    Ejecuta fn() con reintentos para rate limits temporales (429).

    Espera: 30s → 60s → 90s antes de cada reintento.
    Si el error es de cuota diaria, lo propaga inmediatamente (sin reintentar).
    """
    last_err = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            msg = str(e)
            if _is_daily_quota_error(msg):
                raise  # cuota diaria → propagar para que call_with_key_rotation rote key
            if _is_rate_limit_error(msg):
                last_err = e
                if attempt < retries - 1:
                    wait = base_wait * (attempt + 1)
                    print(f"  ⏳ Rate limit temporal. Esperando {wait}s antes de reintentar...")
                    time.sleep(wait)
                    continue
            raise
    raise last_err


def call_with_key_rotation(client, model: str, key_manager, fn_builder):
    """
    Ejecuta una llamada a la API con:
    1. Retry automático para rate limits temporales (misma key, espera 30/60/90s)
    2. Rotación de key SOLO si hay cuota diaria agotada (FreeTier/RESOURCE_EXHAUSTED)

    Args:
        client: genai.Client activo.
        model: Nombre del modelo.
        key_manager: Instancia de KeyManager.
        fn_builder: Callable que recibe client y devuelve una función sin args
                    que hace la llamada. Ejemplo:
                    lambda c: (lambda: c.models.generate_content(...))

    Returns:
        El resultado de la llamada.

    Raises:
        DailyQuotaExceeded: Si todas las keys están agotadas.
    """
    last_err = None

    for attempt in range(len(key_manager.keys)):
        try:
            return _call_with_retry(fn_builder(client))

        except Exception as e:
            msg = str(e)
            if _is_daily_quota_error(msg):
                last_err = e
                new_key = key_manager.next_key()
                client = genai.Client(api_key=new_key)
                print(f"  🔄 Cuota diaria agotada. Rotando a key #{attempt + 2}...")
                continue
            raise  # Error no relacionado a cuota/rate limit

    raise DailyQuotaExceeded(
        "Todas las API keys han agotado su cuota diaria. Reintentar mañana."
    ) from last_err
