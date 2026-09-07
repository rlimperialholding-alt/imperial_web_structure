# Original-source replay samples

Fetched directly over HTTPS on 2026-09-07. Usernames, profile links, avatars,
and unrelated navigation have been removed. These are source/parser fixtures,
not approved brand claims, messages, or permission to publish.

The replay model is a stub returning no extracted questions, the short original
title `Munkadíjak?`, or one literal garage question. A fourth scenario moves the
observation clock 45 days forward while preserving original source dates.
Tests exercise the real page/feed parser, the real
`process_source_attempt`, source dates, retention, and SQLite database identity
over two scan dates. SMTP and publication entry points fail the test if called.

Reproduce the report from the repository root with:

```powershell
python -X utf8 scripts/replay_forum_real_sources.py --output docs/evidence/source-coverage-20260907/replay-report.json
```

The command creates only an isolated in-memory test database and the requested
local report. It does not connect to the live database, model, or publishing services.

## Reddit: original Atom published timestamps

Discovery endpoint: <https://www.reddit.com/r/lakokozosseg/new/.rss?limit=25>
returned HTTP 200 with 25 entries. Four are retained in the anonymized fixture:

| Original post | Original `published` UTC | Role in test |
|---|---|---|
| <https://www.reddit.com/r/lakokozosseg/comments/1w8rs4c/munkad%C3%ADjak/> | 2026-09-06 09:45:34 | Short title; actual floor laying and painting cost question in body |
| <https://www.reddit.com/r/lakokozosseg/comments/1w80vox/milyen_gar%C3%A1zst_%C3%A9p%C3%ADten%C3%A9tek/> | 2026-09-05 13:32:22 | Garage construction and cost comparison |
| <https://www.reddit.com/r/lakokozosseg/comments/1w700z1/lak%C3%A1sfel%C3%BAj%C3%ADt%C3%A1si_k%C3%A9rd%C3%A9sek/> | 2026-09-04 09:59:50 | Apartment renovation question |
| <https://www.reddit.com/r/lakokozosseg/comments/1w9ierm/ez_csotany_akarna_lenni/> | 2026-09-07 04:51:59 | Irrelevant insect-identification control |

The feed does not prove answer count or whether replies are currently open.
Its `updated` value must never replace `published` for original-post age.

## Index: exact post bookmark timestamps

Discovery category: <https://forum.index.hu/Topic/showTopicList?t=52>
returned HTTP 200 after the public, anonymous Indapass cookie handshake.
The construction/renovation topic
<https://forum.index.hu/Article/showArticle?t=9004917> returned 30 posts.

| Exact original post | Bookmark `title`, Europe/Budapest | Role in test |
|---|---|---|
| <https://forum.index.hu/Article/viewArticle?a=172270043&t=9004917> | 2026.09.06 11:18:01 | Whether thicker facade insulation is worth the extra cost |
| <https://forum.index.hu/Article/viewArticle?a=172260264&t=9004917> | 2026.09.03 12:34:58 | Whether a quoted painting/plastering price is reasonable |
| <https://forum.index.hu/Article/viewArticle?a=172254254&t=9004917> | 2026.09.01 18:34:17 | Tiler wanted after a burst pipe |

Each `table.art` binds its own bookmark and `.art_t` text. The thread creation
date, another post's date, and relative link labels are not used as the timestamp.
The exact first post was separately fetched with the pinned public transport:
HTTP 200, 4,873 response bytes, three redirects, 1.16 seconds.

## Prohardver: original body versus quoted earlier reply

Discovery:
<https://prohardver.hu/tema/lakasfelujito_szerelo_szakemberkereso_nagy_topic_viz_gaz_villany_futes_festes_burkolas_stb/friss.html>
returned HTTP 200, 100 current posts.

The anonymized fixture contains post
<https://prohardver.hu/tema/lakasfelujito_szerelo_szakemberkereso_nagy_topic_viz_gaz_villany_futes_festes_burkolas_stb/hsz_171759-171759.html>.
Its own `time.message-time` is `szept. 4., 15:56:47`, observed on 2026-09-07.
It describes an ongoing kitchen renovation and a desired new socket.
The original body is `.message-body-main > .message-content`; the earlier
quoted reply is nested under `.message-body-infos` and must not be attributed
to this post. The anonymized quote remains to exercise that distinction.
The exact post was separately refreshed on 2026-09-07 at 05:57:53 UTC through
the pinned transport and its ordinary anonymous RIOS handshake. The source
returned its own September 4 timestamp and original text. Reply count and
active status remained unknown; they were not invented from HTTP success.

## Access limits observed

One immediate second Reddit feed request returned HTTP 429. A later bounded
request succeeded. Coverage must record and respect rate limits and cannot
claim that an inaccessible feed was scanned. No Facebook group access or
universal coverage of every forum is proven by these fixtures.
