# Pipeline performance baseline — 7 Oct 2026 (perf/pipeline, commit 87542c0)

Measured by `tools/bench.py --label baseline` on the trial box (GB10, unified memory; vision and OCR servers at --max-num-seqs 16) with no trial run active. Findings per case are in `artifacts/bench/baseline/<case>.json` (not tracked); every later optimisation is held to them with `tools/bench_compare.py`.

```
# baseline  (87542c0)

case    state     wall s gpu% mean gpu% max RAM peak GB  RSS MB  flags  verdict
gpf     done       110.0      89.7     96.0      116.52   200.5  1      False
large   done      1461.9      93.8     96.0      117.46   185.0  10     RETURN_FOR_CORRECTION
medium  done       655.1      89.3     96.0      117.01   183.0  4      RETURN_FOR_CORRECTION
small   done       439.2      92.0     96.0      116.46   177.1  1      HOLD

## Time by stage (sum over cases, sorted)
stage         total s  share        gpf    large   medium    small
assertions     1601.9    59%        0.0    970.2    370.5    261.2
extract         561.9    21%       46.0    291.6    121.2    103.2
identify        181.1     7%        0.0     90.8     72.6     17.8
reading         109.5     4%      109.5      0.0      0.0      0.0
assemble         79.2     3%        0.0     25.5     32.0     21.7
verify           76.2     3%        0.0     48.5     11.7     16.0
ingest           58.3     2%        0.0     14.0     34.3     10.1
signatures       17.0     1%        0.0      3.6      5.0      8.4
determine        16.4     1%        0.0     10.9      5.5      0.0
report            9.8     0%        0.0      6.8      2.4      0.7
classify          1.1     0%        1.1      0.0      0.0      0.0
barcodes          0.0     0%        0.0      0.0      0.0      0.0

## Model calls (sum over cases)
role                   calls round trip s  mean s  max s pool wait s errors prompt tok compl tok
vision                   184       3931.4    21.4   84.9     23979.2      0     559735    130595
ocr                       49        373.7     7.6   42.1         0.0      0      58884     56931
qwen3-vl-30b-a3b-fp8      25        106.1     4.2   40.6         0.0      0      66498      4467
paddleocr-vl-1.6           1          2.7     2.7    2.7         0.0      0       1299       467

## By schema
vision:GENERIC_PAGE                         44 calls    1472.2 s  mean 33.5 s
vision:AG_PAY_CERTIFICATE                   15 calls     729.1 s  mean 48.6 s
vision:PAGE_IDENTITY                        85 calls     706.4 s  mean 8.3 s
vision:FORM_D_I                             10 calls     417.8 s  mean 41.8 s
ocr:ocr                                     49 calls     373.7 s  mean 7.6 s
vision:FORM_D_II                             6 calls     296.0 s  mean 49.3 s
vision:NADRA_FRC                             6 calls     126.9 s  mean 21.2 s
vision:DESCRIPTIVE_ROLL                      6 calls      87.6 s  mean 14.6 s
vision:CNIC_CARD                             6 calls      54.9 s  mean 9.2 s
qwen3-vl-30b-a3b-fp8:extract                11 calls      47.3 s  mean 4.3 s
qwen3-vl-30b-a3b-fp8:recalc                  1 calls      40.6 s  mean 40.6 s
vision:PPO                                   2 calls      24.4 s  mean 12.2 s
qwen3-vl-30b-a3b-fp8:classify               13 calls      18.2 s  mean 1.4 s
vision:PSA_SIGNATURE_BLOCK                   4 calls      16.1 s  mean 4.0 s
paddleocr-vl-1.6:?                           1 calls       2.7 s  mean 2.7 s

## Pages read by the vision model more than once (pension cases; the H1 double read counts as 2)
large: pages read >2 times: {6: 3, 7: 5, 8: 3, 10: 3, 11: 3, 12: 3, 13: 3, 14: 3, 17: 3, 18: 3, 23: 3, 24: 3, 25: 3, 26: 3, 28: 3, 29: 4, 30: 3, 31: 3, 34: 3, 38: 3, 40: 3, 41: 8, 42: 5}; total vision calls 100 over 43 pages
   same schema repeated: [(41, 'FORM_D_I', 6), (42, 'AG_PAY_CERTIFICATE', 4), (7, 'AG_PAY_CERTIFICATE', 4), (29, 'AG_PAY_CERTIFICATE', 3), (35, 'PAGE_IDENTITY', 2), (6, 'GENERIC_PAGE', 2), (13, 'GENERIC_PAGE', 2), (40, 'GENERIC_PAGE', 2)]
medium: pages read >2 times: {1: 3, 2: 6, 4: 3, 5: 3, 8: 5, 13: 3, 14: 3, 15: 3, 16: 3, 17: 3}; total vision calls 54 over 29 pages
   same schema repeated: [(2, 'FORM_D_I', 4), (8, 'AG_PAY_CERTIFICATE', 4), (1, 'GENERIC_PAGE', 2), (16, 'GENERIC_PAGE', 2), (17, 'GENERIC_PAGE', 2), (13, 'GENERIC_PAGE', 2), (14, 'GENERIC_PAGE', 2), (4, 'CNIC_CARD', 2)]
small: pages read >2 times: {1: 4, 2: 3, 4: 6, 5: 3, 6: 3, 7: 3, 11: 3}; total vision calls 30 over 12 pages
   same schema repeated: [(4, 'FORM_D_II', 4), (11, 'PPO', 2), (1, 'FORM_D_II', 2), (2, 'CNIC_CARD', 2), (7, 'GENERIC_PAGE', 2), (5, 'DESCRIPTIVE_ROLL', 2), (6, 'NADRA_FRC', 2)]
```
