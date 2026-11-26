"""Step 4: normalise vectors and show that cosine and dot product then give the same ranking."""

import numpy as np
from vector_internals.brute_force import load_chunks, load_queries

def normalise(m):
    """Divide each vector by its own length, so every vector has length 1 (same direction)"""
    return m / np.linalg.norm(m, axis=-1, keepdims=True)

def cosine_scores(m, q):
    """Cosine similarity of q with row of m."""
    return (m @ q) / (np.linalg.norm(m, axis=-1) * np.linalg.norm(q))

def top5(scores):
    """Positions of the 5 biggest scores, biggest first"""
    return np.argsort(-scores, kind="stable")[:5].tolist()

def main() -> None:
    # Part 1: the 2D example (not normalised to start with).
    names = ["p1 (2,3)", "p2 (1,2)", "p3 (0,4)"]
    points = np.array([[2, 3], [1, 2], [0, 4]], dtype=float)
    query = np.array([2, 4], dtype=float)

    print("2D example")
    for label, m, q in [("Before normalizing", points, query),
                        ("After normalizing", normalise(points), normalise(query))]:
        dots, cosines = m @ q, cosine_scores(m, q)                        # both scores for the 3 points
        dot_rank = [names[i] for i in np.argsort(-dots, kind="stable")]  # biggest dot product first
        cos_rank = [names[i] for i in np.argsort(-cosines, kind="stable")]  # biggest cosine first
        print(f"  {label}")
        print(f"    dot product  {np.round(dots, 3).tolist()}  ranking {dot_rank}")
        print(f"    cosine       {np.round(cosines, 3).tolist()}  ranking {cos_rank}")


    # Part 2: the Gemini vectors.
    ids, vectors = load_chunks()
    questions = [np.array(q, dtype=np.float32) for q in load_queries().values()]   # the 10 question vectors, as arrays
    print(f"\nGemini vectors: length of every vector is {np.linalg.norm(vectors, axis=1).mean():.4f} (already normalised)")

    rng = np.random.default_rng(42)                                              # fixed seed = same result every run
    stretched = vectors * rng.uniform(0.5, 2.0, size=(len(vectors), 1)).astype(np.float32)   # give each vector a random length
    unit = normalise(stretched)                                                  # back to length 1

    for label, m in [("Stretched (random lengths)", stretched), ("Normalised again", unit)]:   # check both versions
        agree = sum(top5(m @ q) == top5(cosine_scores(m, q)) for q in questions)              # questions where dot = cosine top 5
        print(f"  {label:<27} dot and cosine give the same top 5 for {agree}/10 questions")


if __name__ == "__main__":
    main()