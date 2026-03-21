#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
一键删除 GitHub Actions cache
支持：
1) 删除指定仓库：python delete_github_actions_cache.py --repo owner/repo
2) 删除所有可访问仓库：python delete_github_actions_cache.py --all
3) 仅预览不删除：--dry-run

认证方式：
- 优先读取环境变量 GITHUB_TOKEN
- 也可以通过 --token 传入

依赖：
pip install requests
"""

import argparse
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import requests


API_BASE = "https://api.github.com"


class GitHubAPIError(Exception):
    pass


def make_session(token: str) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "github-actions-cache-cleaner",
        }
    )
    return session


def github_request(
    session: requests.Session,
    method: str,
    url: str,
    params: Optional[dict] = None,
    timeout: int = 30,
) -> requests.Response:
    resp = session.request(method, url, params=params, timeout=timeout)
    if resp.status_code >= 400:
        msg = f"HTTP {resp.status_code} - {resp.text}"
        raise GitHubAPIError(msg)
    return resp


def get_authenticated_user(session: requests.Session) -> str:
    url = f"{API_BASE}/user"
    resp = github_request(session, "GET", url)
    data = resp.json()
    login = data.get("login")
    if not login:
        raise GitHubAPIError("无法获取当前认证用户 login")
    return login


def list_accessible_repos(
    session: requests.Session,
    visibility: str = "all",
    affiliation: str = "owner,collaborator,organization_member",
) -> List[Dict]:
    """
    列出当前 token 可访问的仓库。
    默认包含：
    - 自己的仓库
    - 协作者仓库
    - 组织成员可访问仓库
    """
    repos: List[Dict] = []
    page = 1

    while True:
        url = f"{API_BASE}/user/repos"
        params = {
            "per_page": 100,
            "page": page,
            "visibility": visibility,
            "affiliation": affiliation,
            "sort": "full_name",
            "direction": "asc",
        }
        resp = github_request(session, "GET", url, params=params)
        items = resp.json()

        if not items:
            break

        repos.extend(items)

        if len(items) < 100:
            break
        page += 1

    return repos


def list_repo_caches(session: requests.Session, owner: str, repo: str) -> List[Dict]:
    caches: List[Dict] = []
    page = 1

    while True:
        url = f"{API_BASE}/repos/{owner}/{repo}/actions/caches"
        params = {
            "per_page": 100,
            "page": page,
            "sort": "last_accessed_at",
            "direction": "desc",
        }
        resp = github_request(session, "GET", url, params=params)
        data = resp.json()

        items = data.get("actions_caches", [])
        if not items:
            break

        caches.extend(items)

        # total_count 只是总量，分页仍按当前页数量判断
        if len(items) < 100:
            break
        page += 1

    return caches


def delete_cache_by_id(
    session: requests.Session, owner: str, repo: str, cache_id: int
) -> None:
    url = f"{API_BASE}/repos/{owner}/{repo}/actions/caches/{cache_id}"
    resp = session.delete(url, timeout=30)
    if resp.status_code != 204:
        raise GitHubAPIError(
            f"删除失败 {owner}/{repo} cache_id={cache_id}, "
            f"HTTP {resp.status_code} - {resp.text}"
        )


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def parse_repo(full_name: str) -> Tuple[str, str]:
    if "/" not in full_name:
        raise ValueError("仓库格式必须是 owner/repo")
    owner, repo = full_name.split("/", 1)
    if not owner or not repo:
        raise ValueError("仓库格式必须是 owner/repo")
    return owner, repo


def process_repo(
    session: requests.Session,
    owner: str,
    repo: str,
    dry_run: bool = False,
    sleep_seconds: float = 0.0,
) -> Tuple[int, int]:
    """
    返回：
    (删除数量, 删除字节数)
    """
    print(f"\n==> 处理仓库: {owner}/{repo}")
    caches = list_repo_caches(session, owner, repo)

    if not caches:
        print("    没有找到 cache")
        return 0, 0

    total_size = sum(int(c.get("size_in_bytes", 0)) for c in caches)
    print(f"    找到 {len(caches)} 个 cache，总大小 {human_size(total_size)}")

    deleted_count = 0
    deleted_bytes = 0

    for c in caches:
        cache_id = c.get("id")
        key = c.get("key", "")
        ref = c.get("ref", "")
        size_in_bytes = int(c.get("size_in_bytes", 0))

        print(
            f"    - cache_id={cache_id}, key={key}, ref={ref}, size={human_size(size_in_bytes)}"
        )

        if dry_run:
            continue

        delete_cache_by_id(session, owner, repo, cache_id)
        deleted_count += 1
        deleted_bytes += size_in_bytes
        print("      已删除")

        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return deleted_count, deleted_bytes


def main():
    parser = argparse.ArgumentParser(description="删除 GitHub Actions cache")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--repo", help="指定仓库，格式：owner/repo")
    group.add_argument("--all", action="store_true", help="删除所有可访问仓库的 cache")

    parser.add_argument("--token", help="GitHub Token；不传则读取环境变量 GITHUB_TOKEN")
    parser.add_argument(
        "--owner-only",
        action="store_true",
        help="仅在 --all 模式下删除当前认证用户自己名下的仓库",
    )
    parser.add_argument(
        "--exclude-forks",
        action="store_true",
        help="在 --all 模式下跳过 fork 仓库（默认会包含 fork）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将删除哪些 cache，不实际删除",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="每次删除后 sleep 秒数，避免触发限流，默认 0",
    )

    args = parser.parse_args()

    token = args.token or os.environ["PAT"]
    if not token:
        print("错误：请通过 --token 或环境变量 GITHUB_TOKEN 提供 GitHub Token", file=sys.stderr)
        sys.exit(1)

    session = make_session(token)

    try:
        current_user = get_authenticated_user(session)
        print(f"当前认证用户: {current_user}")
    except Exception as e:
        print(f"认证失败: {e}", file=sys.stderr)
        sys.exit(1)

    repos_to_process: List[Tuple[str, str]] = []

    try:
        if args.repo:
            repos_to_process.append(parse_repo(args.repo))
        else:
            repos = list_accessible_repos(session)

            for repo in repos:
                full_name = repo.get("full_name", "")
                owner_login = repo.get("owner", {}).get("login", "")
                is_fork = bool(repo.get("fork", False))

                if not full_name:
                    continue

                if args.owner_only and owner_login != current_user:
                    continue

                if args.exclude_forks and is_fork:
                    continue

                repos_to_process.append(parse_repo(full_name))

            print(f"共找到 {len(repos_to_process)} 个待处理仓库")

        total_deleted_count = 0
        total_deleted_bytes = 0
        failed_repos = []

        for owner, repo in repos_to_process:
            try:
                deleted_count, deleted_bytes = process_repo(
                    session=session,
                    owner=owner,
                    repo=repo,
                    dry_run=args.dry_run,
                    sleep_seconds=args.sleep,
                )
                total_deleted_count += deleted_count
                total_deleted_bytes += deleted_bytes
            except Exception as e:
                print(f"    处理失败: {owner}/{repo} -> {e}", file=sys.stderr)
                failed_repos.append(f"{owner}/{repo}")

        print("\n==============================")
        if args.dry_run:
            print("预览完成（未实际删除）")
        else:
            print("删除完成")
        print(f"删除 cache 数量: {total_deleted_count}")
        print(f"释放空间估算: {human_size(total_deleted_bytes)}")

        if failed_repos:
            print(f"失败仓库数: {len(failed_repos)}")
            for name in failed_repos:
                print(f"  - {name}")

    except KeyboardInterrupt:
        print("\n用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"执行失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()