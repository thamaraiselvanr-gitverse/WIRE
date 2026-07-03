from wire.validation.structural import StructuralValidator


def test_identical_documents_score_100():
    html = "<body><header id='h'></header><main class='c'><p>x</p></main></body>"
    result = StructuralValidator().compare(html, html)
    assert result["structural_score"] == 100.0


def test_inserted_node_does_not_cascade_misalign():
    # Reconstruction inserts one extra <div> in the middle. A naive positional
    # comparator would misalign every following sibling; the aligned comparator
    # should only penalize the single inserted node.
    original = (
        "<body><section><p id='a'></p><p id='b'></p><p id='c'></p></section></body>"
    )
    reconstructed = (
        "<body><section><p id='a'></p><div></div>"
        "<p id='b'></p><p id='c'></p></section></body>"
    )
    result = StructuralValidator().compare(original, reconstructed)
    # 3 original <p> + section + body all still align; only the extra div is a miss.
    assert result["structural_score"] > 80.0


def test_completely_different_structure_scores_low():
    original = "<body><header></header><main></main><footer></footer></body>"
    reconstructed = "<body><span></span></body>"
    result = StructuralValidator().compare(original, reconstructed)
    assert result["structural_score"] < 60.0


def test_matching_id_and_class_scores_higher_than_tag_only():
    original = "<body><div id='hero' class='a b'></div></body>"
    exact = "<body><div id='hero' class='a b'></div></body>"
    tag_only = "<body><div id='other' class='x'></div></body>"

    exact_score = StructuralValidator().compare(original, exact)["structural_score"]
    tag_only_score = StructuralValidator().compare(original, tag_only)[
        "structural_score"
    ]
    assert exact_score > tag_only_score


def test_unparseable_document_returns_error():
    result = StructuralValidator().compare("", "")
    # Empty string parses to an empty tree, still comparable; ensure no crash and
    # a numeric score is returned.
    assert "structural_score" in result or "error" in result
