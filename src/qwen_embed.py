import os
import sys


def _session_memory():
    tools_dir = os.environ.get("SESSION_MEMORY_TOOLS", "")
    if tools_dir and tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import session_memory as sm
    except ImportError as exc:
        raise RuntimeError(
            "session_memory is unavailable; set SESSION_MEMORY_TOOLS or PYTHONPATH"
        ) from exc
    return sm
DIM = int(os.environ.get("METTACLAW_EMBED_DIM", "1024"))
DEVICE = os.environ.get("METTACLAW_EMBED_DEVICE", "auto")
BATCH_SIZE = int(os.environ.get("METTACLAW_EMBED_BATCH_SIZE", "1"))
MAX_TOKENS = int(os.environ.get("METTACLAW_EMBED_MAX_TOKENS", "4096"))
QUERY_PROMPT_NAME = os.environ.get("METTACLAW_EMBED_QUERY_PROMPT_NAME", "query")
NORMALIZE = os.environ.get("METTACLAW_EMBED_NORMALIZE", "1").lower() not in {
    "0",
    "false",
    "no",
}


def _embed(text, is_query):
    model = os.environ.get("METTACLAW_EMBED_MODEL", "")
    if not model:
        raise RuntimeError("METTACLAW_EMBED_MODEL is not set")
    sm = _session_memory()
    return sm.sentence_transformer_embed(
        model_name_or_path=model,
        texts=[str(text)],
        is_query=is_query,
        truncate_dim=DIM,
        device=DEVICE,
        batch_size=BATCH_SIZE,
        max_tokens_per_text=MAX_TOKENS,
        normalize_embeddings=NORMALIZE,
        query_prompt_name=QUERY_PROMPT_NAME,
    )[0]


def embed_document(text):
    return _embed(text, False)


def embed_query(text):
    return _embed(text, True)
