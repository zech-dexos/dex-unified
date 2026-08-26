import requests
from urllib.parse import quote

TOOL_NAME = "search"
TRIGGERS = ["who is", "what is", "where is", "when is", "how do", "find", "look up", "search", "weather", "news", "current", "latest", "today", "what are", "tell me about"]

def run(query: str) -> str:
    try:
        url = f"https://api.duckduckgo.com/?q={quote(query)}&format=json&no_redirect=1&no_html=1"
        r = requests.get(url, timeout=8)
        data = r.json()
        
        abstract = data.get("AbstractText", "")
        if abstract and len(abstract) > 50:
            return abstract[:400]
        
        related = data.get("RelatedTopics", [])
        results = []
        for item in related[:3]:
            if isinstance(item, dict) and item.get("Text"):
                results.append(item["Text"][:150])
        
        if results:
            return " | ".join(results)
            
        return ""
        
    except Exception:
        return ""
