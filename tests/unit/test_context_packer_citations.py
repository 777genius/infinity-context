from infinity_context_core.application.context_packer import ContextPacker
from infinity_context_core.application.dto import ContextItem
from infinity_context_core.domain.entities import SourceRef


def test_memory_items_render_text_char_range_citations() -> None:
    result = ContextPacker().pack(
        bundle_id="ctx_text_char_range_citations",
        items=(
            ContextItem(
                item_id="chunk_contract",
                item_type="chunk",
                text="Termination clause starts at the cited character range.",
                score=1.0,
                source_refs=(
                    SourceRef(
                        source_type="document",
                        source_id="contract_1",
                        chunk_id="chunk_7",
                        char_start=120,
                        char_end=188,
                        quote_preview="Termination clause starts here.",
                    ),
                ),
                diagnostics={"memory_scope_id": "memory_scope_default"},
            ),
        ),
        token_budget=512,
    )

    rendered = result.bundle.rendered_text
    assert (
        'citations="document:contract_1#chunk_7 chars=120-188 '
        'quote=\\"Termination clause starts here.\\""'
    ) in rendered
