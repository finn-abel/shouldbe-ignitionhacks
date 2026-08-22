// The call, in the product's own words.
//
// Shared by the analysis result and the ledger so the two never disagree about what a
// verdict is called — they each had their own copy of this map, which is exactly how one
// screen ends up saying "Worth the room" while the other says something else.
//
// The wording is deliberately a full sentence rather than a category. "Worth the room"
// was a label; "Should Be a meeting" is a verdict, and it reads as the answer to the
// question the user asked when they hit Analyze.

export const VERDICT = {
  email: { label: 'Should Be an email', tone: 'leak' },
  keep: { label: 'Should Be a meeting', tone: 'defend' },
};

/** Never returns undefined: an unrecognised verdict defends the meeting rather than flagging it. */
export const verdictOf = (key) => VERDICT[key] ?? VERDICT.keep;
