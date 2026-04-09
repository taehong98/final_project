EUNCHUL CORE PATCH

Use this patch when Taehong's project already has its own DB, RAG, and run environment.

This patch contains:
- AI integration route changes
- AI summary / translation / reason modules
- frontend language/detail integration
- env example updates

Overlay this folder on top of Taehong's project root.

Important:
- Do not copy db.sqlite3 or chroma.sqlite3 from this patch.
- Ollama + qwen3.5:4b should be available if you want translated detail output.
