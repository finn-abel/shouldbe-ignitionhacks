// The API sends money as exact decimal strings ("375.00") rather than floats, so every
// figure is parsed at the point it is displayed and nowhere else.

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const usdCents = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
});

/** Whole dollars — for headline figures, where cents are noise. */
export function formatMoney(value) {
  if (value === null || value === undefined) return '—';
  return usd.format(Number(value));
}

/** Dollars and cents — for anything that has to reconcile. */
export function formatMoneyExact(value) {
  if (value === null || value === undefined) return '—';
  return usdCents.format(Number(value));
}

/**
 * Whether a money field holds an amount worth showing.
 *
 * Money crosses the wire as an exact decimal *string*, and `"0.00"` is truthy in
 * JavaScript — so `value && ...` renders "$0/yr" for a meeting that has no annual cost.
 */
export function hasAmount(value) {
  return value !== null && value !== undefined && Number(value) > 0;
}
