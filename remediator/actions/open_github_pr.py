import os
import time

from github import Github, GithubException

from remediator.actions import ActionResult, github_configured, logger


def open_pr(repo: str, title: str, body: str, branch: str, files: dict[str, str]) -> ActionResult:
    """
    Creates a Git branch in the specified repository, commits the requested files,
    and opens a new Pull Request back to the default branch.
    """
    logger.info(
        "Starting open_pr action", repo=repo, title=title, branch=branch, file_count=len(files)
    )
    start_time = time.time()

    if not github_configured:
        logger.info(
            "remediator mock: open_pr execution", repo=repo, title=title, branch=branch, files=files
        )
        time.sleep(0.5)
        duration = time.time() - start_time
        return ActionResult(
            success=True,
            action_taken=(
                f"Mock: Opened Pull Request in repository '{repo}' for branch '{branch}'. "
                f"PR Title: '{title}'. Files patched: {list(files.keys())} (Mock Mode)."
            ),
            duration_seconds=duration,
        )

    try:
        # Re-authenticate using the environment token
        g_client = Github(os.getenv("GITHUB_TOKEN"))
        r = g_client.get_repo(repo)

        # 1. Get default branch commit SHA
        base_branch = r.default_branch
        sb = r.get_branch(base_branch)
        base_sha = sb.commit.sha

        # 2. Create the branch (git ref)
        ref_path = f"refs/heads/{branch}"
        logger.info("Creating new branch ref", branch=branch, sha=base_sha)
        try:
            r.create_git_ref(ref=ref_path, sha=base_sha)
        except (GithubException, Exception) as e:
            # If the branch already exists, we will reuse it or warn
            logger.warning(
                "Branch ref might already exist, attempting to proceed", branch=branch, error=str(e)
            )

        # 3. Create or update files in the branch
        for filepath, content in files.items():
            try:
                # Check if file already exists in the new branch to get its SHA
                contents = r.get_contents(filepath, ref=branch)
                logger.info("Updating existing file in branch", filepath=filepath, branch=branch)
                r.update_file(
                    path=filepath,
                    message=f"remediation: update config {filepath} for incident",
                    content=content,
                    sha=contents.sha,
                    branch=branch,
                )
            except (GithubException, Exception):
                # File does not exist, create it
                logger.info("Creating new file in branch", filepath=filepath, branch=branch)
                r.create_file(
                    path=filepath,
                    message=f"remediation: create config {filepath} for incident",
                    content=content,
                    branch=branch,
                )

        # 4. Create the Pull Request
        logger.info("Creating GitHub Pull Request", title=title, head=branch, base=base_branch)
        pr = r.create_pull(title=title, body=body, head=branch, base=base_branch)

        duration = time.time() - start_time
        logger.info(
            "GitHub Pull Request created successfully", pr_url=pr.html_url, duration=duration
        )
        return ActionResult(
            success=True,
            action_taken=f"Successfully opened GitHub Pull Request #{pr.number}: '{pr.title}' at {pr.html_url}.",
            duration_seconds=duration,
        )

    except (GithubException, Exception) as e:
        duration = time.time() - start_time
        logger.error("Failed to open GitHub Pull Request", repo=repo, error=str(e))
        return ActionResult(
            success=False,
            action_taken=f"Failed to open GitHub Pull Request in repo '{repo}': {str(e)}",
            duration_seconds=duration,
        )
