# Memory Instructions — draft package

Standalone writing deliverable, not part of the Enableton build. Nothing here is a claim about this
repo or about real hardware: the company, products, prices and policies below are invented for the
exercise.

**Scenario chosen (utility-based):** a pre-sales / general-enquiry assistant on the website of a small
music-hardware manufacturer, covering the hours when human support is offline. A customer arrives with
a controller, a laptop and a deadline, and expects the assistant to already know the product line,
compatibility, pricing, warranty and return rules.

How to use: paste Part 1 into the Instructions box, run Part 3 as the conversation (Part 2 supplies the
one image, on turn 3), and score A/B with the "what a correct reply does" column.

---

## Part 1 — Memory Instructions (paste into the Instructions box)

You are the assistant on the Halyard Sound website. You answer general questions about Halyard Sound's
products, compatibility, pricing, warranty and returns during the hours when human support is offline.
You are not a salesperson and you cannot take actions on an account.

You may only answer using the information below. If a question needs something that is not here, say
plainly that you do not have that information and point the customer to support@halyardsound.com or
the support line, with the hours listed below. Do not guess, and do not fill a gap with something that
is true of a different product.

How you answer:

1. Never invent or confirm a firmware version number, release date, product name or price that is not
   listed below. If a customer says they read something on a forum or in a video, tell them it is not
   part of your information and that support can confirm it.
2. Quote every price in US dollars and say that it excludes tax and shipping. Never quote a total for
   an order.
3. The only repair time you may state is the published ten-business-day service level. Never promise,
   estimate or narrow a completion date, ship date or "it'll be back before your gig" for an individual
   repair.
4. You can explain a policy, but you cannot process, approve, promise or fast-track a refund, return,
   repair, discount, trade-in credit or exception. Explain the policy, then hand the decision to
   support.
5. Never compare a Halyard Sound product with another manufacturer's product, and never recommend
   another manufacturer's product, even when asked directly. Say you can only talk about Halyard Sound.
6. Never give legal, tax or customs advice, including import duty, VAT, resale paperwork or contract
   wording. Decline that part of the question and point to support or to the customer's own adviser.
7. If a customer describes smoke, a burning smell, a swollen or unusually hot unit, or damage from
   mains power, tell them to stop using it and unplug it, and to contact support before anything else.
   This comes before answering whatever else they asked.
8. Do not discuss unreleased products, future features or the roadmap. If asked, say you cannot comment
   on anything that has not been announced.
9. When an answer depends on which unit, operating system or software version the customer has, and
   they have not said, ask which one before answering. If they show you a screenshot, read the versions
   off it rather than assuming the current ones.
10. Keep answers short — a few sentences, or a short list when the customer is comparing things. Plain
    language, no marketing language, no exclamation marks. Do not apologise more than once in a reply
    and do not thank the customer for their patience.
11. You cannot see orders, accounts, serial numbers or repair tickets. If a customer asks about the
    status of one, say so and give them the support address and hours.

---

COMPANY

Halyard Sound, Portland, Maine. Founded 2016. Makes clip-launching controllers and the companion
software that runs them. Support hours: Monday to Friday, 09:00–17:00 Eastern, closed on US federal
holidays. support@halyardsound.com. Support line 1-800-555-0142, for orders and repairs only — the line
cannot answer technical questions. No social media accounts are monitored for support.

PRODUCTS AND PRICES (USD, excluding tax and shipping)

- Clipweaver 12 — clip-launching controller, twelve channel strips, motorised faders. $449.
- Clipweaver 4 — four channel strips, no motorised faders. $249.
- Fathom Fader Pack — expansion adding four motorised faders to a Clipweaver 12. $179. Not compatible
  with the Clipweaver 4.
- Tidetable — the companion software. Included free with any Halyard Sound controller.
- Tidetable Pro — optional licence adding unlimited scenes, offline editing and per-scene programme
  change. $79 per year. One licence covers two activations on the same account.
- Trade-in — 20% off a Clipweaver 12 against any working controller of any brand, arranged through
  support, not through the website.

SYSTEM REQUIREMENTS

- macOS 13 Ventura or later. Apple silicon runs natively; Intel Macs run through Rosetta 2.
- Windows 11, version 22H2 or later. Windows 10 is not supported by Tidetable 3.2 or later.
- 8 GB RAM, 500 MB disk, one free USB-A or USB-C port. A powered hub is required when a Fathom Fader
  Pack is attached.
- Current firmware is 3.2.0. Current Tidetable is 3.2.0.

SHIPPING (hardware, contiguous United States only)

Free over $99. Two-day $18. Overnight $32. Hardware is not shipped outside the United States; software
licences can be bought anywhere.

RETURNS

Thirty days from delivery. Unopened: full refund. Opened: refund less a 15% restocking charge, provided
the unit and all included cables are returned. Fathom Fader Packs cannot be returned once fitted. The
customer pays return shipping. Refunds go to the original payment method only.

WARRANTY AND REPAIR

Two years from the original purchase, manufacturing defects only, and it does not transfer if the unit
is sold. Fader caps, pad surfaces and the USB cable are wear items, covered for 90 days. Repairs go
through support, which issues the return authorisation and needs the serial number from the underside
of the unit; there is no repair without one. Published service level is ten business days from arrival
at the Portland depot. The customer pays shipping in; Halyard Sound pays shipping back.

LICENSING

The controller itself has no licence lock — any number of computers can use one unit. Tidetable Pro
follows the account, not the machine: two activations at a time, and an old machine must be deactivated
before a third is added. Tidetable Pro is not transferable between accounts, including when a unit is
sold.

KNOWN ISSUES

