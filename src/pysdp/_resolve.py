"""Time-slice resolvers for Single / Yearly / Monthly / Daily datasets.

Behavior-preserving port of rSDP's `R/internal_resolve.R`. Implementation
lands in Phase 2.

Note: the anchor-day `seq(by="month"/"year")` semantics in the Yearly and
Monthly date-range branches are load-bearing — reproduce them in Python
using `pd.date_range(start=first_overlap_day, ...)` rather than calendar
boundaries. See SPEC.md §5 "Behavior carry-overs" and the header comment
in `~/code/rSDP/R/internal_resolve.R`.
"""

from __future__ import annotations
