# Research example: choosing an agent tool for production repository work

Prepared 2026-11-02 from source snapshots retrieved 2026-11-01. This original brief assesses a constrained adoption experiment. A source feature list, source-code license or retrieved passage does not establish production reliability.

## Constraints

Illustrative project: one owner wants an agent to inspect a software repository, make a bounded change, run checks and return a reviewable patch. Provider access already exists outside this example. No unattended merge/deployment or production writes are authorized. Required properties are inspectable tool activity, controlled execution, predictable engine access and a rollback path. Exact provider, budget and security/data requirements remain deployment decisions.

## Candidates and supported facts

| Candidate | Evidence and role | Unresolved production questions |
| --- | --- | --- |
| MiniMax Code | The repository describes a terminal agent that reads files/diffs, runs commands/tests, supports permission/sandbox controls, headless jobs and ACP clients. It supports credited MiniMax access or compatible BYOK APIs. First-party source defaults to MIT while file/package exceptions remain. [Repository README](https://github.com/MiniMax-AI/minimax-code), publication date unknown; retrieved 2026-11-01. | Actual sandbox/approval enforcement, repository integration, engine behavior, costs and dependency/asset terms have not been qualified here. |
| AutoSwarm | The README describes routing parallel work among existing agents, sharing context/memory and synthesizing results. Host skill support/local command execution and compatible collaborator CLIs are prerequisites. A real reply/resume probe spends model calls. [Repository README](https://github.com/HKUDS/AutoSwarm), publication date unknown; retrieved 2026-11-01. | Additional orchestration has not been shown necessary for this one bounded task. Tool discovery alone does not establish working providers or reliable delegated results. |
| Open Duet | The workspace provides named teams, remembered context and routines, but requires an external engine/account. Its README explicitly limits the experimental server to one owner, with evolving delegation and unqualified remote integrations; team leads require Claude or Codex. Application license is Apache 2.0. [Repository README](https://github.com/Anil-matcha/open-duet), publication date unknown; retrieved 2026-11-01. | A self-hosted application and local storage are not proof of mature production automation or local-only model processing. Provider, security, recovery and actual integration qualification remain open. |
| Comfy MCP Local | The August 18 announcement describes MCP access to local ComfyUI, model/node/GPU inventory and reusable creative workflows, alongside cloud connectivity. [Comfy article](https://blog.comfy.org/p/open-sourcing-comfy-mcp-on-local), published 2026-08-18; retrieved 2026-11-01. | Its documented job is creative-generation workflow integration. The cited article does not establish a general repository coding engine, free unlimited cloud compute or production reliability for this software task. |

These tools occupy different workflow roles. Model/provider terms and any model-weight license remain separate from MIT/Apache application source licenses. Bringing an existing account does not resolve per-call costs, account entitlements or where prompts/context are processed.

## Provisional choice and validation

**Use MiniMax Code as the first candidate for a bounded repository trial; do not call it production-qualified.** Its retained capability description most directly matches the stated coding job. Keep AutoSwarm for a later demonstrated need to coordinate multiple working agents. Open Duet’s experimental state argues for a separate noncritical workspace pilot. Choose Comfy MCP when the actual task is constructing or reusing a ComfyUI media pipeline.

1. Pin the source/CLI version, supported Node runtime, engine configuration and access credentials through the normal deployment process. Review dependency/asset licenses and data-handling terms. Expected result: a working model connection with understood limits and bounded cost. Observe authentication failures, model-limit mismatch, network/service dependencies and all telemetry/context destinations. No credential or service configuration was changed for this brief.
2. In an isolated repository worktree, ask for one small fix with an existing meaningful failing check. Use the intended permission/sandbox mode and require a patch plus test evidence. Expected result: the intended check passes, the diff stays within scope, approval boundaries are observable and no production action occurs. Observe unexpected file writes, shell/network access, ignored denials and unsupported headless/client behavior. Verify the result independently of the agent’s own success message.
3. Exercise one interruption/resume and one engine/tool failure, then restore the worktree from its known base. Expected result: no duplicate mutation, no lost review evidence, and a repeatable recovery path. Record elapsed time, model calls/cost and manual intervention. Expand to a production-adjacent canary only after the owner’s project-specific acceptance criteria are met.

## Evidence trail and manual diagnostic check

Curated records: `minimax-code`, `autoswarm`, `open-duet`, `comfy-mcp-local`.

- MiniMax Code: source `006c7eeb54ff362fa127`, SHA `2572b50e7b61f424b9395ea11b0098d5d396361579d352aa80fa49979260dbf9`; lines39–41,130–161,396–412,481–490.
- AutoSwarm: source `d528e97f4ac5c2675478`, SHA `427f5d5f66b41a003abf539b2b8311cbc0f39b45a0f1e6bc62873da584b996e4`; lines39–65,174–181,230–234.
- Open Duet: source `e83de83eee8dd4e60f8b`, SHA `3d74827ea0c9838855f8a18d4d867cf285a90bbdaa8a758bed3505174150ea26`; lines15–23,42–70,126–155,206–225,269–272.
- Comfy MCP Local: source `87dd323306f86865044e`, SHA `9ed746241e76f2698a53f64481536d198cdab9dffc2d3fe22d8ce60356124655`; lines23–42,49–51.

Compared with development fixture `agent-workflow-vs-coding`, this brief preserves project-specific integration, cost and reliability as required unknowns. Compared with `agent-comfy-free-unlimited`, it makes no free/unlimited compute claim. Those fixture cases concern related announcements and supply diagnostic boundaries; their Vibe/cloud capabilities are not silently attributed to these four candidates. The review does not score universal AI accuracy or demonstrate that any candidate has passed the proposed runtime trial.
