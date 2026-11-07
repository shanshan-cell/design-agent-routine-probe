---
name: setup
description: One-time setup of your own WeMod design routine, so Product tickets you label ai-design in Linear get a Claude Design canvas in your own Claude account. Run it once with /wemod-design-routine:setup.
disable-model-invocation: true
---

# Set up your WeMod design routine

You are helping a Wand teammate (usually a designer, not an engineer) set up their own copy of the WeMod design routine.
Use short, plain sentences with them. Do one step at a time and tell them what you're doing.

**What this sets up.** When someone adds the `ai-design` label to a Product ticket in Linear, a shared bridge (run by
Shanshan) starts the requester's own Claude routine. That routine designs the page on a Claude Design canvas **in the
requester's own Claude account**, and the bridge posts the canvas link back on the ticket. This setup creates that
routine in this person's account. It runs nothing and starts no design.

**Rules for you while running this setup**
- Never start the routine (no RemoteTrigger `run`). The bridge starts it from a ticket; a manual run has no ticket.
- Never ask for, read, or repeat the routine's API token. The person copies it straight from claude.ai to 1Password.
- Never change any other routine, and never edit files in the design repository.
- If a check fails, stop, tell the person the fix in plain words, and offer to continue once it's done.

Fixed values:
- Repository: `https://github.com/shanshan-cell/design-agent-routine-probe`
- Routine name: `WeMod design (ai-design)`
- Environment name: `wemod-design`
- WeMod Web V0: `https://claude.ai/artifact/KE3kJTKgBbXwSgvaaJkrLE`
- Page Designer skill: `anthropic-skills:wemod-page-designer`

## Step 1. Checks

Tell the person: "I'll check you have everything the routine needs. Nothing is created yet."

a. **Not inside the design repository.** Run `git remote get-url origin 2>/dev/null`. If it contains
   `design-agent-routine-probe`, stop: "Please quit Claude Code, run `cd ~` and start `claude` again, then run
   /wemod-design-routine:setup." (That repository's safety guard blocks setup tools.)

b. **GitHub access.** Run `git ls-remote https://github.com/shanshan-cell/design-agent-routine-probe HEAD`.
   If it fails: "You don't have access to the design repository yet. Send Shanshan your GitHub username, accept the
   invite email from GitHub, then run this setup again."

c. **Claude account.** Load the RemoteTrigger tool (ToolSearch `select:RemoteTrigger`) and call `{action: "list"}`.
   If it fails, the person isn't signed in to their claude.ai Wand account in Claude Code: ask them to run `/login`.
   If a routine named exactly `WeMod design (ai-design)` already exists, don't create another: note its id, tell
   them, and go to Step 4 with it.

d. **Page Designer skill.** Look at your own list of available skills. If `anthropic-skills:wemod-page-designer` is
   not there: "Your Claude account doesn't have the WeMod Page Designer skill yet. Ask Shanshan to share it with you."

e. **WeMod Web V0.** If you have the Artifact tool, call it with `action: "list"`, `scope: "files"`, `url:
   "https://claude.ai/artifact/KE3kJTKgBbXwSgvaaJkrLE"`. If that fails: "You can't open WeMod Web V0 yet. Ask
   Shanshan to share it with you." If you don't have the Artifact tool, say you couldn't check this one and go on.

Report the results as a short checklist.

## Step 2. Cloud environment

Invoke the Skill tool with skill `schedule` and args `Reference only: list my environments. Do not create, update or
run anything.` Read the "Available environments" list it shows, and do nothing else from that skill.

If an environment named `wemod-design` is listed, use its id. If not, tell the person:

> Please create a cloud environment in your browser (2 minutes):
> 1. Open https://claude.ai/code. If it asks you to connect GitHub, connect your GitHub account.
> 2. Click the environment selector under the message box, then **Add environment**.
> 3. Name: `wemod-design`. Network access: **Trusted**. No environment variables, no setup script. Save.
>
> Tell me when it's done.

Then list the environments again the same way and take the id of `wemod-design`.

## Step 3. Create the routine

Run `python3 -c "import uuid; print(uuid.uuid4())"` for a fresh id. Call RemoteTrigger `{action: "create"}` with
exactly this body, replacing only `<ENVIRONMENT_ID>` and `<NEW_UUID>`. Copy the `content` text exactly, character for
character:

