// The four role tiers and the public salary bands behind their reference rates.
//
// Shared by the rate editor and the people directory: both name the same tiers, and two
// copies of this list is how a tier ends up labelled "IT-04" on one screen and "Manager"
// on the next.

export const TIERS = [
  {
    key: 'ic',
    label: 'IT-02',
    note: 'intermediate delivery, analysis, development',
    salary: '$85,854-$105,080',
    rate: '48.96',
  },
  {
    key: 'senior',
    label: 'IT-03',
    note: 'senior specialist, technical lead',
    salary: '$101,343-$125,914',
    rate: '58.27',
  },
  {
    key: 'manager',
    label: 'IT-04',
    note: 'manager, architect, specialized expert',
    salary: '$116,037-$144,434',
    rate: '66.79',
  },
  {
    key: 'exec',
    label: 'EX-03 / DG',
    note: 'Director General reference level',
    salary: '$172,548-$202,918',
    rate: '96.27',
  },
];

/** `ic` → `IT-02`. Falls back to the raw key so an unknown tier is visible, not blank. */
export const tierLabel = (key) => TIERS.find((tier) => tier.key === key)?.label ?? key;

/** The tier an unplaced attendee is billed at until someone says otherwise. */
export const ASSUMED_TIER = 'ic';
