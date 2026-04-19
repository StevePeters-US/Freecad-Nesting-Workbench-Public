import random
import copy

def tournament_selection(ranked_population, k=3):
    """
    Selects a parent from the ranked population using tournament selection.
    ranked_population: list of (fitness, chromosome) tuples.
    """
    # Ensure ranking is sorted (best/lowest fitness first)
    # We select k random individuals
    if len(ranked_population) < k:
        k = len(ranked_population)
    
    participants = random.sample(ranked_population, k)
    # The one with the lowest fitness score wins
    participants.sort(key=lambda x: x[0])
    return participants[0][1]

def crossover_genes(parent1_genes, parent2_genes):
    """
    OX1 crossover on (part_id, angle) gene tuples.
    Copies a random slice from parent1 (preserving angles), fills remaining
    positions from parent2 in order. Returns a new list of tuples.
    """
    size = len(parent1_genes)
    if size == 0:
        return []
    if size == 1:
        return list(parent1_genes)

    child = [None] * size
    start, end = sorted(random.sample(range(size), 2))

    child[start:end] = parent1_genes[start:end]
    child_ids = {gene[0] for gene in child if gene is not None}

    p2_idx = 0
    for i in range(size):
        if child[i] is None:
            while parent2_genes[p2_idx][0] in child_ids:
                p2_idx += 1
            child[i] = parent2_genes[p2_idx]
            child_ids.add(parent2_genes[p2_idx][0])
            p2_idx += 1

    return child


def mutate_genes(genes, mutation_rate, rotation_steps):
    """
    Mutation on (part_id, angle) gene tuples. Returns a new list (not in-place).

    Operators:
    - Swap: exchange two random genes
    - Segment reversal: reverse a sub-sequence
    - Adjacent swap: swap two neighboring genes
    - Rotation: replace angle of one gene with a random valid rotation step
    """
    if len(genes) < 1:
        return list(genes)

    genes = list(genes)

    if len(genes) >= 2:
        if random.random() < mutation_rate:
            i, j = random.sample(range(len(genes)), 2)
            genes[i], genes[j] = genes[j], genes[i]

        if random.random() < mutation_rate * 0.5:
            start = random.randint(0, len(genes) - 2)
            end = random.randint(start + 1, len(genes))
            genes[start:end] = list(reversed(genes[start:end]))

        if random.random() < mutation_rate * 0.3:
            i = random.randint(0, len(genes) - 2)
            genes[i], genes[i + 1] = genes[i + 1], genes[i]

    if rotation_steps > 1 and random.random() < mutation_rate:
        idx = random.randrange(len(genes))
        part_id, _ = genes[idx]
        new_angle = random.randrange(rotation_steps) * (360.0 / rotation_steps)
        genes[idx] = (part_id, new_angle)

    return genes
