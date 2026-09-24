#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "requests",
#   "beautifulsoup4",
# ]
# ///

import argparse
import json
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


def abs_url(base: str, url: str) -> str:
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return urljoin(base, url)


def norm_text(s: str) -> str:
    if s is None:
        return ""
    # Collapse whitespace and strip
    return re.sub(r"\s+", " ", s).strip()


def extract_text_with_newlines(el) -> str:
    if el is None:
        return ""
    frag = BeautifulSoup(str(el), "html.parser")
    for br in frag.find_all("br"):
        br.replace_with("\n")
    text = frag.get_text()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[\t\f\v ]+", " ", ln).strip() for ln in text.split("\n")]
    out_lines = []
    blank = 0
    for ln in lines:
        if ln == "":
            blank += 1
            if blank <= 1:
                out_lines.append("")
        else:
            blank = 0
            out_lines.append(ln)
    return "\n".join(out_lines).strip()


def parse_int(text: str) -> int:
    if not text:
        return 0
    # Keep only digits and commas, then remove commas
    m = re.search(r"([0-9][0-9,]*)", text)
    if not m:
        return 0
    return int(m.group(1).replace(",", ""))


def extract_user(block, base: str):
    name_el = block.select_one(".fullname")
    user_el = block.select_one(".username")
    avatar_img = block.select_one(".tweet-avatar img.avatar")
    user = {
        "name": norm_text(name_el.get_text(" ")) if name_el else None,
        "handle": (norm_text(user_el.get_text(" ")) if user_el else None),
        "profile_url": abs_url(base, user_el["href"]) if user_el and user_el.has_attr("href") else None,
        "avatar_url": abs_url(base, avatar_img["src"]) if avatar_img and avatar_img.has_attr("src") else None,
    }
    # Normalize handle to not include leading @ in a separate field
    if user["handle"]:
        user["handle_stripped"] = user["handle"].lstrip("@")
    return user


def extract_stats(block):
    stats = {"comments": 0, "reposts": 0, "quotes": 0, "likes": 0}
    for st in block.select(".tweet-stats .tweet-stat"):
        ico = st.select_one(".icon-container span")
        val = parse_int(st.get_text(" "))
        if not ico or not ico.has_attr("class"):
            continue
        classes = ico["class"]
        if "icon-comment" in classes:
            stats["comments"] = val
        elif "icon-retweet" in classes:
            stats["reposts"] = val
        elif "icon-quote" in classes:
            stats["quotes"] = val
        elif "icon-heart" in classes:
            stats["likes"] = val
    return stats


def extract_attachments(block, base: str, *, tweet_id: str | None = None, video_url_hint: str | None = None):
    # Images
    imgs = []
    for a in block.select(".attachments .attachment.image a.still-image"):
        href = a.get("href")
        img = a.select_one("img")
        imgs.append({
            "type": "image",
            "original_url": abs_url(base, href),
            "preview_url": abs_url(base, img.get("src")) if img else None,
        })
    # Videos
    vids = []
    # 1) explicit links (rare in this instance)
    for a in block.select('a[href^="/i/videos/tweet/"]'):
        vids.append({
            "type": "video",
            "embed_url": abs_url(base, a.get("href")),
            "poster_url": None,
        })
    # 2) inline video container with overlay (common)
    for vc in block.select('.attachments .gallery-video .video-container, .attachments .gallery-video [class*="video-container"]'):
        poster_img = vc.select_one('img')
        poster_url = abs_url(base, poster_img.get("src")) if poster_img else None
        # Prefer page-provided video URL hint (from og:video:url)
        embed_url = video_url_hint
        if not embed_url and tweet_id:
            # Fallback to instance embed routes (prefer /i/videos/:id as seen in og:video:url)
            embed_url = f"/i/videos/{tweet_id}"
        vids.append({
            "type": "video",
            "embed_url": abs_url(base, embed_url) if embed_url else None,
            "poster_url": poster_url,
        })
    return imgs + vids


