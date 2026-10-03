"""3-stage LLM Council orchestration, behind the Laya gatekeeper."""

from typing import List, Dict, Any, Tuple, AsyncIterator
import asyncio
import time
from .claude_cli import query_model
from .config import (
    CHAIRMAN_MODEL, FAST_MODEL, SOLO_MODEL, DOMAIN_COUNCILS,
    HISTORY_TURNS, HISTORY_ANSWER_CHARS,
)
from . import laya_gate, usage

JUDGE_PROMPT = "You are an impartial judge evaluating answers written by other experts."


async def _query_members(members: List[Dict[str, Any]], messages, system_prompt=None):
    """Query each council member in parallel, in its own role unless one is given."""
    responses = await asyncio.gather(*[
        query_model(m["model"], messages, system_prompt=system_prompt or m["system_prompt"])
        for m in members
    ])
    return {m["id"]: r for m, r in zip(members, responses)}


async def stage1_collect_responses(user_query: str, members: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Stage 1: Collect individual responses from all council models.

    Args:
        user_query: The user's question

    Returns:
        List of dicts with 'model' and 'response' keys
    """
    messages = [{"role": "user", "content": user_query}]

    # Query all members in parallel, each in its role
    responses = await _query_members(members or DOMAIN_COUNCILS["general"], messages)

    # Format results
    stage1_results = []
    for model, response in responses.items():
        if response is not None:  # Only include successful responses
            stage1_results.append({
                "model": model,
                "response": response.get('content', ''),
                "usage": response.get('usage')
            })

    return stage1_results


async def stage2_collect_rankings(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    members: List[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Stage 2: Each model ranks the anonymized responses.

    Args:
        user_query: The original user query
        stage1_results: Results from Stage 1

    Returns:
        Tuple of (rankings list, label_to_model mapping)
    """
    # Create anonymized labels for responses (Response A, Response B, etc.)
    labels = [chr(65 + i) for i in range(len(stage1_results))]  # A, B, C, ...

    # Create mapping from label to model name
    label_to_model = {
        f"Response {label}": result['model']
        for label, result in zip(labels, stage1_results)
    }

    # Build the ranking prompt
    responses_text = "\n\n".join([
        f"Response {label}:\n{result['response']}"
        for label, result in zip(labels, stage1_results)
    ])

    ranking_prompt = f"""You are evaluating different responses to the following question:

Question: {user_query}

Here are the responses from different models (anonymized):

{responses_text}

Your task:
1. First, evaluate each response individually. For each response, explain what it does well and what it does poorly.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for your ENTIRE response:

Response A provides good detail on X but misses Y...
Response B is accurate but lacks depth on Z...
Response C offers the most comprehensive answer...

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""

    messages = [{"role": "user", "content": ranking_prompt}]

    # Get rankings from all council members in parallel, as neutral judges
    responses = await _query_members(members or DOMAIN_COUNCILS["general"], messages, system_prompt=JUDGE_PROMPT)

    # Format results
    stage2_results = []
    for model, response in responses.items():
        if response is not None:
            full_text = response.get('content', '')
            parsed = parse_ranking_from_text(full_text)
            stage2_results.append({
                "model": model,
                "ranking": full_text,
                "parsed_ranking": parsed,
                "usage": response.get('usage')
            })

    return stage2_results, label_to_model


async def stage3_synthesize_final(
    user_query: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Stage 3: Chairman synthesizes final response.

    Args:
        user_query: The original user query
        stage1_results: Individual model responses from Stage 1
        stage2_results: Rankings from Stage 2

    Returns:
        Dict with 'model' and 'response' keys
    """
    # Build comprehensive context for chairman
    stage1_text = "\n\n".join([
        f"Model: {result['model']}\nResponse: {result['response']}"
        for result in stage1_results
    ])

    stage2_text = "\n\n".join([
        f"Model: {result['model']}\nRanking: {result['ranking']}"
        for result in stage2_results
    ])

    chairman_prompt = f"""You are the Chairman of an LLM Council. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.

Original Question: {user_query}

STAGE 1 - Individual Responses:
{stage1_text}

STAGE 2 - Peer Rankings:
{stage2_text}

Your task as Chairman is to synthesize all of this information into a single, comprehensive, accurate answer to the user's original question. Consider:
- The individual responses and their insights
- The peer rankings and what they reveal about response quality
- Any patterns of agreement or disagreement

Provide a clear, well-reasoned final answer that represents the council's collective wisdom:"""

    messages = [{"role": "user", "content": chairman_prompt}]

    # Query the chairman model
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        # Fallback if chairman fails
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Unable to generate final synthesis."
        }

    return {
        "model": CHAIRMAN_MODEL,
        "response": response.get('content', ''),
        "usage": response.get('usage')
    }


