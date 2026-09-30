// Konfiguration aller Seiten und ihrer ausblendbaren Bereiche.
// hide: CSS-Selektoren, die ausgeblendet werden.
// home: true -> gilt nur auf der Startseite/Feed-Seite (html[data-focus-home]).
// Selektoren sind "best effort": die Seiten ändern ihr Markup regelmäßig.
var FOCUS_SITES = [
  {
    id: "youtube", name: "YouTube", hosts: ["youtube.com"],
    features: [
      { id: "home", label: "Startseiten-Feed", default: true, home: true,
        hide: ["ytd-browse[page-subtype='home'] ytd-rich-grid-renderer", "ytd-browse[page-subtype='home'] #primary"] },
      { id: "related", label: "Empfohlene Videos (neben/unter Video)", default: true,
        hide: ["ytd-watch-flexy #related", "ytd-watch-flexy #secondary-inner ytd-watch-next-secondary-results-renderer"] },
      { id: "comments", label: "Kommentare", default: true, hide: ["ytd-comments#comments"] },
      { id: "shorts", label: "Shorts", default: true,
        hide: ["ytd-rich-shelf-renderer[is-shorts]", "ytd-reel-shelf-renderer", "ytd-guide-entry-renderer:has(a[title='Shorts'])",
               "ytd-mini-guide-entry-renderer[aria-label='Shorts']", "ytd-video-renderer:has(a[href^='/shorts/'])",
               "ytd-grid-video-renderer:has(a[href^='/shorts/'])", "ytd-rich-item-renderer:has(a[href^='/shorts/'])"] },
      { id: "endcards", label: "End-Karten & Vorschläge im Player", default: true,
        hide: [".ytp-endscreen-content", ".ytp-ce-element", ".ytp-suggestion-set", ".ytp-cards-teaser"] },
      { id: "sidebar", label: "Seitenleiste", default: false,
        hide: ["ytd-guide-renderer", "ytd-mini-guide-renderer", "tp-yt-app-drawer"] }
    ]
  },
  {
    id: "twitch", name: "Twitch", hosts: ["twitch.tv"],
    features: [
      { id: "recommended", label: "Empfohlene Kanäle (Seitenleiste)", default: true,
        hide: [".side-nav-section[aria-label*='Recommended']", ".side-nav-section[aria-label*='Empfohlen']",
               ".side-nav-section[aria-label*='Empfohlene']"] },
      { id: "home", label: "Startseite / Karussell", default: true, home: true,
        hide: ["[data-a-target='front-page-carousel']", ".front-page-carousel", "main .tw-tower", "main [data-test-selector='shelf-container']"] },
      { id: "sidebar", label: "Komplette Seitenleiste", default: false, hide: [".side-nav"] },
      { id: "chat", label: "Chat", default: false, hide: [".chat-shell", ".right-column"] },
      { id: "highlights", label: "Hype Train / Drops / Highlights im Chat", default: true,
        hide: [".community-highlight-stack__card", ".hype-train-progress", "[data-test-selector='chat-room-component-layout'] .chat-shell__expansion"] }
    ]
  },
  {
    id: "tiktok", name: "TikTok", hosts: ["tiktok.com"],
    features: [
      { id: "feed", label: "„Für dich“-Feed", default: true,
        hide: ["[data-e2e='recommend-list-item-container']", "#main-content-homepage_hot", "[class*='DivVideoFeedV2']"] },
      { id: "comments", label: "Kommentare", default: true,
        hide: ["[data-e2e='comment-list']", "[class*='DivCommentContainer']", "[data-e2e='browse-comment']"] },
      { id: "suggested", label: "Vorgeschlagene Accounts", default: true,
        hide: ["[data-e2e='recommended-accounts']", "[class*='DivSuggestedAccount']", "[data-e2e='suggest-accounts']"] },
      { id: "live", label: "LIVE-Bereiche", default: false, hide: ["a[href*='/live']", "[data-e2e='live-side-more-button']"] },
      { id: "explore", label: "Entdecken / Trends", default: false, hide: ["a[href*='/explore']", "[data-e2e='explore-card']"] }
    ]
  },
  {
    id: "instagram", name: "Instagram", hosts: ["instagram.com"],
    features: [
      { id: "feed", label: "Feed", default: true, home: true, hide: ["main[role='main'] article"] },
      { id: "reels", label: "Reels", default: true, hide: ["a[href='/reels/']", "a[href*='/reels/']"] },
      { id: "explore", label: "Entdecken", default: true, hide: ["a[href='/explore/']"] },
      { id: "stories", label: "Stories-Leiste", default: false, hide: ["div[role='menu']", "[aria-label*='Stories']"] },
      { id: "suggested", label: "Vorschläge für dich", default: true,
        hide: ["a[href*='/explore/people/']", "div:has(> div > a[href*='/explore/people/'])"] }
    ]
  },
  {
    id: "x", name: "X / Twitter", hosts: ["x.com", "twitter.com"],
    features: [
      { id: "timeline", label: "Home-Timeline", default: true, home: true,
        hide: ["[aria-label='Home timeline']", "[aria-label='Timeline: Your Home Timeline']"] },
      { id: "sidebar", label: "Rechte Seitenleiste (Trends, Wem folgen)", default: true, hide: ["[data-testid='sidebarColumn']"] },
      { id: "explore", label: "Erkunden-Tab", default: true, hide: ["a[href='/explore']"] },
      { id: "notifBadge", label: "Benachrichtigungs-Zähler", default: false,
        hide: ["[data-testid='notificationsBadge']", "a[href='/notifications'] div[dir='ltr'] > span"] }
    ]
  },
  {
    id: "facebook", name: "Facebook", hosts: ["facebook.com"],
    features: [
      { id: "feed", label: "Feed", default: true, home: true, hide: ["[role='feed']"] },
      { id: "stories", label: "Stories & Reels-Leiste", default: true, hide: ["[aria-label='Stories']", "[aria-label='Reels']"] },
      { id: "watch", label: "Watch / Reels-Tabs", default: true, hide: ["a[href*='/watch']", "a[href*='/reel/']", "a[href*='/reels/']"] },
      { id: "sidebar", label: "Seitenleisten", default: false, hide: ["[role='complementary']"] },
      { id: "marketplace", label: "Marketplace", default: false, hide: ["a[href*='/marketplace']"] }
    ]
  },
  {
    id: "reddit", name: "Reddit", hosts: ["reddit.com"],
    features: [
      { id: "home", label: "Startseiten-Feed", default: true, home: true, hide: ["shreddit-feed", "main > div.main-container"] },
      { id: "popular", label: "Popular / All", default: true, hide: ["a[href='/r/popular/']", "a[href='/r/all/']", "faceplate-tracker[source='popular']"] },
      { id: "sidebar", label: "Rechte Seitenleiste", default: true, hide: ["#right-sidebar-container", "aside[aria-label*='sidebar']"] },
      { id: "comments", label: "Kommentare", default: false, hide: ["shreddit-comment-tree", "shreddit-comments-page-tools"] }
    ]
  },
  {
    id: "linkedin", name: "LinkedIn", hosts: ["linkedin.com"],
    features: [
      { id: "feed", label: "Feed", default: true, home: true, hide: [".scaffold-finite-scroll", "main .feed-shared-update-v2", "[data-view-name='feed-full-update']"] },
      { id: "news", label: "LinkedIn News", default: true, hide: [".news-module", "aside .artdeco-card:has(.news-module)"] },
      { id: "notifBadge", label: "Zähler-Badges", default: false, hide: [".notification-badge", ".global-nav__nav-item .notification-badge"] }
    ]
  },
  {
    id: "pinterest", name: "Pinterest", hosts: ["pinterest.com"],
    features: [
      { id: "home", label: "Startseiten-Feed", default: true, home: true, hide: ["[data-test-id='homefeed-feed']", "[data-test-id='pin']"] },
      { id: "related", label: "Weitere Pins (unter Pin)", default: true, hide: ["[data-test-id='related-pins-title']", "[data-test-id='relatedPins']"] }
    ]
  },
  {
    id: "threads", name: "Threads", hosts: ["threads.net", "threads.com"],
    features: [
      { id: "feed", label: "Feed", default: true, home: true, hide: ["[data-pressable-container='true']", "main [role='region']"] }
    ]
  }
];