def extract_quote(block, base: str):
    q = block.select_one(".quote")
    if not q:
        return None
    link = q.select_one(".quote-link")
    q_user_block = q.select_one(".tweet-name-row") or q
    q_user = extract_user(q_user_block, base)
    q_text_el = q.select_one(".quote-text")
    q_media_container = q.select_one(".quote-media-container") or q
    q_id = None
    q_url = None
    if link and link.has_attr("href"):
        q_url = abs_url(base, link["href"])  # includes #m
        m = re.search(r"/status/(\d+)", link["href"])
        if m:
            q_id = m.group(1)
    # Now that we know the quoted id, extract media with a proper fallback
    q_attachments = extract_attachments(q_media_container, base, tweet_id=q_id, video_url_hint=None)

    return {
        "id": q_id,
        "url": q_url.split("#")[0] if q_url else None,
        "user": q_user,
        "text": extract_text_with_newlines(q_text_el) if q_text_el else None,
        "attachments": q_attachments,
    }


def extract_replying_to(block):
    rt = block.select_one(".replying-to")
    if not rt:
        return []
    handles = []
    for a in rt.select("a"):
        handles.append(norm_text(a.get_text()))
    return handles


def extract_tweet_id(block):
    # Prefer the direct .tweet-link href
    link = block.select_one("a.tweet-link")
    if link and link.has_attr("href"):
        m = re.search(r"/status/(\d+)", link["href"])
        if m:
            return m.group(1)
    # Fallback: header date link
    date_a = block.select_one(".tweet-header .tweet-date a")
    if date_a and date_a.has_attr("href"):
        m = re.search(r"/status/(\d+)", date_a["href"])
        if m:
            return m.group(1)
    return None


def parse_tweet_block(block, base: str, *, video_url_hint: str | None = None):
    tweet_id = extract_tweet_id(block)
    user = extract_user(block, base)
    content_el = block.select_one(".tweet-content")
    text = extract_text_with_newlines(content_el)
    published_el = block.select_one("p.tweet-published")
    published = norm_text(published_el.get_text(" ")) if published_el else None
    # For thread items without p.tweet-published, use title attribute on date link
    if not published:
        date_a = block.select_one(".tweet-header .tweet-date a")
        if date_a and date_a.has_attr("title"):
            published = norm_text(date_a["title"]) or None

    stats = extract_stats(block)
    attachments = extract_attachments(block, base, tweet_id=tweet_id, video_url_hint=video_url_hint)
    quote = extract_quote(block, base)
    replying_to = extract_replying_to(block)

    # Build URL
    url = None
    if tweet_id and user.get("handle_stripped"):
        url = f"/{user['handle_stripped']}/status/{tweet_id}"
    elif tweet_id:  # generic
        url = f"/i/status/{tweet_id}"

    return {
        "id": tweet_id,
        "url": abs_url(base, url) if url else None,
        "user": user,
        "text": text,
        "published_at": published,
        "replying_to": replying_to,
        "stats": stats,
        "attachments": attachments,
        "quoted_status": quote,
    }


def parse_status_html(html: str, base: str):
    soup = BeautifulSoup(html, "html.parser")
    conv = soup.select_one(".conversation")
    if not conv:
        raise RuntimeError("Could not find conversation container")

    # Possible page-level video hint for the main tweet
    video_url_hint = None
    meta_video = (
        soup.select_one('head meta[property="og:video:url"]')
        or soup.select_one('head meta[property="og:video:secure_url"]')
    )
    if meta_video and meta_video.has_attr('content'):
        video_url_hint = meta_video['content']
        # rewrite localhost to base if necessary
        if video_url_hint.startswith('http://localhost') or video_url_hint.startswith('https://localhost'):
            # strip scheme+host and rebase
            video_url_hint = "/" + video_url_hint.split("/", 3)[-1]

    # Parents (previous tweets in thread)
    parents = []
    for item in soup.select(".main-thread .before-tweet .timeline-item"):
        parents.append(parse_tweet_block(item, base, video_url_hint=video_url_hint))

    # Children (subsequent tweets in thread)
    children = []
    for item in soup.select(".main-thread .after-tweet .timeline-item"):
        children.append(parse_tweet_block(item, base, video_url_hint=video_url_hint))

    # Main tweet
    main_block = soup.select_one(".main-thread #m .timeline-item")
    if not main_block:
        # Some pages may put main tweet directly under .main-thread .timeline-item
        main_block = soup.select_one(".main-thread .timeline-item")
    if not main_block:
        raise RuntimeError("Could not find main tweet block")
    main_tweet = parse_tweet_block(main_block, base, video_url_hint=video_url_hint)

    # Replies: threads under #r .reply.thread
    replies_section = soup.select_one("#r.replies")
    reply_threads = []
    if replies_section:
        for thread in replies_section.select(".reply.thread"):
            items = thread.select(".timeline-item")
            # Build a simple chain: first is the root reply, then successive children
            chain_nodes = [parse_tweet_block(it, base, video_url_hint=video_url_hint) for it in items]
            # Convert chain_nodes into nested replies
            def chain_to_tree(nodes):
                if not nodes:
                    return None
                root = {"tweet": nodes[0], "replies": []}
                cur = root
                for child in nodes[1:]:
                    nxt = {"tweet": child, "replies": []}
                    cur["replies"].append(nxt)
                    cur = nxt
                return root

            thread_tree = chain_to_tree(chain_nodes)
            if thread_tree:
                reply_threads.append(thread_tree)

    return {
        "status": main_tweet,
        "parents": parents,
        "children": children,
        "replies": reply_threads,
    }


