from flask import Flask, request, jsonify
from llama_cpp import Llama
import os

app = Flask(__name__)

# Model configuration
BASE_MODEL_PATH = os.getenv("BASE_MODEL_PATH", "./models/base_model.gguf")
LORA_PATH = os.getenv("LORA_PATH", os.path.join("./models", "lora_sensitive.gguf"))
N_CTX = int(os.getenv("N_CTX", "8192"))
N_THREADS = int(os.getenv("N_THREADS", "8"))

llm = Llama(
    model_path=BASE_MODEL_PATH,
    lora_path=(LORA_PATH or None),
    n_ctx=N_CTX,
    n_threads=N_THREADS,
    logits_all=False,
    verbose=False,
)

@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "base_model": os.path.basename(BASE_MODEL_PATH),
        "lora": (os.path.basename(LORA_PATH) if (LORA_PATH or '').strip() else "none")
    })

@app.post("/complete")
def complete():
    data = request.get_json(silent=True) or {}
    user_input = data.get("input") or data.get("prompt") or ""
    if not user_input:
        return jsonify({"error": "missing input"}), 400

    response = llm(
        user_input,
        max_tokens=int(data.get("max_tokens", 4096)),
        temperature=float(data.get("temperature", 0.0)),
        top_p=float(data.get("top_p", 1.0)),
        stop=data.get("stop")
    )

    full_text = response.get("choices", [{}])[0].get("text", "")
    # first line for quick view, full_output carries entire raw text
    if isinstance(full_text, str) and full_text.splitlines():
        first_line = full_text.splitlines()[0]
    else:
        first_line = full_text

    return jsonify({
        "input": user_input,
        "output": first_line,
        "full_output": full_text,
        "params": {
            "max_tokens": data.get("max_tokens", 4096),
            "temperature": data.get("temperature", 0.0),
            "top_p": data.get("top_p", 1.0),
            "stop": data.get("stop")
        }
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False, threaded=False)