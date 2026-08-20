"""The bumpversion config assertions shared by the language layers.

**Why this module exists.** The same argument :mod:`pytest_rhiza._fences` makes, with far
more weight behind it. That docstring records why the skip-flag helpers were deduplicated
on the move to one distribution::

    Bundles are copied independently — a Rust project receives this file and not the
    other — so a shared helper would need a third home that both bundles ship, which is
    a worse trade for four lines.

    One distribution *is* that third home, so the trade reverses.

``_has_bumpversion_section`` was byte-identical between ``checks/test_cargo_toml.py`` and
``checks/test_go_module.py``, with a third near-copy in ``checks/test_pyproject.py``, and
the two ``TestBumpversionConfig`` classes ran six structurally identical assertions each.
Four lines was the *weak* case for sharing; a hundred and fifty is the strong one (#14).

**What actually varies, and what does not.** The invariant is one thing — bump-my-version
searches four filenames, and finding none it does not fail but falls back to
``git describe``, so a release can be cut at a version that already exists (#1453). Every
layer needs the same six assertions about that. What differs between them is two facts
and three consequences:

* which file holds the version (``Cargo.toml``, ``internal/version/version.go``);
* what anchors the search to it (``[package]``, ``const Version``);
* what specifically goes wrong when each is missing, which is genuinely different — Rust
  has a manifest version to fall back on, Go has nothing but the constant.

So :class:`SyncedBumpversionConfig` holds the logic and the subclass declares those five
things. The prose stays where a reader meets it: in the failure message.

**Why Python does not use the class.** ``checks/test_pyproject.py`` keeps its own, because
for a Python project the config file *is* the manifest. Two of the six assertions have
nothing to say (there is no separate file to target, and nothing to anchor a search to)
and a third inverts: ``current_version`` is forbidden in a file rhiza syncs, but merely
redundant in a pyproject.toml the project owns. It shares the helpers below and stops
there, which is the honest amount.

Security Notes:
- S101 (assert usage): Asserts are appropriate in test code for validating conditions
"""

from __future__ import annotations

import tomllib
from pathlib import Path, PurePosixPath

import pytest

# The only filenames bump-my-version auto-discovers (#1453). Rust and Go projects own
# none of them natively, which is why those bundles ship the first one.
DISCOVERABLE_CONFIGS = (".bumpversion.toml", ".bumpversion.cfg", "setup.cfg", "pyproject.toml")

# The path older template versions shipped a config to. It is never auto-discovered, so a
# leftover copy looks like configuration while doing nothing.
LEGACY_CONFIG = Path(".rhiza") / ".cfg.toml"

# The file rust-core and go-core ship, and the one that must win in both.
SYNCED_CONFIG = ".bumpversion.toml"


def has_bumpversion_section(path: Path) -> bool:
    """Report whether a config file carries a bumpversion section at all.

    Args:
        path: Candidate config file; a missing or malformed file counts as absent.

    Returns:
        True when the file declares ``[tool.bumpversion]`` (TOML) or ``[bumpversion]``
        (INI). ``.bumpversion.toml`` nests the table under ``[tool]`` just as
        pyproject.toml does.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> _ = (root / "pyproject.toml").write_text("[tool.bumpversion]")
        >>> has_bumpversion_section(root / "pyproject.toml")
        True

        A file that exists but declares no section is False, not an error:

        >>> _ = (root / "setup.cfg").write_text("[metadata]")
        >>> has_bumpversion_section(root / "setup.cfg")
        False

        So is a file that is not there at all — the caller asks about candidates:

        >>> has_bumpversion_section(root / ".bumpversion.toml")
        False

        And so is malformed TOML. "We could not read a section out of this" is the same
        answer as "there is none", and the config gate reports the absence rather than
        raising here:

        >>> _ = (root / ".bumpversion.toml").write_text("[tool.bumpversion")
        >>> has_bumpversion_section(root / ".bumpversion.toml")
        False

        Note the ``.cfg`` case above takes the containment branch, not the TOML parser —
        an INI file is never handed to ``tomllib``.
    """
    if not path.is_file():
        return False
    if path.suffix == ".cfg":
        return "[bumpversion]" in path.read_text(encoding="utf-8")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError:
        return False
    return isinstance(data.get("tool", {}).get("bumpversion"), dict)


def discovered_configs(root: Path) -> list[str]:
    """Return the discoverable config filenames that declare a bumpversion section.

    Args:
        root: The repository root.

    Returns:
        The matching names from :data:`DISCOVERABLE_CONFIGS`, in search order.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> discovered_configs(root)
        []

        Search order, not filesystem order — ``.bumpversion.toml`` is what
        bump-my-version reads first, so it leads the list however it was written:

        >>> _ = (root / "pyproject.toml").write_text("[tool.bumpversion]")
        >>> _ = (root / ".bumpversion.toml").write_text("[tool.bumpversion]")
        >>> discovered_configs(root)
        ['.bumpversion.toml', 'pyproject.toml']

        Two entries is the finding, not the goal: the second is a version location
        nobody maintains. :func:`shadowing_configs` is what names it.
    """
    return [name for name in DISCOVERABLE_CONFIGS if has_bumpversion_section(root / name)]


