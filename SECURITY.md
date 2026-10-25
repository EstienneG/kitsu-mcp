# Security

## Reporting a vulnerability

Please report vulnerabilities privately, through GitHub's
[private vulnerability reporting](https://github.com/EstienneG/kitsu-mcp/security/advisories/new), not in a
public issue. Expect an answer within a week. Fixes go out in a patch release, with a `CHANGELOG.md` entry
once users can update.

Only the latest release gets security fixes.

## How the server handles credentials

**Local (stdio).** The server logs in as `KITSU_USER` / `KITSU_PASSWORD`, read from the environment or a
`.env` file. Agents usually store these in plain text in their config file; keep that file private.

**Hosted (HTTP).** Each caller sends their own Kitsu login with every request (`Authorization: Basic`, or
`Bearer email:password`), and every tool call runs with that person's Kitsu permissions. The server's own login
is never used over HTTP.

- The server refuses to listen beyond localhost unless the operator confirms HTTPS terminates in front of it
  (`--behind-tls` / `KITSU_BEHIND_TLS=true`). Never run it on a public address without TLS.
- Credentials are kept only in memory, under keys derived with a per-process secret, and never logged. Only
  logins Kitsu accepted are cached, for an hour of inactivity.
- Repeated rejected logins for one account are slowed down; a recent successful login is always let through,
  so guessing at an email cannot lock its owner out. Spraying many emails from one address is not throttled:
  rate-limit at the proxy if the server is exposed widely.
- Tools that would write files to the server's disk (`download_previews`, `download_video`) are hidden.

**Writes.** Write tools are off unless `KITSU_ALLOW_WRITE=true`, and every write tool has a dry run. Kitsu's own
permissions still apply: the server cannot do anything the person's account cannot.

## Known limitations

- Kitsu accounts with two-factor authentication cannot log in (locally or through the hosted server).
- API tokens (Kitsu bot accounts) are not supported yet; logins use an email and password.
