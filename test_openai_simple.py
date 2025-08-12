from openai import OpenAI
from dotenv import load_dotenv
import os

# Ladda .env-filen först
load_dotenv()

# Enkel test av OpenAI Responses API med gpt-5-mini.
# Förutsätter att OPENAI_API_KEY finns i miljön (.env + python-dotenv om du kör via uv run se-cli etc.)

def extract_text(resp):
    # Försök plocka ut text på ett robust men enkelt sätt
    try:
        pieces = []
        for item in getattr(resp, 'output', []) or []:
            t = getattr(item, 'type', None)
            if t == 'message':
                for block in getattr(item, 'content', []) or []:
                    if getattr(block, 'type', None) in ('output_text', 'text') and hasattr(block, 'text'):
                        pieces.append(block.text)
            elif t in ('output_text', 'text') and hasattr(item, 'text'):
                pieces.append(item.text)
        if pieces:
            return "\n".join(pieces).strip()
        # En del SDK-versioner exponerar output_text direkt
        return getattr(resp, 'output_text', None) or str(resp)
    except Exception:
        return str(resp)

if __name__ == "__main__":
    print(f"API key från miljö: {os.getenv('OPENAI_API_KEY', 'INTE SATT')[:20]}...")
    client = OpenAI()
    prompt = "Write a short bedtime story about a unicorn."
    try:
        resp = client.responses.create(
            model="gpt-5-mini",
            input=prompt,
            max_output_tokens=300,
        )
        print("=== RAW OBJECT (trunkerat) ===")
        print(f"Response type: {type(resp)}")
        print(f"Response dir: {[attr for attr in dir(resp) if not attr.startswith('_')]}")
        if hasattr(resp, 'output'):
            print(f"Output: {resp.output}")
            if resp.output:
                for i, item in enumerate(resp.output):
                    print(f"Output[{i}]: type={getattr(item, 'type', 'NO_TYPE')}, content={getattr(item, 'content', 'NO_CONTENT')}")
        print(str(resp)[:400])
        print("\n=== EXTRAHERAD TEXT ===")
        print(extract_text(resp))
    except Exception as e:
        print("Fel vid anrop:", e)
