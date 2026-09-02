"""Reddit collector via the official OAuth API (PRAW).

Reads creds from env (REDDIT_CLIENT_ID/SECRET/USERNAME/PASSWORD/USER_AGENT).
Incremental by `after` cursor support is left to the caller via `before_id`;
each post (title + selftext + flattened comment tree) is ingested as one
tier-5 document so anecdote clustering can work over it.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone


def _reddit():
    import praw

    cid = os.environ.get("REDDIT_CLIENT_ID")
    sec = os.environ.get("REDDIT_CLIENT_SECRET")
    if not (cid and sec):
        raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set")
    return praw.Reddit(
        client_id=cid, client_secret=sec,
        username=os.environ.get("REDDIT_USERNAME"),
        password=os.environ.get("REDDIT_PASSWORD"),
        user_agent=os.environ.get("REDDIT_USER_AGENT", "webcollect/0.1"),
        check_for_async=False,
    )


def collect_subreddit(con, corpus_dir, subreddit, *, limit=50, sort="new",
                      query=None, with_comments=True, comment_expand=0):
    from lib import fetch

    r = _reddit()
    sr = r.subreddit(subreddit)
    if query:
        posts = sr.search(query, sort="new", limit=limit)
    else:
        posts = getattr(sr, sort)(limit=limit)

    n_new = 0
    for p in posts:
        body = f"# {p.title}\n\n{getattr(p, 'selftext', '') or ''}"
        if with_comments:
            try:
                p.comments.replace_more(limit=comment_expand)
                for c in p.comments.list():
                    body += f"\n\n[u/{getattr(c, 'author', None)} | {getattr(c, 'score', 0)}] {getattr(c, 'body', '')}"
            except Exception:  # noqa: BLE001
                pass
        published = datetime.fromtimestamp(p.created_utc, tz=timezone.utc).isoformat()
        _doc, is_new = fetch.ingest_text(
            con, corpus_dir, text=body,
            source_url=f"https://www.reddit.com{p.permalink}", channel="reddit",
            source_tier=5, source_id=f"reddit:r/{subreddit}", title=p.title,
            author=str(getattr(p, "author", None)), published_at=published,
            extra={"score": getattr(p, "score", None), "num_comments": getattr(p, "num_comments", None)},
        )
        n_new += int(is_new)
    return n_new