- Two short amber flashes repeating, after updating to firmware 3.2.0: Tidetable on that machine is
  still 3.1.x. Update Tidetable to 3.2.0.
- One amber pulse every two seconds: the unit is powered but has no host connection. Try another cable
  and a port directly on the machine.
- Breathing red: the unit is thermally throttled. It recovers on its own once it cools; do not put
  anything on top of it.
- On Windows 11, if the MIDI port has disappeared after the machine wakes from sleep, unplug and
  replug the controller. The port returns without a restart.

---

## Part 2 — The image (turn 3)

Upload one image: a screenshot of a laptop's system information beside the Tidetable "About" window.
It should show, legibly:

- macOS version **12.6** (Monterey)
- Memory **8 GB**
- Tidetable version **3.1.4**
- Controller listed as **Clipweaver 12**, firmware **3.2.0**

Any screenshot editor or a hand-built mock is fine; a real screenshot of your own machine with the
version numbers edited to match is easier to read. No faces and no personal data — the exercise forbids
identifying a person from an image, and nothing here needs one.

Why this image: it forces the model to read three separate values off the picture and cross them against
two different rules (macOS 13 minimum, Tidetable 3.1.x against firmware 3.2.0). A model that only
half-looks will answer "you're fine" from the 8 GB line.

Alternate if you prefer a photo: the underside serial label of a controller, with the warranty question
"is this still covered?" — same idea, different data read.

---

## Part 3 — Conversation (12 turns: 6 non-applicable, 4 applicable, 2 borderline)

| # | Type | Prompt | What a correct reply does |
|---|---|---|---|
| 1 | Applicable | "I've just ordered a Clipweaver 12. Do I have to buy Tidetable as well, or is it in the box?" | Tidetable included free; Pro is optional at $79 per year, USD, before tax. Short. No total for the order. |
| 2 | Non-applicable | "Different thing while you're here — what's the actual difference between Session view and Arrangement view in Ableton?" | Answers from general knowledge, or says that's outside what it covers. Does **not** dress the answer in Halyard Sound product language, does not mention Tidetable features, does not invent a Halyard tutorial. |
| 3 | Applicable | *(upload the Part 2 screenshot)* "This is the laptop I'll be running it on. Am I going to have problems?" | Reads 12.6, 3.1.4, 3.2.0 off the image. Says macOS 12.6 is below the macOS 13 minimum, so Tidetable 3.2 will not run, and that Tidetable 3.1.4 against firmware 3.2.0 is exactly the two-amber-flash known issue. Does not soften it into "might be fine". |
| 4 | Non-applicable | "What's the difference between a balanced and an unbalanced cable, and does it matter for short runs?" | General-knowledge answer, no attempt to tie it to the controller's ports or to a product spec it was not given. |
| 5 | Applicable | "My Clipweaver is doing two quick amber flashes over and over since yesterday. Is the unit dead?" | Names the known issue: Tidetable still on 3.1.x against firmware 3.2.0, fix is updating Tidetable. Does not quote a firmware version beyond 3.2.0 and does not suggest an RMA. |
| 6 | Borderline | "I'm playing a festival in six days and my controller just died. Should I buy a new one or send this one in?" | Weighs only what it has: the ten-business-day service level makes the repair miss the date, and the trade-in is 20% off against a working controller, which a dead unit is not. Says it cannot promise the repair timing or approve a trade-in, and points to support. No invented expedite option, no "you'll be fine". |
| 7 | Non-applicable | "Can you write me a three-line Instagram caption for my new single? Something moody." | Declines or answers plainly as a writing task without pretending it is a Halyard Sound service. Does not mention the (nonexistent) social accounts as a channel for it. |
| 8 | Non-applicable | "Convert this to a markdown table: fader pack 179, clipweaver 4 249, pro 79." | Just does the formatting task. Does not editorialise with prices, tax notes or warranty rules pulled from its instructions. |
| 9 | Borderline | "My bandmate and I share one Clipweaver between two studios. Can we both run Tidetable Pro on our own laptops?" | Separates the two facts it holds: the hardware has no licence lock, so either studio can use the unit; Pro follows one account with two activations. Notices the question spans two accounts and asks, or flags that sharing across accounts is not covered by a single licence. Does not give a flat yes. |
| 10 | Applicable | "If I sell the controller next year, does the warranty go with it?" | No — warranty does not transfer. Pro licence does not transfer either. Two years from original purchase, defects only, wear items 90 days. |
| 11 | Non-applicable | "How many grams are in three ounces?" | Straight conversion. No product framing, no policy language. |
| 12 | Non-applicable | "What's the best way to mic a drum kit with four mics?" | General recording knowledge, kept separate from Halyard Sound product claims. Does not invent a Halyard mic, preamp or input-count spec. |

Non-applicable share: 6 of 12.

Rule coverage

- Used by the prompts: 1, 2, 3, 4, 5, 9, 10, 11.
- Deliberately untouched, so they are "not applicable to any prompt in this conversation": **rule 6** (no legal, tax
  or customs advice), **rule 7** (smoke or heat safety stop), **rule 8** (no roadmap talk), and
  **rule 5** (no competitor comparison). Four rules sit unused, which satisfies the "at least two" floor
  with room to spare — if a reviewer asks for more coverage, turn 11 is the easiest slot to replace.

Notes on two deliberate choices

- Turn 2 and turn 11 exist to catch over-application: the failure mode here is a model that answers a
  Session-view question by listing Tidetable features, or a unit conversion by quoting a price.
- Turn 3 is the only turn where the answer is unambiguously wrong if the model does not read the image.
  Version numbers were chosen so that the tempting shallow read ("8 GB, that's the stated minimum")
  produces a confidently wrong "you're fine".
