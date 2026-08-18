# JAOT documentation — what lives where

There are **two documentation sets**, with different audiences. Neither is a copy
of the other, and neither should become one.

## 1. Product documentation — `frontend/content/docs/`

What a **user** reads, served at `https://jaot.io/docs`. Plain MDX, readable in
the repo as it is. Start at
[`getting-started/concepts.mdx`](../frontend/content/docs/getting-started/concepts.mdx)
for the domain vocabulary, or
[`getting-started/quick-start.mdx`](../frontend/content/docs/getting-started/quick-start.mdx)
to solve something.

Two pages there are aimed at developers rather than end users, and are the public
face of this directory: [`reference/architecture.mdx`](../frontend/content/docs/reference/architecture.mdx)
(how JAOT is built, what you can extend, what self-hosting involves) and
[`getting-started/concepts.mdx`](../frontend/content/docs/getting-started/concepts.mdx)
(the vocabulary). Both link back here for depth; keep them summaries, not copies.

Adding a page there takes three edits, all required or the page 404s:
the `.mdx` file, `frontend/src/lib/docs/navigation.ts`, and the `contentMap` in
`frontend/src/app/[locale]/(public)/docs/[...slug]/page.tsx`. A count test in
`frontend/src/lib/docs/__tests__/navigation.test.ts` fails if you forget one.

## 2. Engineering documentation — this directory

What a **contributor** reads.

| File | What it is |
|------|-----------|
| [`GLOSSARY.md`](GLOSSARY.md) | The domain words mapped onto classes, tables and modules |
| [`ARCHITECTURE/`](ARCHITECTURE/) | System context, backend, infrastructure, decisions (ADRs), tech debt |
| [`BOUNDED_CONTEXTS.md`](BOUNDED_CONTEXTS.md) | The 8 contexts and the extraction plan |
| [`JMODEL_GRAMMAR.md`](JMODEL_GRAMMAR.md) | The JModel language, formally |
| [`TESTING.md`](TESTING.md) | How the suite is organised and what it guarantees |
| [`ROADMAP.md`](ROADMAP.md) | Public roadmap |
| [`CHANGELOG.md`](CHANGELOG.md) | Every user-visible change, newest first |
| [`getting-started/`](getting-started/) | Running the stack locally, configuration |
| [`operations/`](operations/) | Deploy, backups, monitoring |
| [`specifications/`](specifications/) | Formulations written out in full |

## Which one does my change belong in?

- Changing what a **user can do** → the product docs, and a line in `CHANGELOG.md`.
- Changing **how it is built** → `ARCHITECTURE/`.
- A new **word** in the domain → `GLOSSARY.md` here, and the user-facing meaning
  in `concepts.mdx` there.

**Do not copy text between the two sets.** Link instead. Two copies of one
sentence stay equal exactly until the first time somebody edits one of them, and
this project has already spent a session finding claims that had drifted apart
that way.
