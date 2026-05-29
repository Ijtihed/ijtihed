"""
Updates the "⚡ Stats" paragraph in README with live numbers pulled from the
GitHub API, replacing whatever sits between the STATS markers.

All figures are all-time and mirror GitHub's own profile / contribution-graph
semantics:
  - years on GitHub      -> full years since the account was created
  - commits pushed       -> sum of commit contributions across every year
  - issues opened        -> user.issues.totalCount
  - pull requests        -> user.pullRequests.totalCount
  - stars earned         -> sum of stargazers across own, non-fork public repos
  - personal projects    -> count of own, non-fork public repos
  - public repositories  -> own public repos (non-fork projects + forks)
  - commit streak        -> consecutive days up to today with >0 contributions

Private contributions are only counted when the supplied token can see them;
under the default Actions token the numbers are the public ones, which is what
a public profile should advertise.
"""

import os
from datetime import date, datetime, timedelta, timezone

import requests

USERNAME = os.environ.get("GITHUB_USERNAME", "Ijtihed")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
README_PATH = "README.md"

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# ── GraphQL helper ───────────────────────────────────────────────────────────

def gql(query, variables=None):
    r = requests.post(
        "https://api.github.com/graphql",
        headers=GH_HEADERS,
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError(f"GraphQL errors: {payload['errors']}")
    return payload["data"]


# ── stat collectors ──────────────────────────────────────────────────────────

def fetch_profile():
    """Account age, issue/PR totals, repos-contributed-to, own repos + stars."""
    data = gql(
        """
        query($login: String!, $cursor: String) {
          user(login: $login) {
            createdAt
            issues { totalCount }
            pullRequests { totalCount }
            publicRepos: repositories(
              ownerAffiliations: OWNER, privacy: PUBLIC
            ) { totalCount }
            repositories(
              ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC
              first: 100, after: $cursor
            ) {
              totalCount
              pageInfo { hasNextPage endCursor }
              nodes { stargazerCount }
            }
          }
        }
        """,
        {"login": USERNAME, "cursor": None},
    )["user"]

    created = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
    stars = sum(n["stargazerCount"] for n in data["repositories"]["nodes"])

    # paginate own repos if there are more than 100 (defensive; today there aren't)
    page = data["repositories"]["pageInfo"]
    while page["hasNextPage"]:
        more = gql(
            """
            query($login: String!, $cursor: String) {
              user(login: $login) {
                repositories(
                  ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC
                  first: 100, after: $cursor
                ) {
                  pageInfo { hasNextPage endCursor }
                  nodes { stargazerCount }
                }
              }
            }
            """,
            {"login": USERNAME, "cursor": page["endCursor"]},
        )["user"]["repositories"]
        stars += sum(n["stargazerCount"] for n in more["nodes"])
        page = more["pageInfo"]

    return {
        "created": created,
        "issues": data["issues"]["totalCount"],
        "prs": data["pullRequests"]["totalCount"],
        "public_repos": data["publicRepos"]["totalCount"],
        "projects": data["repositories"]["totalCount"],
        "stars": stars,
    }


def fetch_total_commits(created):
    """Sum commit contributions over each <=1y window from signup to now.

    GitHub's contributionsCollection only spans up to a year per query, so we
    walk one calendar year at a time.
    """
    now = datetime.now(timezone.utc)
    total = 0
    year = created.year
    while year <= now.year:
        frm = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
        to = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
        coll = gql(
            """
            query($login: String!, $from: DateTime!, $to: DateTime!) {
              user(login: $login) {
                contributionsCollection(from: $from, to: $to) {
                  totalCommitContributions
                  restrictedContributionsCount
                }
              }
            }
            """,
            {
                "login": USERNAME,
                "from": frm.isoformat(),
                "to": to.isoformat(),
            },
        )["user"]["contributionsCollection"]
        total += coll["totalCommitContributions"] + coll["restrictedContributionsCount"]
        year += 1
    return total


def fetch_commit_streak():
    """Consecutive days ending today (or yesterday) with >0 contributions."""
    now = datetime.now(timezone.utc)
    frm = now - timedelta(days=371)  # contribution calendar caps at ~1 year
    weeks = gql(
        """
        query($login: String!, $from: DateTime!, $to: DateTime!) {
          user(login: $login) {
            contributionsCollection(from: $from, to: $to) {
              contributionCalendar {
                weeks { contributionDays { date contributionCount } }
              }
            }
          }
        }
        """,
        {"login": USERNAME, "from": frm.isoformat(), "to": now.isoformat()},
    )["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]

    counts = {}
    for week in weeks:
        for day in week["contributionDays"]:
            counts[day["date"]] = day["contributionCount"]

    today = date.today()
    # Today isn't over, so a 0 today doesn't break a streak — start from yesterday.
    cursor = today
    if counts.get(today.isoformat(), 0) == 0:
        cursor = today - timedelta(days=1)

    streak = 0
    while counts.get(cursor.isoformat(), 0) > 0:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


# ── prose builder ────────────────────────────────────────────────────────────

def full_years(created):
    today = datetime.now(timezone.utc)
    years = today.year - created.year
    if (today.month, today.day) < (created.month, created.day):
        years -= 1
    return max(years, 0)


def plural(n, singular, suffix="s"):
    word = singular if n == 1 else singular + suffix
    return f"**{n:,}** {word}"


def build_stats(s):
    years = full_years(s["created"])
    # "repository" has an irregular plural, so build that phrase by hand.
    repos = s["public_repos"]
    repo_phrase = (
        f"**{repos:,}** public repository" if repos == 1
        else f"**{repos:,}** public repositories"
    )
    line1 = (
        f"I joined GitHub {plural(years, 'year')} ago and have since "
        f"pushed {plural(s['commits'], 'commit')}, "
        f"opened {plural(s['issues'], 'issue')}, "
        f"submitted {plural(s['prs'], 'pull request')}, "
        f"and earned {plural(s['stars'], 'star')} "
        f"across {plural(s['projects'], 'personal project')}, "
        f"with contributions to {repo_phrase}."
    )

    streak = s["streak"]
    if streak <= 0:
        line2 = "I'm not on a commit streak right now."
    else:
        line2 = f"I'm currently on a **{streak:,}**-day commit streak."

    return f"{line1}\n\n{line2}"


# ── README updater ───────────────────────────────────────────────────────────

def replace_section(readme, marker, content):
    import re

    start = f"<!-- {marker}_START -->"
    end = f"<!-- {marker}_END -->"
    pattern = rf"{re.escape(start)}.*?{re.escape(end)}"
    replacement = f"{start}\n{content}\n{end}"
    if not re.search(pattern, readme, flags=re.DOTALL):
        print(f"WARNING: markers for {marker} not found in README")
        return readme
    return re.sub(pattern, replacement, readme, flags=re.DOTALL)


def update_readme(content):
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()
    readme = replace_section(readme, "STATS", content)
    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(readme)
    print("README stats updated.")


# ── main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    stats = fetch_profile()
    stats["commits"] = fetch_total_commits(stats["created"])
    stats["streak"] = fetch_commit_streak()

    print("-- stats --")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    block = build_stats(stats)
    print("-- block --\n" + block)
    update_readme(block)
