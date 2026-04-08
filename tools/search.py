"""Example tool: search a knowledge base."""

from tools.registry import tool


@tool(description="Search an internal knowledge base by query string")
def search_knowledge_base(query: str, top_k: int = 3) -> dict:
    """Return simulated search results. Replace with Azure AI Search, etc."""
    return {
        "query": query,
        "results": [
            {"title": f"Result {i}", "snippet": f"Snippet for '{query}' (#{i})"}
            for i in range(1, top_k + 1)
        ],
    }
