from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def recommend(candidates, profile_text):
    """Rank actual members using only their public posts and the opt-in user's profile."""
    candidates = [candidate for candidate in candidates if candidate.get("text", "").strip()]
    profile_text = profile_text.strip()
    if not candidates or not profile_text:
        return []
    documents = [candidate["text"] for candidate in candidates]
    vectorizer = TfidfVectorizer(stop_words="english")
    try:
        matrix = vectorizer.fit_transform(documents + [profile_text])
    except ValueError:
        return []
    scores = cosine_similarity(matrix[-1], matrix[:-1]).ravel()
    order = sorted(range(len(candidates)), key=lambda index: (-scores[index], candidates[index]["id"]))
    return [
        {**{key: value for key, value in candidates[index].items() if key != "text"},
         "score": round(float(scores[index]), 4)}
        for index in order if scores[index] > 0
    ][:10]
