# Draft: Building an Explainable FPL Decision Engine

## Working title options

1. From FPL Helper to Decision Engine
2. What I Shipped Next in My FPL Assistant
3. Making FPL Recommendations More Explainable, Practical, and Agent-Ready

## Subtitle options

- Over the last few weeks, I upgraded my FPL Assistant backend from basic recommendations into a system that can score, plan, explain, and evaluate decisions.
- The last stretch of work turned my FPL project into something more serious: better projections, smarter transfer logic, clearer strategy output, and a path toward agentic workflows.

## Draft

When I shared my first article, the project was still closer to a smart FPL helper than a real decision engine.

Over the past few weeks, that changed.

Between March 11 and March 25, 2026, I pushed a new set of backend improvements to my FPL Assistant that made it significantly more useful in practice. The biggest shift is that the system no longer just surfaces interesting players or basic lineup output. It now combines projections, transfer planning, chip scenarios, strategy recommendations, and evaluation into a more complete decision loop.

That matters because FPL is not really a ranking problem. It is a sequencing problem under uncertainty. The best move is not always the player with the highest projected score. It is the move that fits budget constraints, squad structure, captaincy upside, risk, and the gameweeks ahead.

This new iteration is my attempt to build for that reality.

### 1. Better projections, not just raw FPL signals

One of the first improvements I made on March 11 was to strengthen the projection layer.

Instead of leaning too heavily on a single signal, the model now blends points per game and form, and adjusts projections with more contextual logic:

- fixture difficulty
- home vs away context
- opponent recent form
- the player team recent form
- immediate playing probability

That means projected points are now more grounded in actual gameweek context rather than being treated as static player quality.

I also added an evaluation endpoint so the system can compare projected xPts against actual historical outcomes. This was an important step for me because I do not want the project to become a black box that only feels smart. I want to measure whether the logic is directionally useful.

### 2. Transfers became a planning problem

The biggest leap came on March 20, when I reworked the recommender into something much closer to a transfer planner.

The transfer score is no longer just a shallow mix of form and points per game. It now includes:

- consistency signals from total points and minutes
- transfer momentum
- set-piece certainty
- position-based attacking bias
- availability and injury awareness
- seller and buyer guardrails

This matters because good FPL transfers are rarely only about upside. They are also about reliability, role, and timing.

I also introduced beam-search transfer planning. That gave the system the ability to explore sequences of moves instead of treating each transfer in isolation.

In practice, that means the assistant can now ask a more useful question:

“If I make this move now, what does it unlock next?”

That is much closer to how experienced managers actually think.

### 3. Captaincy and chip logic became more realistic

I also refined the captain selection and strategy layer.

Captaincy now includes more ceiling-oriented logic, especially for premium mids and forwards, while also accounting for signals like form and set-piece responsibility. That is a subtle but important change because captain decisions should not be purely conservative. In FPL, ceiling matters.

On top of that, the API now produces a higher-level strategy recommendation:

- roll
- make transfers
- use a chip

The recommendation is backed by thresholds such as projected gain per transfer, bench strength, and captain upside. So instead of just returning data, the backend is starting to return a point of view.

That was a key design goal for me. I want this system to move from “here are some numbers” to “here is the action I would seriously consider, and why.”

### 4. The backend became easier to operate

Another part of this work was operational maturity.

I added:

- timing instrumentation for recommendation requests
- logger output in the main API flow
- an admin refresh endpoint for cache invalidation and next-gameweek snapshot generation
- clearer backend documentation and config reference

This is less flashy than the recommender work, but it is what makes the project sustainable. Once a project starts producing richer outputs, observability and repeatability stop being optional.

### 5. What changed conceptually

The most important change is not any single endpoint or scoring tweak.

The real shift is architectural.

The backend is now closer to a system with four layers:

1. A projection layer that estimates expected points.
2. An optimization layer that picks lineups and chip drafts.
3. A recommendation layer that plans transfers under constraints.
4. A strategy layer that converts output into a clearer action.

That stack feels much more like the foundation for an assistant rather than a calculator.

And that naturally leads to the next stage I am thinking about.

## What I want to build next: agentic workflows

I think the most exciting next step is not just improving the scoring again. It is adding agents on top of the system.

Right now, the backend can generate structured recommendations. The next evolution is to let specialized agents collaborate around those recommendations.

Here is the direction I am considering:

### Agent 1: The Analyst

This agent would read projections, transfer plans, chip outputs, and evaluation metrics, then produce a concise explanation of what is changing and why it matters.

Its role would be interpretation.

### Agent 2: The Challenger

This agent would deliberately stress-test the recommendation.

For example:

- Is the transfer plan too aggressive?
- Is the model over-weighting short-term form?
- Is captain upside being confused with noise?
- Would a more conservative path preserve flexibility better?

Its role would be skepticism.

### Agent 3: The Planner

This agent would turn the best recommendation into a small multi-week plan:

- preferred move now
- fallback move if budget changes
- chip path
- hold/sell watchlist

Its role would be sequencing.

### Agent 4: The Communicator

This agent would transform the backend output into human-facing content:

- a short recommendation summary
- a manager-style explanation
- a newsletter block
- a social post

Its role would be delivery.

If I build this well, the product stops being a single-response tool and becomes a small decision-making workflow.

That is the part I find most interesting now.

## Near-term roadmap

My likely next steps are:

1. Benchmark the current projection and transfer logic on a larger historical sample.
2. Save recommendation snapshots so I can compare predicted decisions with what actually happened later.
3. Add explanation traces for why a player is recommended or rejected.
4. Prototype a simple analyst-plus-challenger multi-agent flow before building a larger agent system.
5. Connect the backend more tightly to a frontend experience that feels conversational instead of purely endpoint-driven.

## Closing

What I like most about this phase of the project is that it feels like a transition from features to systems.

I am still using heuristics in a lot of places, and there is plenty left to improve. But the project is now much closer to the kind of assistant I originally had in mind: something that can project, optimize, recommend, explain, and eventually collaborate.

That is a much stronger base for the next chapter.

If you are building in sports analytics, decision support, or agentic products, I would love to compare notes. I think a lot of the interesting work now sits in the layer between raw scoring and usable action.

## Shorter version for a more direct Substack post

Over the last two weeks, I upgraded my FPL Assistant backend from a recommendation tool into a more complete decision engine.

The biggest changes were:

- stronger xPts projections with fixture and team-context adjustments
- a smarter transfer recommender that now accounts for consistency, availability, set-piece certainty, and multi-move planning
- better captaincy and chip logic
- an evaluation endpoint to compare predicted xPts against actual outcomes
- more operational maturity through logging, refresh flows, and improved documentation

The next thing I want to explore is an agent layer on top of this system.

Instead of one backend response, I am imagining a small team of specialized agents: one that analyzes recommendations, one that challenges them, one that builds a multi-week plan, and one that turns the output into human-facing advice.

That feels like the natural evolution of the project: from model outputs to collaborative decision support.

## Suggested headline + opening hook

### Headline

Making My FPL Assistant More Explainable, Practical, and Agent-Ready

### Opening hook

The latest version of my FPL Assistant is less about predicting the “best player” and more about handling the real shape of FPL decisions: uncertainty, trade-offs, timing, and sequencing. Over the last few weeks, I upgraded the backend so it can project, plan transfers, suggest chip strategy, explain decisions more clearly, and start moving toward agentic workflows.
