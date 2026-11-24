# Method and assumptions

Draft, under review. This note describes how the estimate is built. It contains no results.

## What is estimated

The estimate covers one calendar year, 2029, with the bill treated as in force all year. The bill's new group starts two years after enactment, and the next Congress convenes in January 2027, so 2029 is the earliest year the group could exist. The estimate is static: nobody's income, work or residence changes.

How many people would leave private coverage for Medicaid is the largest unknown, and the model cannot predict it. The estimate therefore reports a set of switching cases, each a stated assumption about who enrolls.

## Model, data and versions

- `policyengine` 6.20.3, which pins `policyengine-us` 2.2.2 and `policyengine-core` 3.34.10.
- The certified Microcosm dataset `populace_us_2024` (build `populace-us-2024-spm-20260915`), a 2024 file that the engine ages to 2029.
- Every scenario is a full microsimulation through `policyengine.us.managed_microsimulation`, with a structural reform defined in [`medikids_act/reform.py`](../medikids_act/reform.py). No figure is scaled, interpolated or extrapolated from another scenario's run.

`policyengine-us` has changed its Medicaid rules since version 2.2.2. The estimate uses the certified version because the dataset's Medicaid take-up was built against it.

## The bill in the model

| Provision | Bill section | In the model |
|---|---|---|
| New group: everyone under 26, no income test | 2(a), new SSA 1902(a)(10)(A)(i)(X) | `is_medicaid_eligible` becomes "eligible through an existing group, or under 26". The engine's own eligibility formula is kept under the name `medikids_existing_group_eligible`. |
| No immigration-status test under 26 | 2(e), new SSA 1903(v)(6) and PRWORA amendments | The new group applies no immigration test. |
| Exception from community engagement requirements | 2(g) | The requirement's age range starts at 26 instead of 19. |
| Eligibility alone does not block the premium tax credit | 2(d), new IRC 36B(c)(2)(D) | The Marketplace gate (`gov.aca.ineligible_coverage`) reads existing-group eligibility. Enrollment still blocks, through the engine's list of qualifying coverage. |
| 100 percent match for people outside the 2025 State plan | 2(f), new SSA 1905(ll) | `medicaid_federal_share` is replaced. See "Who draws the 100 percent match". |
| Automatic enrollment at birth; eligibility continues to 26 | 2(b), 2(c) | Not modeled over time. The switching cases stand in for them. |
| Screening benefits and no cost sharing to 26 | 2(h), 2(i) | Not modeled. |

A person who is eligible only through the new group is "eligible only under (X)" for the premium tax credit rule. That includes people who meet an existing group's income test but fail its immigration test.

## Effects that need nobody to choose

Four things change on the day the group starts, whoever enrolls. Together they are the **floor** case.

1. **Separate CHIP empties under 19.** A "targeted low-income child" must be a child "not found to be eligible for medical assistance under" Medicaid (SSA 2110(b)(1)(C)), and States must enroll children found eligible for Medicaid in Medicaid (SSA 2102(b)(3)). Once every child is Medicaid-eligible, none can be covered by a separate CHIP program. The bill does not amend those sections. The estimate moves every modeled separate-CHIP enrollee under 26 to Medicaid, including pregnant enrollees under 26.
2. **The Basic Health Program loses everyone under 26.** An eligible individual must be "not eligible to enroll in the State's medicaid program" (ACA 1331(e)(1)(A)), and the bill's premium tax credit rule does not reach that section. The estimate moves modeled Basic Health Program enrollees under 26 to Medicaid. Where they go is an assumption: they could instead buy Marketplace coverage with a credit.
3. **Adults aged 19 to 25 who failed the community engagement requirement regain Medicaid** through the adult group, at the take-up the dataset records for them.
4. **State-funded coverage of people under 26 draws the federal match**, with no change in enrollment.

## Who draws the 100 percent match

New SSA 1905(ll) pays 100 percent for people eligible under the new group "who would not have been eligible for medical assistance for full benefits ... under the State plan under this title or a waiver of such plan as such plan or waiver was in effect on January 1, 2025".

The estimate reads this as the 2025 rules applied to a person's circumstances in the reporting year. The date attaches to the plan, and CMS ran the parallel December 2009 test for the ACA adult group the same way (42 CFR 433.206).

The **lookback run** computes that test. It pins every parameter under the engine's Medicaid and CHIP eligibility folders, and the state Medicaid folders its formulas read, to its value on January 1, 2025, for the reporting year. Income limits are percentages of the poverty line, so pinning them applies the 2025 percentage to the 2029 poverty line. The pins undo, among others, the October 2026 narrowing of eligible immigration statuses and the 2027 community engagement requirement. A person is inside the 2025 plan if they have a Medicaid category under those rules (or are in California's former foster youth group) and meet the federal immigration test.

What follows:

