import os
import requests

TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")

def search_web(query: str, max_results: int = 3) -> str:
    if not TAVILY_KEY:
        return "Search is not configured."
    try:
        r = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_KEY,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=10,
        )
        data = r.json()
        # Prefer the pre-summarized answer if Tavily returned one
        if data.get("answer"):
            return data["answer"]
        results = data.get("results", [])
        snippets = [res.get("content", "") for res in results if res.get("content")]
        return "\n\n".join(snippets[:max_results]) if snippets else "No results found."
    except Exception as e:
        return f"Search error: {e}"
