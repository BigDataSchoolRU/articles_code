# ollama (python client) 0.6.2, сервер ollama 0.32.13, прогнано на стенде 2026-08-30
"""
Механизм Modelfile (кастомизация модели поверх готового GGUF-веса) и то, как Ollama
хранит и отдаёт метаданные квантования. Теги qwen2.5:0.5b-instruct-{q4_0,q8_0,fp16}
уже скачаны на стенде.
"""
import ollama

CUSTOM_MODEL = "wiki-ollama-demo"
BASE_MODEL = "qwen2.5:0.5b-instruct-q4_0"
QUANT_TAGS = [
    "qwen2.5:0.5b-instruct-q4_0",
    "qwen2.5:0.5b-instruct-q8_0",
    "qwen2.5:0.5b-instruct-fp16",
]


def demo_modelfile():
    # Modelfile не переобучает и не меняет веса — он навешивает system-промпт и
    # параметры генерации поверх уже скачанного GGUF-файла, поэтому create() занимает
    # секунды, а не время полной загрузки модели.
    for _ in ollama.create(
        model=CUSTOM_MODEL,
        from_=BASE_MODEL,
        system="Отвечай всегда одним словом, без пояснений.",
        parameters={"temperature": 0},
        stream=True,
    ):
        pass  # прогресс создания не нужен статье, важен факт готовности модели

    response = ollama.chat(
        model=CUSTOM_MODEL,
        messages=[{"role": "user", "content": "Столица Франции?"}],
    )
    print(f"[modelfile] кастомная модель '{CUSTOM_MODEL}' ответила: {response['message']['content'].strip()}")

    ollama.delete(CUSTOM_MODEL)
    print(f"[modelfile] '{CUSTOM_MODEL}' удалена, базовый тег {BASE_MODEL} не тронут")


def demo_quantization_metadata():
    # Один и тот же набор весов Qwen2.5 0.5B-instruct, три степени квантования GGUF.
    # ollama show отдаёт эти метаданные без похода в сеть — они лежат в манифесте модели.
    print("[quant] тег -> quantization_level | parameter_size | размер на диске")
    for tag in QUANT_TAGS:
        info = ollama.show(tag)
        details = info.details
        size_mb = _model_size_mb(tag)
        print(f"  {tag:<32} {details.quantization_level:<8} {details.parameter_size:<10} {size_mb} МБ")


def _model_size_mb(tag: str) -> str:
    # ollama.show() не отдаёт размер файла на диске — это поле есть только в ответе
    # /api/tags (то есть в ollama.list()), поэтому размер берётся оттуда отдельно.
    for m in ollama.list().models:
        if m.model == tag:
            return f"{m.size / 1024 / 1024:.0f}"
    return "?"


if __name__ == "__main__":
    demo_modelfile()
    demo_quantization_metadata()
