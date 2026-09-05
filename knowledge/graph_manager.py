import json
from pathlib import Path
from typing import Any, Dict, List

def _load_graph(path: Path) -> Dict[str, Any]:
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {"nodes": {}, "edges": []}

def _save_graph(graph: Dict[str, Any], path: Path) -> None:
    with open(path, "w") as f:
        json.dump(graph, f, indent=2)

def add_node(identifier: str, node_type: str, content: str, path: Path) -> None:
    graph = _load_graph(path)
    graph["nodes"][identifier] = {
        "id": identifier,
        "type": node_type,
        "content": content
    }
    _save_graph(graph, path)

def add_edge(source: str, target: str, relation: str, weight: float, path: Path) -> None:
    graph = _load_graph(path)
    graph["edges"].append({
        "source": source,
        "target": target,
        "relation": relation,
        "weight": weight
    })
    _save_graph(graph, path)

def get_related_knowledge_nodes(concept_identifier: str, max_depth: int = 2, min_relevance_score: float = 0.7, path: Path = None) -> List[Dict[str, Any]]:
    if path is None:
        return []
    graph = _load_graph(path)
    if concept_identifier not in graph["nodes"]:
        return []

    related = []
    visited_ids = {concept_identifier}
    current_level = {concept_identifier}

    for depth in range(max_depth):
        next_level = set()
        for current_id in current_level:
            for edge in graph["edges"]:
                if edge["source"] == current_id and edge["weight"] >= min_relevance_score:
                    target_id = edge["target"]
                    if target_id not in visited_ids and target_id in graph["nodes"]:
                        visited_ids.add(target_id)
                        next_level.add(target_id)
                        related.append(graph["nodes"][target_id])
        if not next_level:
            break
        current_level = next_level

    return related