def cmd_status(args):
    base = args.base.rstrip("/") if args.base else os.environ.get("NITTER_BASE")
    if not base:
        raise SystemExit("NITTER_BASE environment variable not set")
    base = base.rstrip("/")
    user = args.username
    tid = args.tweet_id
    url = f"{base}/{user}/status/{tid}"
    resp = requests.get(url, headers={"User-Agent": "nitter-cli/0.1"}, timeout=30)
    resp.raise_for_status()
    data = parse_status_html(resp.text, base)
    print(json.dumps(data, ensure_ascii=False, indent=2 if args.pretty else None))


def parse_profile(soup: BeautifulSoup, base: str):
    card = soup.select_one('.profile-card')
    if not card:
        return None
    name_el = card.select_one('.profile-card-fullname')
    user_el = card.select_one('.profile-card-username')
    bio_el = card.select_one('.profile-bio')
    avatar_img = card.select_one('.profile-card-avatar img')
    banner_img = soup.select_one('.profile-banner img')

    joined_el = card.select_one('.profile-joindate span')
    joined = joined_el.get('title') if joined_el and joined_el.has_attr('title') else None

    def stat_num(selector):
        el = card.select_one(selector)
        return parse_int(el.get_text(' ')) if el else 0

    prof = {
        'name': norm_text(name_el.get_text(' ')) if name_el else None,
        'handle': norm_text(user_el.get_text(' ')) if user_el else None,
        'profile_url': abs_url(base, user_el['href']) if user_el and user_el.has_attr('href') else None,
        'avatar_url': abs_url(base, avatar_img['src']) if avatar_img and avatar_img.has_attr('src') else None,
        'banner_url': abs_url(base, banner_img['src']) if banner_img and banner_img.has_attr('src') else None,
        'bio': extract_text_with_newlines(bio_el) if bio_el else None,
        'joined': joined,
        'stats': {
            'tweets': stat_num('.profile-statlist .posts .profile-stat-num'),
            'following': stat_num('.profile-statlist .following .profile-stat-num'),
            'followers': stat_num('.profile-statlist .followers .profile-stat-num'),
            'likes': stat_num('.profile-statlist .likes .profile-stat-num'),
        }
    }
    if prof['handle']:
        prof['handle_stripped'] = prof['handle'].lstrip('@')
    return prof


def parse_user_html(html: str, base: str):
    soup = BeautifulSoup(html, "html.parser")
    # Collect tweets under main timeline
    tweets = []
    for item in soup.select('.timeline .timeline-item'):
        tweets.append(parse_tweet_block(item, base))

    # Next cursor for pagination
    next_cursor = None
    more = soup.select_one('.show-more a[href*="cursor="]')
    if more and more.has_attr('href'):
        m = re.search(r'[?&]cursor=([^&]+)', more['href'])
        if m:
            next_cursor = m.group(1)

    profile = parse_profile(soup, base)
    return {"tweets": tweets, "cursor": next_cursor, "profile": profile}


