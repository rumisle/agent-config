---
name: linear
description: Linear issue tracking via GraphQL API. Query/create/update issues, projects, and teams.
---

# Linear CLI

Query Linear via GraphQL API. Returns JSON.

## Usage

```bash
# Basic query
{baseDir}/linear.py 'query { viewer { id name email } }'

# With variables
{baseDir}/linear.py 'query($id: String!) { issue(id: $id) { title state { name } } }' \
    -v '{"id": "ABC-123"}'

# Parse with jq
{baseDir}/linear.py '{ issues(first: 5) { nodes { identifier title } } }' | jq '.data.issues.nodes'
```

## Common Queries

### My assigned issues
```bash
{baseDir}/linear.py '{ viewer { assignedIssues(first: 20) { nodes { identifier title state { name } priority dueDate } } } }'
```

### Issues by team
```bash
{baseDir}/linear.py 'query($teamId: String!) { team(id: $teamId) { issues(first: 50) { nodes { identifier title assignee { name } state { name } } } } }' \
    -v '{"teamId": "TEAM_UUID"}'
```

### Single issue by ID
```bash
{baseDir}/linear.py '{ issue(id: "ABC-123") { title description state { name } assignee { name } labels { nodes { name } } } }'
```

### List teams
```bash
{baseDir}/linear.py '{ teams { nodes { id name } } }'
```

### List workflow states (for a team)
```bash
{baseDir}/linear.py 'query($teamId: String!) { team(id: $teamId) { states { nodes { id name type } } } }' \
    -v '{"teamId": "TEAM_UUID"}'
```

### High priority issues
```bash
{baseDir}/linear.py '{ issues(filter: { priority: { lte: 2, neq: 0 } }, first: 20) { nodes { identifier title priority } } }'
```

### Recently updated
```bash
{baseDir}/linear.py '{ issues(orderBy: updatedAt, first: 10) { nodes { identifier title updatedAt } } }'
```

## Mutations

### Create issue
```bash
{baseDir}/linear.py 'mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { identifier title } } }' \
    -v '{"input": {"title": "Bug report", "teamId": "TEAM_UUID", "description": "Details here"}}'
```

### Update issue
```bash
{baseDir}/linear.py 'mutation($id: String!, $input: IssueUpdateInput!) { issueUpdate(id: $id, input: $input) { success issue { identifier title state { name } } } }' \
    -v '{"id": "ABC-123", "input": {"stateId": "STATE_UUID"}}'
```

### Add comment
```bash
{baseDir}/linear.py 'mutation($input: CommentCreateInput!) { commentCreate(input: $input) { success } }' \
    -v '{"input": {"issueId": "ISSUE_UUID", "body": "Comment text"}}'
```

## Filtering

Use `filter` argument on queries. Comparators: `eq`, `neq`, `in`, `nin`, `lt`, `lte`, `gt`, `gte`, `contains`, `startsWith`.

```bash
# By assignee email
{baseDir}/linear.py '{ issues(filter: { assignee: { email: { eq: "me@example.com" } } }, first: 20) { nodes { identifier title } } }'

# By label
{baseDir}/linear.py '{ issues(filter: { labels: { name: { eq: "Bug" } } }, first: 20) { nodes { identifier title } } }'

# Due soon (relative date: P2W = 2 weeks)
{baseDir}/linear.py '{ issues(filter: { dueDate: { lt: "P2W" } }, first: 20) { nodes { identifier title dueDate } } }'

# Combine with OR
{baseDir}/linear.py '{ issues(filter: { or: [{ priority: { eq: 1 } }, { priority: { eq: 2 } }] }, first: 20) { nodes { identifier title priority } } }'
```

## Priority Values

| Value | Level |
|-------|-------|
| 0 | No priority |
| 1 | Urgent |
| 2 | High |
| 3 | Medium |
| 4 | Low |

## Tips

- **Default to active issues**: When listing issues, exclude completed states unless asked otherwise:
  `state: { name: { nin: ["Done", "Canceled", "Duplicate"] } }`
- **"Today's issues"**: Means `dueDate: { lte: "YYYY-MM-DD" }` (due today or overdue)
- Use `identifier` (e.g., `ABC-123`) for display, `id` (UUID) for mutations
- Get UUIDs in Linear app: Cmd/Ctrl+K → "Copy model UUID"
- Pagination: use `first`/`after` with `pageInfo { hasNextPage endCursor }`
- Default pagination returns 50 items

## Batching

When making related changes (e.g., creating issue then adding comment, or updating multiple issues), **batch into a single GraphQL request** with aliases:

```bash
{baseDir}/linear.py 'mutation($input1: IssueUpdateInput!, $input2: IssueUpdateInput!) { 
  issue1: issueUpdate(id: "ABC-1", input: $input1) { success }
  issue2: issueUpdate(id: "ABC-2", input: $input2) { success }
}' -v '{"input1": {"stateId": "DONE_ID"}, "input2": {"stateId": "DONE_ID"}}'
```

This reduces API calls and respects rate limits (5,000 requests/hour, 250,000 complexity points/hour).
