"""Tests for settings_discovery.py: pruned root walk plus git worktrees (GH-1626)."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from dev10x.skills.permission.catalog_load import find_missing_settings, find_settings_files
from dev10x.skills.permission.settings_discovery import (
    VENDORED_DIRS,
    SettingsDiscovery,
    discover_settings,
    git_registered_worktrees,
    linked_worktree_roots,
    outside_roots,
    resolve_main_project,
    vendored_dirs,
)

from dev10x import subprocess_utils
from dev10x.skills.permission import clean_project_files, settings_discovery

GIT_ENV_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


def _settings(*, project: Path) -> Path:
    claude = project / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    path = claude / "settings.local.json"
    path.write_text("{}")
    return path


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(autouse=True)
def isolated_claude_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "claude-home"
    monkeypatch.setenv("DEV10X_CLAUDE_HOME", str(home))
    for name in GIT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "work"
    path.mkdir()
    return path


@pytest.fixture
def repo_with_outside_worktree(root: Path, tmp_path: Path) -> tuple[Path, Path]:
    repo = root / "proj"
    repo.mkdir()
    _git("init", "-q", cwd=repo)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    worktree = tmp_path / "herdr" / "worktrees" / "proj-1"
    _git("worktree", "add", "-q", "-b", "side", str(worktree), cwd=repo)
    return repo, worktree


@pytest.fixture
def git_discovery(
    repo_with_outside_worktree: tuple[Path, Path],
    root: Path,
) -> tuple[SettingsDiscovery, Path, Path]:
    repo, worktree = repo_with_outside_worktree
    repo_settings = _settings(project=repo)
    worktree_settings = _settings(project=worktree)
    discovery = discover_settings(roots=[str(root)], include_user=False)
    return discovery, repo_settings.resolve(), worktree_settings.resolve()


class TestVendoredPruning:
    @pytest.mark.parametrize("vendored", sorted(VENDORED_DIRS))
    def test_skips_settings_under_vendored_dir(self, root: Path, vendored: str) -> None:
        _settings(project=root / "app" / vendored / "pkg")

        assert discover_settings(roots=[str(root)], include_user=False).files == []

    def test_keeps_project_settings_beside_vendored_dir(self, root: Path) -> None:
        kept = _settings(project=root / "app")
        _settings(project=root / "app" / "node_modules" / ".pnpm" / "thread-stream")

        assert discover_settings(roots=[str(root)], include_user=False).files == [kept.resolve()]

    def test_user_excluded_dir_is_pruned(self, root: Path) -> None:
        _settings(project=root / "app" / "third_party" / "pkg")

        discovery = discover_settings(
            roots=[str(root)],
            include_user=False,
            excluded=vendored_dirs({"exclude_dirs": ["third_party"]}),
        )

        assert discovery.files == []


class TestMissingWorktreeSettings:
    """GH-1664: a worktree whose sibling has settings but it does not."""

    def test_worktree_without_file_beside_a_seeded_main_is_missing(
        self,
        repo_with_outside_worktree: tuple[Path, Path],
        root: Path,
    ) -> None:
        repo, worktree = repo_with_outside_worktree
        _settings(project=repo)

        discovery = discover_settings(roots=[str(root)], include_user=False)

        assert discovery.missing == [(worktree / ".claude" / "settings.local.json").resolve()]

    def test_repo_with_no_settings_anywhere_is_left_alone(
        self,
        repo_with_outside_worktree: tuple[Path, Path],
        root: Path,
    ) -> None:
        discovery = discover_settings(roots=[str(root)], include_user=False)

        assert discovery.missing == []

    def test_fully_seeded_family_has_nothing_missing(
        self,
        git_discovery: tuple[SettingsDiscovery, Path, Path],
    ) -> None:
        discovery, _repo_settings, _worktree_settings = git_discovery

        assert discovery.missing == []

    def test_main_checkout_without_file_is_never_missing(
        self,
        repo_with_outside_worktree: tuple[Path, Path],
        root: Path,
    ) -> None:
        _repo, worktree = repo_with_outside_worktree
        _settings(project=worktree)

        discovery = discover_settings(roots=[str(root)], include_user=False)

        assert discovery.missing == []

    def test_find_missing_settings_reads_the_same_discovery(
        self,
        repo_with_outside_worktree: tuple[Path, Path],
        root: Path,
    ) -> None:
        repo, worktree = repo_with_outside_worktree
        _settings(project=repo)

        assert find_missing_settings(roots=[str(root)]) == [
            (worktree / ".claude" / "settings.local.json").resolve()
        ]


class TestLinkedWorktreeRoots:
    """GH-1666: derive the roots users used to register by hand."""

    def test_outside_worktree_contributes_its_parent(
        self,
        repo_with_outside_worktree: tuple[Path, Path],
    ) -> None:
        repo, worktree = repo_with_outside_worktree

        assert linked_worktree_roots([repo, worktree]) == [str(worktree.parent)]

    def test_worktree_inside_main_checkout_contributes_nothing(self, root: Path) -> None:
        repo = root / "proj"
        repo.mkdir()
        _git("init", "-q", cwd=repo)
        _git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
        inner = repo / ".worktrees" / "proj-1"
        _git("worktree", "add", "-q", "-b", "inner", str(inner), cwd=repo)

        assert linked_worktree_roots([repo, inner]) == []

    def test_non_repo_contributes_nothing(self, root: Path) -> None:
        assert linked_worktree_roots([root]) == []

    @pytest.mark.parametrize(
        "content",
        ["not a gitdir line\n", "gitdir: /somewhere/repo/.git\n"],
        ids=["no-gitdir-prefix", "not-a-worktree-gitdir"],
    )
    def test_git_file_that_is_not_a_linked_worktree(self, root: Path, content: str) -> None:
        (root / ".git").write_text(content)

        assert resolve_main_project(root) is None

    def test_relative_gitdir_resolves_against_the_worktree(self, tmp_path: Path) -> None:
        main = tmp_path / "proj"
        (main / ".git" / "worktrees" / "wt-1").mkdir(parents=True)
        worktree = tmp_path / "wt-1"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: ../proj/.git/worktrees/wt-1\n")

        assert resolve_main_project(worktree) == main.resolve()

    def test_unreadable_git_file_is_not_a_worktree(
        self,
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (root / ".git").write_text("gitdir: /x/.git/worktrees/y\n")

        def _refuse(*_args: object, **_kwargs: object) -> str:
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "read_text", _refuse)

        assert resolve_main_project(root) is None

    def test_resolve_main_project_is_layout_free(
        self,
        repo_with_outside_worktree: tuple[Path, Path],
    ) -> None:
        repo, worktree = repo_with_outside_worktree

        assert resolve_main_project(worktree).resolve() == repo.resolve()


class TestVendoredDirs:
    def test_without_exclude_dirs_is_the_builtin_set(self) -> None:
        assert vendored_dirs({}) == VENDORED_DIRS

    def test_vendor_is_pruned_by_default(self) -> None:
        assert "vendor" in VENDORED_DIRS

    def test_exclude_dirs_extends_the_builtin_set(self) -> None:
        assert vendored_dirs({"exclude_dirs": ["third_party"]}) == VENDORED_DIRS | {"third_party"}

    @pytest.mark.parametrize(
        "value",
        ["third_party", {"third_party": True}, [3, "", None]],
        ids=["string", "mapping", "non-string-entries"],
    )
    def test_malformed_exclude_dirs_adds_nothing(self, value: object) -> None:
        assert vendored_dirs({"exclude_dirs": value}) == VENDORED_DIRS


class TestGitWorktreeDiscovery:
    def test_finds_worktree_outside_roots(
        self, git_discovery: tuple[SettingsDiscovery, Path, Path]
    ) -> None:
        discovery, repo_settings, worktree_settings = git_discovery

        assert discovery.files == [repo_settings, worktree_settings]

    def test_reports_worktree_outside_roots(
        self, git_discovery: tuple[SettingsDiscovery, Path, Path]
    ) -> None:
        discovery, _repo_settings, worktree_settings = git_discovery

        assert discovery.out_of_roots == [worktree_settings]

    def test_worktree_without_settings_is_not_added(
        self, repo_with_outside_worktree: tuple[Path, Path], root: Path
    ) -> None:
        repo, _worktree = repo_with_outside_worktree
        repo_settings = _settings(project=repo)

        discovery = discover_settings(roots=[str(root)], include_user=False)

        assert (discovery.files, discovery.out_of_roots) == ([repo_settings.resolve()], [])

    def test_worktree_inside_roots_is_listed_once(
        self, repo_with_outside_worktree: tuple[Path, Path], tmp_path: Path
    ) -> None:
        _repo, worktree = repo_with_outside_worktree
        worktree_settings = _settings(project=worktree)

        discovery = discover_settings(
            roots=[str(tmp_path / "work"), str(tmp_path / "herdr")], include_user=False
        )

        assert (discovery.files, discovery.out_of_roots) == ([worktree_settings.resolve()], [])

    def test_queries_git_once_per_worktree_family(
        self,
        repo_with_outside_worktree: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _repo, worktree = repo_with_outside_worktree
        calls: list[Path] = []
        real = settings_discovery.git_registered_worktrees

        def recording(root_path: Path) -> list[Path]:
            calls.append(root_path)
            return real(root_path)

        monkeypatch.setattr(settings_discovery, "git_registered_worktrees", recording)

        discover_settings(roots=[str(tmp_path)], include_user=False)

        assert calls == [worktree]


class TestGitRegisteredWorktreesFailures:
    @pytest.mark.parametrize(
        "error",
        [
            subprocess.TimeoutExpired(cmd=["git"], timeout=10),
            FileNotFoundError("git"),
        ],
    )
    def test_raising_git_yields_no_worktrees(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        error: Exception,
    ) -> None:
        def raising(*_args: object, **_kwargs: object) -> None:
            raise error

        monkeypatch.setattr(subprocess_utils, "run", raising)

        assert git_registered_worktrees(tmp_path) == []
        assert "git worktree list" in caplog.text

    def test_non_zero_exit_yields_no_worktrees(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(
            subprocess_utils,
            "run",
            lambda *_a, **_k: SimpleNamespace(returncode=128, stdout=""),
        )

        assert git_registered_worktrees(tmp_path) == []
        assert "exited 128" in caplog.text

    def test_passes_a_bounded_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, object] = {}

        def recording(*_args: object, **kwargs: object) -> SimpleNamespace:
            seen.update(kwargs)
            return SimpleNamespace(returncode=0, stdout="")

        monkeypatch.setattr(subprocess_utils, "run", recording)

        git_registered_worktrees(tmp_path)

        assert seen["timeout"] == settings_discovery.GIT_WORKTREE_TIMEOUT_SECONDS

    def test_timed_out_repo_still_keeps_walked_settings(
        self, root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project = root / "proj"
        (project / ".git").mkdir(parents=True)
        kept = _settings(project=project)

        def raising(*_args: object, **_kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd=["git"], timeout=10)

        monkeypatch.setattr(subprocess_utils, "run", raising)

        assert discover_settings(roots=[str(root)], include_user=False) == SettingsDiscovery(
            files=[kept.resolve()], out_of_roots=[]
        )


class TestClaudeProjectsDir:
    def test_keeps_claude_projects_settings(self, isolated_claude_home: Path) -> None:
        project_settings = isolated_claude_home / "projects" / "-work-app" / "settings.local.json"
        project_settings.parent.mkdir(parents=True)
        project_settings.write_text("{}")

        assert discover_settings(roots=[], include_user=False) == SettingsDiscovery(
            files=[project_settings.resolve()], out_of_roots=[]
        )


class TestDedupe:
    def test_overlapping_roots_list_each_file_once(self, root: Path) -> None:
        kept = _settings(project=root / "app")

        files = discover_settings(roots=[str(root), str(root / "app")], include_user=False).files

        assert files == [kept.resolve()]

    def test_symlinked_root_resolves_to_one_file(self, root: Path, tmp_path: Path) -> None:
        kept = _settings(project=root / "app")
        alias = tmp_path / "alias"
        alias.symlink_to(root)

        files = discover_settings(roots=[str(root), str(alias)], include_user=False).files

        assert files == [kept.resolve()]


class TestOutsideRoots:
    @pytest.mark.parametrize(
        "relative,expected_outside",
        [
            ("work/app/.claude/settings.local.json", False),
            ("elsewhere/app/.claude/settings.local.json", True),
            ("claude-home/settings.json", False),
        ],
    )
    def test_classifies_by_root_and_claude_home(
        self, tmp_path: Path, relative: str, expected_outside: bool
    ) -> None:
        path = tmp_path / relative

        result = outside_roots(files=[path], roots=[str(tmp_path / "work")])

        assert (result == [path]) is expected_outside


class TestCleanProjectFilesDelegate:
    def test_matches_discovery_without_user_files(
        self,
        root: Path,
        isolated_claude_home: Path,
    ) -> None:
        isolated_claude_home.mkdir()
        (isolated_claude_home / "settings.json").write_text("{}")
        _settings(project=root / "app")

        assert clean_project_files.find_settings_files(roots=[str(root)]) == find_settings_files(
            roots=[str(root)], include_user=False
        )

    def test_never_includes_user_files(
        self,
        root: Path,
        isolated_claude_home: Path,
    ) -> None:
        isolated_claude_home.mkdir()
        (isolated_claude_home / "settings.json").write_text("{}")

        assert clean_project_files.find_settings_files(roots=[str(root)]) == []
