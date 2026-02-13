# How to Resolve GitHub Review Comments

This guide documents how to mark review comment conversations as resolved after addressing reviewer feedback in pull requests.

## Quick Reference

```bash
# 1. Get all review threads for PR #74
gh api graphql -f query='
query {
  repository(owner: "eman", name: "nwp500-python") {
    pullRequest(number: 74) {
      reviewThreads(first: 10) {
        nodes {
          id
          path
          line
          isResolved
        }
      }
    }
  }
}
' | jq '.data.repository.pullRequest.reviewThreads.nodes'

# 2. Resolve a specific thread
gh api graphql -f query='
mutation {
  resolveReviewThread(input: {threadId: "PRRT_kwDOP_hNvM5ukIVT"}) {
    thread { isResolved }
  }
}
'
```

## Why Resolve Comments?

- **Clarity**: Shows reviewers their feedback has been acted upon
- **Workflow**: Prevents reviewers from re-reading already-addressed comments
- **Signal Readiness**: Indicates PR is ready for another review pass
- **Clean PR Interface**: Makes GitHub's PR conversation cleaner and easier to follow

## Workflow: Address and Resolve

### 1. Address the Comment

Make the code changes requested by the reviewer:
- Fix bugs
- Update documentation
- Refactor code
- Add tests

**Example:**
```bash
# Edit file based on comment
nano src/nwp500/converters.py

# Commit the change
git add src/nwp500/converters.py
git commit -m "Fix div_10 converter to handle string inputs"

# Push to remote
git push
```

### 2. Verify Tests Pass

Run all validation before marking comments as resolved:

```bash
# Run tests
pytest --ignore=tests/test_mqtt_hypothesis.py

# Run linting
make ci-lint

# Run type checking
python3 -m mypy src/nwp500 --config-file pyproject.toml
```

All must pass before proceeding.

### 3. Get Review Thread IDs

Query GraphQL to find threads that need resolving:

```bash
gh api graphql -f query='
query {
  repository(owner: "eman", name: "nwp500-python") {
    pullRequest(number: 74) {
      reviewThreads(first: 10) {
        nodes {
          id
          path
          line
          isResolved
        }
      }
    }
  }
}
' | jq '.data.repository.pullRequest.reviewThreads.nodes'
```

**Output example:**
```json
[
  {
    "id": "PRRT_kwDOP_hNvM5ukIVT",
    "path": "src/nwp500/converters.py",
    "line": 125,
    "isResolved": false
  },
  {
    "id": "PRRT_kwDOP_hNvM5ukIVo",
    "path": "tests/test_model_converters.py",
    "line": 212,
    "isResolved": false
  }
]
```

### 4. Identify Which Threads to Resolve

Cross-reference the output with:
1. Which file you modified
2. Which line the comment was on (approximately)
3. Whether `isResolved` is `false`

### 5. Resolve the Threads

For each thread you addressed:

```bash
gh api graphql -f query='
mutation {
  resolveReviewThread(input: {threadId: "PRRT_kwDOP_hNvM5ukIVT"}) {
    thread {
      isResolved
    }
  }
}
'
```

Success response:
```json
{
  "data": {
    "resolveReviewThread": {
      "thread": {
        "isResolved": true
      }
    }
  }
}
```

### 6. Verify All Are Resolved

Re-run the query from Step 3 to confirm all addressed threads now show `"isResolved": true`:

```bash
gh api graphql -f query='
query {
  repository(owner: "eman", name: "nwp500-python") {
    pullRequest(number: 74) {
      reviewThreads(first: 10) {
        nodes {
          path
          isResolved
        }
      }
    }
  }
}
' | jq '.data.repository.pullRequest.reviewThreads.nodes'
```

## Batch Resolving Multiple Threads

If you have many threads to resolve, use a loop:

```bash
#!/bin/bash

# Define thread IDs
THREAD_IDS=(
  "PRRT_kwDOP_hNvM5ukIVT"
  "PRRT_kwDOP_hNvM5ukIVo"
  "PRRT_kwDOP_hNvM5ukIVx"
)

# Resolve each one
for thread_id in "${THREAD_IDS[@]}"; do
  gh api graphql -f query="
  mutation {
    resolveReviewThread(input: {threadId: \"$thread_id\"}) {
      thread { isResolved }
    }
  }
  " && echo "✓ $thread_id resolved"
done

echo "All threads resolved!"
```

Or as a one-liner:

