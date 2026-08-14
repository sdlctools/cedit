// @ts-check
// Docusaurus configuration for the cedit documentation site.
//
// The site publishes ../docs — the four user-facing documents — and nothing
// else. AGENTS.md, CLAUDE.md and .claude/rules/ deliberately stay at the
// repository root, unpublished: they are read by AI tooling from fixed paths
// and serve no reader here. Links out of ../docs to those files are absolute
// GitHub URLs for that reason.
//
// Two settings below are load-bearing rather than taste:
//
//   markdown.format: 'detect'  — .md is parsed as CommonMark, not MDX. The
//     corpus is full of angle-bracket placeholders (<KEY>, <X.Y.Z>, <doc>)
//     and brace-heavy code; under the default 'mdx' every one of those is a
//     JSX parse error. 'detect' keeps .md plain and leaves .mdx (the landing
//     page's siblings, if any are ever added) as MDX.
//
//   onBrokenLinks: 'throw'     — a docs set that drifts from the invariants
//     it documents is worse than none, and a dangling cross-link is the
//     cheapest form of that drift to catch. The build fails on one.

import { themes as prismThemes } from 'prism-react-renderer';

const ORG = 'sdlctools';
const REPO = 'cedit';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'cedit',
  tagline: 'Continuous editing of vendored Markdown',
  favicon: 'img/favicon.svg',

  url: `https://${ORG}.github.io`,
  baseUrl: `/${REPO}/`,

  organizationName: ORG,
  projectName: REPO,
  trailingSlash: false,

  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',

  markdown: {
    format: 'detect',
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          // The docs live outside website/ on purpose: they are read from the
          // repository root by anyone working on cedit, and by GitHub's own
          // Markdown rendering, whether or not this site is built.
          path: '../docs',
          routeBasePath: 'docs',
          sidebarPath: './sidebars.js',
          editUrl: `https://github.com/${ORG}/${REPO}/tree/main/`,
          showLastUpdateTime: true,
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'cedit',
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docsSidebar',
            position: 'left',
            label: 'Docs',
          },
          {
            type: 'docsVersionDropdown',
            position: 'right',
          },
          {
            href: 'https://pypi.org/project/cedit/',
            label: 'PyPI',
            position: 'right',
          },
          {
            href: `https://github.com/${ORG}/${REPO}`,
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              { label: 'User guide', to: '/docs/userguide' },
              { label: 'Spec', to: '/docs/spec' },
              { label: 'Architecture', to: '/docs/architecture' },
              {
                label: 'Canonicalization reference',
                to: '/docs/canonicalization-reference',
              },
            ],
          },
          {
            title: 'Working on cedit',
            items: [
              {
                label: 'AGENTS.md',
                href: `https://github.com/${ORG}/${REPO}/blob/main/AGENTS.md`,
              },
              {
                label: 'Hash stability',
                href: `https://github.com/${ORG}/${REPO}/blob/main/.claude/rules/hash-stability.md`,
              },
              {
                label: 'Release pipeline',
                href: `https://github.com/${ORG}/${REPO}/blob/main/.claude/rules/release-pipeline.md`,
              },
            ],
          },
          {
            title: 'More',
            items: [
              { label: 'GitHub', href: `https://github.com/${ORG}/${REPO}` },
              { label: 'PyPI', href: 'https://pypi.org/project/cedit/' },
              {
                label: 'Issues',
                href: `https://github.com/${ORG}/${REPO}/issues`,
              },
            ],
          },
        ],
        copyright: `MIT-licensed. Built with Docusaurus.`,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['bash', 'python', 'json', 'diff', 'toml', 'yaml'],
      },
    }),
};

export default config;
