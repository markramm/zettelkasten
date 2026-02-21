def inverse_link_type(t: str) -> str:
    mapping = {
        "extends": "is_extended_by",
        "is_extended_by": "extends",
        "refines": "is_refined_by",
        "is_refined_by": "refines",
        "supports": "is_supported_by",
        "is_supported_by": "supports",
        "contradicts": "is_contradicted_by",
        "is_contradicted_by": "contradicts",
        "is_example_of": "has_example",
        "has_example": "is_example_of",
        "is_analogous_to": "has_analogy",
        "has_analogy": "is_analogous_to",
        "causally_precedes": "causally_follows",
        "causally_follows": "causally_precedes",
        "asks_question": "answers_question",
        "answers_question": "asks_question",
        "is_part_of": "contains_part",
        "contains_part": "is_part_of",
        "related": "related",
    }
    return mapping.get(t, "related")
