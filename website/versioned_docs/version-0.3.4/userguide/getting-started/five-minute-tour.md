---
slug: /userguide/tour
sidebar_position: 3
---
# Five-minute tour

A complete round trip in a throwaway directory: vendor a skill, adapt it, take
two upstream revisions, hit a conflict, settle it. Copy-paste each block in
order, with the venv activated.

````bash
mkdir -p /tmp/cedit-tour/vendor/skills && cd /tmp/cedit-tour

cat > vendor/skills/deploy.md <<'EOF'
# Deploy skill

This skill takes a build from the artifact store and puts it on staging.

## Preflight

Run the healthcheck before anything else:

```bash
bash scripts/healthcheck.sh --strict
```

## Deploy

```bash
bash scripts/deploy.sh --env staging
```
EOF

cedit snapshot skills/deploy.md --from vendor/skills/deploy.md
````

```console
skills/deploy.md: tracking (base 9ef5a0dbdc298d85, from vendor/skills/deploy.md), 0 local edit(s) recorded
```

`vendor/` is your upstream mirror; `skills/deploy.md` is the document you are
going to own. It did not exist, so `snapshot` vendored it — the working copy now
holds the canonicalized upstream text, and `.cedit/` holds the base snapshot the
merge will remember.

Now adapt it. Your environment has no `bash`, so rewrite the healthcheck fence:

```bash
perl -0pi -e 's/```bash\nbash scripts\/healthcheck/```zsh\nzsh scripts\/healthcheck/' skills/deploy.md
cedit diff
```

```console
skills/deploy.md: 1 local edit(s)
[edit opaque fence] #7b47884c75de548e:0  sim=0.93
    ctx  : Preflight
    info : bash -> zsh
    base : bash scripts/healthcheck.sh --strict
    local: zsh scripts/healthcheck.sh --strict

```

One edit, on one fence, at one address. The `info : bash -> zsh` line is the
fence's info string — the ```` ```bash ```` marker itself is part of what you
edited, not decoration around it.

Upstream evolves: the intro gets a sentence, and the *other* fence gains a flag.

```bash
sed -i 's/puts it on staging./puts it on staging, then promotes it to production./' vendor/skills/deploy.md
sed -i 's/deploy.sh --env staging/deploy.sh --env staging --wait/' vendor/skills/deploy.md
cedit sync --from vendor
```

```console
skills/deploy.md: 1 edit(s) reapplied, 2 block(s) updated from upstream, no conflicts
```

Read that as: your zsh rewrite went back in, upstream's two changes came through,
nobody stepped on anybody. The file now has upstream's new prose, upstream's
`--wait`, and your `zsh` fence.

Now the interesting case. Upstream touches the very fence you rewrote:

```bash
sed -i 's/healthcheck.sh --strict/healthcheck.sh --strict --timeout 60/' vendor/skills/deploy.md
cedit sync --from vendor
echo "rc=$?"
```

```console
skills/deploy.md: 0 edit(s) reapplied, 0 block(s) updated from upstream, 1 conflict(s)
[CONFLICT opaque fence] #7b47884c75de548e:0
    ctx     : Preflight
    base    : bash scripts/healthcheck.sh --strict
    upstream: bash scripts/healthcheck.sh --strict --timeout 60
    local   : zsh scripts/healthcheck.sh --strict  (kept in the working file)
    resolve : cedit resolve skills/deploy.md 7b47884c75de548e:0 --take local|upstream

rc=1
```

Exit code 1 — "a human is needed", distinct from 2, "something is broken". Your
zsh line is still in the file; upstream's version is recorded, not applied. Keep
the adaptation:

```bash
cedit resolve skills/deploy.md 7b47884c75de548e --take local
cedit sync --from vendor
cedit status
```

```console
skills/deploy.md #7b47884c75de548e:0: kept local text — it is now an ordinary overlay edit against the new base
skills/deploy.md: up to date
skills/deploy.md: 1 local edit(s), 0 unresolved conflict(s); base d47b5d46bb5134d8 synced 2026-08-05T00:01:42Z (upstream: vendor)
```

That last state is the whole point. You did not just dismiss a conflict — the
adaptation was **re-keyed to the new upstream block**, so it is an ordinary
overlay edit again, and the next upstream revision that leaves that fence alone
will re-apply it without asking. This is the `git rerere` move.
