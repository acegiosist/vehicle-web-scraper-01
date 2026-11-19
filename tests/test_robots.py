from vehicle_scraper.robots import RobotsRules

UA = "VehicleScraper/1.0 (+contact: x@example.com) Mozilla/5.0 (compatible)"

TRUECAR = """\
User-agent: *
Disallow: /*?*zipcode=
Disallow: /used/
Disallow: *listings/*?*drivetrain=
Disallow: /used-cars-for-sale/listing/*
Disallow: /*.hbs$
Sitemap: https://www.truecar.com/sitemaps/used/used-sitemap-index.xml
"""


def test_wildcards_truecar():
    r = RobotsRules(TRUECAR, UA)
    base = "https://www.truecar.com"
    assert not r.can_fetch(f"{base}/used-cars-for-sale/listing/1HGCV1F34LA012345/2020-honda-accord/")
    assert not r.can_fetch(f"{base}/used-cars-for-sale/listings/?zipcode=90210")
    assert not r.can_fetch(f"{base}/used-cars-for-sale/listings/honda/?drivetrain=awd")
    assert not r.can_fetch(f"{base}/templates/a.hbs")
    assert r.can_fetch(f"{base}/templates/a.hbs.js")              # `$` anchors the end
    assert r.can_fetch(f"{base}/used-cars-for-sale/listings/honda/")
    assert r.can_fetch(f"{base}/sitemaps/used/used-sitemap-index.xml")


def test_longest_match_wins_and_allow_wins_ties():
    r = RobotsRules("User-agent: *\nDisallow: /noticias/\nAllow: /noticias/*\nDisallow: /a\nAllow: /a/b\n", UA)
    assert r.can_fetch("https://x.com/noticias/1")               # same length: Allow wins
    assert not r.can_fetch("https://x.com/a/c")
    assert r.can_fetch("https://x.com/a/b/c")                    # longer Allow wins


def test_own_group_beats_star_and_crawl_delay():
    text = ("User-agent: *\nDisallow: /\nCrawl-delay: 1\n\n"
            "User-agent: vehiclescraper\nUser-agent: otherbot\nDisallow: /private\nCrawl-delay: 5\n")
    r = RobotsRules(text, UA)
    assert r.can_fetch("https://x.com/cars/1")
    assert not r.can_fetch("https://x.com/private/1")
    assert r.crawl_delay == 5


def test_empty_and_percent_encoded():
    assert RobotsRules("", UA).can_fetch("https://x.com/anything")
    assert RobotsRules("User-agent: *\nDisallow:\n", UA).can_fetch("https://x.com/a")
    r = RobotsRules("User-agent: *\nDisallow: /vehiculos/autos-veh%C3%ADculo?*\n", UA)
    assert not r.can_fetch("https://x.com/vehiculos/autos-veh%C3%ADculo?page=2")
    assert r.can_fetch("https://x.com/vehiculos/autos-veh%C3%ADculo/123")
