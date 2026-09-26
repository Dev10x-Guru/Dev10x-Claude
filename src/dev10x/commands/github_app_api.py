"""Compatibility re-export — the client lives in ``dev10x.github.app_api`` (GH-1444)."""

from dev10x.github.app_api import (
    API_ROOT,
    GitHubAPIError,
    create_installation_token,
    create_installation_token_full,
    get_app,
    get_repo,
    get_repo_installation,
    list_installation_repositories,
    list_installations,
    mint_app_jwt,
)

__all__ = [
    "API_ROOT",
    "GitHubAPIError",
    "create_installation_token",
    "create_installation_token_full",
    "get_app",
    "get_repo",
    "get_repo_installation",
    "list_installation_repositories",
    "list_installations",
    "mint_app_jwt",
]
