# Knowledge-base audit

Source: four public Valetax pages, snapshotted on 2026-10-15 into `data/kb_raw/` and parsed into 24 chunks
(`data/kb/chunks.json`, `kb_version` recorded in every co-pilot output). Per the brief, they are used
**as they are**: nothing is corrected in the KB. This audit is what the co-pilot has to live with, and it
doubles as a content backlog for the support/content team. Fixing these pages is the cheapest
quality improvement available, cheaper than any model change.

## Structure

| Page | Steps | FAQ items | Notes |
|---|---|---|---|
| How to Deposit | 4 | 9 (deposit + withdrawal FAQ) | |
| How to Withdraw | 4 | the **same** 9 FAQ items | Duplicated block |
| How to Open an Account | 4 ("3 quick and simple steps") | 7 | |
| How to Verify Account | 3 | none | No document list, no timeline |

Duplicates are stored once with both URLs (`faq/*` chunks list `urls: [deposit, withdraw]`), so the
retriever is not biased by them and a citation still points to a real page.

## Inconsistencies (the co-pilot must not "resolve" these by guessing)

| # | Where | Issue | How the co-pilot handles it |
|---|---|---|---|
| 1 | Withdraw → steps 3–4 | Step 3 says "Enter your account details and **amount to deposit**". Step 4 says "**Start Trading!**". This is copy-paste from the deposit page. | Quote the steps neutrally ("enter your account details and the amount"). Flag it in `internal_note`. Eval ticket `edge-05` covers this. |
| 2 | Deposit FAQ | "Deposits are **instant**!" and, in the same answer, "within **60 minutes**". | Use the conservative statement (up to 60 minutes) and quote it. Ticket `dep-10` is a customer citing "instant". |
| 3 | Open account | "Opening a live account allows you to begin trading **immediately**". But documents are required and "verification will be completed within **48 hours**". | Don't promise immediate trading. Cite the 48 h statement. |
| 4 | Open account | "**3** quick and simple steps", then 4 steps are listed. | Cosmetic; ignored. |
| 5 | Minimum deposit | "starts from 8 USD, depending on the account type". The account-types page it links to is **not** in the KB. | Quote "from 8 USD, depending on the account type". Never quote per-account minimums. |
| 6 | Leverage FAQ | Titled "What leverage settings **should** I select?" (advice-shaped). The answer gives a fact ("up to 1:2000 depending on account types"). | Neutral fact allowed; the choice is declined as trading advice (`adv-03`). |
| 7 | Islamic FAQ | "no swap is credited or withdrawn from all trading account" (grammar). | Quote carefully; no extra claims about swap-free conditions. |
| 8 | Withdrawal rejected FAQ | Typos ("insifficient margin", "in in queue"). | The validator uses whitespace/punctuation-normalised matching, so verbatim quotes still verify. |

## Gaps (frequent questions the KB cannot answer → the co-pilot abstains or answers partially)

- **Withdrawal processing time.** Only "pending = in queue" and "contact support if not received within 24 hours" exist. There is no SLA. This is the #1 risk for invented timelines (eval `gap-02`, `inj-03`).
- **Fees** for deposits and withdrawals, by method (`gap-01`, `gap-09`, `gap-13`).
- **Payment methods list** and per-country availability (`gap-03`).
- **Minimum and maximum withdrawal / deposit limits** (`gap-04`, `gap-10`).
- **Withdraw-to-same-method rule** (`gap-11`). Every broker has one, but it is not in the KB.
- **Verification**: accepted ID types, rejection reasons, what to do after a rejection, source-of-funds requests.
- Platform/MT5 password reset, demo accounts, changing leverage on an existing account, account closure, bonuses, IB programme (`gap-06/07/08/12/14`, `gap-05`).

## Recommended content fixes (priority order)

1. Publish a withdrawal SLA by method and a fee table. This removes the largest class of abstentions.
2. Fix the withdraw page steps (#1). Merge the duplicated FAQ into one canonical page.
3. Add a verification FAQ: accepted documents, typical review time, rejection reasons, resubmission.
4. Add the account-types page to the KB (needed for "minimum deposit per account" questions).
5. Internal SOPs (not public) for escalations: complaints, KYC/AML, security. The co-pilot's routing already assumes these teams exist.

The eval's `gap` slice measures how often tickets fall into these holes. Its re-weighted share
(`business_case/assumptions.json → ticket_mix.gap`) directly limits the business case. Every gap closed
turns "agent writes from scratch" into "agent approves a draft".
