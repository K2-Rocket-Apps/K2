---
name: mcp-step-up-approval
description: Use when a tool call through your K2 gateway returns a browser approval challenge (an approval_required result with a verification URL and a user_code) instead of running, or when a step-up-gated tool seems to want a verification code you do not have.
---

# MCP step-up browser approval

Some tools behind your K2 gateway are protected by browser step-up approval. They never take a
verification code as a tool argument. Instead, the first call returns a device-grant style
challenge, and a human approves that exact call in their own browser. The live code is typed into
the browser, so it never enters your context, your transcript, or your logs.

## Recognising the challenge

The tool result is an error (`isError: true`) that carries both:

- a human-readable message in `content` with a verification URL and a `user_code`, asking a person
  to open the URL, sign in and approve; and
- a machine-readable `structuredContent` with `status: "approval_required"` and the same
  information as typed fields: `request_id`, `user_code`, `verification_uri`, and a pre-filled
  `verification_uri_complete`.

## Never fabricate a code

Never fill a step-up, 2FA or code argument with a guessed or placeholder value (`"000000"` or
anything else you made up). If you do not hold a genuine code, leave the argument out and let the
call return the `approval_required` challenge. A fabricated code is not a shortcut: it is a
malformed call that fails, and if it ever validated it would defeat the purpose of step-up.

## What to do when you see the challenge

1. Read `request_id` and `verification_uri_complete` from `structuredContent`. Use
   `verification_uri` if `verification_uri_complete` is absent.
2. Drive the approval with `k2-agent`:
   ```
   k2-agent approve "<request_id>" "<verification_uri_complete>"
   ```
   It opens the browser and then waits, polling your K2 gateway for the approval status. It exits
   0 (printing that the request was approved) as soon as a person approves. Run it and wait for it
   to exit; you do not need to ask for confirmation in chat while it polls.
3. On exit 0, re-issue the original tool call with byte-identical arguments: same tool, same
   arguments, nothing added. The approval is bound to that exact call, so any change (including
   adding a code) will not match and will mint a new, unrelated challenge.
4. On a non-zero exit (the request `expired`, was `not_found`, or the wait timed out), say so
   plainly and stop. Do not retry blindly. A different tool, or the same tool with different
   arguments, always needs its own fresh approval; there is no way to pre-approve a session.

## Fallback when k2-agent is missing or cannot approve

Use the manual flow below when any of these hold:

- `k2-agent` is not on your `PATH`;
- your installed `k2-agent` does not recognise the `approve` subcommand (an older build); or
- `k2-agent` reports that this machine is not enrolled, and enrolling would itself need an
  interactive confirmation from a person.

The manual flow:

1. Open the verification URL yourself straight away rather than only printing it. Use the command
   for the current OS:
   - macOS: `open "<url>"`
   - Linux: `xdg-open "<url>"`
   - Windows: `start "<url>"`
2. Tell the person briefly that you opened it and what they need to do: sign in (password plus a
   fresh authenticator code) and approve the request.
3. Once they confirm they saw an explicit success message on the approval page (not just that they
   clicked something), re-issue the exact same tool call with the same arguments.
4. If the retry returns the same challenge again (the same `user_code`), the approval was not
   consumed. Do not loop. Ask the person to confirm they saw the success message.

## If the approval page is rate limited

If the approval page itself answers `429 Too Many Requests`, do not hammer it with retries. Space
out attempts and let the limit window reset.

## Why this flow exists

Browser approval keeps the verification code out of the model's context entirely, so it cannot
leak through logs, transcripts or a compromised session. A person still authenticates and approves
each call in their own browser, and the assistant never sees a code.
