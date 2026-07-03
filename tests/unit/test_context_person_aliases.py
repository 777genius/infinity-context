from infinity_context_core.application.context_person_aliases import person_labels_match


def test_person_labels_do_not_match_different_full_names_by_given_name() -> None:
    assert not person_labels_match("Alice Chen", "Alice Smith")


def test_person_labels_preserve_full_name_to_given_name_alias() -> None:
    assert person_labels_match("Alice Chen", "Alice")
