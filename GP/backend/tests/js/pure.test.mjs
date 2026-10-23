// The GP Fund page's pure helpers (frontend review, 9 Oct 2026).
//
//   node --test GP/backend/tests/js
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  escapeHtml, encodeId, formatRupees, formatNumber, throttle, pollBudget, sequence,
  itemHeading,
} from '../../web/js/pure.js';

test('F13: every value put into HTML is escaped, quotes included', () => {
  assert.equal(escapeHtml(`<img src=x onerror="alert('1')">`), '&lt;img src=x onerror=&quot;alert(&#39;1&#39;)&quot;&gt;');
  assert.equal(escapeHtml('a & b'), 'a &amp; b');
  assert.equal(escapeHtml(null), '');
  assert.equal(escapeHtml(0), '0');
});

test('F13: ids in paths are percent-encoded', () => {
  assert.equal(encodeId('refundable-abc12345'), 'refundable-abc12345');
  assert.equal(encodeId('../other/dispose'), '..%2Fother%2Fdispose');
  assert.equal(encodeId('a b?c#d'), 'a%20b%3Fc%23d');
  assert.equal(encodeId(null), '');
});

test('F17: rupees in the office grouping', () => {
  assert.equal(formatRupees(1234567), 'Rs 1,234,567');
  assert.equal(formatRupees('255534.00'), 'Rs 255,534');
  assert.equal(formatRupees(1234.5), 'Rs 1,234.5');
  assert.equal(formatRupees(null), '');
  assert.equal(formatRupees('n/a'), 'n/a');
  assert.equal(formatNumber(1234567), '1,234,567');
});

test('F9: the activity signal is throttled to one per window', () => {
  let t = 0;
  const calls = [];
  const ping = throttle(x => calls.push(x), 10_000, () => t);
  assert.equal(ping('a'), true);
  t = 5_000; assert.equal(ping('b'), false);
  t = 9_999; assert.equal(ping('c'), false);
  t = 10_000; assert.equal(ping('d'), true);
  assert.deepEqual(calls, ['a', 'd']);
});

test('F13: the poll loop tolerates a few failures, then gives up; a success resets; the cap holds', () => {
  const b = pollBudget({ maxFailures: 3, maxPolls: 5 });
  assert.equal(b.failed(), false); assert.equal(b.failed(), false); assert.equal(b.failed(), false);
  assert.equal(b.failed(), true);                                           // the fourth in a row
  b.ok(); assert.equal(b.failures, 0);
  assert.equal(b.failed(), false);
  for (let i = 0; i < 5; i++) assert.equal(b.tick(), false);
  assert.equal(b.tick(), true);
});

test('F13: a slower earlier render is stale once a newer one has started', () => {
  const s = sequence();
  const first = s.next();
  assert.equal(s.isStale(first), false);
  const second = s.next();
  assert.equal(s.isStale(first), true);
  assert.equal(s.isStale(second), false);
});

test('F17: a result row names its document and signatory under the check title', () => {
  assert.deepEqual(itemHeading({ title: 'Signatories and delegation of authority', doc: 'Sanctioning authority, Form A (page 3)' }),
                   { title: 'Signatories and delegation of authority', sub: 'Sanctioning authority, Form A (page 3)' });
  assert.deepEqual(itemHeading({ doc: 'Form A (page 1)', id: 'X' }), { title: 'Form A (page 1)', sub: '' });
  assert.deepEqual(itemHeading({ title: 'Same', doc: 'Same' }), { title: 'Same', sub: '' });
  assert.deepEqual(itemHeading({ id: 'R1' }), { title: 'R1', sub: '' });
});
