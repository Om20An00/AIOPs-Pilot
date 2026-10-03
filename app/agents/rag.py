async def rag_agent(incident: dict, tools) -> dict:
    query = f"{incident['title']}. {incident['description']}"
    data = await tools.call("search_similar_incidents", query=query, top_k=3)
    matches = data["matches"]
    votes = {}
    for m in matches:
        # heuristic: cosine similarity of ~0.6 for MiniLM means "clearly the same kind of incident"
        strength = round(max(0.0, min(1.0, (m["similarity"] - 0.2) / 0.4)), 3)
        votes[m["category"]] = max(votes.get(m["category"], 0), strength)
    top = matches[0] if matches else None
    summary = (f"Most similar past incident {top['id']} ({top['category']}, similarity {top['similarity']})."
               if top else "No similar past incidents found.")
    return {"id": "rag", "source": "pgvector_rag", "summary": summary, "votes": votes,
            "details": {"matches": matches}}
