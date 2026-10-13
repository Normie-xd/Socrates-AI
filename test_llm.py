import config
from llm_client import get_client, generate

client = get_client()

print("Available flash models on your key:")
for m in client.models.list():
    if "flash" in m.name:
        print("  ", m.name)

print(f"\nTesting model: {config.MODEL_NAME}")
print(generate("Reply with exactly: Socrates is online."))