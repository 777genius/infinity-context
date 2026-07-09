"""Vault setup use case for the Obsidian connector."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from infinity_context_obsidian.conflicts import CONFLICTS_DIR
from infinity_context_obsidian.layout import DEFAULT_ROOT_FOLDER, ObsidianVaultLayout
from infinity_context_obsidian.ports import VaultPort
from infinity_context_obsidian.sync import INBOX_DIR

ROOT_DIR = PurePosixPath(DEFAULT_ROOT_FOLDER)
GENERATED_DIR = PurePosixPath(f"{DEFAULT_ROOT_FOLDER}/generated")
SETUP_README = ROOT_DIR / "README.md"
INBOX_README = INBOX_DIR / "README.md"
CONFLICTS_README = CONFLICTS_DIR / "README.md"


@dataclass(frozen=True)
class VaultSetupResult:
    written: tuple[str, ...]
    skipped: tuple[str, ...]


@dataclass
class SetupVaultUseCase:
    vault: VaultPort
    layout: ObsidianVaultLayout = field(default_factory=ObsidianVaultLayout)

    def execute(
        self,
        *,
        space_slug: str,
        memory_scope_external_ref: str,
        overwrite: bool = False,
    ) -> VaultSetupResult:
        return self._run(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            overwrite=overwrite,
            apply=True,
        )

    def plan(
        self,
        *,
        space_slug: str,
        memory_scope_external_ref: str,
        overwrite: bool = False,
    ) -> VaultSetupResult:
        return self._run(
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
            overwrite=overwrite,
            apply=False,
        )

    def _run(
        self,
        *,
        space_slug: str,
        memory_scope_external_ref: str,
        overwrite: bool,
        apply: bool,
    ) -> VaultSetupResult:
        written: list[str] = []
        skipped: list[str] = []
        for path, text in _setup_files(
            layout=self.layout,
            space_slug=space_slug,
            memory_scope_external_ref=memory_scope_external_ref,
        ):
            if self.vault.exists(path) and not overwrite:
                skipped.append(path.as_posix())
                continue
            if apply:
                self.vault.write_text(path, text)
            written.append(path.as_posix())
        return VaultSetupResult(written=tuple(written), skipped=tuple(skipped))


def _setup_files(
    *,
    layout: ObsidianVaultLayout,
    space_slug: str,
    memory_scope_external_ref: str,
) -> tuple[tuple[PurePosixPath, str], ...]:
    return (
        (
            layout.root_dir() / "README.md",
            _root_readme(
                layout=layout,
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
            ),
        ),
        (
            layout.inbox_dir(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
            )
            / "README.md",
            _inbox_readme(),
        ),
        (
            layout.conflicts_dir(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
            )
            / "README.md",
            _conflicts_readme(),
        ),
        (
            layout.facts_dir(
                space_slug=space_slug,
                memory_scope_external_ref=memory_scope_external_ref,
            )
            / ".gitkeep.md",
            _generated_keep_readme(),
        ),
    )


def _root_readme(
    *,
    layout: ObsidianVaultLayout,
    space_slug: str,
    memory_scope_external_ref: str,
) -> str:
    return "\n".join(
        [
            "# Infinity Context",
            "",
            "This folder is managed by the Infinity Context Obsidian connector.",
            "",
            "## Scope",
            "",
            f"- Space: `{space_slug}`",
            f"- MemoryScope: `{memory_scope_external_ref}`",
            f"- Layout: `{layout.version.value}`",
            f"- Root folder: `{layout.root_dir().as_posix()}`",
            "",
            "## Folders",
            "",
            "- `spaces/<project>/memory_scopes/<memory_scope>/generated/facts` contains "
            "managed fact notes.",
            "- `spaces/<project>/memory_scopes/<memory_scope>/inbox` is for free-form suggestions.",
            "- `spaces/<project>/memory_scopes/<memory_scope>/conflicts` contains sync "
            "review artifacts.",
            "",
            "Run preview before applying sync changes:",
            "",
            "```bash",
            "infinity-context-obsidian preview --vault <vault> --space "
            f"{space_slug} --memory_scope {memory_scope_external_ref} "
            f'--root-folder "{layout.root_dir().as_posix()}" '
            f"--layout {layout.version.value}",
            "```",
            "",
        ]
    )


def _inbox_readme() -> str:
    return "\n".join(
        [
            "# Infinity Context Inbox",
            "",
            "Write free-form notes here when you want Infinity Context to create pending"
            " suggestions.",
            "",
            "These notes do not directly update canonical facts.",
            "",
        ]
    )


def _conflicts_readme() -> str:
    return "\n".join(
        [
            "# Infinity Context Conflicts",
            "",
            "The connector writes conflict artifacts here when sync cannot safely apply a change.",
            "",
            "Review the referenced source note and backend fact before deleting a conflict file.",
            "",
        ]
    )


def _generated_keep_readme() -> str:
    return "\n".join(
        [
            "# Generated Facts",
            "",
            "Infinity Context writes managed fact notes into this folder.",
            "",
            "Edit only the managed text block in generated notes.",
            "",
        ]
    )
