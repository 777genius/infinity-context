"""Published PostgreSQL migration identities accepted by all migration consumers."""

PUBLISHED_MIGRATION_CHECKSUMS: dict[str, frozenset[str]] = {
    "0030_suggestion_receipt_tenant_integrity": frozenset(
        {"4d936c3d49f76028eec009a1b1e8ee2bcf214b2b4a03e7ac120bad5321aa3064"}
    ),
    "0039_locator_retrieval_attributes": frozenset(
        {"83f22c9e4087e6f4713294665a00ce99f7ffc981893702a2fbb3a575813c418d"}
    ),
    "0040_locator_profile_lifecycle": frozenset(
        {"2b972527e5a2f6e99f5bd69b6eca9c22a51b8cb4902b1d4e13f7e0260138edaa"}
    ),
    "0046_locator_profile_linearizable_fences": frozenset(
        {"a069a1c2707366c364206e70740b37b9f5720597a133b2d63eab1e324f85313e"}
    ),
}


def is_compatible_migration_checksum(
    migration_id: str,
    observed_checksum: object,
    current_checksum: str,
) -> bool:
    """Return whether history names the current or a published migration identity."""

    return observed_checksum == current_checksum or observed_checksum in (
        PUBLISHED_MIGRATION_CHECKSUMS.get(migration_id, frozenset())
    )


__all__ = ("PUBLISHED_MIGRATION_CHECKSUMS", "is_compatible_migration_checksum")
