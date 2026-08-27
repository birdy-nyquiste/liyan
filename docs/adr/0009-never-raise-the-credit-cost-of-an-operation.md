# A rate change may lower the 额度 cost of an operation, never raise it

The rate card converts 立言阁's measured cost into 额度, and it will change:
providers reprice, models are swapped, the worker's queue split will make worker
seconds cheaper. Changes may only ever move an operation's 额度 cost **down**.
If costs rise, the 额度包 price moves for new purchases instead.

额度 already bought are a promise about how much work they will do. Raising the
额度 cost of a 知言 run breaks that promise for everyone holding a balance, with
no event they could see and no notice they could act on — the same money buys
less, quietly. The honest alternatives are to grandfather balances by FIFO lots
stamped with a rate version, which is real machinery for a case that a ratchet
avoids entirely, or to accept the silent revaluation, which we are not willing
to do.

The ratchet also runs with the grain of the economics rather than against them:
provider prices have fallen consistently, and the queue split is a cost
reduction we are choosing to make. A rule that is easy to keep is one that will
actually be kept.

## Consequences

- A cost increase is absorbed by margin until the next 额度包 repricing, so
  margin needs enough headroom to sit out a provider's price rise.
- Falling costs reach existing holders automatically: their balance buys more
  without anyone deciding it should.
