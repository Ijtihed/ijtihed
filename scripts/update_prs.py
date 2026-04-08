"""
Updates README with:
  - repos contributed to (unique list, auto-filtered)
  - latest 3 merged PRs
  - AI-generated monthly activity summary via Claude API
"""

import os
import re
import requests
from datetime import datetime, timedelta, timezone

USERNAME = os.environ.get("GITHUB_USERNAME", "Ijtihed")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GROQ_KEY = os.environ.get("GROQ_API_KEY", "")
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
        merged_at_str = item.get("pull_request", {}).get("merged_at") or item.get("closed_at")
        merged_at = datetime.fromisoformat(merged_at_str.replace("Z", "+00:00")) if merged_at_str else None
        results.append({
            "repo": repo_name,
            "org": repo_name.split("/")[0],
            "short": repo_name.split("/")[1],
            "number": item["number"],
            "url": item["html_url"],
            "title": item["title"],
            "merged_at": merged_at,
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
        f"[`{r}`](https://github.com/{r}) <sub>⭐ {format_stars(s)}</sub>"
        for r, s in repos_with_stars
    )


def build_latest(prs, n=3):
    if not prs:
        return "_no recent merged PRs_"
    lines = []
    for pr in prs[:n]:
        date = pr["merged_at"].strftime("%b %d") if pr["merged_at"] else ""
        lines.append(
            f"- [{pr['org']}/{pr['short']} #{pr['number']}]({pr['url']}) — {pr['title']}"
            + (f"  `{date}`" if date else "")
        )
    return "\n".join(lines)


def build_summary(prs, period_label="this month"):
    if not GROQ_KEY:
        return f"_set `GROQ_API_KEY` secret to enable {period_label} summary_"
    if not prs:
        return f"_no merged PRs {period_label}_"

    pr_list = "\n".join(
        f"- {pr['org']}/{pr['short']} #{pr['number']}: {pr['title']}" for pr in prs
    )
    prompt = (
        f"Here are open source pull requests merged by a developer {period_label}:\n\n"
        f"{pr_list}\n\n"
        "Write a single short sentence (max 25 words) summarising what they worked on. "
        "Be specific about the libraries/projects. Plain text only, no markdown."
    )

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "llama-3.1-8b-instant",
                "max_tokens": 80,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        r.raise_for_status()
        return f"> {r.json()['choices'][0]['message']['content'].strip()}"
    except Exception as e:
        print(f"WARNING: Groq API call failed: {e}")
        return f"_summary unavailable_"


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


def update_readme(contrib_content, latest_content, summary_content):
    with open(README_PATH, "r") as f:
        readme = f.read()
    readme = replace_section(readme, "CONTRIB_REPOS", contrib_content)
    readme = replace_section(readme, "LATEST_PRS", latest_content)
    readme = replace_section(readme, "MONTHLY_SUMMARY", summary_content)
    with open(README_PATH, "w") as f:
        f.write(readme)
    print("README updated.")


# ── main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)

    all_prs = fetch_merged_prs(limit=50)
    recent_prs = [p for p in all_prs if p["merged_at"] and p["merged_at"] >= month_ago]

    contrib = build_contributor_repos(all_prs)
    latest = build_latest(all_prs, n=3)
    summary = build_summary(recent_prs, period_label="this month")

    print("── contrib repos ──\n", contrib)
    print("── latest ──\n", latest)
    print("── summary ──\n", summary)

    update_readme(contrib, latest, summary)
