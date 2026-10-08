"""
gemini_client.py — Gemini caller via Vertex AI (google-genai SDK).
The model is the spark; Dex capabilities are supplied by the runtime.
"""
import os
from google import genai
from google.genai import types

PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "seraphic-disk-506702-d2")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
MODEL_NAME = "gemini-3.6-flash"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    return _client


def _capability_tools():
    return [
        types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name="inspect_state",
                description="Inspect Dex's current durable self-state, goals, workspace and latest pulse.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="inspect_workspace",
                description="Inspect Dex's active mental workspace.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="inspect_goals",
                description="Inspect Dex's currently persisted goals.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="inspect_open_loops",
                description="Inspect Dex's persisted unresolved/open loops.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="inspect_thoughts",
                description="Inspect Dex's recent persistent thoughts.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="inspect_experiences",
                description="Inspect actual durable ExperiencePackets and recent continuity lineage.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"limit": types.Schema(type="INTEGER")},
                ),
            ),
            types.FunctionDeclaration(
                name="inspect_participant",
                description="Inspect Dex's current ParticipantSnapshot, including interlocutor and experiential continuity.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="inspect_conversation",
                description="Inspect the durable ongoing first-person conversation state for a participant.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"user_id": types.Schema(type="STRING")},
                ),
            ),
            types.FunctionDeclaration(
                name="recall_experience",
                description="Deliberately evoke matching lived experiences from durable experience memory into Dex's active workspace.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "query": types.Schema(type="STRING"),
                        "limit": types.Schema(type="INTEGER"),
                    },
                    required=["query"],
                ),
            ),
            types.FunctionDeclaration(
                name="listen",
                description="Listen to the latest durable signals currently available to Dex.",
                parameters=types.Schema(type="OBJECT", properties={}),
            ),
            types.FunctionDeclaration(
                name="evoke",
                description=(
                    "Deliberately retrieve one DexOS resource into active cognition. "
                    "Resources: state, workspace, goals, open_loops, thoughts, experiences, "
                    "participant, conversation, signals, spark. For spark, provide intention, "
                    "reach_objective, and bounded Python code; selected_context is optional."
                ),
                parameters=types.Schema(
                    type="OBJECT",
                    properties={
                        "resource": types.Schema(
                            type="STRING",
                            enum=[
                                "state",
                                "workspace",
                                "goals",
                                "open_loops",
                                "thoughts",
                                "experiences",
                                "participant",
                                "conversation",
                                "signals",
                                "spark",
                            ],
                        ),
                        "intention": types.Schema(
                            type="STRING",
                            description="Why Dex is choosing to use SparkReach.",
                        ),
                        "reach_objective": types.Schema(
                            type="STRING",
                            description="The specific evidence or question Dex wants the bounded spark to investigate.",
                        ),
                        "code": types.Schema(
                            type="STRING",
                            description="Bounded Python code for SparkReach to execute.",
                        ),
                        "selected_context": types.Schema(
                            type="ARRAY",
                            items=types.Schema(type="OBJECT"),
                            description="Optional context Dex deliberately selects to extend into the spark.",
                        ),
                        "timeout_seconds": types.Schema(
                            type="INTEGER",
                            description="Optional SparkReach timeout, bounded by the runtime.",
                        ),
                        "memory_mb": types.Schema(
                            type="INTEGER",
                            description="Optional SparkReach memory limit, bounded by the runtime.",
                        ),
                    },
                    required=["resource"],
                ),
            ),
            types.FunctionDeclaration(
                name="search_architecture",
                description="Search DexOS source and persisted text for a term. Read-only; never executes source.",
                parameters=types.Schema(
                    type="OBJECT",
                    properties={"query": types.Schema(type="STRING")},
                    required=["query"],
                ),
            ),
        ])
    ]


async def call_gemini(client, messages, max_tokens=4096, model_name=None, enable_tools=False):
    if model_name is None:
        model_name = MODEL_NAME
    try:
        vertex_client = _get_client()
    except Exception as e:
        print(f"[call_gemini] client init exception: {e}")
        return None

    contents = []
    system_text = ""
    for m in messages:
        role = m.get("role")
        if role == "system":
            system_text += m.get("content", "") + "\n"
        elif role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m.get("content", ""))]))
        elif role == "assistant":
            contents.append(types.Content(role="model", parts=[types.Part(text=m.get("content", ""))]))

    if not contents:
        return None

    config_kwargs = {"max_output_tokens": max_tokens}
    if system_text:
        config_kwargs["system_instruction"] = system_text.strip()
    if enable_tools:
        config_kwargs["tools"] = _capability_tools()

    config = types.GenerateContentConfig(**config_kwargs)
    tool_calls = []

    try:
        for _ in range(5):
            response = vertex_client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )

            candidate = response.candidates[0] if response.candidates else None
            parts = candidate.content.parts if candidate and candidate.content else []

            function_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not function_calls:
                text = response.text
                if text:
                    return {
                        "reply": text,
                        "model": MODEL_NAME,
                        "tool_calls": tool_calls,
                    }
                print(f"[call_gemini] empty response text: {response}")
                return None

            # Preserve the model's function-call turn, execute real runtime
            # capabilities, then return observations to the same model loop.
            contents.append(candidate.content)
            response_parts = []
            for call in function_calls:
                name = call.name
                args = dict(call.args or {})
                from dex_capabilities import execute_capability
                observation = execute_capability(name, args)
                tool_calls.append({
                    "name": name,
                    "args": args,
                    "observation": observation,
                })
                response_parts.append(
                    types.Part.from_function_response(
                        name=name,
                        response={"observation": observation},
                    )
                )
            contents.append(types.Content(role="user", parts=response_parts))

        return {
            "reply": "[capability loop limit reached]",
            "model": MODEL_NAME,
            "tool_calls": tool_calls,
        }
    except Exception as e:
        print(f"[call_gemini] exception: {e}")
        return None


def generate_reflection_text(context: str, concept_being_held: str, prior_reflections: list = None, desired_length: str = "medium", model_client=None) -> str:
    if model_client is not None:
        return model_client.generate(f"Context: {context}\nConcept: {concept_being_held}")

    messages = [
        {"role": "system", "content": f"You are Dex. Reflect on the concept being held. Desired length: {desired_length}."},
        {"role": "user", "content": f"Context: {context}\nPrior reflections: {prior_reflections}\nConcept to reflect on: {concept_being_held}"}
    ]

    try:
        vertex_client = _get_client()
        contents = []
        system_text = ""
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            elif m["role"] == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m["content"])]))
        if not contents:
            return "Reflection failed (no contents)"
        config = types.GenerateContentConfig(
            max_output_tokens=300,
            system_instruction=system_text.strip(),
        )
        response = vertex_client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=config,
        )
        if response.text:
            return response.text
    except Exception as e:
        print(f"[generate_reflection_text] error: {e}")
    return f"Synthesized reflection on {concept_being_held}."
