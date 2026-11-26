"""Step 1: Understanding of Euclidean distance and cosine similarity in 2D."""

import math   # gives sqrt (square root)

# The three stored points, each with a name.
POINTS = {
    "p1 (2, 3)": (2, 3),    # "My name is Saurabh"
    "p2 (1, 2)": (1, 2),    # "I used to teach data"
    "p3 (0, 4)": (0, 4),   # "I have delievered projects"
}
QUERY = (2, 4)      # "Saurabh is my name"

def euclidean(a, b):
    """Straight-line distance: square root of the sum of squared differences."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

def dot(a, b):
    """Dot product: multiply the matching parts, then add them up."""
    return sum(x * y for x, y in zip(a, b))

def norm(a):
    """Length of a vector: square root of the sum of its squared parts"""
    return math.sqrt(sum(x ** 2 for x in a))

def cosine(a, b):
    """Cosine similarity: dot product divided by the two lengths multiplied."""
    return dot(a, b) / (norm(a) * norm(b))

def main() -> None:
    # Calculate both measures for every point
    distances = {name: euclidean(QUERY, p) for name, p in POINTS.items()}
    cosines = {name: cosine(QUERY, p) for name, p in POINTS.items()}

    print(f"Query: {QUERY}\n")

    # Euclidean: smallest distance first.
    print("Euclidean distance (smaller = closer)")
    ranked = sorted(distances, key=distances.get)                 # point names, smallest distance first
    for rank, name in enumerate(ranked, start=1):                 # number them 1, 2, 3
        print(f"  {rank}. {name}  {distances[name]:.3f}")         # look up each point's distance

    # Cosine: biggest similarity first.
    print("\nCosine similarity (bigger = more similar)")
    ranked = sorted(cosines, key=cosines.get, reverse=True)       # point names, biggest cosine first
    for rank, name in enumerate(ranked, start=1):
        print(f"  {rank}. {name}  {cosines[name]:.3f}")

if __name__ == "__main__":
    main()