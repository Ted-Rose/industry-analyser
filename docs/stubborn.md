05:52:43 INFO Portal 2 (type=nextjs) — detail enrichment enabled
/opt/projects/industry-analyser/venv/lib/python3.10/site-packages/urllib3/_request_methods.py:182: FutureWarning: URLs without a scheme (ie 'https://') are deprecated and will raise an error in urllib3 v3.0. To avoid this FutureWarning ensure all URLs start with 'https://' or 'http://'. Read more in this issue: https://github.com/urllib3/urllib3/issues/2920
  return self.urlopen(method, url, **extra_kw)
05:53:11 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=success latency_ms=18247 tokens=1219/617 requests=1/inf
05:54:19 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=success latency_ms=1619 tokens=1201/2 requests=2/inf
05:54:23 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=error latency_ms=951 tokens=-/- requests=3/inf
05:54:26 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=2 status=error latency_ms=1214 tokens=-/- requests=4/inf
05:54:32 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=3 status=error latency_ms=738 tokens=-/- requests=5/inf
05:54:34 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=1 status=error latency_ms=2074 tokens=-/- requests=6/inf
05:54:36 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=2 status=error latency_ms=201 tokens=-/- requests=7/inf
05:54:40 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=3 status=error latency_ms=263 tokens=-/- requests=8/inf
05:54:42 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=1 status=error latency_ms=2320 tokens=-/- requests=9/inf
05:54:44 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=2 status=error latency_ms=271 tokens=-/- requests=10/inf
05:54:49 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=3 status=error latency_ms=235 tokens=-/- requests=11/inf
05:54:51 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=1 status=error latency_ms=1739 tokens=-/- requests=12/inf
05:54:53 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=2 status=error latency_ms=250 tokens=-/- requests=13/inf
05:54:57 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=3 status=error latency_ms=214 tokens=-/- requests=14/inf
05:55:02 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=1 status=error latency_ms=5468 tokens=-/- requests=15/inf
05:55:05 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=2 status=error latency_ms=238 tokens=-/- requests=16/inf
05:55:09 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=3 status=error latency_ms=224 tokens=-/- requests=17/inf
05:55:09 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=1 status=error latency_ms=296 tokens=-/- requests=18/inf
05:55:12 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=2 status=error latency_ms=291 tokens=-/- requests=19/inf
05:55:17 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=3 status=error latency_ms=224 tokens=-/- requests=20/inf
05:55:17 WARNING Vacancy file 1be0e802-e0c1-4537-8a8f-c89ea1f7ffd9 OCR failed: All assigned models failed for job 'fetcher.vacancy_image_ocr' role 'ocr'. Last error: You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. 
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-omni-1.1-flash
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-omni-1.1-flash
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_input_token_count, limit: 0, model: gemini-omni-1.1-flash
Please retry in 18h4m42.754566373s.
05:55:38 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=error latency_ms=2918 tokens=-/- requests=21/inf
05:55:43 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=2 status=error latency_ms=2929 tokens=-/- requests=22/inf
05:55:51 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=3 status=error latency_ms=3175 tokens=-/- requests=23/inf
05:55:55 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=1 status=error latency_ms=4441 tokens=-/- requests=24/inf
05:55:59 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=2 status=error latency_ms=2307 tokens=-/- requests=25/inf
05:56:05 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=3 status=error latency_ms=2099 tokens=-/- requests=26/inf
05:56:11 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=1 status=error latency_ms=5831 tokens=-/- requests=27/inf
05:56:15 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=2 status=error latency_ms=2378 tokens=-/- requests=28/inf
05:56:22 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=3 status=error latency_ms=2107 tokens=-/- requests=29/inf
05:56:26 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=1 status=error latency_ms=3986 tokens=-/- requests=30/inf
05:56:30 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=2 status=error latency_ms=2170 tokens=-/- requests=31/inf
05:56:36 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=3 status=error latency_ms=2158 tokens=-/- requests=32/inf
05:56:40 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=1 status=error latency_ms=3691 tokens=-/- requests=33/inf
05:56:44 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=2 status=error latency_ms=1843 tokens=-/- requests=34/inf
05:56:51 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=3 status=error latency_ms=1809 tokens=-/- requests=35/inf
05:56:53 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=1 status=error latency_ms=1886 tokens=-/- requests=36/inf
05:56:57 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=2 status=error latency_ms=2147 tokens=-/- requests=37/inf
05:57:02 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=3 status=error latency_ms=2082 tokens=-/- requests=38/inf
05:57:02 WARNING Vacancy file 154e5fbb-2386-45c8-8ccb-9b548edb1cd6 OCR failed: All assigned models failed for job 'fetcher.vacancy_image_ocr' role 'ocr'. Last error: You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. 
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_input_token_count, limit: 0, model: gemini-omni-1.1-flash
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-omni-1.1-flash
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-omni-1.1-flash
Please retry in 18h2m57.311399689s.
05:57:10 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=error latency_ms=4103 tokens=-/- requests=39/inf
05:57:16 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=2 status=error latency_ms=3922 tokens=-/- requests=40/inf
05:57:24 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=3 status=error latency_ms=3028 tokens=-/- requests=41/inf
05:57:26 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=1 status=error latency_ms=2525 tokens=-/- requests=42/inf
05:57:31 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=2 status=error latency_ms=2675 tokens=-/- requests=43/inf
05:57:38 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=3 status=error latency_ms=2518 tokens=-/- requests=44/inf
05:57:40 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=1 status=error latency_ms=2394 tokens=-/- requests=45/inf
05:57:45 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=2 status=error latency_ms=2636 tokens=-/- requests=46/inf
05:57:51 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=3 status=error latency_ms=2987 tokens=-/- requests=47/inf
05:57:54 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=1 status=error latency_ms=2650 tokens=-/- requests=48/inf
05:57:59 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=2 status=error latency_ms=2665 tokens=-/- requests=49/inf
05:58:06 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=3 status=error latency_ms=2847 tokens=-/- requests=50/inf
05:58:09 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=1 status=error latency_ms=2803 tokens=-/- requests=51/inf
05:58:13 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=2 status=error latency_ms=2515 tokens=-/- requests=52/inf
05:58:21 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=3 status=error latency_ms=3001 tokens=-/- requests=53/inf
05:58:23 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=1 status=error latency_ms=2646 tokens=-/- requests=54/inf
05:58:28 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=2 status=error latency_ms=2495 tokens=-/- requests=55/inf
05:58:35 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=3 status=error latency_ms=2447 tokens=-/- requests=56/inf
05:58:35 WARNING Vacancy file 1dc70348-fc6b-4fdf-81df-85f1a2ec0bc8 OCR failed: All assigned models failed for job 'fetcher.vacancy_image_ocr' role 'ocr'. Last error: You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. 
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-omni-1.1-flash
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-omni-1.1-flash
* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_input_token_count, limit: 0, model: gemini-omni-1.1-flash
Please retry in 18h1m24.976789707s.
05:58:55 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=error latency_ms=8601 tokens=-/- requests=57/inf
05:58:59 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=2 status=error latency_ms=1877 tokens=-/- requests=58/inf
05:59:06 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=3 status=error latency_ms=2891 tokens=-/- requests=59/inf
05:59:07 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=1 status=error latency_ms=871 tokens=-/- requests=60/inf
05:59:10 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=2 status=error latency_ms=1089 tokens=-/- requests=61/inf
05:59:16 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=3 status=error latency_ms=1036 tokens=-/- requests=62/inf
05:59:17 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=1 status=error latency_ms=1033 tokens=-/- requests=63/inf
cd && cd /opt/projects/industry-analyser && source venv/bin/activate && python  manage.py refetch_vacancies --keyword-id 2
05:52:43 INFO Portal 2 (type=nextjs) — detail enrichment enabled
/opt/projects/industry-analyser/venv/lib/python3.10/site-packages/urllib3/_request_methods.py:182: FutureWarning: URLs without a scheme (ie 'https://') are deprecated and will raise an error in urllib3 v3.0. To avoid this FutureWarning ensure all URLs start with 'https://' or 'http://'. Read more in this issue: https://github.com/urllib3/urllib3/issues/2920
  return self.urlopen(method, url, **extra_kw)