def parse_search_html(html: str, base: str, kind: str):
    soup = BeautifulSoup(html, 'html.parser')
    next_cursor = None
    more = soup.select_one('.show-more a[href*="cursor="]')
    if more and more.has_attr('href'):
        m = re.search(r'[?&]cursor=([^&]+)', more['href'])
        if m:
            next_cursor = m.group(1)

    if kind == 'users':
        results = []
        for it in soup.select('.timeline .timeline-item'):
            body = it.select_one('.profile-result')
            if not body:
                continue
            name_el = body.select_one('.fullname')
            user_el = body.select_one('.username')
            avatar_img = body.select_one('.tweet-avatar img')
            bio_el = body.select_one('.tweet-content')
            r = {
                'name': norm_text(name_el.get_text(' ')) if name_el else None,
                'handle': norm_text(user_el.get_text(' ')) if user_el else None,
                'profile_url': abs_url(base, user_el['href']) if user_el and user_el.has_attr('href') else None,
                'avatar_url': abs_url(base, avatar_img['src']) if avatar_img and avatar_img.has_attr('src') else None,
                'bio': extract_text_with_newlines(bio_el) if bio_el else None,
            }
            if r['handle']:
                r['handle_stripped'] = r['handle'].lstrip('@')
            results.append(r)
        return {'cursor': next_cursor, 'users': results}
    else:
        tweets = []
        for it in soup.select('.timeline .timeline-item'):
            tweets.append(parse_tweet_block(it, base))
        return {'cursor': next_cursor, 'tweets': tweets}


def cmd_search(args):
    base = args.base.rstrip('/') if args.base else os.environ.get('NITTER_BASE')
    if not base:
        raise SystemExit("NITTER_BASE environment variable not set")
    base = base.rstrip('/')
    kind = args.kind
    q = args.query

    params = {'f': kind, 'q': q}
    if args.cursor:
        params['cursor'] = args.cursor

    # Build path: global or user-specific
    if args.user:
        path = f"/{args.user}/search"
    else:
        path = "/search"

    url = base + path
    resp = requests.get(url, params=params, headers={"User-Agent": "nitter-cli/0.1"}, timeout=30)
    resp.raise_for_status()
    data = parse_search_html(resp.text, base, kind)
    out = {
        'kind': kind,
        'query': q,
        'cursor': data.get('cursor'),
    }
    if kind == 'users':
        out['users'] = data['users']
    else:
        out['tweets'] = data['tweets']
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))


def cmd_user(args):
    base = args.base.rstrip("/") if args.base else os.environ.get("NITTER_BASE")
    if not base:
        raise SystemExit("NITTER_BASE environment variable not set")
    base = base.rstrip("/")
    user = args.username
    tab = args.tab
    path = f"/{user}"
    if tab == 'with_replies':
        path += "/with_replies"
    elif tab == 'media':
        path += "/media"

    url = f"{base}{path}"
    if args.cursor:
        url = f"{url}?cursor={args.cursor}"

    resp = requests.get(url, headers={"User-Agent": "nitter-cli/0.1"}, timeout=30)
    resp.raise_for_status()
    data = parse_user_html(resp.text, base)
    out = {
        "user": user,
        "tab": tab,
        "cursor": data["cursor"],
        "profile": data.get("profile"),
        "tweets": data["tweets"],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2 if args.pretty else None))


def main():
    p = argparse.ArgumentParser(description="CLI scraper for Nitter status pages → JSON")
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("status", help="Fetch a single status and conversation")
    ps.add_argument("username", help="Username (without @)")
    ps.add_argument("tweet_id", help="Tweet ID")
    ps.add_argument("--base", help="Base Nitter URL (default: env NITTER_BASE)")
    ps.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    pu = sub.add_parser("user", help="Fetch a user's timeline page")
    pu.add_argument("username", help="Username (without @)")
    pu.add_argument("--tab", choices=["tweets", "with_replies", "media"], default="tweets", help="Timeline tab")
    pu.add_argument("--cursor", help="Cursor for pagination", default=None)
    pu.add_argument("--base", help="Base Nitter URL (default: env NITTER_BASE)")
    pu.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    psrch = sub.add_parser("search", help="Search tweets or users")
    psrch.add_argument("query", help="Search query text")
    psrch.add_argument("--kind", choices=["tweets", "users"], default="tweets", help="Search kind")
    # Express filters/date/location in the query string (operators), e.g.:
    #   'since:2024-01-01 until:2024-12-31 filter:media -filter:retweets from:alice'
    # For more information on query syntax, refer to README.md
    psrch.add_argument("--cursor", help="Cursor for pagination")
    psrch.add_argument("--user", help="Limit search to a specific user (uses /:user/search)")
    psrch.add_argument("--base", help="Base Nitter URL (default: env NITTER_BASE)")
    psrch.add_argument("--pretty", action="store_true", help="Pretty-print JSON")

    args = p.parse_args()

    if args.command == "status":
        cmd_status(args)
    elif args.command == "user":
        cmd_user(args)
    elif args.command == "search":
        cmd_search(args)


if __name__ == "__main__":
    main()