- **Separate-CHIP children draw 100 percent.** Separate CHIP is a title XXI plan, and its children are by definition not eligible for Medicaid.
- **People in state-funded coverage draw 100 percent.** A state-only program is not the title XIX State plan.
- **People who were eligible under the 2025 rules and lost eligibility later do not.** They draw the rate current law gives their 2025 group: 90 percent for the ACA adult group, the state's regular rate otherwise.

The bill leaves three points open. The estimate leads with the first reading in each and reports the others beside it:

| Open point | Primary reading | Alternative |
|---|---|---|
| The bill does not amend SSA 1903(v)(5), which since October 2026 bars federal payment for anyone but citizens, lawful permanent residents, Cuban and Haitian entrants and Compact of Free Association residents. | New 1903(v)(6) and the 100 percent match override it. | `strict_v5`: States cover everyone else under 26 with no federal payment. |
| The test names "full benefits" only. The ACA adult group receives benchmark coverage. | Benchmark coverage counts; adult-group members aged 19 to 25 keep 90 percent. | `adult_group_100`: they draw 100 percent. |
| CMS rules take a person out of the adult group once another mandatory group covers them. | They stay "described in" the adult group and keep 90 percent. | `adult_group_regular`: they draw the state's regular rate. |

Limits of the lookback:

- The engine does not record whether a category gives full benefits, so every category counts as full benefits.
- The dataset has no years-since-entry input, so the five-year bar never binds, and recent lawful permanent residents count as inside the 2025 plan.
- The engine models Medicaid-expansion CHIP inside Medicaid's child income limits. Those children are treated as inside the 2025 plan at the regular rate, in the baseline and under the bill, although CHIP pays an enhanced rate for them today. Privately insured children in that income band were not in the 2025 plan and are missed.
- Former foster youth outside California and section 1115 adult coverage are not modeled.

## Current coverage and the uninsured

The engine has no uninsured variable. [`medikids_act/coverage.py`](../medikids_act/coverage.py) assigns each person the first class that fits, in this order:

1. Medicaid (modeled enrollment)
2. Separate CHIP (modeled enrollment)
3. Basic Health Program (modeled enrollment)
4. Employer (reported)
5. Marketplace (a modeled premium tax credit recipient, or reported Marketplace coverage)
6. Reports Medicaid or CHIP, but the model does not enroll them
7. Other (reported direct purchase outside the Marketplace, TRICARE, CHAMPVA, VA, other means-tested coverage; modeled Medicare)
8. Uninsured: none of the above. People with Indian Health Service access only are uninsured.

The estimate reports five groups: Medicaid or CHIP (classes 1, 2 and 6), employer, Marketplace, other (classes 3 and 7), and uninsured.

Modeled enrollment comes first because costs follow it. Reported coverage is at the survey interview; modeled enrollment is for the year. The dataset has no reported-CHIP flag and the engine enrolls every CHIP-eligible child, so modeled CHIP is every income-eligible child with no reported coverage.

## Switching cases

| Case | Who enrolls |
|---|---|
| `floor` | Nobody by choice: only the forced moves above. |
| `newborns` | The floor, plus every child under 1. |
| `uninsured` | The floor, plus everyone under 26 with no coverage. |
| `marketplace` | As above, plus everyone under 26 with Marketplace coverage. |
| `employer_25` | As above, plus the under-26 members of a random quarter of households with employer coverage. |
| `employer_50` | As above, with half of those households. |
| `everyone` | Everyone under 26. |

From `floor` to `everyone`, leaving out `newborns`, each case contains the one before. The household draw is seeded and shared by a household's members.

The dataset stores a Medicaid take-up flag for every person. For someone not eligible today it is a leftover draw, unrelated to their coverage, so the estimate ignores it for people eligible only through the new group: they enroll only if the case says so. People eligible through an existing group keep their stored flag, and a case can add them.

The cases read two ways:

- **First year.** Only children born after the start date are enrolled automatically, so the year starts near `floor` plus `newborns`, and every further case is people opting in.
- **Steady state.** Once every child has been enrolled at birth and stays eligible to 26, everyone is enrolled unless they opt out, which the bill allows only with other coverage. `uninsured` is then the case in which everyone with private coverage has opted out, and `everyone` the case in which nobody has.

No case prices a child who is enrolled and keeps private coverage, with Medicaid paying second.

## Two prices for a Medicaid enrollee

**The engine's allocation.** `medicaid_cost_if_enrolled` spreads each state's total Medicaid spending across enrollees in proportion to an index: the benchmark Marketplace premium for the person's age and rating area. Age rating makes a child's index a large fraction of an adult's, and the total includes spending on aged and disabled enrollees and long-term care. A child therefore carries a share of costs that children do not incur.

Two adjustments apply:

- *Growth.* The engine holds its state totals flat after fiscal 2023. They are grown by the increase CMS projects in Medicaid spending per enrollee from calendar 2024 to 2029 (National Health Expenditure projections 2025-2034, Table 17). Calendar 2024 is the base because the engine pairs fiscal 2023 spending with enrollment calibrated to late 2024.
- *Price base.* A person's price is their state's grown total, times their index, divided by the state's index-weighted enrollment in the lookback run at the dataset's 2024 weights. That holds the price per enrollee at the level the totals were calibrated to. The engine's default divides by baseline enrollment in the simulation year, which would raise every price when the 2027 community engagement requirement shrinks enrollment.

