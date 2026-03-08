"""News and media tools for player/team news gathering."""

import json

from agents import function_tool


@function_tool
def search_player_news(player_name: str) -> str:
    """Search for recent news about an NBA player.

    Args:
        player_name: Full name of the player (e.g., 'LeBron James')
    """
    try:
        from gnews import GNews

        google_news = GNews(language="en", country="US", max_results=5)
        articles = google_news.get_news(f"{player_name} NBA")

        if not articles:
            return json.dumps({"articles": [], "query": player_name})

        results = []
        for article in articles[:5]:
            results.append({
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "published": article.get("published date", ""),
                "source": article.get("publisher", {}).get("title", ""),
            })

        return json.dumps({"articles": results, "query": player_name})
    except Exception as e:
        return json.dumps({"error": f"Failed to search player news: {str(e)}", "articles": []})


@function_tool
def search_team_news(team_name: str) -> str:
    """Search for recent team news including injuries, trades, and lineup changes.

    Args:
        team_name: Full team name (e.g., 'Miami Heat') or city name
    """
    try:
        from gnews import GNews

        google_news = GNews(language="en", country="US", max_results=5)
        articles = google_news.get_news(f"{team_name} NBA injuries lineup")

        if not articles:
            return json.dumps({"articles": [], "query": team_name})

        results = []
        for article in articles[:5]:
            results.append({
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "published": article.get("published date", ""),
                "source": article.get("publisher", {}).get("title", ""),
            })

        return json.dumps({"articles": results, "query": team_name})
    except Exception as e:
        return json.dumps({"error": f"Failed to search team news: {str(e)}", "articles": []})


@function_tool
def search_matchup_news(team1: str, team2: str) -> str:
    """Search for matchup preview articles between two teams.

    Args:
        team1: First team name
        team2: Second team name
    """
    try:
        from gnews import GNews

        google_news = GNews(language="en", country="US", max_results=5)
        articles = google_news.get_news(f"{team1} vs {team2} NBA preview")

        if not articles:
            return json.dumps({"articles": [], "query": f"{team1} vs {team2}"})

        results = []
        for article in articles[:5]:
            results.append({
                "title": article.get("title", ""),
                "description": article.get("description", ""),
                "published": article.get("published date", ""),
                "source": article.get("publisher", {}).get("title", ""),
            })

        return json.dumps({"articles": results, "query": f"{team1} vs {team2}"})
    except Exception as e:
        return json.dumps({"error": f"Failed to search matchup news: {str(e)}", "articles": []})


@function_tool
def get_espn_nba_news() -> str:
    """Get general NBA headlines from ESPN's public API."""
    try:
        import urllib.request

        url = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/news"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            import json as _json
            data = _json.loads(response.read().decode())

        articles = data.get("articles", [])
        results = []
        for article in articles[:8]:
            results.append({
                "headline": article.get("headline", ""),
                "description": article.get("description", ""),
                "published": article.get("published", ""),
            })

        return json.dumps({"articles": results})
    except Exception as e:
        return json.dumps({"error": f"Failed to get ESPN news: {str(e)}", "articles": []})
