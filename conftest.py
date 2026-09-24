import sys
import os

# Unit tests must be deterministic and must never depend on a developer's
# provider credentials. Agent tests replace all model calls with mocks; these
# placeholder values only allow LangChain clients to be constructed offline.
os.environ["MODEL_PROVIDER"] = "openai"
os.environ["LLM_API_KEY"] = "test-key-not-used"
os.environ["LLM_MODEL"] = "gpt-4o-mini"
os.environ["EMBEDDING_PROVIDER"] = "openai"
os.environ["EMBEDDING_API_KEY"] = "test-key-not-used"
os.environ["EMBEDDING_MODEL"] = "text-embedding-3-small"
os.environ["RAG_MODE"] = "local"
os.environ["REDIS_STATE_ENABLED"] = "false"
os.environ["SEMANTIC_CACHE_ENABLED"] = "false"
os.environ["MODEL_ROUTING_ENABLED"] = "false"

# Ensure the project root is on sys.path so that `config`, `agents`,
# `services`, etc. are importable when pytest is invoked from any directory.
sys.path.insert(0, os.path.dirname(__file__))