def shadowing_configs(root: Path, winner: str) -> list[str]:
    """Return the configs that declare a section besides the one meant to win.

    Args:
        root: The repository root.
        winner: The filename that is supposed to be the config in use.

    Returns:
        Every other discoverable config that also declares a section. Whether those
        shadow the winner or are shadowed *by* it depends on search order — either way
        the second config is a version location nobody is maintaining.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> _ = (root / ".bumpversion.toml").write_text("[tool.bumpversion]")
        >>> shadowing_configs(root, ".bumpversion.toml")
        []

        A second section anywhere discoverable is reported, whichever way round the
        search order puts them:

        >>> _ = (root / "pyproject.toml").write_text("[tool.bumpversion]")
        >>> shadowing_configs(root, ".bumpversion.toml")
        ['pyproject.toml']

        The winner need not exist for the question to be worth asking — a repo with only
        the *wrong* config is exactly the case the gate is for:

        >>> shadowing_configs(root, "setup.cfg")
        ['.bumpversion.toml', 'pyproject.toml']
    """
    return [name for name in DISCOVERABLE_CONFIGS if name != winner and has_bumpversion_section(root / name)]


def legacy_config_hint(root: Path) -> str:
    """Return an extra sentence when a never-discovered ``.rhiza/.cfg.toml`` is present.

    Args:
        root: The repository root.

    Returns:
        The hint, with a leading space so it appends to a message, or ``""`` when the
        leftover file is absent.

    Examples:
        >>> import tempfile
        >>> root = Path(tempfile.mkdtemp())
        >>> legacy_config_hint(root)
        ''

        Present, and the caller gets a sentence it can concatenate — note the leading
        space, which is why this returns text rather than a bool:

        >>> _ = (root / ".rhiza").mkdir()
        >>> _ = (root / ".rhiza" / ".cfg.toml").write_text("[tool.bumpversion]")
        >>> legacy_config_hint(root).startswith(" A leftover")
        True
    """
    if not (root / LEGACY_CONFIG).is_file():
        return ""
    return (
        " A leftover .rhiza/.cfg.toml is present: that path is never auto-discovered "
        "(it predates the fix for issue #1453) and can be deleted."
    )


def bumpversion_table(path: Path) -> dict:
    """Return the ``[tool.bumpversion]`` table from a TOML config file.

    Args:
        path: A config file known to exist and parse.

    Returns:
        The table, or an empty dict when the file declares none.
    """
    with path.open("rb") as handle:
        return tomllib.load(handle).get("tool", {}).get("bumpversion", {})


def assert_release_flow_owns_the_commit_and_the_tag(table: dict) -> None:
    """Assert the config leaves committing and tagging to ``/rhiza:release``.

    Args:
        table: A parsed ``[tool.bumpversion]`` table.
    """
    for key in ("commit", "tag"):
        assert table.get(key, False) is False, (
            f"[tool.bumpversion].{key} must be false: the release flow commits and tags "
            f"itself so the changelog lands in the bump commit, and a bare "
            f"`bump-my-version bump` would otherwise add a second commit and a duplicate tag"
        )


