import random
import copy

def create_random_chromosome(parts, rotation_steps=1):
    """
    Creates a random chromosome (list of parts) from the given parts.
    Shuffles order and assigns random rotations if rotation_steps > 1.
    """
    chromosome = [copy.deepcopy(p) for p in parts]
    random.shuffle(chromosome)
    if rotation_steps > 1:
        for part in chromosome:
            angle = random.randrange(rotation_steps) * (360.0 / rotation_steps)
            part.set_rotation(angle)
    return chromosome

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

def ordered_crossover(parent1, parent2):
    """
    Performs ordered crossover (OX1) on the part order to produce a child.
    Preserves relative ordering from parents.
    """
    size = len(parent1)
    child_p = [None] * size
    
    if size > 1:
        start, end = sorted(random.sample(range(size), 2))
    else:
        start, end = 0, size
        
    # Copy slice from parent1
    child_p[start:end] = parent1[start:end]
    child_ids_set = {p.id for p in child_p if p is not None}
    
    # Fill remaining spots from parent2
    p2_index = 0
    for i in range(size):
        if child_p[i] is None:
            # Find next part in parent2 that isn't already in child
            while parent2[p2_index].id in child_ids_set:
                p2_index += 1
            child_p[i] = parent2[p2_index]
            p2_index += 1
            
    return child_p

def mutate_chromosome(chromosome, mutation_rate, rotation_steps):
    """
    Mutates a chromosome in place with multiple mutation operators:
    - Swap mutation: swap two random parts
    - Segment reversal: reverse a random segment
    - Adjacent swap: swap two adjacent parts
    - Rotation mutation: rotate a random part
    """
    if len(chromosome) < 2:
        return
    
    # Swap mutation - swap two random parts
    if random.random() < mutation_rate:
        i, j = random.sample(range(len(chromosome)), 2)
        chromosome[i], chromosome[j] = chromosome[j], chromosome[i]
    
    # Segment reversal mutation - reverse a random segment
    if random.random() < mutation_rate * 0.5:  # Less frequent
        start = random.randint(0, len(chromosome) - 2)
        end = random.randint(start + 1, len(chromosome))
        chromosome[start:end] = reversed(chromosome[start:end])
    
    # Adjacent swap mutation - swap two adjacent parts
    if random.random() < mutation_rate * 0.3:  # Less frequent
        i = random.randint(0, len(chromosome) - 2)
        chromosome[i], chromosome[i + 1] = chromosome[i + 1], chromosome[i]
    
    # Rotation mutation - rotate a random part
    if rotation_steps > 1 and random.random() < mutation_rate:
        part = random.choice(chromosome)
        new_angle = random.randrange(rotation_steps) * (360.0 / rotation_steps)
        part.set_rotation(new_angle)
    
    # Rotation spreading - slightly adjust rotations of multiple parts
    if rotation_steps > 1 and random.random() < mutation_rate * 0.2:
        for part in chromosome:
            if random.random() < 0.3:  # 30% chance per part
                current_step = int(part._angle / (360.0 / rotation_steps)) if hasattr(part, '_angle') else 0
                # Move to adjacent rotation step
                delta = random.choice([-1, 1])
                new_step = (current_step + delta) % rotation_steps
                new_angle = new_step * (360.0 / rotation_steps)
                part.set_rotation(new_angle)


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
