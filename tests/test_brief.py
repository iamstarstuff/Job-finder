from dashboard import brief


def test_lead_sentence_covers_up_down_flat_and_empty():
    assert brief.new_roles_sentence(137, 119) == "137 new roles landed this week, 18 more than last week."
    assert brief.new_roles_sentence(20, 25) == "20 new roles landed this week, 5 fewer than last week."
    assert brief.new_roles_sentence(7, 7) == "7 new roles landed this week, the same as last week."
    assert brief.new_roles_sentence(1, 0) == "1 new role landed this week, 1 more than last week."
    assert brief.new_roles_sentence(0, 4) == "No new roles have landed this week yet."


def test_skills_sentence_joins_up_to_three_with_and():
    rows = [{"skill": "GMP"}, {"skill": "Excel"}, {"skill": "SAP"}, {"skill": "SOP"}]
    assert brief.skills_sentence(rows, "over the last 12 weeks") == "GMP, Excel and SAP lead demand over the last 12 weeks."
    assert brief.skills_sentence(rows[:1], "across everything tracked") == "GMP leads demand across everything tracked."
    assert brief.skills_sentence([], "over the last 4 weeks") is None


def test_companies_sentence_names_the_two_busiest_this_week():
    rows = [
        {"company": "MSD", "active": 9, "new_in_window": 5, "new_previous_window": 1},
        {"company": "BMS", "active": 3, "new_in_window": 0, "new_previous_window": 1},
        {"company": "Regeneron", "active": 4, "new_in_window": 5, "new_previous_window": 0},
        {"company": "Pfizer", "active": 2, "new_in_window": 2, "new_previous_window": 0},
    ]
    assert brief.companies_sentence(rows) == "MSD and Regeneron posted the most."  # ties by name
    assert brief.companies_sentence(rows[3:]) == "Pfizer posted the most."
    assert brief.companies_sentence([rows[1]]) is None


def test_health_sentence_uses_words_up_to_nine():
    assert brief.health_sentence(0) is None
    assert brief.health_sentence(1) == "One scraper needs attention."
    assert brief.health_sentence(2) == "Two scrapers need attention."
    assert brief.health_sentence(12) == "12 scrapers need attention."


def test_compose_brief_assembles_all_parts():
    overview = {"new_this_week": 3, "new_previous_week": 3, "companies_failing": 1}
    out = brief.compose_brief(overview, [{"skill": "GMP"}], [
        {"company": "MSD", "active": 1, "new_in_window": 3, "new_previous_window": 0}], "over the last 12 weeks")
    assert out == {
        "lead": "3 new roles landed this week, the same as last week.",
        "skills": "GMP leads demand over the last 12 weeks.",
        "companies": "MSD posted the most.",
        "health": "One scraper needs attention.",
    }