In states that rate premiums by family tier, the index is a share of a family premium, so a person's price moves when relatives enroll.

**MACPAC group rates.** `medikids_group_rate` prices a person by age:

- *Under 19:* the state's child-group spending per enrollee from the engine's parameters, rescaled so that the national average equals MACPAC's fiscal 2023 child benefit spending per full-year-equivalent enrollee (MACStats February 2026, Exhibit 22). The engine's parameters divide fiscal 2022 spending by people ever enrolled, which understates the cost of a full year.
- *19 to 25:* MACPAC's fiscal 2023 national rate for the "other adult" group, the group the engine assigns to young adults. The national rate is used because the engine's state figures for this group have gaps.

Both rates grow from fiscal 2023 to 2029 at the average annual rate CBO projects for federal spending per enrollee in the matching category over fiscal 2025 to 2029 (February 2026 Medicaid baseline).

The group rates rest on what Medicaid spends on children. Neither price is the cost of the children who would switch: privately insured children are healthier on average than children in Medicaid today.

Separate-CHIP spending is the engine's fiscal 2024 state spending per enrollee, grown by CMS's projected CHIP spending per enrollee from 2024 to 2029.

## Federal and state shares

Under current law the engine gives enrollees in the ACA adult group the 90 percent rate and everyone else with a Medicaid category their state's regular rate, using fiscal 2026 rates for 2029. Version 2.2.2 also gives the regular rate to people who pass the immigration test only through a state-funded route. Federal law pays nothing for them, so the estimate sets their share to zero in the baseline, as later `policyengine-us` versions do. Under the bill, people under 26 draw the rates described above; people 26 and over are untouched.

The net federal figure adds the change in federal Medicaid cost, the federal share of CHIP spending replaced, premium tax credits, and federal Basic Health Program payments. The net state figure adds the change in state Medicaid cost and the state share of CHIP replaced. Other programs that read Medicaid enrollment (WIC, for one) are left out.

## Population

The engine ages the dataset by scaling every household weight with total population growth. The Census Bureau projects the population under 26 to fall, so the default would overstate it in 2029. Weights in the reporting year are rescaled by one factor for all households, so that the population under 26 equals the Census Bureau's July 2025 estimate carried to 2029 at the rate of change in its 2023 projections. The age mix within the under-26 population stays as in 2024.

## Checks

[`medikids_act/checks.py`](../medikids_act/checks.py) runs on the outputs of every national run and fails loudly:

- coverage classes partition the population under 26, and the population equals its target;
- federal plus state equals total, for every person and every case;
- in `floor` and `uninsured`, where no Marketplace enrollee switches, premium tax credits equal the baseline for every tax unit, and subsidized Marketplace enrollment for every person;
- in `floor`, Marketplace eligibility equals the baseline for every person, every new enrollee is a forced move or a community engagement exception, and Medicaid spending is the baseline plus those enrollees;
- no separate-CHIP or Basic Health Program enrollee under 26 is left uncovered in any case;
- enrollment is nested along the chain of cases, costs do not fall, and premium tax credits do not rise;
- anyone enrolled in both the baseline and a case costs the same in both (outside family-tier states);
- nothing changes for people 26 and over;
- the 100 percent rate reaches only people under 26 outside the 2025 plan, and the alternative readings bracket the primary one as their definitions imply.

The tests in [`tests/`](../tests) check the reform on single households against the bill text, and the cases and classification with property-based tests. [`medikids_act/benchmarks.py`](../medikids_act/benchmarks.py) lists the outside figures the baseline is compared with.

## Departures from the certified model

Beyond the bill itself, the estimate changes four things, in every run:

1. the federal share of state-funded coverage (zero);
2. growth in the Medicaid and CHIP calibration totals;
3. the price base for the engine's allocation;
4. the population under 26.

None changes anyone's eligibility, enrollment, premium tax credit or CHIP status under current law, and a test asserts that.

## Known limits

- **Take-up is frozen at 2024.** Coverage and take-up flags are replayed against 2029 rules.
- **The engine enrolls every eligible person in separate CHIP and the Basic Health Program.** Enrollment in both can exceed administrative counts, which enlarges the floor case. The benchmark comparison shows by how much.
- **Incomes outrun the poverty line.** Version 2.2.2 grows weighted incomes by national totals and weights by population, so incomes rise slightly too fast against the poverty line by 2029. Fewer people look eligible under current law, and more fall into the 100 percent group.
- **Marketplace premiums after 2026 are extrapolated**, and the premium tax credit schedule is the 2026 one.
- **Match rates are fiscal 2026 rates.**
- **Not modeled:** the cost of benefits the bill extends to 26, administrative costs, provider payment, state responses, births and aging over time, and the federal payment bar in SSA 1903(v)(5) for emergency services.
