# The denominator trap: 5% packet loss made the headline metric go *up*

**Scenario:** `marketplace` · **Changed setting:** `failures.message_drop: 0.0 → 0.05` · **Nothing else touched**

---

## Part A — Running the baseline

`nest run marketplace` unchanged: 100 agents (50 buyers, 50 sellers), seed 42, 10 rounds.
2,200 events in about two seconds. Buyers send `buy:product-N:price`; sellers reply
`sold:` or `reject:`. All three shipped marketplace validators pass.

Baseline: **500 buy requests, 266 deals, `deal_rate` 0.532, `delivery_rate` 1.000.**

## Part B — The experiment

### Why I chose `message_drop`

I chose it **because it is the quickstart's own worked example**:

> "Try changing `failures.message_drop` from `0.0` to `0.05` and re-running to see how a
> 5% drop rate affects `delivery_rate` and `deal_rate` in the report."

That makes it the most-trodden path into this system. I picked it deliberately rather
than hunting for an exotic dial: I was more interested in whether the obvious experiment
had been read correctly than in finding an unusual one.

### My prediction, written before running

I reasoned about it as a marketplace operator rather than a protocol engineer:

> There is no abandonment metric here — nothing that notices a stalled buyer and
> triggers a retry, an alert, or a re-engagement. So a buyer who never hears back never
> comes back.
>
> 1. **Agents stall.** They're set up to run one order, with no concept of abandonment.
> 2. **Buy requests decrease**, because of the calls that vanished.
> 3. **`deal_rate` decreases**, because some buyers never reach the happy path of a buy
>    request that ends in a sold item.

Points 1 and 2 were right. Point 3 was wrong — and the way it was wrong is the finding.

### What actually happened

```
                                  baseline   drop=0.05      change
------------------------------------------------------------------
Buy requests sent                      500         304      -39.2%
Deals closed                           266         174      -34.6%
deal_rate (headline metric)          0.532       0.572       +7.6%
delivery_rate                        1.000       0.941       -5.9%
Buyers with zero deals                   0           9          +9
Sellers with zero deals                  1           2      +100.0%
Gini across buyers                   0.220       0.426      +93.7%
Gini across sellers                  0.185       0.275      +48.9%
```

**Total message traffic fell 42% (2,000 → 1,151) and `deal_rate` went up.**

An operator watching the shipped report would have seen `delivery_rate` dip to 94% — a
rounding error, easily dismissed as noise — alongside conversion at its best all week.

## Investigation

### Why my own prediction contained the answer

`deal_rate` is `deals ÷ buy_requests`. My second point said the denominator would fall.
My third point then ignored it: I held 500 fixed in my head and asked only "how many
deals do I lose?" With the bottom number pinned, fewer deals *must* mean a lower rate.

But 500 wasn't pinned. Deals fell 35%; requests fell 39%. **The denominator fell faster
than the numerator**, so the ratio rose.

The mechanism is the one I'd already described. The failure was injected on the response
path, and it propagated *backwards into demand*: a buyer whose reply is dropped stalls
waiting for an answer that never arrives, and never issues its next request. One lost
message doesn't cost a transaction — it removes a participant.

`deal_rate` measures **conversion**. The damage was to **participation**. A ratio cannot
count the customers who never walked in.

### Is it seed 42?

No. Across eight seeds, `deal_rate` rose in **8 of 8**, with buy volume falling 27–39%
every time.

```
 seed  deal_rate  deal_rate    buys    buys  starved
          (base)     (drop)  (base)  (drop)   (drop)
----------------------------------------------------
   42      0.532      0.572     500     304        9
   43      0.532      0.572     500     362        1
   44      0.514      0.545     500     352        6
   45      0.530      0.563     500     348        6
   46      0.552      0.567     500     344        9
   47      0.528      0.589     500     336        4
   48      0.546      0.557     500     336        6
   49      0.548      0.588     500     325        6

deal_rate rose in 8/8 seeds
```

### What the validators caught — and what they didn't

| Validator | baseline | drop=0.05 |
|---|---|---|
| `marketplace_no_double_sell` | PASS | PASS |
| `marketplace_all_responded` | PASS | **FAIL** |
| `marketplace_price_agreement` | PASS | PASS |

The rig is **not** blind. `marketplace_all_responded` correctly flags that some requests
went unanswered.

But note what that failure reports and what it doesn't. It says *some messages went
missing* — which I already knew, because I injected it. It does not say demand collapsed
39%, and it does not say **nine of fifty buyers completed zero transactions** while the
headline metric improved. The validator catches the injury I caused. Nothing catches the
injury that followed from it.

