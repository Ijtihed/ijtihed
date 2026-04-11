"""
Updates README with:
  - repos contributed to (unique list, auto-filtered)
"""

import os
import re
import requests

USERNAME = os.environ.get("GITHUB_USERNAME", "Ijtihed")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
README_PATH = "README.md"

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# ── helpers ────────────────────────────────────────────────────────────────────

def fetch_own_repos():
    repos, page = set(), 1
    while True:
        r = requests.get(
            f"https://api.github.com/users/{USERNAME}/repos",
            headers=GH_HEADERS,
            params={"per_page": 100, "page": page},
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for repo in data:
            repos.add(repo["full_name"].lower())
        page += 1
    return repos


def fetch_merged_prs(limit=50):
    own = fetch_own_repos()
    params = {
        "q": f"author:{USERNAME} is:pr is:merged",
        "sort": "updated",
        "order": "desc",
        "per_page": limit,
    }
    r = requests.get("https://api.github.com/search/issues", headers=GH_HEADERS, params=params)
    r.raise_for_status()
    items = r.json().get("items", [])

    results = []
    for item in items:
        repo_name = item["repository_url"].replace("https://api.github.com/repos/", "")
        if repo_name.lower() in own:
            continue
        results.append({
            "repo": repo_name,
            "org": repo_name.split("/")[0],
            "short": repo_name.split("/")[1],
            "number": item["number"],
            "url": item["html_url"],
            "title": item["title"],
        })
    return results


# ── section builders ───────────────────────────────────────────────────────────

def fetch_star_count(repo):
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}", headers=GH_HEADERS)
        r.raise_for_status()
        return r.json().get("stargazers_count", 0)
    except Exception:
        return 0


def format_stars(n):
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k")
    return str(n)


def build_contributor_repos(all_prs):
    seen = []
    for pr in all_prs:
        repo = pr["repo"]
        if repo not in seen:
            seen.append(repo)
    if not seen:
        return "_no external contributions yet_"
    repos_with_stars = [(r, fetch_star_count(r)) for r in seen]
    repos_with_stars.sort(key=lambda x: x[1], reverse=True)
    return " ".join(
        f"[`{r}`](https://github.com/{r}/pulls?q=is%3Apr+author%3A{USERNAME}) ⭐ {format_stars(s)}"
        for r, s in repos_with_stars
    )


# ── README updater ──────────────────────────────────────────────────────────────

def replace_section(readme, marker, content):
    start = f"<!-- {marker}_START -->"
    end = f"<!-- {marker}_END -->"
    pattern = rf"{re.escape(start)}.*?{re.escape(end)}"
    replacement = f"{start}\n{content}\n{end}"
    if not re.search(pattern, readme, flags=re.DOTALL):
        print(f"WARNING: markers for {marker} not found in README")
        return readme
    return re.sub(pattern, replacement, readme, flags=re.DOTALL)


def update_readme(contrib_content):
    with open(README_PATH, "r") as f:
        readme = f.read()
    readme = replace_section(readme, "CONTRIB_REPOS", contrib_content)
    with open(README_PATH, "w") as f:
        f.write(readme)
    print("README updated.")


# ── main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    all_prs = fetch_merged_prs(limit=50)
    contrib = build_contributor_repos(all_prs)
    print("── contrib repos ──\n", contrib)
    update_readme(contrib)