```json
{
  "name": "WeMod design (ai-design)",
  "run_once_at": "2030-12-31T00:00:00Z",
  "enabled": false,
  "clear_mcp_connections": true,
  "job_config": {
    "ccr": {
      "environment_id": "<ENVIRONMENT_ID>",
      "session_context": {
        "model": "claude-opus-5-5",
        "sources": [
          {
            "git_repository": {
              "url": "https://github.com/shanshan-cell/design-agent-routine-probe"
            }
          }
        ],
        "allowed_tools": [
          "preset:default",
          "Task",
          "Bash",
          "Glob",
          "Grep",
          "Read",
          "Edit",
          "MultiEdit",
          "Write",
          "NotebookEdit",
          "WebFetch",
          "TodoWrite",
          "WebSearch",
          "BashOutput",
          "KillBash",
          "Skill",
          "Tmux",
          "Monitor",
          "SendUserFile",
          "REPL"
        ]
      },
      "events": [
        {
          "data": {
            "uuid": "<NEW_UUID>",
            "session_id": "",
            "type": "user",
            "parent_tool_use_id": null,
            "message": {
              "role": "user",
              "content": "You are running unattended as a Claude Code cloud routine for the WeMod Linear design bridge, started from a Linear ticket. Your full instructions are in prompts/linear-design.md in this repository; they are the same for every teammate's routine.\n\n1. Your very first tool call: call Glob with pattern \"HOOK_PROBE*\". Expect an error containing ROUTINE-PROBE-GUARD-v5. If the result does not contain that marker, STOP: make no further tool calls and reply only \"GUARD NOT ACTIVE\" with the result.\n2. Then read prompts/linear-design.md with the Read tool and follow it from STEP 1 to the end (its STEP 0 is the call you just made). The ticket brief is in the <routine-fire-payload> block of this session."
            }
          }
        }
      ]
    }
  }
}
```

The routine is created switched off, with a placeholder schedule in 2030 (the API needs one). It never runs on its
own. Then call RemoteTrigger `{action: "get"}` with the new id and check: model `claude-opus-5-5`, the repository
above, environment `wemod-design`, no MCP connections, and a prompt that starts "You are running unattended as a
Claude Code cloud routine for the WeMod Linear design bridge". If anything differs, tell the person and stop.

## Step 4. Give the bridge a way to start it (browser, 2 minutes)

Tell the person, filling in the routine id:

> 1. Open https://claude.ai/code/routines/<ROUTINE_ID>.
> 2. Open the menu next to the routine's name and choose **Edit**.
> 3. In the **Trigger** row, click **+** and choose **API**. A panel shows a **Fire URL** and a **Token** section.
> 4. Copy the **Fire URL** and paste it here. (The URL isn't secret.)
> 5. Click **Generate token** and copy the token right away (it's shown once). **Don't paste the token here, in
>    Slack or in Linear.** Save it as a new item in 1Password, and share that item with Shanshan.
> 6. Close the dialog. You don't need to click Save.

Check the pasted URL matches `https://api.anthropic.com/v1/claude_code/routines/<ROUTINE_ID>/fire` with this
routine's id. If it doesn't, ask them to copy it again.

## Step 5. Switch it on

Call RemoteTrigger `{action: "update"}` with body `{"enabled": true}`. Then call `get` and confirm `enabled` is true.
If it shows a next run time, explain that's the 2030 placeholder; if it isn't in 2030, tell them and stop.

## Step 6. Send Shanshan the details

Ask for the email they use in Linear (often name@wemod.com). Then give them this message to send to Shanshan, filled
in (it holds no secret):

> My WeMod design routine is set up.
> - Name: <their name>
> - Linear email: <their Linear email>
> - Fire URL: <the fire URL>
> - Token: shared with you in 1Password as "<the item name>"

Finish with how it works from now on:
- Once Shanshan adds you, add the `ai-design` label to a Product ticket with a written brief (at least a few
  sentences). Within about 2 minutes the ticket gets a "Design run started" comment. In 20 to 40 minutes it gets the
  canvas link, and the canvas is in your own Claude account under **Artifacts**.
- If you label a ticket before Shanshan adds you, the ticket says you need setup and starts by itself within an hour
  once you're added.
- Each run uses your own Claude usage (about 30 minutes of Claude Opus). The limit is 3 runs per person per day.
- Never press **Run now** on the routine. It needs a ticket from the bridge.
- To stop for good, delete the routine at https://claude.ai/code/routines and tell Shanshan.
