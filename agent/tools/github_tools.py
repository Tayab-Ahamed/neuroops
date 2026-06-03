import datetime
import os

import structlog
from github import Github
from langchain_core.tools import tool

logger = structlog.get_logger()

# Setup GitHub client
github_configured = False
github_token = os.getenv("GITHUB_TOKEN")
try:
    if github_token:
        g = Github(github_token)
        # Touch API to verify config
        g.get_user().login
        github_configured = True
        logger.info("Successfully configured PyGithub client")
    else:
        logger.warning("GITHUB_TOKEN is not configured, running GitHub tools in mock mode")
except Exception as e:
    logger.warning("Failed to configure GitHub client, running in mock mode", error=str(e))


@tool
def get_recent_deploys(repo: str, minutes: int = 60) -> str:
    """Retrieves list of commits and tags pushed to the target repository in the last N minutes."""
    if not github_configured:
        logger.info("github mock: get_recent_deploys", repo=repo, minutes=minutes)
        # Mock recent commit/deploy activity
        now = datetime.datetime.now(datetime.UTC)
        deploy_time = (now - datetime.timedelta(minutes=10)).isoformat()
        return (
            f"Recent deployments & commits in {repo} (last {minutes}m):\n"
            f"Commit: a1b2c3d4e5f6\n"
            f"Author: Alice Smith <alice@neuroops.io>\n"
            f"Date: {deploy_time}\n"
            f"Message: chore(backend): update database connection pool configuration (#42)\n"
            f"Files changed: backend/db.py (updated pool size limits)"
        )

    try:
        g_client = Github(github_token)
        r = g_client.get_repo(repo)

        cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=minutes)
        commits = r.get_commits(since=cutoff)

        records = []
        for c in commits[:10]:
            commit_data = c.commit
            author_date = commit_data.author.date
            # Ensure author_date is timezone-aware
            if author_date.tzinfo is None:
                author_date = author_date.replace(tzinfo=datetime.UTC)

            records.append(
                f"Commit: {c.sha[:12]}\n"
                f"Author: {commit_data.author.name} <{commit_data.author.email}>\n"
                f"Date: {author_date.isoformat()}\n"
                f"Message: {commit_data.message.splitlines()[0]}\n"
            )

        if not records:
            return f"No deployments or commits found in the last {minutes} minutes for repository {repo}."

        return f"Recent deployments & commits in {repo} (last {minutes}m):\n" + "\n---\n".join(
            records
        )
    except Exception as e:
        logger.error("Failed to query GitHub repository", repo=repo, error=str(e))
        return f"Error querying GitHub deployments for {repo}: {str(e)}"
