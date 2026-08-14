// The landing page. Deliberately hand-written rather than routing `/` at
// README.md: the README is the PyPI long description and is written for that
// audience, and it carries a documentation table this site's navigation
// already is. What a first-time reader needs here is the one-sentence claim,
// the install line, and four doors.

import clsx from 'clsx';
import Link from '@docusaurus/Link';
import Layout from '@theme/Layout';
import CodeBlock from '@theme/CodeBlock';

import styles from './index.module.css';

const DOORS = [
  {
    to: '/docs/userguide',
    title: 'User guide',
    body:
      'How to drive it: a five-minute tour, every flag of every subcommand, ' +
      'the conflict lifecycle worked end to end, and a troubleshooting table.',
  },
  {
    to: '/docs/spec',
    title: 'Spec',
    body:
      'The design: the merge matrix, the normative sync algorithm, the state ' +
      'format, the reuse rules, and what is phase 1 versus phase 2.',
  },
  {
    to: '/docs/architecture',
    title: 'Architecture',
    body:
      'The code: every module, function and constant, the call graph from ' +
      'cli.main down to the splice, and where each invariant is enforced.',
  },
  {
    to: '/docs/canonicalization-reference',
    title: 'Canonicalization reference',
    body:
      'Every Markdown element and what cedit md canonicalize does to it, ' +
      'with the known caveats and quick test commands.',
  },
];

function Hero() {
  return (
    <header className={styles.hero}>
      <h1>cedit</h1>
      <p className={styles.tagline}>
        Keep local adaptations of vendored Markdown alive across upstream
        updates — a persistent block-level overlay, re-applied by a 3-way
        structural merge over the document&rsquo;s AST rather than over lines.
      </p>
      <div className={styles.buttons}>
        <Link
          className="button button--secondary button--lg"
          to="/docs/userguide">
          Read the user guide
        </Link>
        <Link
          className="button button--outline button--secondary button--lg"
          to="https://github.com/sdlctools/cedit">
          GitHub
        </Link>
      </div>
    </header>
  );
}

function Pitch() {
  return (
    <section className={styles.section}>
      <h2>The problem</h2>
      <p>
        You vendored a Markdown document — a skill file, a runbook, a
        template — and adapted it: a few fenced commands rewritten for the
        shell your environment actually has. Then upstream ships an update.
        Today you either freeze the file and lose upstream&rsquo;s fixes, or
        take the update and re-apply your edits by hand, every time.
      </p>
      <p>
        cedit makes those edits a durable overlay and turns &ldquo;update from
        upstream&rdquo; into a structural merge that either succeeds silently
        or reports a precise, per-block conflict — with all three versions
        recorded, and your text kept in the working file.
      </p>
      <CodeBlock language="bash">{`pipx install cedit

cedit snapshot skills/SKILL.md --from vendor/skills/SKILL.md   # start tracking
# ... adapt the file in place ...
cedit diff                    # what your overlay currently holds
cedit sync --from vendor      # re-apply it over the new upstream
cedit status                  # edits re-applied, conflicts outstanding`}</CodeBlock>
      <p>
        Exit codes are contract: <code>0</code> clean, <code>1</code>{' '}
        unresolved conflicts, <code>2</code> errors — for a human and for CI
        alike.
      </p>
    </section>
  );
}

function Doors() {
  return (
    <section className={styles.cards}>
      {DOORS.map((door) => (
        <Link key={door.to} className={clsx(styles.card)} to={door.to}>
          <h3>{door.title}</h3>
          <p>{door.body}</p>
        </Link>
      ))}
    </section>
  );
}

export default function Home() {
  return (
    <Layout
      title="Continuous editing of vendored Markdown"
      description="Keep local adaptations of vendored Markdown alive across upstream updates, via a 3-way structural merge over the document's AST.">
      <Hero />
      <main>
        <Pitch />
        <Doors />
      </main>
    </Layout>
  );
}