def parse_ranking_from_text(ranking_text: str) -> List[str]:
    """
    Parse the FINAL RANKING section from the model's response.

    Args:
        ranking_text: The full text response from the model

    Returns:
        List of response labels in ranked order
    """
    import re

    # Look for "FINAL RANKING:" section
    if "FINAL RANKING:" in ranking_text:
        # Extract everything after "FINAL RANKING:"
        parts = ranking_text.split("FINAL RANKING:")
        if len(parts) >= 2:
            ranking_section = parts[1]
            # Try to extract numbered list format (e.g., "1. Response A")
            # This pattern looks for: number, period, optional space, "Response X"
            numbered_matches = re.findall(r'\d+\.\s*Response [A-Z]', ranking_section)
            if numbered_matches:
                # Extract just the "Response X" part
                return [re.search(r'Response [A-Z]', m).group() for m in numbered_matches]

            # Fallback: Extract all "Response X" patterns in order
            matches = re.findall(r'Response [A-Z]', ranking_section)
            return matches

    # Fallback: try to find any "Response X" patterns in order
    matches = re.findall(r'Response [A-Z]', ranking_text)
    return matches


def calculate_aggregate_rankings(
    stage2_results: List[Dict[str, Any]],
    label_to_model: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    Calculate aggregate rankings across all models.

    Args:
        stage2_results: Rankings from each model
        label_to_model: Mapping from anonymous labels to model names

    Returns:
        List of dicts with model name and average rank, sorted best to worst
    """
    from collections import defaultdict

    # Track positions for each model
    model_positions = defaultdict(list)

    for ranking in stage2_results:
        ranking_text = ranking['ranking']

        # Parse the ranking from the structured format
        parsed_ranking = parse_ranking_from_text(ranking_text)

        for position, label in enumerate(parsed_ranking, start=1):
            if label in label_to_model:
                model_name = label_to_model[label]
                model_positions[model_name].append(position)

    # Calculate average position for each model
    aggregate = []
    for model, positions in model_positions.items():
        if positions:
            avg_rank = sum(positions) / len(positions)
            aggregate.append({
                "model": model,
                "average_rank": round(avg_rank, 2),
                "rankings_count": len(positions)
            })

    # Sort by average rank (lower is better)
    aggregate.sort(key=lambda x: x['average_rank'])

    return aggregate


async def generate_conversation_title(user_query: str) -> str:
    """
    Generate a short title for a conversation based on the first user message.

    Args:
        user_query: The first user message

    Returns:
        A short title (3-5 words)
    """
    title_prompt = f"""Generate a very short title (3-5 words maximum) that summarizes the following question.
The title should be concise and descriptive. Do not use quotes or punctuation in the title.

Question: {user_query}

Title:"""

    messages = [{"role": "user", "content": title_prompt}]

    # Use the fast model for title generation
    response = await query_model(FAST_MODEL, messages, timeout=60.0)

    if response is None:
        # Fallback to a generic title
        return "New Conversation"

    title = response.get('content', 'New Conversation').strip()

    # Clean up the title - remove quotes, limit length
    title = title.strip('"\'')

    # Truncate if too long
    if len(title) > 50:
        title = title[:47] + "..."

    return title


MODES = ("auto",) + laya_gate.ROUTES


async def laya_route(user_query: str, mode: str = "auto") -> Dict[str, Any]:
    """
    Ask the Laya gatekeeper how to handle the query, and attach the chosen members.

    Args:
        user_query: The user's current message (without history; Laya reads ~500 tokens)
        mode: "auto" to follow Laya, or "fast" / "solo" / "council" to override it
    """
    decision = await laya_gate.classify(user_query)
    if mode != "auto" and mode != decision["route"]:
        laya_gate.log_override(user_query, decision["route"], mode)
        decision["laya_route"] = decision["route"]
        decision["route"] = mode
        decision["override"] = True
    if decision["route"] == "fast":
        decision["members"] = [FAST_MODEL]
    elif decision["route"] == "solo":
        decision["members"] = [SOLO_MODEL]
    else:
        decision["members"] = [m["id"] for m in DOMAIN_COUNCILS[decision["domain"]]]
    return decision


async def single_answer(query: str, route: str, domain: str) -> Dict[str, Any]:
    """Answer with one model: the fast model, or the solo model in the topic's lead role."""
    if route == "fast":
        model, system_prompt = FAST_MODEL, None
    else:
        model, system_prompt = SOLO_MODEL, DOMAIN_COUNCILS[domain][0]["system_prompt"]
    response = await query_model(model, [{"role": "user", "content": query}], system_prompt=system_prompt)
    if response is None:
        return {"model": model, "response": "Error: Unable to generate a response."}
    return {"model": model, "response": response.get('content', ''), "usage": response.get('usage')}


def with_history(history: List[Dict[str, Any]], query: str) -> str:
    """
    Put the earlier conversation in front of the new question, so follow-ups make sense.

    Args:
        history: Stored conversation messages before this question
        query: The new question
    """
    turns = []
    pending_user = None
    for msg in history:
        if msg["role"] == "user":
            pending_user = msg["content"]
        elif pending_user is not None:
            answer = ((msg.get("stage3") or {}).get("response") or "").strip()
            if len(answer) > HISTORY_ANSWER_CHARS:
                answer = answer[:HISTORY_ANSWER_CHARS] + " [...]"
            turns.append((pending_user, answer))
            pending_user = None
    turns = turns[-HISTORY_TURNS:]
    if not turns:
        return query

    earlier = "\n\n".join(f"User: {q}\n\nAssistant: {a}" for q, a in turns)
    return f"""Conversation so far:

{earlier}

---

Now answer the user's new message, using the conversation above as context:

{query}"""


async def run_turn(
    user_query: str,
    history: List[Dict[str, Any]] = None,
    mode: str = "auto"
) -> AsyncIterator[Tuple[str, Dict[str, Any]]]:
    """
    Answer one message: Laya gate, then the fast, solo or full council route.

    Yields (event_type, payload) as each step finishes. The last event is "turn_result",
    carrying everything needed to save the answer.
    """
    started = time.perf_counter()
    laya = await laya_route(user_query, mode)
    yield "laya_complete", {"data": laya}

    query = with_history(history or [], user_query)
    route = laya["route"]
    stage1_results, stage2_results, metadata = [], [], {}

    if route in ("fast", "solo"):
        yield "stage3_start", {}
        stage3_result = await single_answer(query, route, laya["domain"])
        yield "stage3_complete", {"data": stage3_result}
    else:
        members = DOMAIN_COUNCILS[laya["domain"]]

        yield "stage1_start", {}
        stage1_results = await stage1_collect_responses(query, members)
        yield "stage1_complete", {"data": stage1_results}

        if not stage1_results:
            stage3_result = {"model": "error", "response": "All models failed to respond. Please try again."}
            yield "stage3_complete", {"data": stage3_result}
        else:
            yield "stage2_start", {}
            stage2_results, label_to_model = await stage2_collect_rankings(query, stage1_results, members)
            metadata = {
                "label_to_model": label_to_model,
                "aggregate_rankings": calculate_aggregate_rankings(stage2_results, label_to_model),
            }
            yield "stage2_complete", {"data": stage2_results, "metadata": metadata}

            yield "stage3_start", {}
            stage3_result = await stage3_synthesize_final(query, stage1_results, stage2_results)
            yield "stage3_complete", {"data": stage3_result}

    turn_usage = {
        **usage.total(stage1_results, stage2_results, stage3_result),
        "seconds": round(time.perf_counter() - started, 1),
        "route": route,
    }
    usage.record(route, turn_usage, turn_usage["seconds"], bool(laya.get("override")))
    yield "usage_complete", {"data": turn_usage}

    yield "turn_result", {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": {**metadata, "laya": laya},
        "laya": laya,
        "usage": turn_usage,
    }


async def run_full_council(user_query: str, history=None, mode: str = "auto") -> Dict[str, Any]:
    """Run one turn to completion and return its result (non-streaming)."""
    result = {}
    async for event_type, payload in run_turn(user_query, history, mode):
        if event_type == "turn_result":
            result = payload
    return result
