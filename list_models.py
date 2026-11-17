"""List the model names your API key can use. Run: python list_models.py"""
from core import get_client, MODEL

try:
    names = sorted(m.id.replace("models/", "") for m in get_client().models.list())
except Exception as e:
    print("Could not list models:", e)
    print("Check LLM_BASE_URL in .env is exactly:")
    print("https://generativelanguage.googleapis.com/v1beta/openai/")
    raise SystemExit

flash = [n for n in names if "flash" in n and not any(
    x in n for x in ("image", "tts", "audio", "live", "embedding"))]
print("Text 'flash' models you can use:")
for n in flash:
    print("  ", n)
print("\nCurrently in .env: LLM_MODEL =", MODEL,
      "(OK)" if MODEL in names else "(NOT AVAILABLE - pick one from the list)")