### Nothing here measures distribution

Every metric in `nest_core/metrics.py` — `delivery_rate`, `deal_rate`, `rejection_rate`,
`mean_latency`, `message_count`, `throughput` — is an average or a total. Grepping the
codebase for `gini`, `fairness`, `starvation`, `concentration`, `inequality` returns
nothing.

That is why `analyze.py` computes Gini and starvation counts. At 5% drop, buyer Gini
nearly doubles (0.220 → 0.426) and 18% of buyers are shut out entirely. Averages survive;
specific agents don't.

The project has been bitten by a neighbouring version of this. The docstring on
`_delivery_rate` reads:

> "This was previously named `_success_rate`. The old name was misleading — a 100%
> delivery rate does NOT mean the protocol succeeded."

They caught that failure of interpretation once and renamed the metric. The same trap is
still sitting in `deal_rate`.

### A side finding: `catalog_size` does nothing

While isolating variables I tested `task.config.catalog_size`, documented in the scenario
guide as part of the marketplace task config. At 5, 200, and 2000:

```
catalog_size=5     distinct_products=10  buys=500  deals=266
catalog_size=200   distinct_products=10  buys=500  deals=266
catalog_size=2000  distinct_products=10  buys=500  deals=266
```

Identical. Product variety is driven entirely by `rounds` — agents cycle `product-0` …
`product-9`, one per round — and the catalogue is never consulted.

I report it for what it changed about my method, not as a bug. It is why I stopped
trusting any setting until I had diffed two traces, and it is the reason the drop-rate
result got eight seeds instead of one. Having already been fooled by a knob that did
nothing, I was not willing to believe the first surprising number I saw.

## What I learned

1. **A ratio can improve while the thing it describes collapses.** Report the denominator
   next to the ratio, always.
2. **Failures propagate backwards into participation.** Loss injected on the response path
   destroyed demand. In an agent economy a dropped message costs you a participant, not a
   transaction.
3. **Passing validators and healthy averages are not a healthy system.** Both were broadly
   true here while 18% of buyers got nothing.
4. **Aggregate-only instrumentation cannot answer "who got left behind."** For protocol
   correctness that may be acceptable. For agent economies it isn't.

**What I'd do next:** all of this is Tier 1 — deterministic state machines. The open
question is whether Tier 2 LLM-backed agents behave the same way. A state machine stalls
silently when its reply is dropped; an LLM agent might retry, escalate, or route around.
If those differ, Tier 1 results are a weaker guarantee than they appear, and that gap
seems worth measuring.

---

## Reproducing this

From the repository root:

```bash
uv sync

uv run nest run marketplace -o ./traces/marketplace.jsonl
uv run nest run examples/message-drop-denominator/marketplace_drop05.yaml \
  -o ./traces/marketplace_drop05.jsonl

uv run python examples/message-drop-denominator/analyze.py \
  traces/marketplace.jsonl traces/marketplace_drop05.jsonl

uv run python examples/message-drop-denominator/seed_sweep.py 42 43 44 45 46 47 48 49
```

| File | What it is |
|---|---|
| `marketplace_drop05.yaml` | `scenarios/marketplace.yaml` with one setting changed |
| `analyze.py` | Volume and distribution figures for two traces (stdlib only) |
| `seed_sweep.py` | Repeats the paired run across seeds |

No changes to `nest_core` or to any plugin.

## Use of AI and other help

I used **Claude (Opus 5)** throughout, and it did most of the mechanical work.

- **Orientation.** I had it read the repo, the scenario guide and the layer docs and
  explain the architecture to me — I don't come from a distributed-systems background. It
  also surveyed the existing PRs so I could avoid re-treading covered ground.
- **Code.** It wrote `analyze.py` and `seed_sweep.py`. I specified what to measure and
  why; it implemented.
- **Environment.** It diagnosed the Python 3.12 requirement and pointed me at `uv`, which
  saved me an hour of version wrangling.
- **Mine.** The choice of setting and the reasoning behind it; the prediction, including
  the abandonment framing that turned out to be the correct mechanism; the decision to
  measure distribution rather than aggregates alone; the call to check eight seeds before
  believing anything; and the interpretation.

Two places I pushed back on the AI. It proposed adding new metrics and a validator
directly into `nest_core`, which I cut as overbuilding for this exercise. And our working
assumption had been that every shipped validator would still pass under drop — a tidier
story. Running them showed `marketplace_all_responded` fails, so the weaker and accurate
claim is the one above.
