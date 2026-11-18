---
name: implement-spec
description: "Implement the result of /to-spec and /to-tickets in code."
disable-model-invocation: true
---

You have been provided a spec. This spec should have tickets associated with it, describing how to implement the spec.

The issue tracker should have been provided to you. If not, tell the user to run `/setup-matt-pocock-skills`.

The goal is the entire spec implemented on a single **integration branch**, with every ticket resolved the way the issue tracker closes work.

The tickets are not a list of steps. They are a **task graph** with blocking relationships between them. This means there is always a **frontier** of tickets which are ready to be grabbed.

Start every subagent with a fresh context window.

Communication to and from subagents should be sparse. Communicate primarily through **context pointers**: to the spec, tickets, research notes, and previous commits. Don't duplicate information already available via pointers.

**Implementer subagents** should be run in the background where possible for maximum concurrency.

## Steps

1. Read the spec and tickets to understand the task graph.

2. (optional) Use an **exploration subagent** to conduct any exploration required by the tickets - relevant codebase files or external documentation. Ensure the exploration subagent can save files - it should save its markdown notes in the `.shared/notes/` directory under the project root (the parent directory of the integration branch's worktree), accessible by all future subagents. This lets **implementer subagents** focus on implementation rather than exploration.

3. The integration branch already exists and you are standing in its worktree. Do not create it. Do not open a PR and do not push: the pull request and all pushing are handled outside this session.

4. Use a fresh **implementer subagent** for each ticket, each in its own worktree on its own branch. Worktrees are created for you: run `sopreq new-worktree <ticket number>` (for example `sopreq new-worktree 01`) and it prints the path of a worktree for that ticket, already on its own branch based on the integration branch. Never create a worktree or a branch any other way: no `git worktree add`, no `git branch`, no `git checkout -b`, and do not use any worktree-isolation feature of the subagent tool. Each implementer subagent works only inside the worktree path it was given. Each implementer subagent:
   - confirms its worktree is based on the integration branch before starting, and resets onto it if not;
   - calls the Skill tool with `tdd` to build the ticket;
   - merges the integration branch tip into its own branch before reporting done

5. Once an **implementer subagent** completes, merge its work to the integration branch with a **merger subagent**: a plain local `git merge` inside the integration branch's worktree. After each successful merge, run `sopreq merged <ticket number>` and wait for it to answer `ok` before moving on; if it answers anything else, stop and report what it said.

6. If this changes the **frontier** of available tickets, kick off more **implementer subagents** to work on the new tickets. This allows for maximum concurrency.

7. Once all tickets are complete, call the Skill tool with `code-review` on the integration branch (the fixed point to compare against is `main`). Fix all issues raised by the code review in a single fresh **implementer subagent**; get its worktree with `sopreq new-worktree fix`, and after merging its work run `sopreq merged fix`.

8. Resolve each ticket the way the issue tracker closes work, commit that on the integration branch, run `sopreq done`, and report the integration branch. Do not mark any pull request ready: that is handled outside this session.

9. Do not clean up the worktrees. They are removed outside this session after you finish.