class SyncedBumpversionConfig:
    """The six assertions a layer needs when rhiza ships its ``.bumpversion.toml``.

    Subclass it as ``TestBumpversionConfig`` in a check module and declare the five class
    attributes below. The base class name deliberately does not start with ``Test``:
    pytest collects classes out of the importing module's namespace, so a ``Test``-prefixed
    base would be collected a second time in every module that imports it.

    Attributes:
        version_file: Repository-relative path a ``[[files]]`` entry must target, in
            ``filename`` form — forward slashes, as TOML carries it.
        search_anchor: Text the entry's ``search`` must contain, so the rewrite cannot
            match a version elsewhere in the same file.
        search_is_regex: Whether the entry must also declare ``regex = true``. True only
            where the anchor cannot be expressed literally.
        bundle: The rhiza bundle that ships the config, named in the restore hint.
        missing_config_consequence: What happens on the fallback to ``git describe``, for
            this language specifically.
        untargeted_consequence: What a bump does when no entry targets the version file.
        unanchored_complaint: How an unanchored ``search`` is wrong here, and what it
            would rewrite instead.
    """

    version_file: str
    search_anchor: str
    search_is_regex: bool = False
    bundle: str
    missing_config_consequence: str
    untargeted_consequence: str
    unanchored_complaint: str

    @property
    def version_file_label(self) -> str:
        """Return the version file's bare name, as messages and skip reasons refer to it.

        Derived, not declared: both layers wanted the basename anyway. ``PurePosixPath``
        because :attr:`version_file` is TOML ``filename`` form — forward-slashed on every
        platform, including the one where ``Path`` would disagree.

        Returns:
            The basename of :attr:`version_file`.
        """
        return PurePosixPath(self.version_file).name

    @pytest.fixture
    def bumpversion(self, root: Path) -> dict:
        """Return the ``[tool.bumpversion]`` table from the synced config.

        Args:
            root: Repository root, from the plugin's :func:`~pytest_rhiza.plugin.root`
                fixture.

        Returns:
            The table. Skips when the file is absent, which
            :meth:`test_a_discoverable_config_exists` reports instead.
        """
        path = root / SYNCED_CONFIG
        if not path.is_file():
            pytest.skip(f"{SYNCED_CONFIG} not found — reported by TestBumpversionConfig")
        return bumpversion_table(path)

    def test_a_discoverable_config_exists(self, root: Path) -> None:
        """A bumpversion section must live in a file bump-my-version actually reads."""
        assert discovered_configs(root), (
            f"No bumpversion config was found in any file bump-my-version searches "
            f"({', '.join(DISCOVERABLE_CONFIGS)}). It will silently fall back to "
            f"`git describe`{self.missing_config_consequence}. Restore the {SYNCED_CONFIG} "
            f"the {self.bundle} bundle ships.{legacy_config_hint(root)}"
        )

    def test_no_other_config_shadows_the_synced_one(self, root: Path) -> None:
        """No second bumpversion section may compete with the synced config.

        ``.bumpversion.toml`` is searched first and wins, so a table declared in a
        manifest the repo carries for other tooling — a helper package's pyproject.toml, a
        stray setup.cfg — is inert. Being inert, it drifts out of step unnoticed, and the
        next reader cannot tell which of the two is live.
        """
        if not has_bumpversion_section(root / SYNCED_CONFIG):
            pytest.skip(f"no {SYNCED_CONFIG} — reported by test_a_discoverable_config_exists")
        duplicates = shadowing_configs(root, SYNCED_CONFIG)
        assert not duplicates, (
            f"{duplicates} also declares a bumpversion section. {SYNCED_CONFIG} is searched "
            f"first and wins, so the other config is inert — and being inert, it drifts."
        )

    def test_the_config_does_not_pin_a_current_version(self, bumpversion: dict) -> None:
        """``current_version`` must stay absent from a synced config.

        The file is owned by rhiza, so a value only the consuming repo can maintain would
        be reset by the next ``/rhiza:update``. Omitting it makes bump-my-version derive
        the version from the newest tag matching ``tag_name``, which is what the version
        file carries in any repo whose version and tags agree.
        """
        assert "current_version" not in bumpversion, (
            "[tool.bumpversion].current_version is set in a file rhiza syncs; the next "
            "/rhiza:update would overwrite it. Omit the key and let the newest tag supply it."
        )

    def test_the_config_targets_the_version_file(self, bumpversion: dict) -> None:
        """A ``[[files]]`` entry must point at the version file, or nothing is rewritten.

        With no entry for it the bump still "succeeds": it reports a new version, and
        leaves the file that states the old one untouched.
        """
        targets = [entry.get("filename") for entry in bumpversion.get("files", [])]
        assert self.version_file in targets, (
            f"no [[tool.bumpversion.files]] entry targets {self.version_file} (found "
            f"{targets}); {self.untargeted_consequence}"
        )

    def test_the_search_is_anchored_to_the_version_declaration(self, bumpversion: dict) -> None:
        """The search must be anchored, or it rewrites some other matching version.

        ``search``/``replace`` are applied to *every* occurrence in the file, so a bare
        version number is not specific enough to be safe — what it would hit instead is
        language-specific, and :attr:`unanchored_complaint` says which.
        """
        entries = [entry for entry in bumpversion.get("files", []) if entry.get("filename") == self.version_file]
        if not entries:
            pytest.skip(f"no {self.version_file_label} entry — reported by test_the_config_targets_the_version_file")
        for entry in entries:
            search = str(entry.get("search", ""))
            if self.search_is_regex:
                assert entry.get("regex") is True, (
                    f"the {self.version_file_label} entry's search {search!r} is not a regex, so it "
                    f"cannot be anchored to {self.search_anchor} — and an unanchored pattern is "
                    f"applied to every occurrence in the file, not just the declaration"
                )
            # Backslashes stripped before matching: where the anchored form is a regex,
            # the anchor is escaped there — `[package]` is written `\[package\]`.
            assert self.search_anchor in search.replace("\\", ""), (
                f"the {self.version_file_label} entry's search {search!r} {self.unanchored_complaint}"
            )

    def test_the_release_flow_owns_the_commit_and_the_tag(self, bumpversion: dict) -> None:
        """``/rhiza:release`` folds the changelog into the bump commit and tags it itself."""
        assert_release_flow_owns_the_commit_and_the_tag(bumpversion)
