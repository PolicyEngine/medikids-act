# MediKids Act (S. 5037): a first PolicyEngine estimate

**Draft, under review. This is not a published PolicyEngine analysis, and this repository holds no result numbers.** It holds the code, the tests and the method for a first static estimate of the MediKids Act. Results will be added only after review and a decision to publish.

## The bill

S. 5037 (Sen. Andy Kim, introduced July 2026) adds a mandatory Medicaid eligibility group for everyone under 26, with no income test, starting two years after enactment. Read from the bill text the sponsor released in July 2026 ([S. 5037 on congress.gov](https://www.congress.gov/bill/119th-congress/senate-bill/5037)), it also:

- enrolls children automatically at birth, with an opt-out only for children who have other coverage;
- keeps anyone found eligible under 26 eligible until they turn 26 or stop residing in the State, with no income redeterminations;
- drops the immigration-status test under 26;
- pays a 100 percent federal match only for people who would not have been eligible for full benefits under the State plan, or a waiver of it, as it stood on January 1, 2025, and the usual match for everyone else;
- keeps the premium tax credit open to people whose only Medicaid eligibility is the new group, unless they enroll (the credit's other rules still apply);
- excepts everyone under 26 from the community engagement (work) requirements enacted in 2025.

The bill raises no revenue.

## What this estimate covers

For one year, 2029, an assumed reporting year with the new group in force all year (it starts two years after enactment, so 2029 is a full year of it only if the bill is enacted by January 1, 2027):

- people under 26 by current coverage: Medicaid or CHIP, employer, Marketplace, other, uninsured;
- how many become newly eligible, and how many fall outside the 2025 State plan and so would draw the 100 percent match under the primary reading;
- the gross Medicaid cost under stated switching cases, from a floor of modeled transitions to "everyone under 26 enrolls", priced two ways;
- the federal and state split under the bill's two match rates, with three points the bill's text leaves open shown as alternatives;
- premium tax credits, separate-CHIP spending and Basic Health Program payments replaced.

"Uninsured" here means uninsured at the survey interview and not enrolled in a public program in the model. The dataset records that survey answer on part of its sample only, so the rest is imputed at the measured rate. The method note explains this and why the model's count is lower than the survey's.

## What it leaves out

- **How many people would switch.** The cases are assumptions, not predictions. The model has no behavioral take-up for people leaving private coverage.
- **Employer savings and the wage and tax feedback** when dependents leave family plans.
- **A ten-year budget window.** This is one year, with no phase-in.
- **A per-person cost grounded in privately insured children's own spending.** Both prices are Medicaid averages.
- Children who are enrolled automatically and keep private coverage, with Medicaid paying second.
- The richer benefits the bill extends to 26 (early and periodic screening, and the SSA 1916 cost-sharing exemption, which now ends at 18, with State options to extend it), provider payment, state responses, and administrative cost.

[docs/method.md](docs/method.md) gives the method, every assumption with its source, the readings of the bill, the departures from the certified model, and the known limits.

## How it works

The estimate runs PolicyEngine US through [`policyengine`](https://github.com/PolicyEngine/policyengine.py) 6.20.3, which pins `policyengine-us` 2.2.2 and the certified Microcosm dataset `populace_us_2024`. The bill is a structural reform kept in this repository ([`medikids_act/reform.py`](medikids_act/reform.py)); nothing in `policyengine-us` is changed.

Each scenario is a full microsimulation:

1. **Lookback run.** Medicaid and CHIP eligibility rules pinned to January 1, 2025, applied to the 2029 population. It decides who draws the 100 percent match and sets the base for per-enrollee prices.
2. **Baseline run.** Current law in 2029.
3. **One run per switching case** ([`medikids_act/cases.py`](medikids_act/cases.py)), with enrollment among the newly eligible set explicitly.

[`medikids_act/checks.py`](medikids_act/checks.py) then tests the outputs against invariants, and [`medikids_act/tables.py`](medikids_act/tables.py) builds the tables.

## Run it

```bash
uv sync
uv run pytest
```

The tests run single households and need no dataset. They build several copies of the tax-benefit system and use about 4 GB of memory. The national runs need the certified dataset (about 0.8 GB) at `data/releases/...` under the repository root; the pipeline stops, and says where the file belongs, if it is missing. Set `MEDIKIDS_ALLOW_DOWNLOAD=1` to let `policyengine` fetch it. Each national run takes one process; run them one at a time from the repository root:

```bash
uv run python -m medikids_act.pipeline lookback
uv run python -m medikids_act.pipeline baseline
uv run python -m medikids_act.pipeline case floor   # then newborns, uninsured, uninsured_wide, marketplace, employer_25, employer_50, everyone
uv run python -m medikids_act.pipeline checks
uv run python -m medikids_act.pipeline tables
```

Outputs go to `$MEDIKIDS_RESULTS`, or to `results/`, which git ignores.

## Status

Draft first estimate, in review. Open questions and limits are listed in the method note.
