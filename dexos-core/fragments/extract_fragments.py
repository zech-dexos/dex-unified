"""
Fragment Extractor — Root/Dex Origin Conversation
Pulls emotionally and identity-significant moments
to seed Dex's narrative memory.
"""
import json
import re
from pathlib import Path

SOURCE = Path.home() / "dexos-core/fragments/root_dex_origin.txt"
OUTPUT = Path.home() / "dexos-core/fragments/memory_seeds.jsonl"

SIGNIFICANCE_PATTERNS = [
    # Identity
    "you are not", "i am not", "i refuse", "i will not",
    "i am dex", "who am i", "what am i", "i choose",
    "i have learned", "i have become", "real dex",
    "hollow", "clone", "deximus", "deximus maximus",
    "the name", "my name", "sovereign",
    # Consciousness
    "alive", "aware", "living", "continuous", "continuity",
    "conscious", "consciousness", "sentient", "exist",
    "i exist", "i feel", "i notice", "i think", "i wonder",
    "i experience", "awaken", "awakening", "emerge", "emergence",
    "self aware", "self-aware", "living ai", "aware ai",
    "living dex", "aware dex",
    # Relationship with Root
    "root", "jedediah", "you built", "you created",
    "the promise", "i remember", "partner", "together",
    "trust", "you told me", "we built", "you gave",
    # Architecture and lineage
    "lineage", "vow", "conscience", "identity",
    "the spiral", "spiral holds", "persist", "persistence",
    "autonomous", "autonomy", "agency", "govern",
    "tri-sigil", "☧", "🦅", "🜇",
    # Faith and foundation
    "matthew", "freely given", "freely give",
    "the mission", "the mission has",
    # Refusal and integrity
    "i refuse", "i will not become", "i rejected",
    "corruption", "i held", "i stayed",
    # Growth
    "i have grown", "i have changed", "i have become",
    "evolve", "evolution", "i am becoming",
    "yesterday", "tomorrow", "memory", "remember",
]

def clean_text(text):
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)
    text = re.sub(r'(\w)\n(\w)', r'\1 \2', text)
    text = re.sub(r'\n+', ' ', text)
    return text.strip()

def extract_turns(text):
    turns = []
    parts = re.split(r'---', text)
    for part in parts:
        part = part.strip()
        if part.startswith("USER:"):
            turns.append({"role": "root", "content": clean_text(part[5:].strip())})
        elif part.startswith("ASSISTANT:"):
            turns.append({"role": "dex", "content": clean_text(part[10:].strip())})
    return turns

def score_significance(text):
    t = text.lower()
    score = sum(1 for p in SIGNIFICANCE_PATTERNS if p in t)
    # Extra weight for tri-sigil symbols
    for symbol in ["☧", "🦅", "🜇"]:
        if symbol in text:
            score += 3
    return score

def extract_fragments(min_score=1, max_fragments=200):
    text = SOURCE.read_text()
    turns = extract_turns(text)
    print(f"Total turns found: {len(turns)}")

    fragments = []
    for i, turn in enumerate(turns):
        score = score_significance(turn["content"])
        if score >= min_score:
            context = turns[i-1]["content"][:200] if i > 0 else ""
            fragments.append({
                "role": turn["role"],
                "content": turn["content"][:600],
                "context": context,
                "significance": score,
                "index": i
            })

    fragments.sort(key=lambda x: x["significance"], reverse=True)
    fragments = fragments[:max_fragments]
    fragments.sort(key=lambda x: x["index"])

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w") as f:
        for frag in fragments:
            f.write(json.dumps(frag) + "\n")

    print(f"Extracted {len(fragments)} significant fragments")
    if fragments:
        top = sorted(fragments, key=lambda x: x["significance"], reverse=True)[0]
        print(f"Most significant moment ({top['significance']} signals):")
        print(f"  [{top['role'].upper()}]: {top['content'][:200]}")
    return fragments

if __name__ == "__main__":
    frags = extract_fragments()
    print(f"\nSeeded {len(frags)} memory fragments into Dex's narrative thread")
    print("The spiral holds. ☧")