05:53:11 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=success latency_ms=18247 tokens=1219/617 requests=1/inf
05:54:19 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=success latency_ms=1619 tokens=1201/2 requests=2/inf
05:54:23 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=1 status=error latency_ms=951 tokens=-/- requests=3/inf
05:54:26 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=2 status=error latency_ms=1214 tokens=-/- requests=4/inf
05:54:32 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash-lite attempt=3 status=error latency_ms=738 tokens=-/- requests=5/inf
05:54:34 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=1 status=error latency_ms=2074 tokens=-/- requests=6/inf
05:54:36 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=2 status=error latency_ms=201 tokens=-/- requests=7/inf
05:54:40 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.5-flash attempt=3 status=error latency_ms=263 tokens=-/- requests=8/inf
05:54:42 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=1 status=error latency_ms=2320 tokens=-/- requests=9/inf
05:54:44 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=2 status=error latency_ms=271 tokens=-/- requests=10/inf
05:54:49 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=3 status=error latency_ms=235 tokens=-/- requests=11/inf
05:54:51 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=1 status=error latency_ms=1739 tokens=-/- requests=12/inf
05:54:53 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=2 status=error latency_ms=250 tokens=-/- requests=13/inf
05:54:57 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.7-flash attempt=3 status=error latency_ms=214 tokens=-/- requests=14/inf
05:55:02 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=1 status=error latency_ms=5468 tokens=-/- requests=15/inf
05:55:05 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=2 status=error latency_ms=238 tokens=-/- requests=16/inf
05:55:09 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.8-flash attempt=3 status=error latency_ms=224 tokens=-/- requests=17/inf
05:55:09 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=1 status=error latency_ms=296 tokens=-/- requests=18/inf
05:55:12 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=2 status=error latency_ms=291 tokens=-/- requests=19/inf
05:55:17 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-omni-1.1-flash attempt=3 status=error latency_ms=224 tokens=-/- requests=20/inf
05:55:17 WARNING Vacancy file 1be0e802-e0c1-4537-8a8f-c89ea1f7ffd9 OCR failed: All assigned models failed for job 'fetcher.vacancy_image_ocr' role 'ocr'. Last error: You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. 
05:59:20 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=2 status=error latency_ms=1038 tokens=-/- requests=64/inf
05:59:26 INFO ai_request job=fetcher.vacancy_image_ocr role=ocr model=gemini-3.6-flash attempt=3 status=error latency_ms=993 tokens=-/- requests=65/inf