```bash
for id in PRRT_kwDOP_hNvM5ukIVT PRRT_kwDOP_hNvM5ukIVo PRRT_kwDOP_hNvM5ukIVx; do
  gh api graphql -f query="mutation { resolveReviewThread(input: {threadId: \"$id\"}) { thread { isResolved } } }" && echo "✓ $id resolved"
done
```

## Shell Function (Optional)

Add this to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.):

```bash
# Resolve a single GitHub PR review thread
resolve-pr-thread() {
  local thread_id="$1"
  if [[ -z "$thread_id" ]]; then
    echo "Usage: resolve-pr-thread THREAD_ID"
    echo "Example: resolve-pr-thread PRRT_kwDOP_hNvM5ukIVT"
    return 1
  fi
  
  gh api graphql -f query="
  mutation {
    resolveReviewThread(input: {threadId: \"$thread_id\"}) {
      thread { isResolved }
    }
  }
  " | jq '.data.resolveReviewThread.thread.isResolved'
}

# Get all unresolved threads for a PR
pr-threads() {
  local pr_num="${1:?PR number required}"
  gh api graphql -f query="
  query {
    repository(owner: \"eman\", name: \"nwp500-python\") {
      pullRequest(number: $pr_num) {
        reviewThreads(first: 10) {
          nodes {
            id
            path
            line
            isResolved
          }
        }
      }
    }
  }
  " | jq '.data.repository.pullRequest.reviewThreads.nodes'
}
```

Usage:
```bash
pr-threads 74                          # List all threads for PR #74
resolve-pr-thread PRRT_kwDOP_hNvM5ukIVT  # Resolve one thread
```

## Special Cases

### Unresolving a Thread

If a reviewer asks for changes after you marked it resolved, unresolve it:

```bash
gh api graphql -f query='
mutation {
  unresolveReviewThread(input: {threadId: "PRRT_kwDOP_hNvM5ukIVT"}) {
    thread {
      isResolved
    }
  }
}
'
```

### Force-Pushed Commits

When you amend and force-push commits:
1. Old review threads remain resolvable
2. Thread IDs don't change
3. Line numbers may be different in new commits
4. Comments still point to old code but threads can be resolved
5. This is normal GitHub behavior - resolve all threads once your changes are complete

### Multiple Changes to Same File

If a reviewer left multiple comments on the same file and you addressed them all:
1. Make all changes to the file
2. Commit and push
3. Get all thread IDs for that file
4. Resolve each one individually

## Troubleshooting

### "Not Found" Error

**Problem:**
```
{
  "message": "Not Found",
  "documentation_url": "https://docs.github.com/rest",
  "status": 404
}
```

**Solutions:**
- Verify PR number is correct
- Check you have access to the repository
- Verify `gh auth status` shows you're authenticated
- Try running `gh auth login` again

### No Threads Returned

**Problem:**
```
{
  "data": {
    "repository": {
      "pullRequest": {
        "reviewThreads": {
          "nodes": []
        }
      }
    }
  }
}
```

**Solutions:**
- Verify PR number is correct
- The PR may have only general comments (not review comments)
- Try increasing `first: 10` to `first: 100` if there are many threads
- Verify reviewers left inline code comments, not just PR comments

### Thread Won't Resolve

**Problem:**
Mutation succeeds but `isResolved` still returns `false` on next check

**Solutions:**
- Wait a moment and query again (GitHub API may have delay)
- Verify you're using the exact same thread ID
- Check that you have write permissions on the repository
- Try running `gh auth refresh` to refresh your token

### Can't Find Thread ID for Comment I Fixed

**Problem:**
You fixed the code but can't find the matching thread ID

**Possible Causes:**
1. The comment was a general PR comment, not an inline code comment (can't be resolved)
2. The thread was already resolved by someone else
3. You're looking at the wrong PR number
4. The comment was deleted by the reviewer

**Solution:**
Go to the PR on GitHub.com and manually verify the comment still exists and is an inline review comment (not a general comment).

## References

- [GitHub GraphQL API: resolveReviewThread](https://docs.github.com/en/graphql/reference/mutations#resolvereviewthread)
- [GitHub GraphQL API: unresolveReviewThread](https://docs.github.com/en/graphql/reference/mutations#unresolvereviewthread)
- [GitHub GraphQL API: Review Threads](https://docs.github.com/en/graphql/reference/objects#reviewthread)
- [GitHub CLI: gh api](https://cli.github.com/manual/gh_api)
- [GitHub: Review conversations](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/commenting-on-a-pull-request#about-pull-request-reviews)
