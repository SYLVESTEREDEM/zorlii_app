import re


WORD_RE = re.compile(r"[a-z0-9']+", re.IGNORECASE)


def extractive_context(text: str, question: str, limit: int = 3):
    """Return relevant original sentences; this deliberately does not generate prose."""
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text)
        if sentence.strip()
    ]
    if not sentences:
        return []
    query_terms = {
        word.lower()
        for word in WORD_RE.findall(question)
        if len(word) > 2
    }

    def score(sentence):
        words = [word.lower() for word in WORD_RE.findall(sentence)]
        if not words:
            return 0.0
        overlap = sum(1 for word in words if word in query_terms)
        return overlap / (len(set(words)) ** 0.5)

    ranked = sorted(enumerate(sentences), key=lambda item: (-score(item[1]), item[0]))
    selected = [sentence for _, sentence in ranked[:limit] if score(sentence) > 0]
    if not selected:
        selected = sentences[: min(limit, len(sentences))]
    selected_set = set(selected)
    return [sentence for sentence in sentences if sentence in selected_set][:limit]
